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
    DEVICE_CLASS_VOLUME_FLOW_RATE,
    DEVICE_CLASS_VOLUME_STORAGE,
    DEVICE_CLASS_WATER,
    DEVICE_CLASS_WEIGHT,
    ENTITY_CATEGORY_DIAGNOSTIC,
    STATE_CLASS_MEASUREMENT,
    STATE_CLASS_TOTAL_INCREASING,
    UNIT_AMPERE,
    UNIT_CELSIUS,
    UNIT_CUBIC_METER,
    UNIT_CUBIC_METER_PER_HOUR,
    UNIT_DEGREE_PER_SECOND,
    UNIT_DEGREES,
    UNIT_HECTOPASCAL,
    UNIT_KILOGRAM,
    UNIT_KILOWATT_HOURS,
    UNIT_LITRE,
    UNIT_LUX,
    UNIT_METER,
    UNIT_METER_PER_SECOND,
    UNIT_METER_PER_SECOND_SQUARED,
    UNIT_MICROGRAMS_PER_CUBIC_METER,
    UNIT_MICROSIEMENS_PER_CENTIMETER,
    UNIT_MILLIMETER,
    UNIT_PARTS_PER_MILLION,
    UNIT_PERCENT,
    UNIT_REVOLUTIONS_PER_MINUTE,
    UNIT_SECOND,
    UNIT_VOLT,
    UNIT_WATT,
)

from . import CONF_DEVICES, NRF24BTHomeDevice

CONF_NRF24_BTHOME_DEVICE_ID = "nrf24_bthome_device_id"
CONF_LAST_SEEN = "last_seen"

MEAS = STATE_CLASS_MEASUREMENT
TOTAL = STATE_CLASS_TOTAL_INCREASING

