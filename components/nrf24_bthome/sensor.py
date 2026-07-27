import esphome.codegen as cg
import esphome.config_validation as cv
import esphome.final_validate as fv
from esphome.components import sensor
from esphome.const import (
    CONF_CO2,
    CONF_CURRENT,
    CONF_HUMIDITY,
    CONF_ID,
    CONF_ILLUMINANCE,
    CONF_INDEX,
    CONF_POWER,
    CONF_PRESSURE,
    CONF_SPEED,
    CONF_TEMPERATURE,
    CONF_TIME_ID,
    CONF_VOLTAGE,
    DEVICE_CLASS_BATTERY,
    DEVICE_CLASS_CARBON_DIOXIDE,
    DEVICE_CLASS_CURRENT,
    DEVICE_CLASS_DISTANCE,
    DEVICE_CLASS_DURATION,
    DEVICE_CLASS_ENERGY,
    DEVICE_CLASS_GAS,
    DEVICE_CLASS_HUMIDITY,
    DEVICE_CLASS_ILLUMINANCE,
    DEVICE_CLASS_MOISTURE,
    DEVICE_CLASS_PM10,
    DEVICE_CLASS_PM25,
    DEVICE_CLASS_POWER,
    DEVICE_CLASS_PRECIPITATION,
    DEVICE_CLASS_PRESSURE,
    DEVICE_CLASS_SPEED,
    DEVICE_CLASS_TEMPERATURE,
    DEVICE_CLASS_TIMESTAMP,
    DEVICE_CLASS_VOLATILE_ORGANIC_COMPOUNDS,
    DEVICE_CLASS_VOLTAGE,
    DEVICE_CLASS_VOLUME,
    DEVICE_CLASS_WEIGHT,
    ENTITY_CATEGORY_DIAGNOSTIC,
    STATE_CLASS_MEASUREMENT,
    STATE_CLASS_TOTAL_INCREASING,
    UNIT_AMPERE,
    UNIT_CELSIUS,
    UNIT_CUBIC_METER,
    UNIT_DEGREES,
    UNIT_HECTOPASCAL,
    UNIT_KILOGRAM,
    UNIT_KILOWATT_HOURS,
    UNIT_LUX,
    UNIT_METER,
    UNIT_METER_PER_SECOND,
    UNIT_MICROGRAMS_PER_CUBIC_METER,
    UNIT_MICROSIEMENS_PER_CENTIMETER,
    UNIT_MILLIMETER,
    UNIT_PARTS_PER_MILLION,
    UNIT_PERCENT,
    UNIT_SECOND,
    UNIT_VOLT,
    UNIT_WATT,
)

from . import CONF_DEVICES, NRF24BTHomeDevice

CONF_NRF24_BTHOME_DEVICE_ID = "nrf24_bthome_device_id"
CONF_LAST_SEEN = "last_seen"

