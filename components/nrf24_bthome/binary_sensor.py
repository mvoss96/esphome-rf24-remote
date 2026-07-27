import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import binary_sensor
from esphome.const import (
    CONF_INDEX,
    CONF_LIGHT,
    CONF_POWER,
    DEVICE_CLASS_BATTERY,
    DEVICE_CLASS_BATTERY_CHARGING,
    DEVICE_CLASS_CARBON_MONOXIDE,
    DEVICE_CLASS_COLD,
    DEVICE_CLASS_CONNECTIVITY,
    DEVICE_CLASS_DOOR,
    DEVICE_CLASS_GARAGE_DOOR,
    DEVICE_CLASS_GAS,
    DEVICE_CLASS_HEAT,
    DEVICE_CLASS_LIGHT,
    DEVICE_CLASS_LOCK,
    DEVICE_CLASS_MOISTURE,
    DEVICE_CLASS_MOTION,
    DEVICE_CLASS_MOVING,
    DEVICE_CLASS_OCCUPANCY,
    DEVICE_CLASS_OPENING,
    DEVICE_CLASS_PLUG,
    DEVICE_CLASS_POWER,
    DEVICE_CLASS_PRESENCE,
    DEVICE_CLASS_PROBLEM,
    DEVICE_CLASS_RUNNING,
    DEVICE_CLASS_SAFETY,
    DEVICE_CLASS_SMOKE,
    DEVICE_CLASS_SOUND,
    DEVICE_CLASS_TAMPER,
    DEVICE_CLASS_VIBRATION,
    DEVICE_CLASS_WINDOW,
    ENTITY_CATEGORY_DIAGNOSTIC,
)

from . import NRF24BTHomeDevice
from .sensor import CONF_NRF24_BTHOME_DEVICE_ID

CONF_CONNECTED = "connected"

# The BTHome binary objects, keyed by the name they take in YAML. Every one of
# them is a single byte, 0 or 1, so unlike the measurements there is nothing to
# scale - what the table adds is the device class, which decides what Home
# Assistant calls the two states: a door is open/closed, a motion sensor is
# detected/clear, a lock is locked/unlocked.
#
# BTHome's own names are kept, except where one is already taken by something
# this component observes rather than receives - see `connectivity` below.
BINARY_TYPES = {
    # key: (object id, device class)
    # No device class: BTHome's generic boolean says nothing about meaning.
    "generic": (0x0F, None),
    CONF_POWER: (0x10, DEVICE_CLASS_POWER),
    "opening": (0x11, DEVICE_CLASS_OPENING),
    "battery_low": (0x15, DEVICE_CLASS_BATTERY),
    "battery_charging": (0x16, DEVICE_CLASS_BATTERY_CHARGING),
    "carbon_monoxide": (0x17, DEVICE_CLASS_CARBON_MONOXIDE),
    "cold": (0x18, DEVICE_CLASS_COLD),
    # Not `connected`: that one is the receiver's own view of the link, derived
    # from the quiet period, while this is a flag the sender puts in a frame.
    # A sender cannot report over the radio that its radio stopped working.
    "connectivity": (0x19, DEVICE_CLASS_CONNECTIVITY),
    "door": (0x1A, DEVICE_CLASS_DOOR),
    "garage_door": (0x1B, DEVICE_CLASS_GARAGE_DOOR),
    "gas": (0x1C, DEVICE_CLASS_GAS),
    "heat": (0x1D, DEVICE_CLASS_HEAT),
    CONF_LIGHT: (0x1E, DEVICE_CLASS_LIGHT),
    "lock": (0x1F, DEVICE_CLASS_LOCK),
    "moisture": (0x20, DEVICE_CLASS_MOISTURE),
    "motion": (0x21, DEVICE_CLASS_MOTION),
    "moving": (0x22, DEVICE_CLASS_MOVING),
    "occupancy": (0x23, DEVICE_CLASS_OCCUPANCY),
    "plug": (0x24, DEVICE_CLASS_PLUG),
    "presence": (0x25, DEVICE_CLASS_PRESENCE),
    "problem": (0x26, DEVICE_CLASS_PROBLEM),
    "running": (0x27, DEVICE_CLASS_RUNNING),
    "safety": (0x28, DEVICE_CLASS_SAFETY),
    "smoke": (0x29, DEVICE_CLASS_SMOKE),
    "sound": (0x2A, DEVICE_CLASS_SOUND),
    "tamper": (0x2B, DEVICE_CLASS_TAMPER),
    "vibration": (0x2C, DEVICE_CLASS_VIBRATION),
    "window": (0x2D, DEVICE_CLASS_WINDOW),
}

# What the device reports about itself rather than about the world.
DIAGNOSTIC_KEYS = {"battery_low", "battery_charging", "connectivity", "problem", "tamper"}


def _binary_schema(key):
    object_id, device_class = BINARY_TYPES[key]
    del object_id  # used by to_code(), not by the schema

    # cv.UNDEFINED is the "not given" sentinel; passing None explicitly would
    # have it validated as a string.
    optional = {}
    if device_class is not None:
        optional["device_class"] = device_class
    if key in DIAGNOSTIC_KEYS:
        optional["entity_category"] = ENTITY_CATEGORY_DIAGNOSTIC

    return binary_sensor.binary_sensor_schema(**optional).extend(
        {
            # The k-th object of a type addresses instance k, as for the
            # measurements: a node with two door contacts gets one entity each.
            cv.Optional(CONF_INDEX, default=1): cv.int_range(min=1, max=8),
        }
    )


CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_NRF24_BTHOME_DEVICE_ID): cv.use_id(NRF24BTHomeDevice),
        # True while frames keep arriving; flips to false after the device's
        # `timeout` quiet period (set timeout > the sender's status interval).
        # Observed by the receiver, not sent - hence not in the table above.
        cv.Optional(CONF_CONNECTED): binary_sensor.binary_sensor_schema(
            device_class=DEVICE_CLASS_CONNECTIVITY,
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
        **{cv.Optional(key): _binary_schema(key) for key in BINARY_TYPES},
    }
)


async def to_code(config):
    device = await cg.get_variable(config[CONF_NRF24_BTHOME_DEVICE_ID])
    if CONF_CONNECTED in config:
        sens = await binary_sensor.new_binary_sensor(config[CONF_CONNECTED])
        cg.add(device.set_connected_binary_sensor(sens))
    for key, (object_id, _) in BINARY_TYPES.items():
        if key not in config:
            continue
        conf = config[key]
        sens = await binary_sensor.new_binary_sensor(conf)
        cg.add(device.add_object_binary_sensor(object_id, conf[CONF_INDEX], sens))
