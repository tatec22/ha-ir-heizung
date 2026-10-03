"""The integration inside a real Home Assistant instance."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.ir_heizung.const import (
    CONF_BATTERY_POWER,
    CONF_BOOST_ENABLED,
    CONF_CAR_CHARGING,
    CONF_GRID_POWER,
    CONF_HEATERS,
    CONF_OUTDOOR_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_OPTIONS,
    DOMAIN,
)

ROOM = "sensor.room"
HEATERS = ["input_boolean.heater_a", "input_boolean.heater_b"]
CLIMATE = "climate.dg"
MODE = "sensor.dg_mode"
TEMP_ATTRS = {"device_class": "temperature", "unit_of_measurement": "°C"}


@pytest.fixture(autouse=True)
def frozen(freezer):
    freezer.move_to("2026-11-03 10:00:00+00:00")
    return freezer


def set_room(hass: HomeAssistant, value: float) -> None:
    hass.states.async_set(ROOM, str(value), TEMP_ATTRS)


async def setup(hass: HomeAssistant, temperature: float = 15.0, **options) -> MockConfigEntry:
    await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"heater_a": None, "heater_b": None}})
    set_room(hass, temperature)
    entry = MockConfigEntry(
        domain=DOMAIN, title="DG",
        data={CONF_HEATERS: HEATERS, CONF_TEMPERATURE_SENSOR: ROOM},
        options={**DEFAULT_OPTIONS, **options})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    return entry


async def settle(hass: HomeAssistant) -> None:
    await hass.async_block_till_done(wait_background_tasks=True)


async def advance(hass: HomeAssistant, freezer, seconds: int, step: int = 30,
                  heartbeat: bool = False) -> None:
    for _ in range(seconds // step):
        freezer.tick(timedelta(seconds=step))
        if heartbeat:                           # same value, reported again
            set_room(hass, float(hass.states.get(ROOM).state))
        async_fire_time_changed(hass, dt_util.utcnow())
        await settle(hass)


def heaters_on(hass: HomeAssistant) -> list[bool]:
    return [hass.states.is_state(e, "on") for e in HEATERS]


async def test_heats_when_cold_and_stops_when_warm(hass, frozen):
    await setup(hass, temperature=10.0)
    state = hass.states.get(CLIMATE)
    assert state.state == HVACMode.HEAT
    assert state.attributes["temperature"] == 16
    assert state.attributes["preset_mode"] == "automatik"
    assert hass.states.get(MODE).state == "eco"
    assert hass.states.get("sensor.dg_output").state == "100.0"

    await advance(hass, frozen, 210)            # minimum off time since the plugs appeared
    assert heaters_on(hass) == [True, True]
    assert hass.states.get(CLIMATE).attributes["hvac_action"] == HVACAction.HEATING

    set_room(hass, 17.0)
    await settle(hass)
    await advance(hass, frozen, 210)            # minimum on time
    assert heaters_on(hass) == [False, False]
    assert hass.states.get(CLIMATE).attributes["hvac_action"] == HVACAction.IDLE


async def test_off_mode_switches_off_at_once(hass, frozen):
    await setup(hass, temperature=10.0)
    await advance(hass, frozen, 210)
    assert heaters_on(hass) == [True, True]
    await hass.services.async_call("climate", "set_hvac_mode",
                                   {"entity_id": CLIMATE, "hvac_mode": "off"}, blocking=True)
    await settle(hass)
    assert heaters_on(hass) == [False, False]
    assert hass.states.get(MODE).state == "aus"
    assert hass.states.get(CLIMATE).attributes["hvac_action"] == HVACAction.OFF


async def test_comfort_button_runs_for_its_period(hass, frozen):
    await setup(hass, temperature=18.0)
    assert hass.states.get(MODE).state == "eco"
    await hass.services.async_call("button", "press",
                                   {"entity_id": "button.dg_start_comfort"}, blocking=True)
    await settle(hass)
    state = hass.states.get(CLIMATE)
    assert state.attributes["preset_mode"] == "komfort"
    assert state.attributes["temperature"] == 20
    assert hass.states.get(MODE).state == "komfort"
    await advance(hass, frozen, 210)
    assert heaters_on(hass) == [True, True]

    await advance(hass, frozen, 3 * 3600, step=300, heartbeat=True)
    assert hass.states.get(MODE).state == "eco"
    assert hass.states.get(CLIMATE).attributes["preset_mode"] == "automatik"


async def test_manual_temperature_is_temporary(hass, frozen):
    await setup(hass, temperature=18.0)
    await hass.services.async_call("climate", "set_temperature",
                                   {"entity_id": CLIMATE, "temperature": 21}, blocking=True)
    await settle(hass)
    state = hass.states.get(CLIMATE)
    assert state.attributes["preset_mode"] == "manuell"
    assert state.attributes["temperature"] == 21
    await hass.services.async_call("button", "press",
                                   {"entity_id": "button.dg_back_to_automatic"}, blocking=True)
    await settle(hass)
    assert hass.states.get(CLIMATE).attributes["temperature"] == 16


async def test_stale_sensor_switches_off(hass, frozen):
    await setup(hass, temperature=10.0)
    await advance(hass, frozen, 210)
    assert heaters_on(hass) == [True, True]
    await advance(hass, frozen, 181 * 60, step=300)
    assert hass.states.get(MODE).state == "sensorfehler"
    assert heaters_on(hass) == [False, False]
    set_room(hass, 10.5)                        # sensor is back
    await settle(hass)
    assert hass.states.get(MODE).state == "eco"


async def test_pv_boost_heats_with_surplus_and_yields_to_the_car(hass, frozen):
    hass.states.async_set("sensor.grid", "-1200", {"device_class": "power"})
    hass.states.async_set("sensor.battery", "0", {"device_class": "power"})
    hass.states.async_set("binary_sensor.car", "off")
    await setup(hass, temperature=18.0, **{
        CONF_BOOST_ENABLED: True, CONF_GRID_POWER: "sensor.grid",
        CONF_BATTERY_POWER: "sensor.battery", CONF_CAR_CHARGING: "binary_sensor.car"})
    assert hass.states.get(MODE).state == "eco"
    await advance(hass, frozen, 9 * 60)
    assert hass.states.get("binary_sensor.dg_pv_boost").state == "off"
    await advance(hass, frozen, 120)
    assert hass.states.get("binary_sensor.dg_pv_boost").state == "on"
    assert hass.states.get(MODE).state == "pv_boost"
    assert hass.states.get(CLIMATE).attributes["temperature"] == 22
    await advance(hass, frozen, 210)
    assert heaters_on(hass) == [True, True]

    hass.states.async_set("binary_sensor.car", "on")
    await settle(hass)
    assert hass.states.get(MODE).state == "eco"
    await advance(hass, frozen, 210)
    assert heaters_on(hass) == [False, False]


async def test_summer_pause_blocks_eco_but_not_comfort(hass, frozen):
    hass.states.async_set("sensor.outside", "22", TEMP_ATTRS)
    await setup(hass, temperature=10.0, **{CONF_OUTDOOR_SENSOR: "sensor.outside"})
    assert hass.states.get(MODE).state == "sommerpause"
    assert hass.states.get("sensor.dg_outdoor_average").state == "22.0"
    await advance(hass, frozen, 210)
    assert heaters_on(hass) == [False, False]
    await hass.services.async_call("button", "press",
                                   {"entity_id": "button.dg_start_comfort"}, blocking=True)
    await settle(hass)
    assert hass.states.get(MODE).state == "komfort"


async def test_device_auto_off_does_not_cause_a_rest_phase(hass, frozen):
    await setup(hass, temperature=10.0)
    await advance(hass, frozen, 210)
    assert heaters_on(hass) == [True, True]
    for heater in HEATERS:                      # the plug's own timer cuts power
        await hass.services.async_call("input_boolean", "turn_off",
                                       {"entity_id": heater}, blocking=True)
    await advance(hass, frozen, 30)
    assert heaters_on(hass) == [True, True]


async def test_on_command_is_repeated(hass, frozen):
    await setup(hass, temperature=10.0)
    await advance(hass, frozen, 210)
    calls = async_capture_events(hass, EVENT_CALL_SERVICE)
    await advance(hass, frozen, 4 * 60)
    assert not [c for c in calls if c.data["service"] == "turn_on"]
    await advance(hass, frozen, 90)
    assert len([c for c in calls if c.data["service"] == "turn_on"]) == 2


async def test_unload_switches_heaters_off(hass, frozen):
    entry = await setup(hass, temperature=10.0)
    await advance(hass, frozen, 210)
    assert heaters_on(hass) == [True, True]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await settle(hass)
    assert heaters_on(hass) == [False, False]


async def test_comfort_survives_a_restart(hass, frozen, hass_storage):
    until = (dt_util.utcnow() + timedelta(hours=2)).isoformat()
    entry_id = "restored"
    hass_storage[f"{DOMAIN}.{entry_id}"] = {
        "version": 1, "key": f"{DOMAIN}.{entry_id}",
        "data": {"enabled": True, "override": {"kind": "komfort", "until": until,
                                                "target": 20}}}
    await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"heater_a": None, "heater_b": None}})
    set_room(hass, 18.0)
    entry = MockConfigEntry(domain=DOMAIN, title="DG", entry_id=entry_id,
                            data={CONF_HEATERS: HEATERS, CONF_TEMPERATURE_SENSOR: ROOM},
                            options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    assert hass.states.get(MODE).state == "komfort"


async def test_config_and_options_flow(hass):
    await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"heater_a": None, "heater_b": None}})
    set_room(hass, 18.0)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "name": "DG", CONF_HEATERS: HEATERS, CONF_TEMPERATURE_SENSOR: ROOM})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.options["eco_temp"] == 16
    await settle(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "pv_boost"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        CONF_BOOST_ENABLED: True, "boost_start_export": 800, "boost_start_minutes": 10,
        "boost_stop_import": 100, "boost_stop_minutes": 5})
    assert result["errors"] == {"base": "boost_needs_grid"}

    hass.states.async_set("sensor.grid", "0", {"device_class": "power"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        CONF_BOOST_ENABLED: True, CONF_GRID_POWER: "sensor.grid",
        "boost_start_export": 800, "boost_start_minutes": 10,
        "boost_stop_import": 100, "boost_stop_minutes": 5})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await settle(hass)
    assert entry.options[CONF_GRID_POWER] == "sensor.grid"
    assert entry.options["eco_temp"] == 16      # other sections untouched

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "pv_boost"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        CONF_BOOST_ENABLED: False, "boost_start_export": 800, "boost_start_minutes": 10,
        "boost_stop_import": 100, "boost_stop_minutes": 5})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_GRID_POWER not in entry.options   # cleared field is removed
