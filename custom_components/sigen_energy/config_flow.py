"""Setting up Sigen Energy for ELAN: pick the data source; options: settings and the rate plan."""

from __future__ import annotations

from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY,
    CONF_PRICE_ENTITY,
    CONF_PUBLISH_AUTO,
    CONF_PUBLISH_DIR,
    CONF_PUBLISH_PNG,
    CONF_SNAPSHOT_FILE,
    CONF_TYPICAL_LOOKUP,
    DOMAIN,
    ENERGY_OPTIONS,
)
from .sources import SOURCE_ENPHASE, SOURCE_SOLAREDGE, SOURCE_SIGENERGY
from .sources.enphase import (
    ARRAYS_BEHIND,
    ARRAYS_SEPARATE,
    CONF_ARRAYS,
    CONF_ENVOYS,
    CONF_MAIN,
    ENPHASE_DOMAIN,
    enable_power_screen_readings,
    has_grid_ct,
)
from .sources.solaredge import SOLAREDGE_DOMAINS

ARRAY_OPTIONS = [
    selector.SelectOptionDict(value=ARRAYS_BEHIND, label="Behind the main grid meter (they feed the house panel)"),
    selector.SelectOptionDict(value=ARRAYS_SEPARATE, label="Separate (their output does not pass the main grid meter)"),
]


class InnovoEnergyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def _candidates(self) -> dict[str, tuple[str, str, ConfigEntry]]:
        """Data sources found on this system: {value: (label, kind, brand entry)}."""
        found = {}
        for entry in self.hass.config_entries.async_entries("sigen"):
            found[f"{SOURCE_SIGENERGY}:sigen:{entry.entry_id}"] = (
                f"Sigenergy - {entry.title} (single-phase test adapter)", SOURCE_SIGENERGY, entry)
        return found

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        candidates = self._candidates()
        if not candidates:
            return self.async_abort(reason="no_source")
        if user_input is not None:
            kind, domain, entry_id = user_input["source"].split(":", 2)
            if kind == SOURCE_ENPHASE:
                return await self.async_step_enphase()
            await self.async_set_unique_id(f"{kind}:{entry_id}")
            self._abort_if_unique_id_configured()
            label, _, brand_entry = candidates[user_input["source"]]
            # a site moving from Innovo Solar Edge keeps its energy settings
            options = {k: brand_entry.options[k] for k in ENERGY_OPTIONS if k in brand_entry.options}
            return self.async_create_entry(
                title=f"Sigen Energy for ELAN ({label.split(' - ')[0]})",
                data={"source": kind, "source_domain": domain, "source_entry_id": entry_id},
                options=options,
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("source", default=next(iter(candidates))): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[selector.SelectOptionDict(value=k, label=v[0])
                                                       for k, v in candidates.items()]))}),
        )

    async def async_step_enphase(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Enphase: which Envoy has the grid meter, how the other arrays are wired."""
        envoys = self.hass.config_entries.async_entries(ENPHASE_DOMAIN)
        if user_input is not None:
            main = user_input[CONF_MAIN]
            await self.async_set_unique_id(f"{SOURCE_ENPHASE}:{main}")
            self._abort_if_unique_id_configured()
            if user_input.get("enable_readings", True):
                if enable_power_screen_readings(self.hass, main):
                    self.hass.config_entries.async_schedule_reload(main)  # the Envoy picks them up
            return self.async_create_entry(
                title="Sigen Energy for ELAN (Enphase)",
                data={"source": SOURCE_ENPHASE, CONF_ENVOYS: [e.entry_id for e in envoys], CONF_MAIN: main,
                      CONF_ARRAYS: user_input.get(CONF_ARRAYS, ARRAYS_BEHIND)},
            )
        main = next((e for e in envoys if has_grid_ct(self.hass, e.entry_id)), envoys[0])
        fields: dict = {
            vol.Required(CONF_MAIN, default=main.entry_id): selector.SelectSelector(selector.SelectSelectorConfig(
                options=[selector.SelectOptionDict(value=e.entry_id, label=e.title + (" (grid meter)" if has_grid_ct(
                    self.hass, e.entry_id) else "")) for e in envoys])),
        }
        if len(envoys) > 1:
            fields[vol.Required(CONF_ARRAYS, default=ARRAYS_BEHIND)] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=ARRAY_OPTIONS))
        fields[vol.Optional("enable_readings", default=True)] = cv.boolean
        return self.async_show_form(step_id="enphase", data_schema=vol.Schema(fields))

    async def async_step_import(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Handed over by Innovo Solar Edge 2.0 when a site's energy model moves here."""
        brand_entry = self.hass.config_entries.async_get_entry(data["source_entry_id"])
        if brand_entry is None:
            return self.async_abort(reason="no_source")
        await self.async_set_unique_id(f"{data['source']}:{brand_entry.entry_id}")
        self._abort_if_unique_id_configured()
        options = {k: brand_entry.options[k] for k in ENERGY_OPTIONS if k in brand_entry.options}
        return self.async_create_entry(title="Sigen Energy for ELAN (SolarEdge)", data=dict(data), options=options)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return InnovoEnergyOptionsFlow()


class InnovoEnergyOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["settings", "rate_plan"])

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            folder = (user_input.get(CONF_PUBLISH_DIR) or "").strip()
            if folder and (not folder.startswith("/") or ".." in folder.split("/")):
                errors[CONF_PUBLISH_DIR] = "invalid_publish_dir"
            else:
                data = {**self.config_entry.options, **user_input, CONF_PUBLISH_AUTO: True}  # chosen: never auto-set again
                if folder:
                    data[CONF_PUBLISH_DIR] = folder.rstrip("/")
                else:
                    data.pop(CONF_PUBLISH_DIR, None)
                if not user_input.get(CONF_PRICE_ENTITY):
                    data.pop(CONF_PRICE_ENTITY, None)
                return self.async_create_entry(title="", data=data)
        o = user_input or self.config_entry.options
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema({
                vol.Optional(CONF_PRICE_ENTITY, description={"suggested_value": o.get(CONF_PRICE_ENTITY)}):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(CONF_TYPICAL_LOOKUP, default=o.get(CONF_TYPICAL_LOOKUP, True)): cv.boolean,
                vol.Optional(CONF_BATTERY, default=o.get(CONF_BATTERY, True)): cv.boolean,
                vol.Optional(CONF_SNAPSHOT_FILE, default=o.get(CONF_SNAPSHOT_FILE, False)): cv.boolean,
                vol.Optional(CONF_PUBLISH_DIR, description={"suggested_value": o.get(CONF_PUBLISH_DIR)}): str,
                vol.Optional(CONF_PUBLISH_PNG, default=o.get(CONF_PUBLISH_PNG, False)): cv.boolean,
                **self._enphase_fields(o),
            }),
            errors=errors,
        )

    def _enphase_fields(self, o) -> dict:
        data = self.config_entry.data
        if data.get("source") != SOURCE_ENPHASE or len(data.get(CONF_ENVOYS) or []) < 2:
            return {}
        return {vol.Optional(CONF_ARRAYS, default=o.get(CONF_ARRAYS, data.get(CONF_ARRAYS, ARRAYS_BEHIND))):
                selector.SelectSelector(selector.SelectSelectorConfig(options=ARRAY_OPTIONS))}

    async def async_step_rate_plan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit the manual time-of-use rate plan."""
        from .tariff import format_months, format_rows, parse_months, parse_rows

        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
        model = entry_data.get("energy") if isinstance(entry_data, dict) else None
        if model is None:
            return self.async_abort(reason="energy_not_loaded")

        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            try:
                seasons = []
                for n in (1, 2):
                    months = (user_input.get(f"season{n}_months") or "").strip()
                    weekday = (user_input.get(f"season{n}_weekday") or "").strip()
                    if not months and not weekday:
                        continue
                    season = {
                        "name": user_input.get(f"season{n}_name") or f"Season {n}",
                        "months": parse_months(months) if months else list(range(1, 13)),
                        "weekday": parse_rows(weekday),
                    }
                    weekend = parse_rows(user_input.get(f"season{n}_weekend") or "")
                    if weekend:
                        season["weekend"] = weekend
                    seasons.append(season)
                model.tariff.set_plan({
                    "name": user_input.get("name") or "Rate plan",
                    "currency": user_input.get("currency") or self.hass.config.currency,
                    "tier_period": "month",
                    "seasons": seasons,
                })
                return self.async_create_entry(title="", data=dict(self.config_entry.options))
            except (HomeAssistantError, ValueError) as err:
                errors["base"] = "invalid_plan"
                placeholders["error"] = str(err)

        plan = model.tariff.plan or {}
        seasons = plan.get("seasons") or []

        def season_value(n: int, key: str) -> str:
            if user_input is not None:
                return user_input.get(f"season{n}_{key}") or ""
            if len(seasons) < n:
                return ""
            season = seasons[n - 1]
            if key == "name":
                return season.get("name") or ""
            if key == "months":
                return format_months(season.get("months"))
            return format_rows(season.get(key))

        multiline = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
        fields: dict = {
            vol.Optional("name", description={"suggested_value": (user_input or plan).get("name")}): str,
            vol.Optional("currency", description={
                "suggested_value": (user_input or plan).get("currency") or self.hass.config.currency}): str,
        }
        for n in (1, 2):
            fields[vol.Optional(f"season{n}_name", description={"suggested_value": season_value(n, "name")})] = str
            fields[vol.Optional(f"season{n}_months", description={"suggested_value": season_value(n, "months")})] = str
            fields[vol.Optional(f"season{n}_weekday", description={"suggested_value": season_value(n, "weekday")})] = multiline
            fields[vol.Optional(f"season{n}_weekend", description={"suggested_value": season_value(n, "weekend")})] = multiline
        return self.async_show_form(step_id="rate_plan", data_schema=vol.Schema(fields), errors=errors,
                                    description_placeholders=placeholders)
