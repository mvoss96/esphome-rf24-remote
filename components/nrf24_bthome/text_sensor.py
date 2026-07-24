import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import text_sensor
from esphome.const import ENTITY_CATEGORY_DIAGNOSTIC

from . import NRF24BTHomeDevice
from .sensor import CONF_NRF24_BTHOME_DEVICE_ID

CONF_DEVICE_NAME = "device_name"
CONF_FIRMWARE_VERSION = "firmware_version"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_NRF24_BTHOME_DEVICE_ID): cv.use_id(NRF24BTHomeDevice),
        cv.Optional(CONF_DEVICE_NAME): text_sensor.text_sensor_schema(
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
        cv.Optional(CONF_FIRMWARE_VERSION): text_sensor.text_sensor_schema(
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
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
