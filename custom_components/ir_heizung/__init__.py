"""IR-Heizung: PID thermostat with comfort periods and PV boost for on/off heaters."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .controller import IrHeizungController

type IrHeizungConfigEntry = ConfigEntry[IrHeizungController]


async def async_setup_entry(hass: HomeAssistant, entry: IrHeizungConfigEntry) -> bool:
    controller = IrHeizungController(hass, entry)
    await controller.async_load()
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    controller.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IrHeizungConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def _async_options_updated(hass: HomeAssistant, entry: IrHeizungConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
