"""Control logic for the IR heating thermostat.

Nothing in here imports Home Assistant, so every rule can be tested on its own.
The PID idea follows ScratMan/HASmartThermostat (MIT), simplified to heating only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from math import exp, inf


class Mode(StrEnum):
    """Why the thermostat currently aims for its target (or does not heat)."""

    OFF = "aus"
    SENSOR_FAULT = "sensorfehler"
    SUMMER = "sommerpause"
    ECO = "eco"
    COMFORT = "komfort"
    MANUAL = "manuell"
    PV_BOOST = "pv_boost"


HEATING_MODES = (Mode.ECO, Mode.COMFORT, Mode.MANUAL, Mode.PV_BOOST)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class PID:
    """Heating-only PID with output 0-100 %.

    P acts on the error, D on the measured temperature change (no kick on
    setpoint changes), and I integrates only while that does not push the
    output further into saturation.
    """

    def __init__(self, kp: float, ki: float, kd: float) -> None:
        self.kp, self.ki, self.kd = kp, ki, kd
        self.integral = 0.0
        self.p = self.d = 0.0
        self.output = 0.0

    def reset(self) -> None:
        self.integral = 0.0
        self.p = self.d = self.output = 0.0

    def update(self, temperature: float, target: float, dt: float,
               temperature_rate: float = 0.0) -> float:
        """Return the new output. ``temperature_rate`` is in K per second."""
        error = target - temperature
        self.p = self.kp * error
        self.d = -self.kd * temperature_rate
        candidate = self.integral + self.ki * error * max(dt, 0.0)
        unclamped = self.p + candidate + self.d
        winding_up = unclamped > 100 and error > 0
        winding_down = unclamped < 0 and error < 0
        if not (winding_up or winding_down):
            self.integral = clamp(candidate, 0.0, 100.0)
        self.output = clamp(self.p + self.integral + self.d, 0.0, 100.0)
        return self.output


def pwm_should_be_on(output: float, is_on: bool, since_change: float, period: float,
                     min_on: float, min_off: float) -> bool:
    """Time-proportional switching of an on/off heater.

    ``since_change`` is how long the heaters have been in their current state.
    Phases shorter than the minimum on/off time are stretched, so a small
    output becomes a short pulse in a longer cycle rather than relay chatter.
    """
    if output >= 100:
        return is_on or since_change >= min_off
    if output <= 0:
        return is_on and since_change < min_on
    on_time = period * output / 100
    off_time = period - on_time
    if on_time < min_on:
        off_time *= min_on / on_time
        on_time = min_on
    if off_time < min_off:
        on_time *= min_off / off_time
        off_time = min_off
    if is_on:
        return since_change < on_time
    return since_change >= off_time


@dataclass
class PvBoostSettings:
    start_export: float = 800.0      # W fed into the grid before boosting
    start_delay: float = 600.0       # s the export must last
    stop_import: float = 100.0       # W drawn from grid or battery that ends it
    stop_delay: float = 300.0        # s that draw must last


class PvBoost:
    """Decides whether PV surplus may heat the room.

    The car always wins: while it charges there is no boost. Export only
    happens once the house battery is full or charge-limited, so the battery
    is served before the heaters as well.
    """

    def __init__(self, settings: PvBoostSettings) -> None:
        self.settings = settings
        self.active = False
        self._since: float | None = None

    def update(self, now: float, grid_power: float | None, battery_power: float | None,
               car_charging: bool, allowed: bool) -> bool:
        """``grid_power`` > 0 is import, ``battery_power`` > 0 is discharge (evcc)."""
        if not allowed or car_charging or grid_power is None:
            self.active = False
            self._since = None
            return False
        s = self.settings
        discharge = battery_power if battery_power is not None else 0.0
        if self.active:
            draw = max(grid_power, 0.0) + max(discharge, 0.0)
            condition = draw >= s.stop_import
            delay = s.stop_delay
        else:
            condition = -grid_power >= s.start_export and discharge < s.stop_import
            delay = s.start_delay
        if not condition:
            self._since = None
        elif self._since is None:
            self._since = now
        if self._since is not None and now - self._since >= delay:
            self.active = not self.active
            self._since = None
        return self.active


class OutdoorAverage:
    """Exponential moving average of the outdoor temperature (time constant 24 h)."""

    def __init__(self, tau: float = 86400.0) -> None:
        self.tau = tau
        self.value: float | None = None
        self.updated: float | None = None

    def update(self, now: float, temperature: float) -> float:
        if self.value is None or self.updated is None:
            self.value = temperature
        else:
            alpha = 1 - exp(-max(now - self.updated, 0.0) / self.tau)
            self.value += alpha * (temperature - self.value)
        self.updated = now
        return self.value


def is_summer(average: float | None, limit: float, currently_summer: bool,
              hysteresis: float = 0.5) -> bool:
    """Heating limit with hysteresis; without data the heating stays allowed."""
    if average is None:
        return False
    if currently_summer:
        return average > limit - hysteresis
    return average > limit + hysteresis


def override_end(now: datetime, duration: timedelta, latest_end: time | None) -> datetime:
    """When a comfort or manual period ends: after ``duration``, but no later
    than ``latest_end`` if that time still lies ahead today."""
    end = now + duration
    if latest_end is not None:
        cap = now.replace(hour=latest_end.hour, minute=latest_end.minute,
                          second=latest_end.second, microsecond=0)
        if now < cap < end:
            end = cap
    return end


@dataclass
class Override:
    kind: Mode          # Mode.COMFORT or Mode.MANUAL
    until: datetime
    target: float


@dataclass
class Targets:
    eco: float
    comfort: float
    boost: float


def select_mode(*, enabled: bool, sensor_ok: bool, summer: bool, boost_active: bool,
                override: Override | None, now: datetime,
                targets: Targets) -> tuple[Mode, float | None]:
    """Pick the mode and its target temperature, highest priority first.

    A comfort or manual period is a deliberate wish and also applies in the
    summer pause. PV boost only raises the target, never lowers it.
    """
    if not enabled:
        return Mode.OFF, None
    if not sensor_ok:
        return Mode.SENSOR_FAULT, None
    if override is not None and override.until > now:
        if boost_active and not summer and targets.boost > override.target:
            return Mode.PV_BOOST, targets.boost
        return override.kind, override.target
    if summer:
        return Mode.SUMMER, None
    if boost_active:
        return Mode.PV_BOOST, max(targets.boost, targets.eco)
    return Mode.ECO, targets.eco


__all__ = [
    "HEATING_MODES", "Mode", "OutdoorAverage", "Override", "PID", "PvBoost",
    "PvBoostSettings", "Targets", "clamp", "inf", "is_summer", "override_end",
    "pwm_should_be_on", "select_mode",
]
