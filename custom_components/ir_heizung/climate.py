"""The thermostat itself."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IrHeizungConfigEntry
from .entity import IrHeizungEntity
from .logic import Mode

PRESET_AUTO = "automatik"
PRESET_COMFORT = "komfort"
PRESET_MANUAL = "manuell"


async def async_setup_entry(hass: HomeAssistant, entry: IrHeizungConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([IrHeizungClimate(entry.runtime_data)])


class IrHeizungClimate(IrHeizungEntity, ClimateEntity):
    """Heat/off plus presets.

    Automatik lets the controller choose between Eco and PV boost. Komfort and
    a manually set temperature last for the configured period, then Automatik
    returns by itself.
    """

    _attr_name = None
    _attr_translation_key = "thermostat"
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_AUTO, PRESET_COMFORT, PRESET_MANUAL]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS
    _attr_target_temperature_step = 0.5
    _attr_supported_features = (ClimateEntityFeature.TARGET_TEMPERATURE
                                | ClimateEntityFeature.PRESET_MODE
                                | ClimateEntityFeature.TURN_ON
                                | ClimateEntityFeature.TURN_OFF)

    def __init__(self, controller) -> None:
        super().__init__(controller, None)
        self._attr_translation_key = "thermostat"

    @property
    def min_temp(self) -> float:
        return self.controller.min_temp

    @property
    def max_temp(self) -> float:
        return self.controller.max_temp

    @property
    def current_temperature(self) -> float | None:
        return self.controller.current_temperature

    @property
    def target_temperature(self) -> float | None:
        c = self.controller
        if c.target is not None:
            return c.target
        return c.targets.eco if c.enabled else None

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self.controller.enabled else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        if not self.controller.enabled:
            return HVACAction.OFF
        return HVACAction.HEATING if self.controller.heating else HVACAction.IDLE

    @property
    def preset_mode(self) -> str:
        override = self.controller.override
        if override is None:
            return PRESET_AUTO
        return PRESET_COMFORT if override.kind == Mode.COMFORT else PRESET_MANUAL

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.controller.attributes

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.controller.async_set_enabled(hvac_mode == HVACMode.HEAT)

    async def async_turn_on(self) -> None:
        await self.controller.async_set_enabled(True)

    async def async_turn_off(self) -> None:
        await self.controller.async_set_enabled(False)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.controller.async_set_manual(float(temperature))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == PRESET_COMFORT:
            await self.controller.async_start_comfort()
        elif preset_mode == PRESET_MANUAL:
            await self.controller.async_set_manual(
                self.target_temperature or self.controller.targets.comfort)
        else:
            await self.controller.async_end_override()
