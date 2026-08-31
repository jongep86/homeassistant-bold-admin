"""Bold Admin: holds a full-scope Bold token and keeps it warm.

Deliberately a separate domain from the stock `bold` integration rather than a
patch to it. That one authenticates through Home Assistant Cloud (Nabu Casa's
account-linking relay), whose token is scoped for lock control only and returns
403 on any share mutation. Rather than re-authenticating a working integration
that your lock entities and dashboards depend on, this sits alongside it with
its own credentials and its own token.

It owns no locks and no control surface. Its only job is to keep a
write-capable token alive so external callers can borrow it.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import BoldAdminCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type BoldAdminConfigEntry = ConfigEntry[BoldAdminCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: BoldAdminConfigEntry) -> bool:
    """Set up Bold Admin from a config entry."""
    coordinator = BoldAdminCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BoldAdminConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
