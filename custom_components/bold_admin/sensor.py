"""Diagnostic sensor so the keep-alive is visible instead of invisible.

The previous chain died silently and nobody noticed for three weeks. One
timestamp entity makes "is this still alive?" answerable at a glance, and gives
automations something to alert on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BoldAdminConfigEntry
from .const import CONF_EXPIRES_AT
from .coordinator import BoldAdminCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BoldAdminConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the diagnostic sensor."""
    async_add_entities([BoldTokenExpirySensor(entry.runtime_data, entry)])


class BoldTokenExpirySensor(
    CoordinatorEntity[BoldAdminCoordinator], SensorEntity
):
    """When the current Bold access token stops working."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Token expires"

    def __init__(
        self, coordinator: BoldAdminCoordinator, entry: BoldAdminConfigEntry
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_token_expires"

    @property
    def native_value(self) -> datetime | None:
        """Return the expiry as a timezone-aware datetime."""
        expires_at = (self.coordinator.data or {}).get(CONF_EXPIRES_AT)
        if expires_at is None:
            return None
        return datetime.fromtimestamp(expires_at, tz=UTC)
