"""The YASNO cabinet integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .api import YasnoApiError
from .const import (
    ATTR_ACCOUNT_ID,
    ATTR_READINGS,
    DOMAIN,
    SERVICE_SEND_METER_READINGS,
    SERVICE_UPDATE_DATA,
)
from .coordinator import YasnoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SEND_METER_READINGS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ACCOUNT_ID): cv.string,
        vol.Required(ATTR_READINGS): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required("zone"): cv.string,
                        vol.Required("value"): vol.Coerce(float),
                    }
                )
            ],
        ),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up YASNO from a config entry."""
    coordinator = YasnoDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def handle_send_meter_readings(call: ServiceCall) -> None:
        """Handle send meter readings service call."""
        account_id = call.data[ATTR_ACCOUNT_ID]
        readings = call.data[ATTR_READINGS]

        try:
            result = await coordinator.api.async_send_meter_readings(account_id, readings)
            _LOGGER.info(
                f"Meter readings sent successfully. New balance: {result.get('balance')}"
            )
            await coordinator.async_refresh()
        except YasnoApiError as err:
            _LOGGER.error(f"Failed to send meter readings: {err}")
            raise

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_METER_READINGS,
        handle_send_meter_readings,
        schema=SEND_METER_READINGS_SCHEMA,
    )

    async def handle_update_data(call: ServiceCall) -> None:
        """Handle update data service call."""
        _LOGGER.info("Force updating YASNO data")
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_DATA,
        handle_update_data,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
