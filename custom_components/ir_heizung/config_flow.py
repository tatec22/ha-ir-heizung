"""Setup and options in the UI."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_POWER,
    CONF_BOOST_ENABLED,
    CONF_BOOST_START_EXPORT,
    CONF_BOOST_START_MINUTES,
    CONF_BOOST_STOP_IMPORT,
    CONF_BOOST_STOP_MINUTES,
    CONF_BOOST_TEMP,
    CONF_CAR_CHARGING,
    CONF_COMFORT_TEMP,
    CONF_ECO_TEMP,
    CONF_GRID_POWER,
    CONF_HEATERS,
    CONF_HEATING_LIMIT,
    CONF_KD,
    CONF_KI,
    CONF_KP,
    CONF_LATEST_END,
    CONF_MAX_TEMP,
    CONF_MIN_OFF_MINUTES,
    CONF_MIN_ON_MINUTES,
    CONF_MIN_TEMP,
    CONF_NAME,
    CONF_OUTDOOR_SENSOR,
    CONF_OVERRIDE_MINUTES,
    CONF_PWM_MINUTES,
    CONF_REFRESH_MINUTES,
    CONF_STALE_MINUTES,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_OPTIONS,
    DOMAIN,
    OPTION_SECTIONS,
)

HEATER_SELECTOR = selector.EntitySelector(selector.EntitySelectorConfig(
    domain=["switch", "input_boolean"], multiple=True))
TEMPERATURE_SELECTOR = selector.EntitySelector(selector.EntitySelectorConfig(
    domain="sensor", device_class="temperature"))
POWER_SELECTOR = selector.EntitySelector(selector.EntitySelectorConfig(
    domain="sensor", device_class="power"))
BINARY_SELECTOR = selector.EntitySelector(selector.EntitySelectorConfig(
    domain="binary_sensor"))


def _number(minimum: float, maximum: float, step: float | str, unit: str | None = None):
    config = selector.NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=selector.NumberSelectorMode.BOX)
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


FIELD_SELECTORS: dict[str, Any] = {
    CONF_ECO_TEMP: _number(5, 25, 0.5, "°C"),
    CONF_COMFORT_TEMP: _number(5, 28, 0.5, "°C"),
    CONF_BOOST_TEMP: _number(5, 28, 0.5, "°C"),
    CONF_MIN_TEMP: _number(5, 20, 0.5, "°C"),
    CONF_MAX_TEMP: _number(15, 30, 0.5, "°C"),
    CONF_OVERRIDE_MINUTES: _number(15, 720, 15, "min"),
    CONF_LATEST_END: selector.TimeSelector(),
    CONF_BOOST_ENABLED: selector.BooleanSelector(),
    CONF_GRID_POWER: POWER_SELECTOR,
    CONF_BATTERY_POWER: POWER_SELECTOR,
    CONF_CAR_CHARGING: BINARY_SELECTOR,
    CONF_BOOST_START_EXPORT: _number(100, 10000, 50, "W"),
    CONF_BOOST_START_MINUTES: _number(1, 60, 1, "min"),
    CONF_BOOST_STOP_IMPORT: _number(0, 5000, 50, "W"),
    CONF_BOOST_STOP_MINUTES: _number(1, 60, 1, "min"),
    CONF_OUTDOOR_SENSOR: TEMPERATURE_SELECTOR,
    CONF_HEATING_LIMIT: _number(5, 25, 0.5, "°C"),
    CONF_KP: _number(0, 500, 1),
    CONF_KI: _number(0, 1, "any"),
    CONF_KD: _number(0, 100000, 10),
    CONF_PWM_MINUTES: _number(5, 60, 1, "min"),
    CONF_MIN_ON_MINUTES: _number(0, 30, 1, "min"),
    CONF_MIN_OFF_MINUTES: _number(0, 30, 1, "min"),
    CONF_REFRESH_MINUTES: _number(0, 60, 1, "min"),
    CONF_STALE_MINUTES: _number(30, 1440, 15, "min"),
}

# Fields that may be left empty; clearing them removes the setting.
OPTIONAL_FIELDS = {CONF_GRID_POWER, CONF_BATTERY_POWER, CONF_CAR_CHARGING,
                   CONF_OUTDOOR_SENSOR, CONF_LATEST_END}


def section_schema(section: str, values: dict[str, Any]) -> vol.Schema:
    schema: dict[Any, Any] = {}
    for key in OPTION_SECTIONS[section]:
        marker = vol.Optional if key in OPTIONAL_FIELDS else vol.Required
        if values.get(key) is not None:
            schema[marker(key, description={"suggested_value": values[key]})] = FIELD_SELECTORS[key]
        else:
            schema[marker(key)] = FIELD_SELECTORS[key]
    return vol.Schema(schema)


def merge_section(options: dict[str, Any], section: str,
                  user_input: dict[str, Any]) -> dict[str, Any]:
    merged = dict(options)
    for key in OPTION_SECTIONS[section]:
        if key in user_input and user_input[key] not in (None, ""):
            merged[key] = user_input[key]
        elif key in OPTIONAL_FIELDS:
            merged.pop(key, None)
    return merged


def validate_options(options: dict[str, Any]) -> str | None:
    """Return an error key, or None when the combination makes sense."""
    o = {**DEFAULT_OPTIONS, **options}
    if o[CONF_MIN_TEMP] >= o[CONF_MAX_TEMP]:
        return "min_above_max"
    for key in (CONF_ECO_TEMP, CONF_COMFORT_TEMP, CONF_BOOST_TEMP):
        if not o[CONF_MIN_TEMP] <= o[key] <= o[CONF_MAX_TEMP]:
            return "target_out_of_range"
    if o[CONF_BOOST_ENABLED] and not o.get(CONF_GRID_POWER):
        return "boost_needs_grid"
    return None


class IrHeizungConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> IrHeizungOptionsFlow:
        return IrHeizungOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_HEATERS):
                errors[CONF_HEATERS] = "no_heaters"
            else:
                self._async_abort_entries_match(
                    {CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR]})
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_HEATERS: user_input[CONF_HEATERS],
                          CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR]},
                    options=dict(DEFAULT_OPTIONS))
        schema = vol.Schema({
            vol.Required(CONF_NAME, default="IR-Heizung"): selector.TextSelector(),
            vol.Required(CONF_HEATERS): HEATER_SELECTOR,
            vol.Required(CONF_TEMPERATURE_SENSOR): TEMPERATURE_SELECTOR,
        })
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None
                                     ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        if user_input is not None and user_input.get(CONF_HEATERS):
            return self.async_update_reload_and_abort(
                entry, data_updates={
                    CONF_HEATERS: user_input[CONF_HEATERS],
                    CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR]})
        schema = vol.Schema({
            vol.Required(CONF_HEATERS): HEATER_SELECTOR,
            vol.Required(CONF_TEMPERATURE_SENSOR): TEMPERATURE_SELECTOR,
        })
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, dict(entry.data)))


class IrHeizungOptionsFlow(OptionsFlow):
    """One menu entry per topic; each saves only its own fields."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=list(OPTION_SECTIONS))

    async def _section(self, section: str, user_input: dict[str, Any] | None
                       ) -> ConfigFlowResult:
        current = {**DEFAULT_OPTIONS, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = merge_section(current, section, user_input)
            if (error := validate_options(merged)) is None:
                return self.async_create_entry(data=merged)
            errors["base"] = error
            current = {**current, **user_input}
        return self.async_show_form(step_id=section,
                                    data_schema=section_schema(section, current),
                                    errors=errors)

    async def async_step_temperatures(self, user_input=None) -> ConfigFlowResult:
        return await self._section("temperatures", user_input)

    async def async_step_comfort(self, user_input=None) -> ConfigFlowResult:
        return await self._section("comfort", user_input)

    async def async_step_pv_boost(self, user_input=None) -> ConfigFlowResult:
        return await self._section("pv_boost", user_input)

    async def async_step_season(self, user_input=None) -> ConfigFlowResult:
        return await self._section("season", user_input)

    async def async_step_controller(self, user_input=None) -> ConfigFlowResult:
        return await self._section("controller", user_input)
