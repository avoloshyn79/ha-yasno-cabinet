"""Data update coordinator for YASNO."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from curl_cffi.requests import AsyncSession

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import YasnoApiClient, YasnoApiError, YasnoAuthenticationError
from .const import (
    CONF_ACCOUNT_ID,
    CONF_CABINET_URL,
    CONF_COOKIE,
    CONF_PASSWORD,
    CONF_PHONE,
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
        self._session = AsyncSession(impersonate="chrome")
        self.api = YasnoApiClient(
            session=self._session,
            cabinet_url=entry.data[CONF_CABINET_URL],
            cookie=entry.data.get(CONF_COOKIE),
            account_id=entry.data.get(CONF_ACCOUNT_ID),
            phone=entry.data.get(CONF_PHONE),
            password=entry.data.get(CONF_PASSWORD),
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

    async def async_shutdown(self) -> None:
        """Close the curl_cffi session on unload."""
        await super().async_shutdown()
        await self._session.close()