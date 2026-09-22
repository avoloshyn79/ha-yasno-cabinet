"""Constants for the YASNO cabinet integration."""

from __future__ import annotations

DOMAIN = "yasno_cabinet"

CONF_CABINET_URL = "cabinet_url"
CONF_COOKIE = "cookie"
CONF_ACCOUNT_ID = "account_id"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_PHONE = "phone"
CONF_PASSWORD = "password"

DEFAULT_NAME = "YASNO Cabinet"
DEFAULT_CABINET_URL = "https://app.yasno.ua"
DEFAULT_SCAN_INTERVAL_MINUTES = 1440

SERVICE_SEND_METER_READINGS = "send_meter_readings"
SERVICE_UPDATE_DATA = "update_data"
ATTR_READINGS = "readings"
ATTR_ACCOUNT_ID = "account_id"

EVENT_DATA_UPDATED = f"{DOMAIN}_data_updated"
EVENT_READINGS_SUBMITTED = f"{DOMAIN}_readings_submitted"
EVENT_READINGS_FAILED = f"{DOMAIN}_readings_failed"

PLATFORMS: list[str] = ["sensor"]
