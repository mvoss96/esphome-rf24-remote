import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import binary_sensor
from esphome.const import DEVICE_CLASS_CONNECTIVITY, ENTITY_CATEGORY_DIAGNOSTIC

from . import NRF24BTHomeDevice
from .sensor import CONF_NRF24_BTHOME_DEVICE_ID

CONF_CONNECTED = "connected"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_NRF24_BTHOME_DEVICE_ID): cv.use_id(NRF24BTHomeDevice),
        # True while frames keep arriving; flips to false after the device's
        # `timeout` quiet period (set timeout > the sender's status interval).
        cv.Optional(CONF_CONNECTED): binary_sensor.binary_sensor_schema(
            device_class=DEVICE_CLASS_CONNECTIVITY,
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
    }
)


async def to_code(config):
    device = await cg.get_variable(config[CONF_NRF24_BTHOME_DEVICE_ID])
    if CONF_CONNECTED in config:
        sens = await binary_sensor.new_binary_sensor(config[CONF_CONNECTED])
        cg.add(device.set_connected_binary_sensor(sens))
