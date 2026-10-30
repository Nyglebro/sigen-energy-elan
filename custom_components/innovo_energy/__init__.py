"""Sigen Energy for ELAN: one energy model, the same entities and the same screens for any
solar / battery brand (SolarEdge today; Enphase and Tesla next).

It reads the brand's own Home Assistant integration through a data source
(sources/), keeps the energy model (live flows, daily totals, costs, savings,
performance, rate plans), creates the universal sensor.energy_* entities that
controllers read, and publishes the dashboard screens through the screens web app.
"""

from __future__ import annotations

import logging
import os

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import ConfigType

from .const import AURA_WEB_ICONS, CONF_PUBLISH_AUTO, CONF_PUBLISH_DIR, DOMAIN, LEGACY_DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
ENTRY = {vol.Optional("config_entry_id"): cv.string}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    _register_services(hass, DOMAIN)
    return True


def _register_services(hass: HomeAssistant, domain: str) -> None:
    """The energy actions. Also registered under innovo_solar_edge's name (when that
    doesn't provide them any more), so anything calling the old names keeps working."""

    def energy_model(call: ServiceCall):
        loaded = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED
                  and e.entry_id == call.data.get("config_entry_id", e.entry_id)]
        if not loaded:
            raise HomeAssistantError("Sigen Energy for ELAN is not running")
        return hass.data[DOMAIN][loaded[0].entry_id]["energy"]

    async def provision_dashboards(call: ServiceCall) -> None:
        """Build the Energy dashboard and the Solar & Energy dashboard."""
        from .provision import DEFAULT_TITLE, DEFAULT_URL_PATH, async_provision

        model = energy_model(call)
        await async_provision(hass, model.entry, energy_dashboard=call.data.get("energy_dashboard", True),
                              dashboard=call.data.get("dashboard", True),
                              url_path=call.data.get("url_path", DEFAULT_URL_PATH),
                              title=call.data.get("title", DEFAULT_TITLE))

    async def set_tariff(call: ServiceCall) -> None:
        """Replace the rate plan (JSON) - used by home-control platforms."""
        energy_model(call).tariff.set_plan(dict(call.data["plan"]))

    async def set_tariff_rates(call: ServiceCall) -> None:
        """Change prices in the current plan by period name."""
        rates = {str(k): float(v) for k, v in dict(call.data["rates"]).items()}
        energy_model(call).tariff.set_rates(rates, call.data.get("season"))

    async def generate_screens(call: ServiceCall) -> ServiceResponse:
        """Publish the screens in a look (graphics style + colours + mode)."""
        from .control import async_command

        snap = energy_model(call).snapshot
        if not snap.publish_dir:
            raise HomeAssistantError("Set a publish folder in the integration settings first")
        result = await async_command(hass, {"action": "generate", "style": call.data["style"],
                                            "palette": call.data["colours"], "mode": call.data.get("mode", "dark")})
        return {"look": result["look"], "folder": os.path.join(snap.publish_dir, result["look"])}

    async def remove_screens(call: ServiceCall) -> None:
        from .control import async_command

        energy_model(call)
        await async_command(hass, {"action": "remove", "look": call.data["look"]})

    async def clean_screens(call: ServiceCall) -> ServiceResponse:
        """Delete every published image or folder that isn't in use."""
        from .control import async_command

        energy_model(call)
        return {"removed": (await async_command(hass, {"action": "clean"}))["cleaned"]}

    services = {
        "set_tariff": (set_tariff, vol.Schema({**ENTRY, vol.Required("plan"): dict}), None),
        "set_tariff_rates": (set_tariff_rates, vol.Schema({**ENTRY, vol.Required("rates"): dict,
                                                           vol.Optional("season"): cv.string}), None),
        "provision_dashboards": (provision_dashboards, vol.Schema({
            **ENTRY, vol.Optional("energy_dashboard", default=True): cv.boolean,
            vol.Optional("dashboard", default=True): cv.boolean,
            vol.Optional("url_path"): cv.string, vol.Optional("title"): cv.string}), None),
        "generate_screens": (generate_screens, vol.Schema({
            **ENTRY, vol.Required("style"): cv.string, vol.Required("colours"): cv.string,
            vol.Optional("mode", default="dark"): cv.string}), SupportsResponse.OPTIONAL),
        "remove_screens": (remove_screens, vol.Schema({**ENTRY, vol.Required("look"): cv.string}), None),
        "clean_screens": (clean_screens, vol.Schema(ENTRY), SupportsResponse.OPTIONAL),
    }
    for name, (handler, schema, response) in services.items():
        if domain != DOMAIN and hass.services.has_service(domain, name):
            continue  # the old integration still provides it
        hass.services.async_register(domain, name, handler, schema=schema,
                                     supports_response=response or SupportsResponse.NONE)


