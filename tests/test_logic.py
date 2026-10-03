"""Rules of the controller, without Home Assistant."""

from datetime import datetime, time, timedelta, timezone
from math import inf

import pytest

from custom_components.ir_heizung.logic import (
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

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
TARGETS = Targets(eco=16, comfort=20, boost=22)


# --- PID -------------------------------------------------------------------

def test_pid_proportional_only():
    pid = PID(60, 0, 0)
    assert pid.update(19.5, 20, 30) == pytest.approx(30)
    assert pid.update(21, 20, 30) == 0          # too warm: no heat, not negative
    assert pid.update(15, 20, 30) == 100        # clamped


def test_pid_integral_removes_offset_and_does_not_wind_up():
    pid = PID(60, 0.003, 0)
    for _ in range(120):                        # one hour at 0.5 K below target
        pid.update(19.5, 20, 30)
    assert pid.integral == pytest.approx(0.003 * 0.5 * 3600)
    pid.reset()
    for _ in range(1000):                       # far too cold: output saturated
        pid.update(10, 20, 30)
    assert pid.integral == 0                    # nothing piled up meanwhile


def test_pid_integral_unwinds_when_slightly_warm_and_holds_when_saturated():
    pid = PID(60, 0.003, 0)
    pid.integral = 10.0
    pid.update(20.1, 20, 300)                   # 0.1 K too warm, output still above 0
    assert pid.integral == pytest.approx(10.0 - 0.003 * 0.1 * 300)
    held = pid.integral
    pid.update(25, 20, 300)                     # far too warm: output pinned at 0
    assert pid.integral == held


def test_pid_derivative_brakes_on_rising_temperature():
    pid = PID(60, 0, 1000)
    rising = pid.update(19.5, 20, 30, temperature_rate=0.01)
    pid2 = PID(60, 0, 0)
    assert rising < pid2.update(19.5, 20, 30)


# --- PWM -------------------------------------------------------------------

P, MIN = 900, 180


def test_pwm_full_and_zero():
    assert pwm_should_be_on(100, False, inf, P, MIN, MIN)
    assert not pwm_should_be_on(100, False, 60, P, MIN, MIN)     # respects min off
    assert pwm_should_be_on(0, True, 60, P, MIN, MIN)            # respects min on
    assert not pwm_should_be_on(0, True, 200, P, MIN, MIN)


def test_pwm_half_output():
    assert pwm_should_be_on(50, True, 449, P, MIN, MIN)
    assert not pwm_should_be_on(50, True, 451, P, MIN, MIN)
    assert not pwm_should_be_on(50, False, 449, P, MIN, MIN)
    assert pwm_should_be_on(50, False, 451, P, MIN, MIN)


def test_pwm_stretches_short_pulses():
    # 10 % of 15 min would be 90 s on; stretched to 180 s on, 1620 s off
    assert pwm_should_be_on(10, True, 179, P, MIN, MIN)
    assert not pwm_should_be_on(10, True, 181, P, MIN, MIN)
    assert not pwm_should_be_on(10, False, 1600, P, MIN, MIN)
    assert pwm_should_be_on(10, False, 1621, P, MIN, MIN)


def test_pwm_stretches_short_pauses():
    # 95 % would pause 45 s; stretched to 180 s pause, 3420 s on
    assert pwm_should_be_on(95, True, 3400, P, MIN, MIN)
    assert not pwm_should_be_on(95, True, 3430, P, MIN, MIN)


# --- PV boost ----------------------------------------------------------------

def boost():
    return PvBoost(PvBoostSettings(start_export=800, start_delay=600,
                                   stop_import=100, stop_delay=300))


def test_boost_needs_lasting_export():
    b = boost()
    assert not b.update(0, -1000, 0, False, True)
    assert not b.update(300, -1000, 0, False, True)
    assert not b.update(400, -500, 0, False, True)      # dip resets the clock
    assert not b.update(500, -1000, 0, False, True)
    assert not b.update(1000, -1000, 0, False, True)
    assert b.update(1100, -1000, 0, False, True)


def test_boost_survives_own_load_and_stops_on_draw():
    b = boost()
    b.update(0, -1000, 0, False, True)
    assert b.update(600, -1000, 0, False, True)
    assert b.update(700, -300, 0, False, True)          # heaters on: less export, fine
    assert b.update(800, 50, 0, False, True)            # small import tolerated
    assert b.update(900, 50, 200, False, True)          # battery starts covering
    assert b.update(1100, 50, 200, False, True)
    assert not b.update(1200, 50, 200, False, True)     # 300 s of 250 W draw


def test_boost_car_first_and_not_while_battery_discharges():
    b = boost()
    b.update(0, -1000, 0, False, True)
    assert b.update(600, -1000, 0, False, True)
    assert not b.update(610, -1000, 0, True, True)      # car starts charging
    b = boost()
    b.update(0, -1000, 500, False, True)
    assert not b.update(700, -1000, 500, False, True)   # export while battery empties


def test_boost_not_allowed_or_no_grid_value():
    b = boost()
    b.update(0, -1000, 0, False, True)
    assert b.update(600, -1000, 0, False, True)
    assert not b.update(610, None, 0, False, True)
    assert not b.update(620, -1000, 0, False, False)


# --- Season ------------------------------------------------------------------

def test_outdoor_average_moves_slowly():
    avg = OutdoorAverage()
    avg.update(0, 10)
    avg.update(3600, 20)                                # one hour of 20 °C
    assert 10 < avg.value < 11


def test_summer_hysteresis():
    assert not is_summer(None, 15, False)
    assert not is_summer(15.4, 15, False)
    assert is_summer(15.6, 15, False)
    assert is_summer(14.6, 15, True)
    assert not is_summer(14.4, 15, True)


# --- Override end ------------------------------------------------------------

def test_override_end_caps_at_latest_end_today():
    evening = datetime(2026, 11, 3, 21, 30)
    assert override_end(evening, timedelta(hours=3), time(23, 0)) == datetime(2026, 11, 3, 23, 0)
    afternoon = datetime(2026, 11, 3, 15, 0)
    assert override_end(afternoon, timedelta(hours=3), time(23, 0)) == datetime(2026, 11, 3, 18, 0)
    late = datetime(2026, 11, 3, 23, 30)                # past the cap: full duration
    assert override_end(late, timedelta(hours=3), time(23, 0)) == datetime(2026, 11, 4, 2, 30)
    assert override_end(evening, timedelta(hours=3), None) == datetime(2026, 11, 4, 0, 30)


# --- Mode selection ----------------------------------------------------------

def mode(**kw):
    args = dict(enabled=True, sensor_ok=True, summer=False, boost_active=False,
                override=None, now=NOW, targets=TARGETS)
    args.update(kw)
    return select_mode(**args)


def test_mode_priorities():
    comfort = Override(Mode.COMFORT, NOW + timedelta(hours=1), 20)
    assert mode() == (Mode.ECO, 16)
    assert mode(enabled=False, override=comfort) == (Mode.OFF, None)
    assert mode(sensor_ok=False) == (Mode.SENSOR_FAULT, None)
    assert mode(summer=True) == (Mode.SUMMER, None)
    assert mode(summer=True, override=comfort) == (Mode.COMFORT, 20)
    assert mode(boost_active=True) == (Mode.PV_BOOST, 22)
    assert mode(boost_active=True, override=comfort) == (Mode.PV_BOOST, 22)
    manual_hot = Override(Mode.MANUAL, NOW + timedelta(hours=1), 23)
    assert mode(boost_active=True, override=manual_hot) == (Mode.MANUAL, 23)
    expired = Override(Mode.COMFORT, NOW - timedelta(seconds=1), 20)
    assert mode(override=expired) == (Mode.ECO, 16)
