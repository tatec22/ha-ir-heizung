"""Runtime of one IR heating thermostat: reads sensors, decides, switches heaters."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, time as dtime, timedelta
import logging
from math import inf, isfinite
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    EVENT_HOMEASSISTANT_STARTED,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

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
    CONF_OUTDOOR_SENSOR,
    CONF_OVERRIDE_MINUTES,
    CONF_PWM_MINUTES,
    CONF_REFRESH_MINUTES,
    CONF_STALE_MINUTES,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_OPTIONS,
    DOMAIN,
    MAX_PID_DT,
    TICK_SECONDS,
)
from .logic import (
    HEATING_MODES,
    PID,
    Mode,
    OutdoorAverage,
    Override,
    PvBoost,
    PvBoostSettings,
    Targets,
    is_summer,
    override_end,
    pwm_should_be_on,
    select_mode,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
COMMAND_TIMEOUT = 15
COMMAND_RETRY_SECONDS = 10
ROUTINE_SAVE_SECONDS = 900


def _number(state: State | None) -> float | None:
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _available(state: State | None) -> bool:
    return (state is not None
            and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            and not state.attributes.get("restored", False))


class IrHeizungController:
    """Owns the control loop. Entities only display it and forward user wishes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.options: dict[str, Any] = {**DEFAULT_OPTIONS, **entry.options}
        self.heaters: list[str] = list(entry.data[CONF_HEATERS])
        self.temperature_sensor: str = entry.data[CONF_TEMPERATURE_SENSOR]
        o = self.options
        self.pid = PID(o[CONF_KP], o[CONF_KI], o[CONF_KD])
        self.boost = PvBoost(PvBoostSettings(
            start_export=o[CONF_BOOST_START_EXPORT],
            start_delay=o[CONF_BOOST_START_MINUTES] * 60,
            stop_import=o[CONF_BOOST_STOP_IMPORT],
            stop_delay=o[CONF_BOOST_STOP_MINUTES] * 60,
        ))
        self.outdoor = OutdoorAverage()
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")

        # User-facing state
        self.enabled = True
        self.override: Override | None = None
        self.summer = False
        self.mode = Mode.SENSOR_FAULT
        self.target: float | None = None
        self.output = 0.0

        # Sensor tracking
        self.current_temperature: float | None = None
        self._temperature_seen: float | None = None
        self._previous_reading: tuple[float, float] | None = None
        self._temperature_rate = 0.0
        self._last_pid_at: float | None = None

        # Commands sent to the heaters
        self._last_command: bool | None = None
        self._last_command_at = 0.0

        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._lock = asyncio.Lock()
        self._pending = False
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._saved_key: tuple | None = None
        self._saved_at = 0.0

    # ------------------------------------------------------------------ setup

    @property
    def name(self) -> str:
        return self.entry.title

    @property
    def targets(self) -> Targets:
        o = self.options
        return Targets(eco=o[CONF_ECO_TEMP], comfort=o[CONF_COMFORT_TEMP],
                       boost=o[CONF_BOOST_TEMP])

    @property
    def min_temp(self) -> float:
        return self.options[CONF_MIN_TEMP]

    @property
    def max_temp(self) -> float:
        return self.options[CONF_MAX_TEMP]

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.enabled = bool(data.get("enabled", True))
        self.summer = bool(data.get("summer", False))
        override = data.get("override")
        if isinstance(override, dict):
            until = dt_util.parse_datetime(str(override.get("until")))
            try:
                kind = Mode(override.get("kind"))
                target = float(override["target"])
            except (KeyError, TypeError, ValueError):
                until = None
            if until is not None and kind in (Mode.COMFORT, Mode.MANUAL):
                self.override = Override(kind, until, target)
        outdoor = data.get("outdoor")
        if isinstance(outdoor, dict) and outdoor.get("value") is not None:
            self.outdoor.value = float(outdoor["value"])
            self.outdoor.updated = float(outdoor["updated"])
        integral = data.get("integral")
        if isinstance(integral, (int, float)) and 0 <= integral <= 100:
            self.pid.integral = float(integral)

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "summer": self.summer,
            "override": None if self.override is None else {
                "kind": self.override.kind.value,
                "until": self.override.until.isoformat(),
                "target": self.override.target,
            },
            "outdoor": {"value": self.outdoor.value, "updated": self.outdoor.updated},
            "integral": self.pid.integral,
        }

    @callback
    def async_start(self) -> None:
        watched = [self.temperature_sensor, *self.heaters]
        if car := self.options.get(CONF_CAR_CHARGING):
            watched.append(car)
        self._unsubs.append(async_track_state_change_event(
            self.hass, watched, self._async_state_changed))
        self._unsubs.append(async_track_time_interval(
            self.hass, self._async_tick, timedelta(seconds=TICK_SECONDS)))
        if self.hass.is_running:
            self.request_update()
            return

        @callback
        def started(_event: Event) -> None:
            self._unsubs.remove(unsub_started)
            self.request_update()

        unsub_started = self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, started)
        self._unsubs.append(unsub_started)

    async def async_stop(self) -> None:
        """Stop the loop and switch the heaters off: no thermostat, no heat."""
        self._stopped = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self._async_switch(False, force=True)
        await self._store.async_save(self._data_to_save())

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    # ------------------------------------------------------------ user wishes

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.override = None
        await self.async_update_now()

    async def async_start_comfort(self) -> None:
        await self._async_set_override(Mode.COMFORT, self.targets.comfort)

    async def async_set_manual(self, target: float) -> None:
        target = max(self.min_temp, min(self.max_temp, target))
        await self._async_set_override(Mode.MANUAL, target)

    async def async_end_override(self) -> None:
        self.override = None
        await self.async_update_now()

    async def _async_set_override(self, kind: Mode, target: float) -> None:
        latest = self.options.get(CONF_LATEST_END)
        until = override_end(
            dt_util.now(),
            timedelta(minutes=self.options[CONF_OVERRIDE_MINUTES]),
            dtime.fromisoformat(latest) if latest else None,
        )
        self.override = Override(kind, until, target)
        self.enabled = True
        await self.async_update_now()

    # ------------------------------------------------------------- the loop

    @callback
    def _async_state_changed(self, event: Event) -> None:
        if event.data.get("entity_id") == self.temperature_sensor:
            self._record_temperature(event.data.get("new_state"))
        self.request_update()

    async def _async_tick(self, _now: datetime) -> None:
        self.request_update()

    @callback
    def request_update(self) -> None:
        """Coalesce bursts of events into one evaluation."""
        if self._stopped:
            return
        if self._task is not None and not self._task.done():
            self._pending = True
            return
        self._task = self.hass.async_create_background_task(
            self._async_run(), f"{DOMAIN} {self.entry.entry_id} update")

    async def _async_run(self) -> None:
        self._pending = True
        while self._pending and not self._stopped:
            self._pending = False
            await self.async_update_now()

    async def async_update_now(self) -> None:
        async with self._lock:
            try:
                await self._async_evaluate()
            except Exception:  # keep the loop alive; the next tick tries again
                _LOGGER.exception("%s: control update failed", self.name)
        for listener in list(self._listeners):
            listener()
        self._maybe_save()

    @callback
    def _maybe_save(self) -> None:
        """Save at once when a user-visible setting changed, else now and then
        for the slowly drifting values (outdoor average, integral)."""
        key = (self.enabled, self.summer, self.override)
        now = dt_util.utcnow().timestamp()
        if key != self._saved_key or now - self._saved_at >= ROUTINE_SAVE_SECONDS:
            self._saved_key = key
            self._saved_at = now
            self._store.async_delay_save(self._data_to_save, 1)

    def _record_temperature(self, state: State | None) -> None:
        value = _number(state)
        if value is None or state is None:
            return
        seen = state.last_reported.timestamp()
        if self._previous_reading is not None and value != self._previous_reading[0]:
            previous_value, previous_seen = self._previous_reading
            if seen > previous_seen:
                self._temperature_rate = (value - previous_value) / (seen - previous_seen)
        if self._previous_reading is None or value != self._previous_reading[0]:
            self._previous_reading = (value, seen)
        self.current_temperature = value
        self._temperature_seen = max(seen, self._temperature_seen or seen)

    def _read(self, key: str) -> float | None:
        entity_id = self.options.get(key)
        return _number(self.hass.states.get(entity_id)) if entity_id else None

    async def _async_evaluate(self) -> None:
        now_dt = dt_util.utcnow()
        now = now_dt.timestamp()
        o = self.options

        self._record_temperature(self.hass.states.get(self.temperature_sensor))
        if self._previous_reading is not None and now - self._previous_reading[1] > MAX_PID_DT * 6:
            self._temperature_rate = 0.0    # no change for half an hour: not rising
        sensor_ok = (self._temperature_seen is not None
                     and now - self._temperature_seen <= o[CONF_STALE_MINUTES] * 60)

        outdoor = self._read(CONF_OUTDOOR_SENSOR)
        if outdoor is not None:
            self.outdoor.update(now, outdoor)
        self.summer = is_summer(self.outdoor.value if o.get(CONF_OUTDOOR_SENSOR) else None,
                                o[CONF_HEATING_LIMIT], self.summer)

        if self.override is not None and self.override.until <= now_dt:
            self.override = None

        car = o.get(CONF_CAR_CHARGING)
        car_charging = bool(car) and self.hass.states.is_state(car, STATE_ON)
        self.boost.update(
            now, self._read(CONF_GRID_POWER), self._read(CONF_BATTERY_POWER), car_charging,
            allowed=(o[CONF_BOOST_ENABLED] and self.enabled and sensor_ok
                     and not self.summer and bool(o.get(CONF_GRID_POWER))))

        self.mode, self.target = select_mode(
            enabled=self.enabled, sensor_ok=sensor_ok, summer=self.summer,
            boost_active=self.boost.active, override=self.override, now=now_dt,
            targets=self.targets)

        if self.mode not in HEATING_MODES:
            if self.mode != Mode.SENSOR_FAULT:
                self.pid.reset()       # the next heating period starts fresh
            self.output = 0.0
            self._last_pid_at = None
            await self._async_switch(False, force=True)
            return

        dt = 0.0 if self._last_pid_at is None else min(now - self._last_pid_at, MAX_PID_DT)
        self._last_pid_at = now
        self.output = self.pid.update(self.current_temperature, self.target, dt,
                                      self._temperature_rate)
        is_on, since_change = self._heater_phase(now)
        desired = pwm_should_be_on(
            self.output, is_on, since_change,
            period=o[CONF_PWM_MINUTES] * 60,
            min_on=o[CONF_MIN_ON_MINUTES] * 60,
            min_off=o[CONF_MIN_OFF_MINUTES] * 60)
        await self._async_switch(desired)

    def _heater_phase(self, now: float) -> tuple[bool, float]:
        """Current on/off phase of the heaters and how long it has lasted.

        An off that this thermostat did not command (the switch's own auto-off
        timer, or someone at the plug) does not count as a rest phase, so
        heating resumes at once instead of waiting for the minimum off time.
        """
        states = [s for s in (self.hass.states.get(e) for e in self.heaters) if _available(s)]
        if not states:
            return False, inf
        is_on = any(s.state == STATE_ON for s in states)
        since = now - max(s.last_changed.timestamp() for s in states)
        if not is_on and self._last_command is True:
            since = inf
        return is_on, since

    @property
    def heating(self) -> bool:
        return any(self.hass.states.is_state(e, STATE_ON) for e in self.heaters)

    async def _async_switch(self, on: bool, force: bool = False) -> None:
        now = dt_util.utcnow().timestamp()
        refresh = self.options[CONF_REFRESH_MINUTES] * 60
        since_command = now - self._last_command_at
        sent = False
        for entity_id in self.heaters:
            state = self.hass.states.get(entity_id)
            if not _available(state):
                continue
            if (state.state == STATE_ON) == on:
                # Re-send ON now and then: keeps the device in step with HA, and
                # a device-side auto-off timer only fires when HA stops sending.
                if not (on and refresh and since_command >= refresh):
                    continue
            elif (not force and self._last_command is on
                  and since_command < COMMAND_RETRY_SECONDS):
                continue   # command still on its way
            await self._async_call(entity_id, on)
            sent = True
        if sent or self._last_command is not on:
            self._last_command_at = now
        self._last_command = on

    async def _async_call(self, entity_id: str, on: bool) -> None:
        domain = entity_id.split(".", 1)[0]
        service = SERVICE_TURN_ON if on else SERVICE_TURN_OFF
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT):
                await self.hass.services.async_call(
                    domain, service, {ATTR_ENTITY_ID: entity_id}, blocking=True)
        except Exception as err:  # noqa: BLE001 - a dead plug must not stop the loop
            _LOGGER.warning("%s: %s %s failed: %s", self.name, service, entity_id, err)

    # ---------------------------------------------------------- diagnostics

    @property
    def attributes(self) -> dict[str, Any]:
        return {
            "betriebsart": self.mode.value,
            "stellwert": round(self.output, 1),
            "override_bis": self.override.until.isoformat() if self.override else None,
            "pv_boost": self.boost.active,
            "sommerpause": self.summer,
            "aussen_mittel": None if self.outdoor.value is None else round(self.outdoor.value, 1),
            "pid_p": round(self.pid.p, 2),
            "pid_i": round(self.pid.integral, 2),
            "pid_d": round(self.pid.d, 2),
        }