# One entry per BTHome measurement object this component can map, keyed by the
# name it takes in YAML. The object id is what the sender puts on the air; the
# rest is what Home Assistant needs to show the value properly, and BTHome does
# not carry it - bthome-cpp knows a value's width, sign and scale, but not that
# 0x02 is a temperature in degrees Celsius.
#
# Named keys rather than a bare object id, so a configuration cannot end up with
# a plausible-looking entity carrying the wrong unit or device class. The list is
# deliberately finite: adding a type is a few lines here, and every line is a
# decision about how the value should read in Home Assistant.
#
# Binary BTHome objects (motion, door, opening, ...) are not here; they belong on
# the binary_sensor platform and are left for their own change.
SENSOR_TYPES = {
    # key: (object id, unit, device class, accuracy, state class)
    "battery": (0x01, UNIT_PERCENT, DEVICE_CLASS_BATTERY, 0, STATE_CLASS_MEASUREMENT),
    CONF_TEMPERATURE: (
        0x02, UNIT_CELSIUS, DEVICE_CLASS_TEMPERATURE, 2, STATE_CLASS_MEASUREMENT),
    CONF_HUMIDITY: (0x03, UNIT_PERCENT, DEVICE_CLASS_HUMIDITY, 2, STATE_CLASS_MEASUREMENT),
    CONF_PRESSURE: (
        0x04, UNIT_HECTOPASCAL, DEVICE_CLASS_PRESSURE, 2, STATE_CLASS_MEASUREMENT),
    CONF_ILLUMINANCE: (0x05, UNIT_LUX, DEVICE_CLASS_ILLUMINANCE, 2, STATE_CLASS_MEASUREMENT),
    "mass": (0x06, UNIT_KILOGRAM, DEVICE_CLASS_WEIGHT, 2, STATE_CLASS_MEASUREMENT),
    "dewpoint": (0x08, UNIT_CELSIUS, DEVICE_CLASS_TEMPERATURE, 2, STATE_CLASS_MEASUREMENT),
    # A plain counter: no unit and no device class, because BTHome does not say
    # what is being counted.
    "count": (0x09, None, None, 0, STATE_CLASS_MEASUREMENT),
    "energy": (
        0x0A, UNIT_KILOWATT_HOURS, DEVICE_CLASS_ENERGY, 3, STATE_CLASS_TOTAL_INCREASING),
    CONF_POWER: (0x0B, UNIT_WATT, DEVICE_CLASS_POWER, 2, STATE_CLASS_MEASUREMENT),
    CONF_VOLTAGE: (0x0C, UNIT_VOLT, DEVICE_CLASS_VOLTAGE, 3, STATE_CLASS_MEASUREMENT),
    "pm2_5": (
        0x0D, UNIT_MICROGRAMS_PER_CUBIC_METER, DEVICE_CLASS_PM25, 0, STATE_CLASS_MEASUREMENT),
    "pm10": (
        0x0E, UNIT_MICROGRAMS_PER_CUBIC_METER, DEVICE_CLASS_PM10, 0, STATE_CLASS_MEASUREMENT),
    CONF_CO2: (
        0x12, UNIT_PARTS_PER_MILLION, DEVICE_CLASS_CARBON_DIOXIDE, 0, STATE_CLASS_MEASUREMENT),
    "tvoc": (
        0x13,
        UNIT_MICROGRAMS_PER_CUBIC_METER,
        DEVICE_CLASS_VOLATILE_ORGANIC_COMPOUNDS,
        0,
        STATE_CLASS_MEASUREMENT,
    ),
    "moisture": (0x14, UNIT_PERCENT, DEVICE_CLASS_MOISTURE, 2, STATE_CLASS_MEASUREMENT),
    "rotation": (0x3F, UNIT_DEGREES, None, 1, STATE_CLASS_MEASUREMENT),
    # Two distances of different resolution, both kept: a sender picks one, and
    # folding them onto a single key would hide which.
    "distance_mm": (0x40, UNIT_MILLIMETER, DEVICE_CLASS_DISTANCE, 0, STATE_CLASS_MEASUREMENT),
    "distance_m": (0x41, UNIT_METER, DEVICE_CLASS_DISTANCE, 1, STATE_CLASS_MEASUREMENT),
    "duration": (0x42, UNIT_SECOND, DEVICE_CLASS_DURATION, 3, STATE_CLASS_MEASUREMENT),
    CONF_CURRENT: (0x43, UNIT_AMPERE, DEVICE_CLASS_CURRENT, 3, STATE_CLASS_MEASUREMENT),
    CONF_SPEED: (0x44, UNIT_METER_PER_SECOND, DEVICE_CLASS_SPEED, 2, STATE_CLASS_MEASUREMENT),
    "uv_index": (0x46, None, None, 1, STATE_CLASS_MEASUREMENT),
    # esphome has no UNIT_LITER constant; the symbol is the unit. One decimal,
    # not three: the object is scaled by 0.1, so the further places would be
    # zeros the sender never measured.
    "volume": (0x47, "L", DEVICE_CLASS_VOLUME, 1, STATE_CLASS_MEASUREMENT),
    "gas": (0x4B, UNIT_CUBIC_METER, DEVICE_CLASS_GAS, 3, STATE_CLASS_TOTAL_INCREASING),
    "conductivity": (
        0x56, UNIT_MICROSIEMENS_PER_CENTIMETER, None, 0, STATE_CLASS_MEASUREMENT),
    "precipitation": (
        0x5F, UNIT_MILLIMETER, DEVICE_CLASS_PRECIPITATION, 1, STATE_CLASS_MEASUREMENT),
}

