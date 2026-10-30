"""Moving a site's energy layer from Innovo Solar Edge (1.x) to Sigen Energy for ELAN.

Up to Innovo Solar Edge 1.21 the energy model, its entities, the rate plan and the
screens lived inside that integration. Sigen Energy for ELAN takes them over once:

* the entities move to this integration with the SAME entity ids and unique ids, so
  their history, long-term statistics, the Energy dashboard and controllers that
  read them (the ELAN driver) carry on unchanged;
* the stored model (daily history, today's counters, rate plan, settings, peaks,
  looks) is copied to this integration's store;
* the screens web app's state (generated looks) is copied.

It only runs while the old energy model is NOT running (Innovo Solar Edge 2.0 has
none); otherwise setup stops with a clear message, so the two can never both
create sensor.energy_*.
"""

from __future__ import annotations

import logging
import os
import shutil

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN, LEGACY_DOMAIN

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1


async def async_migrate_from_legacy(hass: HomeAssistant, entry: ConfigEntry, uid_base: str) -> None:
    """Take over a site's energy layer from Innovo Solar Edge 1.x, once (safe to repeat)."""
    if entry.data.get("source_domain") != LEGACY_DOMAIN:
        return
    legacy_id = entry.data["source_entry_id"]

    running = hass.data.get(LEGACY_DOMAIN, {}).get(legacy_id)
    if isinstance(running, dict) and running.get("energy") is not None:
        raise ConfigEntryError(
            "Innovo Solar Edge on this system still runs its own energy model. Update Innovo Solar Edge "
            "to 2.0 or newer (HACS) and restart Home Assistant; Sigen Energy for ELAN then takes over the energy "
            "entities, history, rate plan and screens."
        )

    # 1. the stored model (only when this integration has none yet)
    new_store = Store(hass, STORE_VERSION, f"{DOMAIN}.energy.{entry.entry_id}")
    if await new_store.async_load() is None:
        old = await Store(hass, STORE_VERSION, f"{LEGACY_DOMAIN}.energy.{legacy_id}").async_load()
        if old:
            await new_store.async_save(old)
            _LOGGER.info("Took over the energy model's stored data from Innovo Solar Edge (%d days of history)",
                         len(old.get("history") or []))

    # 2. the screens web app's state (the generated looks)
    old_state = hass.config.path(".storage", f"{LEGACY_DOMAIN}.webapp.json")
    new_state = hass.config.path(".storage", f"{DOMAIN}.webapp.json")
    if os.path.exists(old_state) and not os.path.exists(new_state):
        await hass.async_add_executor_job(shutil.copy2, old_state, new_state)

    # 3. the entities: same entity id and unique id, now provided by this integration
    from homeassistant.helpers.entity import entity_sources

    reg = er.async_get(hass)
    prefix = f"{uid_base}_"
    loaded = entity_sources(hass)
    moved = 0
    for ent in list(reg.entities.values()):
        if ent.platform != LEGACY_DOMAIN or not ent.unique_id.startswith(prefix):
            continue
        if ent.entity_id in loaded:  # (only an old Innovo Solar Edge would provide it)
            raise ConfigEntryError(f"{ent.entity_id} is still provided by Innovo Solar Edge; update it to 2.0")
        # (the unique id stays the same; passing it again counts as a clash with itself)
        reg.async_update_entity_platform(ent.entity_id, DOMAIN, new_config_entry_id=entry.entry_id, new_device_id=None)
        moved += 1

    # 4. the old, now empty "SolarEdge Energy" device
    dev_reg = dr.async_get(hass)
    if hasattr(dev_reg, "async_get_device_by_identifier"):  # HA 2026.x
        old_device = dev_reg.async_get_device_by_identifier((LEGACY_DOMAIN, uid_base), entry.data["source_entry_id"])
    else:
        old_device = dev_reg.async_get_device(identifiers={(LEGACY_DOMAIN, uid_base)})
    if old_device is not None and not er.async_entries_for_device(reg, old_device.id, include_disabled_entities=True):
        dev_reg.async_remove_device(old_device.id)
    if moved:
        _LOGGER.info("Took over %d energy entities from Innovo Solar Edge (same entity ids)", moved)
