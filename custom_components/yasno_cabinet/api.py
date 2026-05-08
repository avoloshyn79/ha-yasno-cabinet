"""Client for reading YASNO API data."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
import uuid

from aiohttp import ClientError, ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)

DEFAULT_API_BASE_URL = "https://app.yasno.ua"
LOGIN_BASE_URL = "https://login.yasno.ua"

class YasnoApiError(Exception):
    """Base error for YASNO API."""

class YasnoAuthenticationError(YasnoApiError):
    """Authentication failed."""

class YasnoApiClient:
    """Client for YASNO web API used by the personal cabinet."""

    def __init__(
        self,
        session: ClientSession,
        cabinet_url: str,
        cookie: str | None,
        account_id: str | None = None,
    ) -> None:
        self._session = session
        self._api_base_url = cabinet_url.rstrip("/") if cabinet_url else DEFAULT_API_BASE_URL
        self._cookie = (cookie or "").strip()
        self._account_id = account_id
        self._device_id = str(uuid.uuid4())
        self._auth_in_progress = False

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch selected account data from API endpoints."""
        accounts_data = await self._api_get("/api/account-service/users/me/accounts")
        if not isinstance(accounts_data, list) or not accounts_data:
            raise YasnoApiError("No accounts found in YASNO profile")

        account = self._select_account(accounts_data)
        account_id = str(account["id"])

        debt_data, consumption_data, last_fees_data, tariff_data, payments_history_data, meter_readings_data = await asyncio.gather(
            self._api_get("/api/account-service/users/me/b2c/debt"),
            self._api_get("/api/account-service/statistics/consumptions-by-accounts"),
            self._api_get("/api/account-service/users/me/accounts/b2c/last-fees"),
            self._api_get(f"/api/account-service/users/me/accounts/v3/b2c/{account_id}/tariff"),
            self._api_get(f"/api/payment-service/payment/history?accountId={account_id}&limit=1&offset=0"),
            self._api_get(f"/api/account-service/users/me/b2c/meter-readings/history/{account_id}?includeRejected=false&limit=1&offset=0"),
        )

        debt_info = self._extract_account_mapping(debt_data, account_id)
        consumption_info = self._extract_account_mapping(consumption_data, account_id)
        last_fee_raw = self._extract_account_mapping(last_fees_data, account_id)
        tariff_prices = self._extract_tariff_prices(tariff_data)
        last_payment_info = self._extract_last_payment(payments_history_data)
        meter_readings_info = self._extract_last_meter_readings(meter_readings_data)

        balance_value = self._safe_float(self._mapping_value(debt_info, "balance"))
        debt_value = self._safe_float(self._mapping_value(debt_info, "balance"))
        if debt_value == balance_value:
            debt_value = 0.0

        return {
            "balance": balance_value,
            "debt": debt_value,
            "consumption_kwh": self._extract_latest_consumption(consumption_info),
            "last_payment": last_payment_info.get("amount"),
            "last_payment_date": last_payment_info.get("date"),
            "last_fee_date": last_fee_raw if isinstance(last_fee_raw, str) else None,
            "account_number": account.get("accountNumber"),
            "account_id": account_id,
            "account_name": account.get("accountName"),
            "address": (account.get("details", {}).get("b2C", {}) or {}).get("address"),
            "region": account.get("region"),
            "supplier": account.get("supplier"),
            "tariff_name": tariff_data.get("overview", {}).get("name"),
            "tariff_price_day": tariff_prices.get("day"),
            "tariff_price_night": tariff_prices.get("night"),
            "tariff_price_single": tariff_prices.get("single"),
            "dso_name": tariff_data.get("distributionSystemOperator", {}).get("name"),
            "meter_reading_day": meter_readings_info.get("day"),
            "meter_reading_night": meter_readings_info.get("night"),
            "meter_reading_alltime": meter_readings_info.get("alltime"),
            "meter_reading_date": meter_readings_info.get("date"),
            "raw_payload": {
                "account": account,
                "debt": debt_info,
                "consumption": consumption_info,
                "last_fees": last_fees_data,
                "tariff": tariff_data,
                "payments_history": payments_history_data,
                "meter_readings": meter_readings_data,
            },
        }

    async def async_send_meter_readings(
        self, account_id: str, meter_readings: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Send meter readings to YASNO API."""
        payload = {"meteringReadings": meter_readings}
        path = f"/api/account-service/users/me/b2c/meter-readings/{account_id}"
        return await self._api_post(path, payload)

    def _extract_last_payment(self, payments_data: dict[str, Any]) -> dict[str, Any]:
        """Extract last payment info from payments history data."""
        if not isinstance(payments_data, dict) or not (items := payments_data.get("items")):
            return {}
        if items and isinstance(items, list) and len(items) > 0:
            last_payment = items[0]
            return {
                "amount": self._safe_float(last_payment.get("amount")),
                "date": last_payment.get("createdOn"),
            }
        return {}

    def _extract_last_meter_readings(self, readings_data: dict[str, Any]) -> dict[str, Any]:
        """Extract last meter readings from meter readings history data."""
        if not isinstance(readings_data, dict) or not (items := readings_data.get("items")):
            return {}
        if items and isinstance(items, list) and len(items) > 0:
            last_reading = items[0]
            readings_info = {"date": last_reading.get("createdOn")}
            if metering_readings := last_reading.get("meteringReadings"):
                for reading in metering_readings:
                    zone = reading.get("zone", "").lower()
                    value = self._safe_float(reading.get("value"))
                    if zone:
                        readings_info[zone] = value
            return readings_info
        return {}

    def _extract_tariff_prices(self, tariff_data: dict[str, Any]) -> dict[str, float]:
        """Extract prices from tariff data."""
        prices = {}
        if not isinstance(tariff_data, dict):
            return prices
        try:
            for period in tariff_data.get("priceAtPeriods", []):
                for tier in period.get("tiers", []):
                    for t in tier.get("tariff", []):
                        zone = t.get("zone")
                        price = t.get("price")
                        if zone and price is not None:
                            prices[zone.lower()] = float(price)
        except (TypeError, ValueError):
            pass
        return prices

    async def _api_get(self, path: str, _retry_after_auth: bool = True) -> Any:
        """Perform authenticated GET request to YASNO API."""
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://yasno.ua",
            "Referer": "https://yasno.ua/",
            "User-Agent": "HomeAssistant-YASNO/1.0",
            "x-platform": "Web",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie

        url = f"{self._api_base_url}{path}"
        _LOGGER.debug(f"GET request to {path}")
        try:
            response = await self._session.get(
                url,
                headers=headers,
                allow_redirects=False,
                timeout=ClientTimeout(total=30),
            )
        except TimeoutError as err:
            _LOGGER.error(f"Timeout reaching YASNO API endpoint: {path} (30s)")
            raise YasnoApiError(f"Cannot reach YASNO API endpoint: {path} (timeout)") from err
        except ClientError as err:
            _LOGGER.error(f"Network error reaching YASNO API endpoint: {path}: {err}")
            raise YasnoApiError(f"Cannot reach YASNO API endpoint: {path} ({type(err).__name__})") from err

        _LOGGER.debug(f"GET {path} returned HTTP {response.status}")
        if response.status in (401, 403):
            _LOGGER.warning(f"Authentication error (HTTP {response.status}) for {path}, attempting re-login...")
            raise YasnoAuthenticationError("Authentication failed. Cookie/session is invalid.")
        if response.status >= 400:
            error_text = await response.text()
            _LOGGER.error(f"YASNO API error HTTP {response.status} for {path}: {error_text[:200]}")
            raise YasnoApiError(f"YASNO API returned HTTP {response.status} for {path}")

        try:
            return await response.json(content_type=None)
        except ValueError as err:
            _LOGGER.error(f"Invalid JSON response for {path}: {err}")
            raise YasnoApiError(f"YASNO API returned invalid JSON for {path}") from err

    async def _api_post(
        self, path: str, payload: dict[str, Any], _retry_after_auth: bool = True
    ) -> Any:
        """Perform authenticated POST request to YASNO API."""
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://yasno.ua",
            "Referer": "https://yasno.ua/",
            "User-Agent": "HomeAssistant-YASNO/1.0",
            "x-platform": "Web",
            "Content-Type": "application/json",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie

        url = f"{self._api_base_url}{path}"
        _LOGGER.debug(f"POST request to {path} with payload keys: {list(payload.keys())}")
        try:
            response = await self._session.post(
                url,
                json=payload,
                headers=headers,
                allow_redirects=False,
                timeout=ClientTimeout(total=30),
            )
        except TimeoutError as err:
            _LOGGER.error(f"Timeout reaching YASNO API endpoint: {path} (30s)")
            raise YasnoApiError(f"Cannot reach YASNO API endpoint: {path} (timeout)") from err
        except ClientError as err:
            _LOGGER.error(f"Network error reaching YASNO API endpoint: {path}: {err}")
            raise YasnoApiError(f"Cannot reach YASNO API endpoint: {path} ({type(err).__name__})") from err

        _LOGGER.debug(f"POST {path} returned HTTP {response.status}")
        if response.status in (401, 403):
            _LOGGER.warning(f"Authentication error (HTTP {response.status}) for {path}, attempting re-login...")
            raise YasnoAuthenticationError("Authentication failed. Cookie/session is invalid.")
        if response.status >= 400:
            error_text = await response.text()
            _LOGGER.error(f"YASNO API error HTTP {response.status} for {path}: {error_text[:200]}")
            raise YasnoApiError(f"YASNO API returned HTTP {response.status} for {path}")

        try:
            return await response.json(content_type=None)
        except ValueError as err:
            _LOGGER.error(f"Invalid JSON response for {path}: {err}")
            raise YasnoApiError(f"YASNO API returned invalid JSON for {path}") from err

    def _select_account(self, accounts: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        """Select configured account or first B2C one."""
        if self._account_id is not None:
            for account in accounts:
                if str(account.get("id")) == str(self._account_id):
                    return account
            raise YasnoApiError(f"Account ID '{self._account_id}' not found in API data")

        for account in accounts:
            if account.get("customerType") == "B2C":
                return account

        return accounts[0]

    def _extract_account_mapping(self, obj: Any, account_id: str) -> Any:
        """Read value from map-like payload by account id key."""
        if isinstance(obj, Mapping):
            return obj.get(account_id)
        return None

    def _extract_latest_consumption(self, consumption_info: Any) -> float | None:
        """Get summed consumption from the latest month."""
        if not isinstance(consumption_info, Mapping):
            return None

        months = consumption_info.get("months")
        if not isinstance(months, list) or not months:
            return None

        latest_month = months[-1]
        if not isinstance(latest_month, Mapping):
            return None

        stats = latest_month.get("stats")
        if not isinstance(stats, list):
            return None

        total = 0.0
        found = False
        for stat in stats:
            if not isinstance(stat, Mapping):
                continue
            value = self._safe_float(stat.get("consumedAmount"))
            if value is None:
                continue
            total += value
            found = True
        return total if found else None

    def _mapping_value(self, obj: Any, key: str) -> Any:
        """Return mapping key value."""
        if isinstance(obj, Mapping):
            return obj.get(key)
        return None

    def _safe_float(self, value: Any) -> float | None:
        """Convert value to float safely."""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            normalized = value.replace(",", ".").strip()
            try:
                return float(normalized)
            except ValueError:
                return None
        return None

    def _first(self, values: list[str] | None) -> str | None:
        """Return first value from a list."""
        if values:
            return values[0]
        return None
