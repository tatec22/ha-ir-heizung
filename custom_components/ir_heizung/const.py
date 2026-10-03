"""Constants for the IR heating thermostat."""

DOMAIN = "ir_heizung"
PLATFORMS = ["binary_sensor", "button", "climate", "sensor"]

# Setup (config entry data)
CONF_NAME = "name"
CONF_HEATERS = "heaters"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"

# Options: temperatures
CONF_ECO_TEMP = "eco_temp"
CONF_COMFORT_TEMP = "comfort_temp"
CONF_BOOST_TEMP = "boost_temp"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"

# Options: comfort / manual period
CONF_OVERRIDE_MINUTES = "override_minutes"
CONF_LATEST_END = "latest_end"

# Options: PV boost
CONF_BOOST_ENABLED = "boost_enabled"
CONF_GRID_POWER = "grid_power_sensor"
CONF_BATTERY_POWER = "battery_power_sensor"
CONF_CAR_CHARGING = "car_charging_sensor"
CONF_BOOST_START_EXPORT = "boost_start_export"
CONF_BOOST_START_MINUTES = "boost_start_minutes"
CONF_BOOST_STOP_IMPORT = "boost_stop_import"
CONF_BOOST_STOP_MINUTES = "boost_stop_minutes"

# Options: season
CONF_OUTDOOR_SENSOR = "outdoor_sensor"
CONF_HEATING_LIMIT = "heating_limit"

# Options: controller
CONF_KP = "kp"
CONF_KI = "ki"
CONF_KD = "kd"
CONF_PWM_MINUTES = "pwm_minutes"
CONF_MIN_ON_MINUTES = "min_on_minutes"
CONF_MIN_OFF_MINUTES = "min_off_minutes"
CONF_REFRESH_MINUTES = "refresh_minutes"
CONF_STALE_MINUTES = "stale_minutes"

DEFAULT_OPTIONS = {
    CONF_ECO_TEMP: 16.0,
    CONF_COMFORT_TEMP: 20.0,
    CONF_BOOST_TEMP: 22.0,
    CONF_MIN_TEMP: 5.0,
    CONF_MAX_TEMP: 24.0,
    CONF_OVERRIDE_MINUTES: 180,
    CONF_LATEST_END: "23:00:00",
    CONF_BOOST_ENABLED: False,
    CONF_BOOST_START_EXPORT: 800,
    CONF_BOOST_START_MINUTES: 10,
    CONF_BOOST_STOP_IMPORT: 100,
    CONF_BOOST_STOP_MINUTES: 5,
    CONF_HEATING_LIMIT: 15.0,
    CONF_KP: 60.0,
    CONF_KI: 0.003,
    CONF_KD: 0.0,
    CONF_PWM_MINUTES: 15,
    CONF_MIN_ON_MINUTES: 3,
    CONF_MIN_OFF_MINUTES: 3,
    CONF_REFRESH_MINUTES: 5,
    CONF_STALE_MINUTES: 180,
}

OPTION_SECTIONS = {
    "temperatures": (CONF_ECO_TEMP, CONF_COMFORT_TEMP, CONF_BOOST_TEMP,
                     CONF_MIN_TEMP, CONF_MAX_TEMP),
    "comfort": (CONF_OVERRIDE_MINUTES, CONF_LATEST_END),
    "pv_boost": (CONF_BOOST_ENABLED, CONF_GRID_POWER, CONF_BATTERY_POWER,
                 CONF_CAR_CHARGING, CONF_BOOST_START_EXPORT, CONF_BOOST_START_MINUTES,
                 CONF_BOOST_STOP_IMPORT, CONF_BOOST_STOP_MINUTES),
    "season": (CONF_OUTDOOR_SENSOR, CONF_HEATING_LIMIT),
    "controller": (CONF_KP, CONF_KI, CONF_KD, CONF_PWM_MINUTES, CONF_MIN_ON_MINUTES,
                   CONF_MIN_OFF_MINUTES, CONF_REFRESH_MINUTES, CONF_STALE_MINUTES),
}

# Optional entity fields: clearing them in the form removes them.
OPTIONAL_ENTITIES = (CONF_GRID_POWER, CONF_BATTERY_POWER, CONF_CAR_CHARGING,
                     CONF_OUTDOOR_SENSOR)

TICK_SECONDS = 30
MAX_PID_DT = 300
