"""Client for reading YASNO API data."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import logging
import re
import secrets
from typing import Any
import uuid

from aiohttp import ClientError, ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)

DEFAULT_API_BASE_URL = "https://app.yasno.ua"
LOGIN_BASE_URL = "https://login.yasno.ua"

# Azure AD B2C tenant/policy backing the YASNO personal cabinet login.
# Reverse-engineered from the browser login flow (login.yasno.ua HAR capture).
B2C_TENANT = "yasnomobileprod.onmicrosoft.com"
B2C_POLICY = "B2C_1A_signup_signin_web"
B2C_CLIENT_ID = "0ce1809d-fd6a-40e5-9341-4222d06c00a3"
B2C_REDIRECT_URI = f"{DEFAULT_API_BASE_URL}/api/user-service/signin-oidc"
B2C_SCOPE = (
    "openid profile "
    "https://yasnomobileprod.onmicrosoft.com/BackendAPI/user_access "
    "offline_access"
)
B2C_AUTHORIZE_URL = (
    f"{LOGIN_BASE_URL}/{B2C_TENANT}/{B2C_POLICY}/oauth2/v2.0/authorize"
)
B2C_SELF_ASSERTED_URL = f"{LOGIN_BASE_URL}/{B2C_TENANT}/{B2C_POLICY}/SelfAsserted"
B2C_CONFIRMED_URL = (
    f"{LOGIN_BASE_URL}/{B2C_TENANT}/{B2C_POLICY}/api/SelfAsserted/confirmed"
)

_LOGIN_USER_AGENT = "HomeAssistant-YASNO/1.0"

_SETTINGS_RE = re.compile(r"var SETTINGS\s*=\s*(\{.*?\});", re.DOTALL)
_FORM_ACTION_RE = re.compile(r"<form[^>]*action=['\"]([^'\"]+)['\"]")
_INPUT_TAG_RE = re.compile(r"<input[^>]*>")
_INPUT_NAME_RE = re.compile(r"name=['\"]([^'\"]+)['\"]")
_INPUT_VALUE_RE = re.compile(r"value=['\"]([^'\"]*)['\"]")

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
        phone: str | None = None,
        password: str | None = None,
    ) -> None:
        self._session = session
        self._api_base_url = cabinet_url.rstrip("/") if cabinet_url else DEFAULT_API_BASE_URL
        self._cookie = (cookie or "").strip()
        self._account_id = account_id
        self._phone = (phone or "").strip()
        self._password = password or ""
        self._device_id = str(uuid.uuid4())
        self._auth_in_progress = False

    @property
    def can_login(self) -> bool:
        """Return whether phone/password credentials are configured."""
        return bool(self._phone and self._password)

    @property
    def cookie(self) -> str:
        """Return the current session cookie string."""
        return self._cookie

    async def async_login(self) -> None:
        """Authenticate against the YASNO Azure AD B2C login and obtain a session cookie."""
        if self._auth_in_progress:
            raise YasnoAuthenticationError("Login already in progress")
        if not self._phone or not self._password:
            raise YasnoAuthenticationError("Phone number and password are required to log in")

        self._auth_in_progress = True
        try:
            csrf_token, trans_id = await self._b2c_start_login()
            await self._b2c_submit_credentials(csrf_token, trans_id)
            action_url, hidden_fields = await self._b2c_fetch_token_form(csrf_token, trans_id)
            self._cookie = await self._b2c_exchange_token(action_url, hidden_fields)
        finally:
            self._auth_in_progress = False

    async def _b2c_start_login(self) -> tuple[str, str]:
        """Load the B2C authorize page and extract the csrf token and transaction id."""
        params = {
            "client_id": B2C_CLIENT_ID,
            "redirect_uri": B2C_REDIRECT_URI,
            "response_type": "token id_token",
            "scope": B2C_SCOPE,
            "response_mode": "form_post",
            "nonce": secrets.token_urlsafe(32),
            "client_info": "1",
            "deviceId": self._device_id,
            "backLink": "",
            "state": secrets.token_urlsafe(48),
        }
        try:
            response = await self._session.get(
                B2C_AUTHORIZE_URL,
                params=params,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": _LOGIN_USER_AGENT,
                },
                timeout=ClientTimeout(total=30),
            )
            page_html = await response.text()
        except TimeoutError as err:
            raise YasnoApiError("Cannot reach YASNO login page (timeout)") from err
        except ClientError as err:
            raise YasnoApiError(f"Cannot reach YASNO login page ({type(err).__name__})") from err

        if response.status != 200:
            raise YasnoAuthenticationError(f"YASNO login page returned HTTP {response.status}")

        match = _SETTINGS_RE.search(page_html)
        if not match:
            raise YasnoAuthenticationError("Could not locate login session data on YASNO login page")
        try:
            settings = json.loads(match.group(1))
        except ValueError as err:
            raise YasnoAuthenticationError(f"Could not parse YASNO login session data: {err}") from err

        csrf_token = settings.get("csrf")
        trans_id = settings.get("transId")
        if not csrf_token or not trans_id:
            raise YasnoAuthenticationError("YASNO login page did not provide a csrf token")
        return csrf_token, trans_id

    async def _b2c_submit_credentials(self, csrf_token: str, trans_id: str) -> None:
        """Submit phone number and password to the B2C self-asserted endpoint."""
        payload = {
            "flowType": "Login",
            "phoneNumber": self._phone,
            "executeValidation": "",
            "deviceId": self._device_id,
            "messageType": "viber",
            "verificationCode": "",
            "password": self._password,
            "newWebPassword": "",
            "reenterWebPassword": "",
            "request_type": "RESPONSE",
        }
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": LOGIN_BASE_URL,
            "X-CSRF-TOKEN": csrf_token,
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": _LOGIN_USER_AGENT,
        }
        try:
            response = await self._session.post(
                B2C_SELF_ASSERTED_URL,
                params={"tx": trans_id, "p": B2C_POLICY},
                data=payload,
                headers=headers,
                timeout=ClientTimeout(total=30),
            )
            result = await response.json(content_type=None)
        except TimeoutError as err:
            raise YasnoApiError("Cannot reach YASNO login endpoint (timeout)") from err
        except ClientError as err:
            raise YasnoApiError(f"Cannot reach YASNO login endpoint ({type(err).__name__})") from err
        except ValueError as err:
            raise YasnoAuthenticationError(f"YASNO login returned invalid JSON: {err}") from err

        if response.status != 200 or str(result.get("status")) != "200":
            raise YasnoAuthenticationError(
                f"YASNO rejected phone/password credentials: {result}"
            )

    async def _b2c_fetch_token_form(
        self, csrf_token: str, trans_id: str
    ) -> tuple[str, dict[str, str]]:
        """Fetch the auto-submit form containing the OIDC tokens after a successful login."""
        try:
            response = await self._session.get(
                B2C_CONFIRMED_URL,
                params={"csrf_token": csrf_token, "tx": trans_id, "p": B2C_POLICY},
                headers={"User-Agent": _LOGIN_USER_AGENT},
                timeout=ClientTimeout(total=30),
            )
            confirm_html = await response.text()
        except TimeoutError as err:
            raise YasnoApiError("Cannot reach YASNO login confirmation (timeout)") from err
        except ClientError as err:
            raise YasnoApiError(f"Cannot reach YASNO login confirmation ({type(err).__name__})") from err

        if response.status != 200:
            raise YasnoAuthenticationError(
                f"YASNO login confirmation returned HTTP {response.status}"
            )

        action_match = _FORM_ACTION_RE.search(confirm_html)
        if not action_match:
            raise YasnoAuthenticationError("Could not find token submission form after login")

        hidden_fields: dict[str, str] = {}
        for tag in _INPUT_TAG_RE.findall(confirm_html):
            name_match = _INPUT_NAME_RE.search(tag)
            value_match = _INPUT_VALUE_RE.search(tag)
            if name_match and value_match:
                hidden_fields[name_match.group(1)] = value_match.group(1)

        if "access_token" not in hidden_fields or "id_token" not in hidden_fields:
            raise YasnoAuthenticationError("YASNO login did not return an access token")

        return action_match.group(1), hidden_fields

    async def _b2c_exchange_token(self, action_url: str, hidden_fields: dict[str, str]) -> str:
        """Post the OIDC tokens to app.yasno.ua and return the resulting session cookie string."""
        try:
            response = await self._session.post(
                action_url,
                data=hidden_fields,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": LOGIN_BASE_URL,
                    "Referer": f"{LOGIN_BASE_URL}/",
                    "User-Agent": _LOGIN_USER_AGENT,
                },
                allow_redirects=False,
                timeout=ClientTimeout(total=30),
            )
        except TimeoutError as err:
            raise YasnoApiError("Cannot complete YASNO sign-in (timeout)") from err
        except ClientError as err:
            raise YasnoApiError(f"Cannot complete YASNO sign-in ({type(err).__name__})") from err

        if response.status not in (200, 302):
            raise YasnoAuthenticationError(f"YASNO sign-in exchange failed with HTTP {response.status}")

        cookie_pairs = [f"{morsel.key}={morsel.value}" for morsel in response.cookies.values()]
        if not cookie_pairs:
            raise YasnoAuthenticationError("YASNO sign-in did not return a session cookie")
        return "; ".join(cookie_pairs)

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch selected account data from API endpoints."""
        if not self._cookie and self.can_login:
            await self.async_login()

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
            if _retry_after_auth and self.can_login:
                _LOGGER.warning(f"Authentication error (HTTP {response.status}) for {path}, re-logging in...")
                await self.async_login()
                return await self._api_get(path, _retry_after_auth=False)
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
            if _retry_after_auth and self.can_login:
                _LOGGER.warning(f"Authentication error (HTTP {response.status}) for {path}, re-logging in...")
                await self.async_login()
                return await self._api_post(path, payload, _retry_after_auth=False)
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