def _aura_publish_dir() -> str | None:
    """The screens folder on an Innovo Aura, if this is one (and it is writable)."""
    if os.path.isdir(AURA_WEB_ICONS) and os.access(AURA_WEB_ICONS, os.W_OK):
        return os.path.join(AURA_WEB_ICONS, "solar")
    return None


async def _async_auto_publish(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Once per install: on an Innovo Aura, publish the screens to its web folder
    (http://<box>/icons/solar/) without any setup. Runs before the options listener is
    added, so it doesn't trigger a reload; saving the settings marks it done, so a
    cleared folder stays cleared."""
    if entry.options.get(CONF_PUBLISH_AUTO):
        return
    options = {**entry.options, CONF_PUBLISH_AUTO: True}
    folder = await hass.async_add_executor_job(_aura_publish_dir)
    if folder and not entry.options.get(CONF_PUBLISH_DIR):
        options[CONF_PUBLISH_DIR] = folder
        _LOGGER.info("Innovo Aura detected: publishing the energy screens to %s", folder)
    hass.config_entries.async_update_entry(entry, options=options)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .energy import EnergyModel
    from .sources import make_source

    from homeassistant.exceptions import ConfigEntryError
    from homeassistant.helpers import entity_registry as er

    # Solar Pro requires fixed common entity IDs and a shared image folder.
    # Refuse concurrent providers instead of silently creating _2 entities.
    registry = er.async_get(hass)
    conflicts = [e.entity_id for e in registry.entities.values()
                 if e.platform in ("sigen_energy", "innovo_solar_edge")
                 and e.entity_id.startswith(("sensor.energy_", "image.energy_", "number.energy_"))]
    if hass.data.get("sigen_energy") or conflicts:
        raise ConfigEntryError(
            "Remove the old Sigen Energy or Innovo Solar Edge energy entry before setting up Sigen Energy for ELAN. "
            "Both providers use the same Solar Pro entity names and image folder. Back up first."
        )
    if any(key != entry.entry_id for key in hass.data.get(DOMAIN, {})):
        raise ConfigEntryError("Only one Sigen Energy for ELAN entry can run at a time")
    source = make_source(hass, entry)
    await source.async_setup()  # ConfigEntryNotReady until the brand's integration is up
    await _async_auto_publish(hass, entry)

    model = EnergyModel(hass, entry, source)
    await model.async_load()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"energy": model, "source": source}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    model.async_start()
    if model.snapshot.publish_dir:
        # the screens web app (published screens, looks, previews, viewer page) runs as its own process
        from .control import WebAppSupervisor

        webapp = WebAppSupervisor(hass)
        webapp.start()
        hass.data[DOMAIN][entry.entry_id]["webapp"] = webapp

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        if data.get("webapp") is not None:
            await data["webapp"].async_stop()
        await data["energy"].async_stop()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Integration removed: take down the published screens and viewer page."""
    from .snapshot import remove_published

    if folder := entry.options.get(CONF_PUBLISH_DIR):
        await hass.async_add_executor_job(remove_published, folder)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
