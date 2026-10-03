"""PV boost indicator."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IrHeizungConfigEntry
from .entity import IrHeizungEntity


async def async_setup_entry(hass: HomeAssistant, entry: IrHeizungConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([PvBoostSensor(entry.runtime_data)])


class PvBoostSensor(IrHeizungEntity, BinarySensorEntity):
    def __init__(self, controller) -> None:
        super().__init__(controller, "pv_boost")

    @property
    def is_on(self) -> bool:
        return self.controller.boost.active