# One entry per BTHome measurement this component can map, keyed by the name it
# takes in YAML. The object ids are what the sender puts on the air; the rest is
# what Home Assistant needs to show the value properly, and BTHome does not
# carry it - bthome-cpp knows a value's width, sign and scale, but not that 0x02
# is a temperature in degrees Celsius.
#
# Named keys rather than a bare object id, so a configuration cannot end up with
# a plausible-looking entity carrying the wrong unit or device class.
#
# Several ids under one key, but only when they differ in width or sign alone -
# BTHome states a count six ways and energy two, all of them the same quantity
# in the same unit at the same resolution, and a sender picks one. Where the
# resolution or the unit differs the key is separate, even for the same
# quantity: folding 0x02 (0.01 C) together with 0x57 (whole degrees) would make
# one entity claim a precision that depends on which id happened to arrive.
# Those carry the library's own name for the id as a suffix, so the id a sender
# documents can be found here.
#
# Binary BTHome objects live in binary_sensor.py, on the platform they belong to.
SENSOR_TYPES = {
    # key: (object ids, unit, device class, accuracy, state class)
    "battery": ((0x01,), UNIT_PERCENT, DEVICE_CLASS_BATTERY, 0, MEAS),
    CONF_TEMPERATURE: ((0x02,), UNIT_CELSIUS, DEVICE_CLASS_TEMPERATURE, 2, MEAS),
    CONF_HUMIDITY: ((0x03,), UNIT_PERCENT, DEVICE_CLASS_HUMIDITY, 2, MEAS),
    CONF_PRESSURE: ((0x04,), UNIT_HECTOPASCAL, DEVICE_CLASS_PRESSURE, 2, MEAS),
    CONF_ILLUMINANCE: ((0x05,), UNIT_LUX, DEVICE_CLASS_ILLUMINANCE, 2, MEAS),
    "mass": ((0x06,), UNIT_KILOGRAM, DEVICE_CLASS_WEIGHT, 2, MEAS),
    # esphome has no constant for pounds; the symbol is the unit.
    "mass_lb": ((0x07,), "lb", DEVICE_CLASS_WEIGHT, 2, MEAS),
    "dewpoint": ((0x08,), UNIT_CELSIUS, DEVICE_CLASS_TEMPERATURE, 2, MEAS),
    # Six widths of the same thing. No unit and no device class: BTHome does not
    # say what is being counted.
    "count": ((0x09, 0x3D, 0x3E, 0x59, 0x5A, 0x5B), None, None, 0, MEAS),
    "energy": ((0x0A, 0x4D), UNIT_KILOWATT_HOURS, DEVICE_CLASS_ENERGY, 3, TOTAL),
    "power": ((0x0B, 0x5C), UNIT_WATT, DEVICE_CLASS_POWER, 2, MEAS),
    CONF_VOLTAGE: ((0x0C,), UNIT_VOLT, DEVICE_CLASS_VOLTAGE, 3, MEAS),
    "pm2_5": ((0x0D,), UNIT_MICROGRAMS_PER_CUBIC_METER, DEVICE_CLASS_PM25, 0, MEAS),
    "pm10": ((0x0E,), UNIT_MICROGRAMS_PER_CUBIC_METER, DEVICE_CLASS_PM10, 0, MEAS),
    CONF_CO2: ((0x12,), UNIT_PARTS_PER_MILLION, DEVICE_CLASS_CARBON_DIOXIDE, 0, MEAS),
    "tvoc": (
        (0x13,),
        UNIT_MICROGRAMS_PER_CUBIC_METER,
        DEVICE_CLASS_VOLATILE_ORGANIC_COMPOUNDS,
        0,
        MEAS,
    ),
    "moisture": ((0x14,), UNIT_PERCENT, DEVICE_CLASS_MOISTURE, 2, MEAS),
    "humidity_u8": ((0x2E,), UNIT_PERCENT, DEVICE_CLASS_HUMIDITY, 0, MEAS),
    "moisture_u8": ((0x2F,), UNIT_PERCENT, DEVICE_CLASS_MOISTURE, 0, MEAS),
    "rotation": ((0x3F,), UNIT_DEGREES, None, 1, MEAS),
    # Two distances of different resolution, both kept: a sender picks one, and
    # folding them onto a single key would hide which.
    "distance_mm": ((0x40,), UNIT_MILLIMETER, DEVICE_CLASS_DISTANCE, 0, MEAS),
    "distance_m": ((0x41,), UNIT_METER, DEVICE_CLASS_DISTANCE, 1, MEAS),
    "duration": ((0x42,), UNIT_SECOND, DEVICE_CLASS_DURATION, 3, MEAS),
    CONF_CURRENT: ((0x43, 0x5D), UNIT_AMPERE, DEVICE_CLASS_CURRENT, 3, MEAS),
    CONF_SPEED: ((0x44,), UNIT_METER_PER_SECOND, DEVICE_CLASS_SPEED, 2, MEAS),
    "temperature_c1": ((0x45,), UNIT_CELSIUS, DEVICE_CLASS_TEMPERATURE, 1, MEAS),
    "uv_index": ((0x46,), None, None, 1, MEAS),
    "volume": ((0x47,), UNIT_LITRE, DEVICE_CLASS_VOLUME, 1, MEAS),
    "volume_ml": ((0x48,), "mL", DEVICE_CLASS_VOLUME, 0, MEAS),
    "volume_flow_rate": (
        (0x49,),
        UNIT_CUBIC_METER_PER_HOUR,
        DEVICE_CLASS_VOLUME_FLOW_RATE,
        3,
        MEAS,
    ),
    "voltage_centi": ((0x4A,), UNIT_VOLT, DEVICE_CLASS_VOLTAGE, 1, MEAS),
    "gas": ((0x4B, 0x4C), UNIT_CUBIC_METER, DEVICE_CLASS_GAS, 3, TOTAL),
    "volume_u32": ((0x4E,), UNIT_LITRE, DEVICE_CLASS_VOLUME, 3, MEAS),
    "water": ((0x4F,), UNIT_LITRE, DEVICE_CLASS_WATER, 3, TOTAL),
    # An instant, not a quantity: no unit, no state class. Published as an epoch
    # like last_seen, which is how esphome carries a timestamp on a sensor.
    "timestamp": ((0x50,), None, DEVICE_CLASS_TIMESTAMP, 0, None),
    "acceleration": ((0x51,), UNIT_METER_PER_SECOND_SQUARED, None, 3, MEAS),
    "gyroscope": ((0x52,), UNIT_DEGREE_PER_SECOND, None, 3, MEAS),
    "volume_storage": ((0x55,), UNIT_LITRE, DEVICE_CLASS_VOLUME_STORAGE, 3, MEAS),
    "conductivity": ((0x56,), UNIT_MICROSIEMENS_PER_CENTIMETER, None, 0, MEAS),
    "temperature_s8": ((0x57,), UNIT_CELSIUS, DEVICE_CLASS_TEMPERATURE, 0, MEAS),
    # Whole degrees would lose a third of the range: the object is a signed byte
    # scaled by 0.35, so its steps land between the second decimal places.
    "temperature_s8_035": ((0x58,), UNIT_CELSIUS, DEVICE_CLASS_TEMPERATURE, 2, MEAS),
    # A bearing in degrees. No device class: esphome's wind_direction would claim
    # a meaning BTHome does not give this object.
    "direction": ((0x5E,), UNIT_DEGREES, None, 2, MEAS),
    "precipitation": ((0x5F,), UNIT_MILLIMETER, DEVICE_CLASS_PRECIPITATION, 1, MEAS),
    "channel": ((0x60,), None, None, 0, MEAS),
    "rotational_speed": ((0x61,), UNIT_REVOLUTIONS_PER_MINUTE, None, 0, MEAS),
    # Six decimals, which is the point of these two: they exist for senders whose
    # resolution the 0x44 / 0x51 forms cannot express.
    "speed_s32": ((0x62,), UNIT_METER_PER_SECOND, DEVICE_CLASS_SPEED, 6, MEAS),
    "acceleration_s32": ((0x63,), UNIT_METER_PER_SECOND_SQUARED, None, 6, MEAS),
    "light_level": ((0x64,), None, None, 0, MEAS),
    "settings_revision": ((0x65,), None, None, 0, None),
}