# What a device says about itself rather than about the world, so it does not
# clutter the device's main controls in Home Assistant.
DIAGNOSTIC_KEYS = {"battery", CONF_VOLTAGE}


def _sensor_schema(key):
    object_id, unit, device_class, accuracy, state_class = SENSOR_TYPES[key]
    del object_id  # used by to_code(), not by the schema

    # cv.UNDEFINED rather than None: sensor_schema() distinguishes "not given"
    # from a value, and passing None explicitly makes it validate None as a
    # string. So a type without a unit or device class - a bare counter, a UV
    # index - has to leave the argument out entirely.
    optional = {}
    if unit is not None:
        optional["unit_of_measurement"] = unit
    if device_class is not None:
        optional["device_class"] = device_class
    if key in DIAGNOSTIC_KEYS:
        optional["entity_category"] = ENTITY_CATEGORY_DIAGNOSTIC

    return sensor.sensor_schema(
        accuracy_decimals=accuracy,
        state_class=state_class,
        **optional,
    ).extend(
        {
            # Which occurrence of this object in a frame the sensor takes. The
            # k-th object of a type addresses instance k, as it already does for
            # buttons and dimmers, so a node with two probes of one kind can have
            # an entity for each instead of the second overwriting the first. A
            # second instance needs its own platform entry.
            cv.Optional(CONF_INDEX, default=1): cv.int_range(min=1, max=8),
        }
    )


CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_NRF24_BTHOME_DEVICE_ID): cv.use_id(NRF24BTHomeDevice),
        # Epoch of the last unique packet; needs time_id on the hub. Not a BTHome
        # object - the receiver observes it - so it is not in the table above.
        # float32 quantizes the epoch to ~2 minutes, plenty for battery remotes.
        cv.Optional(CONF_LAST_SEEN): sensor.sensor_schema(
            device_class=DEVICE_CLASS_TIMESTAMP,
            accuracy_decimals=0,
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
        **{cv.Optional(key): _sensor_schema(key) for key in SENSOR_TYPES},
    }
)


def _require_hub_time_id(config):
    """last_seen publishes rtc->utcnow(); without time_id on the hub the
    entity would exist in HA but stay 'unknown' forever - fail loudly."""
    if CONF_LAST_SEEN not in config:
        return config
    device_id = str(config[CONF_NRF24_BTHOME_DEVICE_ID])
    for hub in fv.full_config.get().get("nrf24_bthome") or []:
        for dev in hub.get(CONF_DEVICES, []):
            if str(dev[CONF_ID]) == device_id and CONF_TIME_ID not in hub:
                raise cv.Invalid(
                    "last_seen requires time_id on the nrf24_bthome hub "
                    "(add e.g. a 'time: - platform: homeassistant' component "
                    "and reference it via time_id)"
                )
    return config


FINAL_VALIDATE_SCHEMA = _require_hub_time_id


async def to_code(config):
    device = await cg.get_variable(config[CONF_NRF24_BTHOME_DEVICE_ID])
    for key, entry in SENSOR_TYPES.items():
        if key not in config:
            continue
        conf = config[key]
        sens = await sensor.new_sensor(conf)
        cg.add(device.add_object_sensor(entry[0], conf[CONF_INDEX], sens))
    if CONF_LAST_SEEN in config:
        sens = await sensor.new_sensor(config[CONF_LAST_SEEN])
        cg.add(device.set_last_seen_sensor(sens))
