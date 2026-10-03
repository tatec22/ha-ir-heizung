"""Start or end a comfort period with one tap."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IrHeizungConfigEntry
from .entity import IrHeizungEntity


async def async_setup_entry(hass: HomeAssistant, entry: IrHeizungConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    async_add_entities([ComfortStartButton(c), ComfortEndButton(c)])


class ComfortStartButton(IrHeizungEntity, ButtonEntity):
    def __init__(self, controller) -> None:
        super().__init__(controller, "komfort_starten")

    async def async_press(self) -> None:
        await self.controller.async_start_comfort()


class ComfortEndButton(IrHeizungEntity, ButtonEntity):
    def __init__(self, controller) -> None:
        super().__init__(controller, "komfort_beenden")

    async def async_press(self) -> None:
        await self.controller.async_end_override()
