"""Data update coordinator for YASNO."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import YasnoApiClient, YasnoApiError, YasnoAuthenticationError
from .const import (
    CONF_ACCOUNT_ID,
    CONF_CABINET_URL,
    CONF_COOKIE,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    EVENT_DATA_UPDATED,
)

_LOGGER = logging.getLogger(__name__)


class YasnoDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for YASNO cabinet polling."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        self.entry = entry
        session = async_get_clientsession(hass)
        self.api = YasnoApiClient(
            session=session,
            cabinet_url=entry.data[CONF_CABINET_URL],
            cookie=entry.data.get(CONF_COOKIE),
            account_id=entry.data.get(CONF_ACCOUNT_ID),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=entry.options.get(CONF_SCAN_INTERVAL, 60)),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from YASNO."""
        try:
            data = await self.api.async_get_data()
        except YasnoAuthenticationError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except YasnoApiError as err:
            raise UpdateFailed(str(err)) from err

        self.hass.bus.async_fire(
            EVENT_DATA_UPDATED,
            {
                "balance": data.get("balance"),
                "debt": data.get("debt"),
            },
        )
        return data
