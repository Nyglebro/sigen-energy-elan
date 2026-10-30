"""Data sources: where the readings come from (SolarEdge, Enphase, Tesla, ...).

Sigen Energy for ELAN never talks to equipment itself. A source reads the entities of the
brand's own Home Assistant integration and hands the energy model one common set of
readings, so the model, rates, dashboards and screens are the same for every brand.

Sign conventions (as in the model): grid power + = importing, battery power + = charging.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

# the electric() readings that only exist with a grid meter
GRID_READINGS = frozenset({"l1_v", "l2_v", "l1_a", "l2_a", "imported_kwh", "exported_kwh"})

SOURCE_SOLAREDGE = "solaredge"
SOURCE_ENPHASE = "enphase"
SOURCE_SIGENERGY = "sigenergy"


class Source:
    """What every source provides. Readings are plain numbers in W, kWh, %, V, A."""

    brand = "?"
    domain = "?"              # the brand integration whose entities are read

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self._ids: dict[str, str | None] = {}

    # ----- identity and capabilities -----
    @property
    def uid_base(self) -> str:
        """Stable prefix for this site's Sigen Energy for ELAN unique ids."""
        raise NotImplementedError

    @property
    def parent_entry_id(self) -> str | None:
        """The brand integration's config entry that owns via_device."""
        return None

    @property
    def via_device(self) -> tuple[str, str] | None:
        """The brand's main device (identifier), shown as the parent of Sigen Energy for ELAN."""
        return None

    @property
    def has_grid(self) -> bool:
        """A grid meter (import and export) is connected."""
        return False

    @property
    def has_battery_hardware(self) -> bool:
        """A battery (or an empty battery slot) is reported at all."""
        return False

    @property
    def inverter_kw(self) -> float | None:
        """Inverter AC rating, for gauges and plausibility checks."""
        return None

    def nameplate_kwh(self) -> float | None:
        """Battery usable capacity as reported by the equipment."""
        return None

    # ----- lifecycle -----
    async def async_setup(self) -> None:
        """Find the brand integration's data; raise ConfigEntryNotReady while it isn't loaded."""

    def track(self, update: Callable[[], None]) -> Callable[[], None]:
        """Call update() whenever new readings are available; return an unsubscribe."""
        raise NotImplementedError

    # ----- readings -----
    def read(self) -> dict[str, Any]:
        """Live and counter readings for the model:

        inv_w            inverter AC output (W) - with a DC-coupled battery it includes battery discharge
        dc_w             inverter DC input (W), for the array plausibility check
        ac_energy        inverter lifetime AC energy (kWh) - the model's solar counter
        inverter_status  "Producing" / "Sleeping" / "Offline" / "Fault <code>" / other words
        grid_on          False during a grid outage, True when connected, None if unknown
        grid_w           grid power (W), + importing
        import / export  grid meter lifetime energy (kWh)
        soe              battery state of energy (%)
        battery_w        battery power (W), + charging - optional; derived from soe when absent
        solar_w, house_w optional direct readings (sources that measure them)
        """
        raise NotImplementedError

    def electric(self) -> dict[str, Any]:
        """Equipment and electrical readings (Power / System Health screens, universal entities):

        ac_w, ac_v, ac_a, hz, dc_w, dc_v, dc_a, temp, temp_unit, temp_c, status (raw inverter
        status), grid_on, produced_kwh, l1_v, l2_v, l1_a, l2_a, imported_kwh, exported_kwh, battery_soh.
        A reading without a value right now is None (unknown).
        """
        return {}

    def not_available(self) -> set[str]:
        """The readings this site's equipment genuinely doesn't have (shown as NA, not unknown):
        electric() keys, plus "battery" when the brand reports no battery at all. Decided from
        what the equipment is, never from a missing value - a reading that is only late is unknown."""
        return set()

    @property
    def has_panels(self) -> bool:
        """Per-panel readings exist (microinverters / optimizers)."""
        return False

    def panels(self) -> list[dict[str, Any]]:
        """Per-panel output: [{"id": serial, "group": array name, "w": watts or None (not reporting)}]."""
        return []

    def reserve_pct(self) -> float | None:
        """The battery's backup reserve as set in the equipment, if it reports one."""
        return None

    def dashboard_grid(self) -> dict[str, str | None] | None:
        """Entities for the HA Energy dashboard's grid source:
        {"import": entity, "export": entity, "power_inverted": entity (+ = exporting) or None}."""
        return None

    # ----- helpers -----
    def entity_id(self, platform: str, unique_id: str) -> str | None:
        """The brand integration's entity with this unique id (cached once found)."""
        key = f"{platform}:{unique_id}"
        if self._ids.get(key) is None:
            self._ids[key] = er.async_get(self.hass).async_get_entity_id(platform, self.domain, unique_id)
        return self._ids[key]

    def state(self, entity_id: str | None):
        if entity_id is None:
            return None
        st = self.hass.states.get(entity_id)
        if st is None or st.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        return st

    def num(self, entity_id: str | None) -> float | None:
        st = self.state(entity_id)
        try:
            return float(st.state) if st else None
        except ValueError:
            return None

    def scaled(self, entity_id: str | None, scale: dict[str, float]) -> float | None:
        """A reading converted by its own unit (brands report kW or W, MWh or kWh ...)."""
        st = self.state(entity_id)
        try:
            value = float(st.state) if st else None
        except ValueError:
            return None
        if value is None:
            return None
        return value * scale.get(st.attributes.get("unit_of_measurement") or "", 1.0)

    def power_w(self, entity_id: str | None) -> float | None:
        return self.scaled(entity_id, {"W": 1.0, "kW": 1000.0, "MW": 1_000_000.0})

    def energy_kwh(self, entity_id: str | None) -> float | None:
        return self.scaled(entity_id, {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0, "GWh": 1_000_000.0})


def make_source(hass: HomeAssistant, entry: ConfigEntry) -> Source:
    kind = entry.data.get("source")
    if kind == SOURCE_SIGENERGY:
        from .sigenergy import SigenergySource
        return SigenergySource(hass, entry)
    if kind == SOURCE_SOLAREDGE:
        from .solaredge import SolarEdgeSource

        return SolarEdgeSource(hass, entry)
    if kind == SOURCE_ENPHASE:
        from .enphase import EnphaseSource

        return EnphaseSource(hass, entry)
    raise ValueError(f"Unknown data source {kind!r}")
