"""Config flow for YASNO cabinet integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig

from .api import YasnoApiClient, YasnoApiError, YasnoAuthenticationError
from .const import (
    CONF_ACCOUNT_ID,
    CONF_CABINET_URL,
    CONF_COOKIE,
    CONF_SCAN_INTERVAL,
    DEFAULT_CABINET_URL,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)


class YasnoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for YASNO."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Mapping[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(
                user_input.get(CONF_ACCOUNT_ID) or user_input[CONF_CABINET_URL]
            )
            self._abort_if_unique_id_configured()

            valid = await self._async_validate_input(user_input, errors)
            if valid:
                data = {
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_CABINET_URL: user_input[CONF_CABINET_URL],
                    CONF_COOKIE: user_input.get(CONF_COOKIE),
                    CONF_ACCOUNT_ID: user_input.get(CONF_ACCOUNT_ID),
                }
                options = {CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL]}
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=data, options=options
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Required(CONF_CABINET_URL, default=DEFAULT_CABINET_URL): str,
                    vol.Optional(CONF_COOKIE): str,
                    vol.Optional(CONF_ACCOUNT_ID): str,
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL_MINUTES
                    ): NumberSelector(
                        NumberSelectorConfig(min=5, max=1440, mode="box", step=5)
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_validate_input(
        self, user_input: Mapping[str, Any], errors: dict[str, str]
    ) -> bool:
        """Validate by performing a real request."""
        has_cookie = bool(user_input.get(CONF_COOKIE))
        if not has_cookie:
            errors["base"] = "missing_auth"
            return False

        session = async_get_clientsession(self.hass)
        client = YasnoApiClient(
            session=session,
            cabinet_url=user_input[CONF_CABINET_URL],
            cookie=user_input.get(CONF_COOKIE),
            account_id=user_input.get(CONF_ACCOUNT_ID),
        )
        try:
            await client.async_get_data()
        except YasnoAuthenticationError:
            errors["base"] = "auth"
            return False
        except YasnoApiError:
            errors["base"] = "cannot_connect"
            return False
        return True

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return YasnoOptionsFlow(config_entry)


class YasnoOptionsFlow(config_entries.OptionsFlow):
    """Handle YASNO options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._entry = config_entry

    async def async_step_init(
        self, user_input: Mapping[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            test_data = {
                CONF_CABINET_URL: self._entry.data[CONF_CABINET_URL],
                CONF_COOKIE: user_input[CONF_COOKIE],
                CONF_ACCOUNT_ID: self._entry.data.get(CONF_ACCOUNT_ID),
            }
            if await self._async_validate_input(test_data, errors):
                new_data = {
                    **self._entry.data,
                    CONF_COOKIE: user_input[CONF_COOKIE],
                }
                self.hass.config_entries.async_update_entry(self._entry, data=new_data)
                return self.async_create_entry(
                    title="",
                    data={CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL]},
                )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_COOKIE,
                        default=self._entry.data.get(CONF_COOKIE, ""),
                    ): str,
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self._entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(min=5, max=1440, mode="box", step=5)
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_validate_input(
        self, user_input: Mapping[str, Any], errors: dict[str, str]
    ) -> bool:
        """Validate by performing a real request."""
        session = async_get_clientsession(self.hass)
        client = YasnoApiClient(
            session=session,
            cabinet_url=user_input[CONF_CABINET_URL],
            cookie=user_input.get(CONF_COOKIE),
            account_id=user_input.get(CONF_ACCOUNT_ID),
        )
        try:
            await client.async_get_data()
        except YasnoAuthenticationError:
            errors["base"] = "auth"
            return False
        except YasnoApiError:
            errors["base"] = "cannot_connect"
            return False
        return True
