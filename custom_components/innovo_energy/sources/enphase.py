"""Enphase source: reads Home Assistant's own Enphase Envoy integration (enphase_envoy).

One site can have several Envoys. The *main* Envoy is the one with the grid
(net-consumption) CT - and usually the batteries (Encharge / IQ Battery) and the
IQ Meter Collar or System Controller. Every Envoy's production is solar.

Readings:
  solar   = every Envoy's production (microinverters, measured by the production CTs)
  grid    = the main Envoy's net consumption (+ importing)
  battery = minus the main Envoy's battery discharge (+ charging)
  home    = solar behind the grid meter + grid + battery discharge
  daily totals come from the lifetime meters: the Envoy's own "today" and
  "last seven days" counters are wrong on recent firmware (they repeat the lifetime total).

How other Envoys' arrays are wired (CONF_ARRAYS): "behind_meter" (the usual case - they
feed the house panel, so the main grid CT sees their export) or "separate" (their output
does not pass the main grid CT, so it is not part of the house's use).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import Event, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from . import GRID_READINGS, Source

ENPHASE_DOMAIN = "enphase_envoy"
CONF_ENVOYS = "envoys"          # config entry ids of every Envoy on the site
CONF_MAIN = "main"              # config entry id of the Envoy with the grid CT
CONF_ARRAYS = "arrays"          # "behind_meter" | "separate"
ARRAYS_BEHIND, ARRAYS_SEPARATE = "behind_meter", "separate"
# readings the Power screen needs that the Envoy integration disables by default
POWER_SCREEN_KEYS = ("voltage_l1", "voltage_l2", "net_ct_current_l1", "net_ct_current_l2", "frequency",
                     "production_ct_current", "production_ct_voltage", "production_ct_frequency")
# microinverters turn DC into AC at each panel: there is no DC side or inverter cabinet to read
NO_ENPHASE = frozenset({"dc_w", "dc_v", "dc_a", "temp_c", "battery_soh"})


def envoy_serial(hass, entry_id: str) -> str | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    return entry.unique_id if entry else None


def has_grid_ct(hass, entry_id: str) -> bool:
    serial = envoy_serial(hass, entry_id)
    return bool(serial and er.async_get(hass).async_get_entity_id("sensor", ENPHASE_DOMAIN, f"{serial}_net_consumption"))


class EnphaseSource(Source):
    brand = "Enphase"
    domain = ENPHASE_DOMAIN

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self.envoy_ids: list[str] = list(entry.data.get(CONF_ENVOYS) or [])
        self.main_id: str = entry.data[CONF_MAIN]
        self.arrays = entry.options.get(CONF_ARRAYS, entry.data.get(CONF_ARRAYS, ARRAYS_BEHIND))
        self.main = ""
        self.serials: list[str] = []
        self.collar: str | None = None

    async def async_setup(self) -> None:
        for entry_id in self.envoy_ids:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.state.name != "LOADED":
                raise ConfigEntryNotReady("Waiting for the Enphase Envoy integration to start")
        self.main = envoy_serial(self.hass, self.main_id)
        self.serials = [s for s in (envoy_serial(self.hass, i) for i in self.envoy_ids) if s]
        if not self.main or self.main not in self.serials:
            raise ConfigEntryNotReady("The main Envoy is not available")
        # the IQ Meter Collar / System Controller reports whether the grid is there
        reg = er.async_get(self.hass)
        self.collar = next((e.entity_id for e in er.async_entries_for_config_entry(reg, self.main_id)
                            if e.unique_id.endswith("_grid_state")), None)
        # readings the Envoy integration ships disabled (sites set up before they were needed)
        if enable_power_screen_readings(self.hass, self.main_id):
            self.hass.config_entries.async_schedule_reload(self.main_id)

    # ----- identity and capabilities -----
    @property
    def uid_base(self) -> str:
        return f"enphase_{self.main}_energy"

    @property
    def parent_entry_id(self) -> str:
        return self.main_id

    @property
    def via_device(self) -> tuple[str, str]:
        return (ENPHASE_DOMAIN, self.main)

    def _e(self, serial: str, key: str, platform: str = "sensor") -> str | None:
        return self.entity_id(platform, f"{serial}_{key}")

    @property
    def has_grid(self) -> bool:
        return self._e(self.main, "net_consumption") is not None

    @property
    def has_battery_hardware(self) -> bool:
        return self._e(self.main, "battery_level") is not None

    def nameplate_kwh(self) -> float | None:
        return self.energy_kwh(self._e(self.main, "max_capacity"))

    @property
    def others(self) -> list[str]:
        return [s for s in self.serials if s != self.main]

    # ----- updates -----
    def track(self, update: Callable[[], None]) -> Callable[[], None]:
        """Run once shortly after the Envoys' readings change (they update together)."""
        watched = [e for s in self.serials for e in (self._e(s, "production"),) if e]
        watched += [e for e in (self._e(self.main, "net_consumption"), self._e(self.main, "battery_discharge"),
                                self._e(self.main, "battery_level"), self.collar) if e]
        pending: list[Callable[[], None]] = []

        @callback
        def fire(_now=None) -> None:
            pending.clear()
            update()

        @callback
        def changed(_event: Event) -> None:
            if not pending:
                pending.append(async_call_later(self.hass, 1, fire))

        unsub = async_track_state_change_event(self.hass, watched, changed)
        self.hass.loop.call_soon(update)  # a first reading straight away

        def stop() -> None:
            unsub()
            for cancel in pending:
                cancel()
        return stop

    # ----- readings -----
    def _sum(self, values) -> float | None:
        values = [v for v in values if v is not None]
        return sum(values) if values else None

    def read(self) -> dict[str, Any]:
        main = self.main
        main_solar = self.power_w(self._e(main, "production"))
        other_solar = self._sum(self.power_w(self._e(s, "production")) for s in self.others)
        solar = self._sum([main_solar, other_solar])
        grid = self.power_w(self._e(main, "net_consumption"))
        discharge = self.power_w(self._e(main, "battery_discharge"))
        battery_w = None if discharge is None else -discharge
        behind = self._sum([main_solar, other_solar if self.arrays == ARRAYS_BEHIND else None])
        house = None if grid is None or behind is None else behind + grid + (discharge or 0)
        grid_state = self.state(self.collar)
        offline = main_solar is None
        return {
            "inv_w": solar, "dc_w": None, "solar_w": solar, "house_w": house, "battery_w": battery_w,
            "ac_energy": self._lifetime("lifetime_production"),
            "solar_kwh": self._lifetime("lifetime_production"),
            "charged_kwh": self.energy_kwh(self._e(main, "lifetime_battery_charged")),
            "discharged_kwh": self.energy_kwh(self._e(main, "lifetime_battery_discharged")),
            "inverter_status": "Offline" if offline else "Producing" if (solar or 0) > 50 else "Sleeping",
            "grid_on": None if grid_state is None else grid_state.state == "on_grid",
            "grid_w": grid,
            "import": self.energy_kwh(self._e(main, "lifetime_net_consumption")),
            "export": self.energy_kwh(self._e(main, "lifetime_net_production")),
            "soe": self.num(self._e(main, "battery_level")),
        }

    def _lifetime(self, key: str) -> float | None:
        """A lifetime meter added up over every Envoy (None until all of them report)."""
        values = [self.energy_kwh(self._e(s, key)) for s in self.serials]
        return None if any(v is None for v in values) else sum(values)

    def electric(self) -> dict[str, Any]:
        main = self.main
        grid_state = self.state(self.collar)
        solar = self._sum(self.power_w(self._e(s, "production")) for s in self.serials)
        producing = solar is not None and solar > 50
        return {
            # Enphase has a microinverter per panel and no single inverter: the status is the site's
            "status": None if solar is None else "I_STATUS_MPPT" if producing else "I_STATUS_SLEEPING",
            "grid_on": None if grid_state is None else grid_state.state == "on_grid",
            "ac_w": solar,
            "ac_v": self._first("production_ct_voltage", "voltage"),
            "ac_a": self.num(self._e(main, "production_ct_current")),
            "hz": self._first("production_ct_frequency", "frequency"),
            "l1_v": self.num(self._e(main, "voltage_l1")), "l2_v": self.num(self._e(main, "voltage_l2")),
            "l1_a": self.num(self._e(main, "net_ct_current_l1")), "l2_a": self.num(self._e(main, "net_ct_current_l2")),
            "produced_kwh": self._lifetime("lifetime_production"),
            "imported_kwh": self.energy_kwh(self._e(main, "lifetime_net_consumption")),
            "exported_kwh": self.energy_kwh(self._e(main, "lifetime_net_production")),
        }

    def _first(self, *keys: str) -> float | None:
        """The first of the main Envoy's readings that exists (production CT, else the grid CT)."""
        for key in keys:
            if self._e(self.main, key):
                return self.num(self._e(self.main, key))
        return None

    def not_available(self) -> set[str]:
        out = set(NO_ENPHASE)
        if not self.has_grid:
            out |= GRID_READINGS
        main = self.main
        for reading, keys in (("l1_v", ("voltage_l1",)), ("l2_v", ("voltage_l2",)), ("l1_a", ("net_ct_current_l1",)),
                              ("l2_a", ("net_ct_current_l2",)), ("ac_a", ("production_ct_current",)),
                              ("ac_v", ("production_ct_voltage", "voltage")),
                              ("hz", ("production_ct_frequency", "frequency"))):
            if not any(self._e(main, k) for k in keys):
                out.add(reading)
        if self.collar is None:  # no IQ Meter Collar / System Controller: nothing reports the grid
            out.add("grid_on")
        if not self.has_battery_hardware:
            out.add("battery")
        return out

    def reserve_pct(self) -> float | None:
        return self.num(self._e(self.main, "reserve_soc"))

    # ----- per panel: one microinverter per panel -----
    def _inverters(self) -> list[tuple[str, str, str]]:
        """[(serial, array name, power entity)] for every microinverter, found once."""
        if getattr(self, "_micro", None) is None:
            reg = er.async_get(self.hass)
            names = {s: f"Array {i + 1}" for i, s in enumerate([self.main, *self.others])}
            serial_of = {i: envoy_serial(self.hass, i) for i in self.envoy_ids}
            found = []
            for entry_id in self.envoy_ids:
                for ent in er.async_entries_for_config_entry(reg, entry_id):
                    if ent.domain == "sensor" and ent.unique_id.isdigit() and ent.entity_id.startswith("sensor.inverter_"):
                        found.append((ent.unique_id, names.get(serial_of[entry_id], "Array"), ent.entity_id))
            self._micro = sorted(found, key=lambda x: (x[1], x[0]))
        return self._micro

    @property
    def has_panels(self) -> bool:
        return bool(self._inverters())

    def panels(self) -> list[dict[str, Any]]:
        return [{"id": serial, "group": group, "w": self.power_w(entity)} for serial, group, entity in self._inverters()]

    def dashboard_grid(self) -> dict[str, str | None] | None:
        if not self.has_grid:
            return None
        return {"import": self._e(self.main, "lifetime_net_consumption"),
                "export": self._e(self.main, "lifetime_net_production"),
                "power": self._e(self.main, "net_consumption")}


def enable_power_screen_readings(hass, main_entry_id: str) -> list[str]:
    """Turn on the Envoy entities the Power screen needs (leg voltage and current) - the
    Envoy integration ships them disabled. Returns the entity ids that were enabled."""
    serial = envoy_serial(hass, main_entry_id)
    reg = er.async_get(hass)
    enabled = []
    for key in POWER_SCREEN_KEYS:
        entity_id = reg.async_get_entity_id("sensor", ENPHASE_DOMAIN, f"{serial}_{key}")
        entry = reg.async_get(entity_id) if entity_id else None
        if entry and entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
            reg.async_update_entity(entity_id, disabled_by=None)
            enabled.append(entity_id)
    return enabled
