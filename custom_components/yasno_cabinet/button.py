"""Button platform for YASNO cabinet."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import YasnoDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities from config entry."""
    coordinator: YasnoDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([YasnoRefreshButton(coordinator, config_entry)])


class YasnoRefreshButton(CoordinatorEntity[YasnoDataUpdateCoordinator], ButtonEntity):
    """Button to manually refresh YASNO data."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        coordinator: YasnoDataUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize refresh button."""
        super().__init__(coordinator)
        self._entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_refresh"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info to group button with other entities."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": "YASNO",
            "model": "Personal Cabinet",
        }

    async def async_press(self) -> None:
        """Handle button press — request coordinator refresh."""
        await self.coordinator.async_request_refresh()
