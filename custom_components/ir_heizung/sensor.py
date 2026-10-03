"""Mode and output sensors: why the room is heated, and how hard."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IrHeizungConfigEntry
from .entity import IrHeizungEntity
from .logic import Mode


async def async_setup_entry(hass: HomeAssistant, entry: IrHeizungConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    async_add_entities([ModeSensor(c), OutputSensor(c), OutdoorAverageSensor(c)])


class ModeSensor(IrHeizungEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [m.value for m in Mode]

    def __init__(self, controller) -> None:
        super().__init__(controller, "betriebsart")

    @property
    def native_value(self) -> str:
        return self.controller.mode.value

    @property
    def extra_state_attributes(self) -> dict:
        override = self.controller.override
        return {"bis": override.until.isoformat() if override else None,
                "ziel": self.controller.target}


class OutputSensor(IrHeizungEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, controller) -> None:
        super().__init__(controller, "stellwert")

    @property
    def native_value(self) -> float:
        return round(self.controller.output, 1)


class OutdoorAverageSensor(IrHeizungEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 1

    def __init__(self, controller) -> None:
        super().__init__(controller, "aussen_mittel")

    @property
    def available(self) -> bool:
        return self.controller.outdoor.value is not None

    @property
    def native_value(self) -> float | None:
        return self.controller.outdoor.value
