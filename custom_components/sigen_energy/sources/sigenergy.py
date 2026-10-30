"""Read-only Sigenergy ESS 1.2.7.5 adapter; single plant/inverter, L/N.

Uses registered entities, not private coordinator objects or a second Modbus client.
Local experimental extension to Sigen Energy for ELAN 1.2.2.
"""
from __future__ import annotations

from datetime import timedelta
from math import isfinite

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval

from . import Source

SIGENERGY_DOMAIN = "sigen"


class SigenergySource(Source):
    brand = "Sigenergy"
    domain = SIGENERGY_DOMAIN

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self.source_entry_id = entry.data["source_entry_id"]
        self._entities = []

    @property
    def uid_base(self):
        return f"sigen_{self.source_entry_id}_energy"

    @property
    def parent_entry_id(self):
        return self.source_entry_id

    @property
    def via_device(self):
        return (self.domain, f"{self.source_entry_id}_plant")

    def _refresh(self):
        self._entities = [e for e in er.async_entries_for_config_entry(
            er.async_get(self.hass), self.source_entry_id
        ) if e.platform == self.domain and e.entity_id.startswith("sensor.")
            and not e.disabled_by]

    def _id(self, key):
        # Match stable unique IDs, so friendly-name changes do not break mapping.
        matches = [e.entity_id for e in self._entities
                   if e.unique_id.startswith(f"{self.source_entry_id}_")
                   and e.unique_id.endswith(f"_{key}")]
        return matches[0] if len(matches) == 1 else None

    def _num(self, key, kind=None):
        entity = self._id(key)
        state = self.state(entity)
        if state is None:
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        if not isfinite(value):
            return None
        unit = state.attributes.get("unit_of_measurement")
        if kind:
            scales = {"power": {"W": 1, "kW": 1000, "MW": 1000000},
                      "energy": {"Wh": .001, "kWh": 1, "MWh": 1000}}[kind]
            if unit not in scales:
                return None  # Never guess a unit for a power/energy reading.
            value *= scales[unit]
        return value

    def _text(self, key):
        state = self.state(self._id(key))
        return state.state if state else None

    async def async_setup(self):
        self._refresh()
        if not self._id("plant_ess_soc") or not self._id("plant_grid_sensor_active_power"):
            raise ConfigEntryNotReady("Waiting for enabled Sigenergy plant SOC and grid power sensors")
        inverters = [e for e in self._entities if e.unique_id.endswith("_inverter_active_power")]
        if len(inverters) > 1:
            raise ConfigEntryNotReady("This test adapter supports one Sigenergy inverter only")
        output = self._text("inverter_output_type")
        if output is not None and output != "L/N":
            raise ConfigEntryNotReady("This test adapter supports single-phase L/N only")

    def track(self, update):
        # Read already-published HA states every 10 seconds. No device polling.
        # Refresh registry to pick up newly enabled or renamed sensors.
        def tick(_now):
            self._refresh()
            update()
        return async_track_time_interval(self.hass, tick, timedelta(seconds=10))

    @property
    def has_grid(self):
        return True

    @property
    def has_battery_hardware(self):
        return True

    @property
    def inverter_kw(self):
        value = self._num("inverter_rated_active_power", "power")
        return value / 1000 if value is not None and value > 0 else None

    def nameplate_kwh(self):
        value = self._num("plant_ess_rated_energy_capacity", "energy")
        return value if value is not None and value > 0 else None

    def reserve_pct(self):
        return self._num("plant_ess_discharge_cut_off_soc")

    def _grid_on(self):
        status = self._text("plant_on_off_grid_status")
        if status == "On Grid":
            return True
        if status in ("Off Grid (Auto)", "Off Grid (Manual)"):
            return False
        return None  # Grid-meter connectivity is not utility availability.

    def read(self):
        return {
            "direct_measurements": True,
            "meter_counters": True,
            "inv_w": self._num("plant_active_power", "power"),
            "dc_w": self._num("plant_sigen_photovoltaic_power", "power"),
            "ac_energy": None,  # PV lifetime must not be treated as inverter AC energy.
            "solar_w": self._num("plant_photovoltaic_power", "power"),
            "house_w": self._num("plant_consumed_power", "power"),
            "grid_w": self._num("plant_grid_sensor_active_power", "power"),
            "battery_w": self._num("plant_ess_power", "power"),
            "soe": self._num("plant_ess_soc"),
            "solar_kwh": self._num("plant_accumulated_pv_energy", "energy"),
            "charged_kwh": self._num("plant_accumulated_battery_charge_energy", "energy"),
            "discharged_kwh": self._num("plant_accumulated_battery_discharge_energy", "energy"),
            "import": self._num("plant_accumulated_grid_import_energy", "energy"),
            "export": self._num("plant_accumulated_grid_export_energy", "energy"),
            "inverter_status": self._text("plant_running_state"),
            "grid_on": self._grid_on(),
        }

    def electric(self):
        temp = self._num("inverter_pcs_internal_temperature")
        state = self.state(self._id("inverter_pcs_internal_temperature"))
        unit = state.attributes.get("unit_of_measurement") if state else None
        temp_c = temp if unit == "°C" else (temp - 32) * 5 / 9 if unit == "°F" and temp is not None else None
        return {
            "ac_w": self._num("inverter_active_power", "power"),
            "ac_v": self._num("inverter_phase_a_voltage"),
            "ac_a": self._num("inverter_phase_a_current"),
            "hz": self._num("inverter_grid_frequency"),
            "dc_w": self._num("plant_sigen_photovoltaic_power", "power"),
            "temp": temp, "temp_unit": unit, "temp_c": temp_c,
            "status": self._text("plant_running_state"),
            "grid_on": self._grid_on(),
            "produced_kwh": self._num("plant_accumulated_pv_energy", "energy"),
            "imported_kwh": self._num("plant_accumulated_grid_import_energy", "energy"),
            "exported_kwh": self._num("plant_accumulated_grid_export_energy", "energy"),
            "battery_soh": self._num("plant_ess_soh"),
            # Explicitly no grid L1/L2: these sensors measure inverter output.
            # No claimed voltage health range until configured for the site.
            "voltage_health_unconfigured": True,
        }

    def not_available(self):
        # No single DC bus voltage/current or grid leg measurements mapped here.
        return {"dc_v", "dc_a", "l1_v", "l2_v", "l1_a", "l2_a"}

    def dashboard_grid(self):
        return {"import": self._id("plant_accumulated_grid_import_energy"),
                "export": self._id("plant_accumulated_grid_export_energy"),
                "power": self._id("plant_grid_sensor_active_power")}
