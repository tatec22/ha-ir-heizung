"""Base entity: one device per thermostat, refreshed by the controller."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .controller import IrHeizungController


class IrHeizungEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: IrHeizungController, key: str | None) -> None:
        self.controller = controller
        entry_id = controller.entry.entry_id
        self._attr_unique_id = entry_id if key is None else f"{entry_id}_{key}"
        if key is not None:
            self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=controller.name,
            manufacturer="ir_heizung",
            model="PID-Thermostat",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.controller.async_add_listener(self.async_write_ha_state))