# What a device says about itself rather than about the world, so it does not
# clutter the device's main controls in Home Assistant.
DIAGNOSTIC_KEYS = {"battery", CONF_VOLTAGE, "voltage_centi", "settings_revision"}


def _sensor_schema(key):
    object_ids, unit, device_class, accuracy, state_class = SENSOR_TYPES[key]
    del object_ids  # used by to_code(), not by the schema

    # cv.UNDEFINED rather than None: sensor_schema() distinguishes "not given"
    # from a value, and passing None explicitly makes it validate None as a
    # string. So a type without a unit or device class - a bare counter, a UV
    # index - has to leave the argument out entirely.
    optional = {}
    if unit is not None:
        optional["unit_of_measurement"] = unit
    if device_class is not None:
        optional["device_class"] = device_class
    if state_class is not None:
        optional["state_class"] = state_class
    if key in DIAGNOSTIC_KEYS:
        optional["entity_category"] = ENTITY_CATEGORY_DIAGNOSTIC

    return sensor.sensor_schema(
        accuracy_decimals=accuracy,
        **optional,
    ).extend(
        {
            # Which occurrence of this object in a frame the sensor takes. The
            # k-th object of a type addresses instance k, as it already does for
            # buttons and dimmers, so a node with two probes of one kind can have
            # an entity for each instead of the second overwriting the first. A
            # second instance needs its own platform entry.
            cv.Optional(CONF_INDEX, default=1): cv.int_range(min=1, max=12),
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
        # One registration per object id the key covers: whichever of them a
        # sender uses, the value lands on the same entity.
        for object_id in entry[0]:
            cg.add(device.add_object_sensor(object_id, conf[CONF_INDEX], sens))
    if CONF_LAST_SEEN in config:
        sens = await sensor.new_sensor(config[CONF_LAST_SEEN])
        cg.add(device.set_last_seen_sensor(sens))
