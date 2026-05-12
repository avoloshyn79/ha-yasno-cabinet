"""Logbook support for YASNO Cabinet."""

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import callback

from .const import DOMAIN, EVENT_DATA_UPDATED, EVENT_READINGS_FAILED, EVENT_READINGS_SUBMITTED


@callback
def async_describe_events(hass, async_describe_event):
    """Describe logbook events."""

    @callback
    def async_describe_data_updated(event):
        balance = event.data.get("balance")
        debt = event.data.get("debt")
        parts = ["Дані оновлено"]
        if balance is not None:
            parts.append(f"до сплати: {balance} грн")
        if debt is not None:
            parts.append(f"борг: {debt} грн")
        msg = parts[0] if len(parts) == 1 else f"{parts[0]}. {', '.join(parts[1:])}"
        return {
            LOGBOOK_ENTRY_NAME: "YASNO",
            LOGBOOK_ENTRY_MESSAGE: msg,
        }

    @callback
    def async_describe_readings_submitted(event):
        account_id = event.data.get("account_id")
        readings = event.data.get("readings", [])
        readings_str = ", ".join(
            f"{r.get('zone')}: {r.get('value')} кВт·год" for r in readings
        )
        return {
            LOGBOOK_ENTRY_NAME: "YASNO",
            LOGBOOK_ENTRY_MESSAGE: f"Передано показання лічильника {account_id}: {readings_str}",
        }

    @callback
    def async_describe_readings_failed(event):
        account_id = event.data.get("account_id")
        error = event.data.get("error", "невідома помилка")
        return {
            LOGBOOK_ENTRY_NAME: "YASNO",
            LOGBOOK_ENTRY_MESSAGE: f"Помилка передачі показань {account_id}: {error}",
        }

    async_describe_event(DOMAIN, EVENT_DATA_UPDATED, async_describe_data_updated)
    async_describe_event(DOMAIN, EVENT_READINGS_SUBMITTED, async_describe_readings_submitted)
    async_describe_event(DOMAIN, EVENT_READINGS_FAILED, async_describe_readings_failed)
