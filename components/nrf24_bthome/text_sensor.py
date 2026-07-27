import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import text_sensor
from esphome.const import CONF_INDEX, CONF_RAW, CONF_TEXT, ENTITY_CATEGORY_DIAGNOSTIC

from . import NRF24BTHomeDevice
from .sensor import CONF_NRF24_BTHOME_DEVICE_ID

CONF_DEVICE_NAME = "device_name"
CONF_FIRMWARE_VERSION = "firmware_version"
CONF_SENDER_ID = "sender_id"

# The two variable-length BTHome objects. Both are [length][bytes] on the wire;
# what differs is what the bytes mean, and that decides how the entity reads:
# text goes through as characters, raw as hex, because raw bytes are not a
# string - a zero in the middle would end one, and most values are not
# printable.
TEXT_TYPES = {
    CONF_TEXT: 0x53,
    CONF_RAW: 0x54,
}


def _text_schema():
    return text_sensor.text_sensor_schema().extend(
        {
            # Which occurrence of the object in a frame this entity takes, as
            # for the measurements. `device_name` below is instance 1 of the
            # text object under the name senders use it for.
            cv.Optional(CONF_INDEX, default=1): cv.int_range(min=1, max=8),
        }
    )


CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_NRF24_BTHOME_DEVICE_ID): cv.use_id(NRF24BTHomeDevice),
        cv.Optional(CONF_DEVICE_NAME): text_sensor.text_sensor_schema(
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
        cv.Optional(CONF_FIRMWARE_VERSION): text_sensor.text_sensor_schema(
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
        cv.Optional(CONF_SENDER_ID): text_sensor.text_sensor_schema(
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
        **{cv.Optional(key): _text_schema() for key in TEXT_TYPES},
    }
)


async def to_code(config):
    device = await cg.get_variable(config[CONF_NRF24_BTHOME_DEVICE_ID])
    if CONF_DEVICE_NAME in config:
        sens = await text_sensor.new_text_sensor(config[CONF_DEVICE_NAME])
        cg.add(device.set_name_text_sensor(sens))
    if CONF_FIRMWARE_VERSION in config:
        sens = await text_sensor.new_text_sensor(config[CONF_FIRMWARE_VERSION])
        cg.add(device.set_firmware_text_sensor(sens))
    if CONF_SENDER_ID in config:
        sens = await text_sensor.new_text_sensor(config[CONF_SENDER_ID])
        cg.add(device.set_sender_id_text_sensor(sens))
    for key, object_id in TEXT_TYPES.items():
        if key not in config:
            continue
        conf = config[key]
        sens = await text_sensor.new_text_sensor(conf)
        cg.add(device.add_object_text_sensor(object_id, conf[CONF_INDEX], sens))
