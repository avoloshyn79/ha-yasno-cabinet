"""Sensor platform for YASNO cabinet."""

from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import YasnoDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class YasnoSensorDescription(SensorEntityDescription):
    """Describe YASNO sensor."""

    value_key: str


SENSORS: tuple[YasnoSensorDescription, ...] = (
    YasnoSensorDescription(
        key="balance",
        translation_key="balance",
        name="Balance",
        value_key="balance",
        icon="mdi:wallet",
        native_unit_of_measurement="UAH",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    YasnoSensorDescription(
        key="debt",
        translation_key="debt",
        name="Debt",
        value_key="debt",
        icon="mdi:alert-circle-outline",
        native_unit_of_measurement="UAH",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    YasnoSensorDescription(
        key="consumption_kwh",
        translation_key="consumption",
        name="Consumption",
        value_key="consumption_kwh",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    YasnoSensorDescription(
        key="last_payment_amount",
        translation_key="last_payment_amount",
        name="Last payment amount",
        value_key="last_payment",
        icon="mdi:cash",
        native_unit_of_measurement="UAH",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    YasnoSensorDescription(
        key="last_payment_date",
        translation_key="last_payment_date",
        name="Last payment date",
        value_key="last_payment_date",
        icon="mdi:calendar-month-outline",
    ),
    YasnoSensorDescription(
        key="last_fee_date",
        translation_key="last_fee_date",
        name="Last invoice date",
        value_key="last_fee_date",
        icon="mdi:calendar-month-outline",
    ),
    YasnoSensorDescription(
        key="tariff_name",
        translation_key="tariff_name",
        name="Tariff",
        value_key="tariff_name",
        icon="mdi:script-text-outline",
    ),

    YasnoSensorDescription(
        key="tariff_price_day",
        translation_key="tariff_price_day",
        name="Tariff price (day)",
        value_key="tariff_price_day",
        icon="mdi:currency-uah",
        native_unit_of_measurement="UAH/kWh",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    YasnoSensorDescription(
        key="tariff_price_night",
        translation_key="tariff_price_night",
        name="Tariff price (night)",
        value_key="tariff_price_night",
        icon="mdi:currency-uah",
        native_unit_of_measurement="UAH/kWh",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    YasnoSensorDescription(
        key="tariff_price_single",
        translation_key="tariff_price_single",
        name="Tariff price",
        value_key="tariff_price_single",
        icon="mdi:currency-uah",
        native_unit_of_measurement="UAH/kWh",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    YasnoSensorDescription(
        key="dso_name",
        translation_key="dso_name",
        name="DSO",
        value_key="dso_name",
        icon="mdi:office-building",
    ),
    YasnoSensorDescription(
        key="meter_reading_day",
        translation_key="meter_reading_day",
        name="Meter reading (day)",
        value_key="meter_reading_day",
        icon="mdi:meter-electric",
        native_unit_of_measurement="kWh",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    YasnoSensorDescription(
        key="meter_reading_night",
        translation_key="meter_reading_night",
        name="Meter reading (night)",
        value_key="meter_reading_night",
        icon="mdi:meter-electric",
        native_unit_of_measurement="kWh",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    YasnoSensorDescription(
        key="meter_reading_alltime",
        translation_key="meter_reading_alltime",
        name="Meter reading (total)",
        value_key="meter_reading_alltime",
        icon="mdi:meter-electric",
        native_unit_of_measurement="kWh",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    YasnoSensorDescription(
        key="meter_reading_date",
        translation_key="meter_reading_date",
        name="Meter reading date",
        value_key="meter_reading_date",
        icon="mdi:calendar-month-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from config entry."""
    coordinator: YasnoDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    data = coordinator.data

    entities: list[YasnoBaseEntity] = []

    # Common sensors that are always present
    always_present_keys = {
        "balance",
        "debt",
        "consumption_kwh",
        "last_payment_amount",
        "last_payment_date",
        "last_fee_date",
        "tariff_name",
        "dso_name",
        "meter_reading_date",
    }

    # Determine if it's a multi-zone meter (day/night)
    is_multi_zone = data.get("tariff_price_night") is not None or data.get("meter_reading_night") is not None

    for description in SENSORS:
        if description.key in always_present_keys:
            entities.append(YasnoCabinetSensor(coordinator, config_entry, description))
            continue

        if is_multi_zone:
            # Add day/night sensors for multi-zone
            if description.key in ["tariff_price_day", "tariff_price_night", "meter_reading_day", "meter_reading_night"]:
                entities.append(YasnoCabinetSensor(coordinator, config_entry, description))
        else:
            # Add single/alltime sensors for single-zone
            if description.key in ["tariff_price_single", "meter_reading_alltime"]:
                entities.append(YasnoCabinetSensor(coordinator, config_entry, description))

    entities.append(YasnoAccountNumberSensor(coordinator, config_entry))
    async_add_entities(entities)



class YasnoBaseEntity(CoordinatorEntity[YasnoDataUpdateCoordinator], SensorEntity):
    """Base entity for YASNO sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: YasnoDataUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize base entity."""
        super().__init__(coordinator)
        self._entry = config_entry

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info for entities."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": "YASNO",
            "model": "Personal Cabinet",
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose parsed raw payload for debugging."""
        raw = self.coordinator.data.get("raw_payload")
        if isinstance(raw, dict):
            return {"raw_payload_keys": list(raw.keys())[:20]}
        return {}


class YasnoCabinetSensor(YasnoBaseEntity):
    """A numeric sensor from coordinator payload."""

    entity_description: YasnoSensorDescription

    def __init__(
        self,
        coordinator: YasnoDataUpdateCoordinator,
        config_entry: ConfigEntry,
        description: YasnoSensorDescription,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, config_entry)
        self.entity_description = description
        self._attr_unique_id = f"{config_entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> float | str | None:
        """Return sensor value."""
        if self.entity_description.key == "tariff_name":
            data = self.coordinator.data
            is_multi_zone = (
                data.get("tariff_price_night") is not None
                or data.get("meter_reading_night") is not None
            )
            return "День/Ніч" if is_multi_zone else "Побутовий"

        value = self.coordinator.data.get(self.entity_description.value_key)

        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            if self.entity_description.value_key in {"last_payment_date","meter_reading_date", "last_fee_date", "last_payment"}:
                return _format_date_only(value)
            return value
        return None


class YasnoAccountNumberSensor(YasnoBaseEntity):
    """Account number sensor."""

    _attr_name = "Account number"
    _attr_icon = "mdi:identifier"
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: YasnoDataUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize account number sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_account_number"

    @property
    def native_value(self) -> str | None:
        """Return account number."""
        value = self.coordinator.data.get("account_number")
        return str(value) if value not in (None, "") else None


def _format_date_only(value: str) -> str:
    """Convert datetime-like string to YYYY-MM-DD."""
    normalized = value.strip()
    if "T" in normalized:
        normalized = normalized.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).date().isoformat()
        except ValueError:
            return value.split("T", maxsplit=1)[0]
    if " " in normalized:
        return normalized.split(" ", maxsplit=1)[0]
    return normalized
