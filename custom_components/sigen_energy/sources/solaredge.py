"""SolarEdge source: reads Innovo Solar Edge (or the upstream SolarEdge Modbus Multi)
integration - its inverter, grid meter and battery entities, and its hub for what
the equipment is (meter type, battery nameplate, inverter model)."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from homeassistant.exceptions import ConfigEntryNotReady

from . import GRID_READINGS, Source

SOLAREDGE_DOMAINS = ("innovo_solar_edge", "solaredge_modbus_multi")


class SolarEdgeSource(Source):
    brand = "SolarEdge"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self.domain = entry.data.get("source_domain", "innovo_solar_edge")
        self.source_entry_id = entry.data["source_entry_id"]
        self.hub = None
        self.coordinator = None

    async def async_setup(self) -> None:
        found = self.hass.data.get(self.domain, {}).get(self.source_entry_id)
        if not isinstance(found, dict) or found.get("hub") is None:
            raise ConfigEntryNotReady(f"Waiting for the SolarEdge integration ({self.domain}) to start")
        self.hub, self.coordinator = found["hub"], found.get("coordinator")
        if not self.hub.inverters:
            raise ConfigEntryNotReady("The SolarEdge integration has no inverter yet")

    # ----- equipment -----
    @property
    def inverter(self):
        return self.hub.inverters[0]

    @property
    def uid_base(self) -> str:
        # the same unique ids the energy entities had inside Innovo Solar Edge, so a
        # site that moves to Sigen Energy for ELAN keeps its entities, history and statistics
        return f"{self.inverter.uid_base}_energy"

    @property
    def parent_entry_id(self) -> str:
        return self.source_entry_id

    @property
    def via_device(self) -> tuple[str, str]:
        return (self.domain, self.inverter.uid_base)

    @property
    def grid_meter(self):
        return next((m for m in self.hub.meters if "Import" in str(m.option)), None)

    @property
    def batteries(self) -> list:
        return list(self.hub.batteries) + list(getattr(self.hub, "der_batteries", []))

    @property
    def has_grid(self) -> bool:
        return self.grid_meter is not None

    @property
    def has_battery_hardware(self) -> bool:
        return bool(self.batteries)

    @property
    def inverter_kw(self) -> float | None:
        match = re.search(r"SE(\d{3,5})", str(getattr(self.inverter, "model", "")))
        return int(match.group(1)) / 1000 if match else None

    def nameplate_kwh(self) -> float | None:
        for battery in self.batteries:
            try:
                rated = float(battery.battery_info.B_RatedEnergy)
            except (AttributeError, TypeError, ValueError):
                continue
            if 0 < rated < 1_000_000:
                return round(rated / 1000, 2)
        return None

    def track(self, update: Callable[[], None]) -> Callable[[], None]:
        # the brand's entities write their states in their own coordinator callbacks:
        # read once they all have
        return self.coordinator.async_add_listener(lambda: self.hass.loop.call_soon(update))

    # ----- readings -----
    def read(self) -> dict[str, Any]:
        inv = self.inverter.uid_base
        grid, batteries = self.grid_meter, self.batteries
        battery = batteries[0] if batteries else None
        status = self.state(self.entity_id("sensor", f"{inv}_status"))
        vendor = self.state(self.entity_id("sensor", f"{inv}_status_vendor4"))
        grid_on = self.state(self.entity_id("binary_sensor", f"{inv}_grid_status_on_off"))
        meter_w = self.num(self.entity_id("sensor", f"{grid.uid_base}_ac_power")) if grid else None
        return {
            "inv_w": self.num(self.entity_id("sensor", f"{inv}_ac_power")),
            "dc_w": self.num(self.entity_id("sensor", f"{inv}_dc_power")),
            "ac_energy": self.num(self.entity_id("sensor", f"{inv}_ac_energy_kwh")),
            "inverter_status": _status(status.state if status else None, vendor.state if vendor else None),
            "grid_on": None if grid_on is None else grid_on.state == "on",
            "grid_w": None if meter_w is None else -meter_w,  # the meter reads + exporting
            "import": self.num(self.entity_id("sensor", f"{grid.uid_base}_imported_kwh")) if grid else None,
            "export": self.num(self.entity_id("sensor", f"{grid.uid_base}_exported_kwh")) if grid else None,
            "soe": self.num(self.entity_id("sensor", f"{battery.uid_base}_battery_soe")) if battery else None,
        }

    def electric(self) -> dict[str, Any]:
        inv = self.inverter.uid_base
        grid, batteries = self.grid_meter, self.batteries

        def num(platform, uid):
            return self.num(self.entity_id(platform, uid))

        temp = self.state(self.entity_id("sensor", f"{inv}_temp_sink"))
        try:
            t = float(temp.state) if temp else None
        except ValueError:
            t = None
        unit = (temp.attributes.get("unit_of_measurement") if temp else None) or "°C"
        status = self.state(self.entity_id("sensor", f"{inv}_status"))
        grid_on = self.state(self.entity_id("binary_sensor", f"{inv}_grid_status_on_off"))
        out = {
            "ac_w": num("sensor", f"{inv}_ac_power"),
            "dc_w": num("sensor", f"{inv}_dc_power"),
            "dc_v": num("sensor", f"{inv}_dc_voltage"),
            "dc_a": num("sensor", f"{inv}_dc_current"),
            "ac_v": num("sensor", f"{inv}_ac_voltage_ab") or num("sensor", f"{inv}_ac_voltage_an"),
            "ac_a": num("sensor", f"{inv}_ac_current"),
            "hz": num("sensor", f"{inv}_ac_frequency"),
            "temp": t, "temp_unit": unit,
            "temp_c": None if t is None else ((t - 32) * 5 / 9 if "F" in unit else t),
            "status": status.state if status else None,
            "grid_on": None if grid_on is None else grid_on.state == "on",
            "produced_kwh": num("sensor", f"{inv}_ac_energy_kwh"),
        }
        if grid:
            g = grid.uid_base
            out.update({
                "l1_v": num("sensor", f"{g}_ac_voltage_an"), "l2_v": num("sensor", f"{g}_ac_voltage_bn"),
                "l1_a": num("sensor", f"{g}_ac_current_a"), "l2_a": num("sensor", f"{g}_ac_current_b"),
                "imported_kwh": num("sensor", f"{g}_imported_kwh"), "exported_kwh": num("sensor", f"{g}_exported_kwh"),
            })
        if batteries:
            out["battery_soh"] = num("sensor", f"{batteries[0].uid_base}_battery_soh")
        return out

    def not_available(self) -> set[str]:
        # the battery is left to the "This system has a battery" setting: the inverter's
        # battery check can miss at start-up, and a missed check is not "no battery"
        out = set() if self.grid_meter else set(GRID_READINGS)
        if not self.batteries:
            out.add("battery_soh")
        return out

    def dashboard_grid(self) -> dict[str, str | None] | None:
        grid = self.grid_meter
        if grid is None:
            return None
        return {"import": self.entity_id("sensor", f"{grid.uid_base}_imported_kwh"),
                "export": self.entity_id("sensor", f"{grid.uid_base}_exported_kwh"),
                "power_inverted": self.entity_id("sensor", f"{grid.uid_base}_ac_power")}


def _status(status: str | None, vendor: str | None) -> str:
    if status is None:
        return "Offline"
    if vendor not in (None, "0x0"):
        return f"Fault {vendor}"
    if status == "I_STATUS_MPPT":
        return "Producing"
    if status in ("I_STATUS_SLEEPING", "I_STATUS_OFF", "I_STATUS_STARTING"):
        return "Sleeping"
    return status.replace("I_STATUS_", "").title()
