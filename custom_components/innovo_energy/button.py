"""Buttons (provision dashboards) of the Sigen Energy for ELAN model."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .provision import energy_buttons


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    if entities := energy_buttons(hass, entry):
        async_add_entities(entities)
