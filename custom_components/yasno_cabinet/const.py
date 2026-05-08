"""Constants for the YASNO cabinet integration."""

from __future__ import annotations

DOMAIN = "yasno_cabinet"

CONF_CABINET_URL = "cabinet_url"
CONF_COOKIE = "cookie"
CONF_ACCOUNT_ID = "account_id"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_NAME = "YASNO Cabinet"
DEFAULT_CABINET_URL = "https://app.yasno.ua"
DEFAULT_SCAN_INTERVAL_MINUTES = 360

SERVICE_SEND_METER_READINGS = "send_meter_readings"
SERVICE_UPDATE_DATA = "update_data"
ATTR_READINGS = "readings"
ATTR_ACCOUNT_ID = "account_id"

PLATFORMS: list[str] = ["sensor"]
