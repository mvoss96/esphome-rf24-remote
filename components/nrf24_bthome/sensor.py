import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import sensor
from esphome.const import (
    CONF_VOLTAGE,
    DEVICE_CLASS_BATTERY,
    DEVICE_CLASS_VOLTAGE,
    ENTITY_CATEGORY_DIAGNOSTIC,
    STATE_CLASS_MEASUREMENT,
    UNIT_PERCENT,
    UNIT_VOLT,
)

from . import NRF24BTHomeDevice

CONF_NRF24_BTHOME_DEVICE_ID = "nrf24_bthome_device_id"
CONF_BATTERY = "battery"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_NRF24_BTHOME_DEVICE_ID): cv.use_id(NRF24BTHomeDevice),
        cv.Optional(CONF_BATTERY): sensor.sensor_schema(
            unit_of_measurement=UNIT_PERCENT,
            accuracy_decimals=0,
            device_class=DEVICE_CLASS_BATTERY,
            state_class=STATE_CLASS_MEASUREMENT,
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
        cv.Optional(CONF_VOLTAGE): sensor.sensor_schema(
            unit_of_measurement=UNIT_VOLT,
            accuracy_decimals=3,
            device_class=DEVICE_CLASS_VOLTAGE,
            state_class=STATE_CLASS_MEASUREMENT,
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
    }
)


async def to_code(config):
    device = await cg.get_variable(config[CONF_NRF24_BTHOME_DEVICE_ID])
    if CONF_BATTERY in config:
        sens = await sensor.new_sensor(config[CONF_BATTERY])
        cg.add(device.set_battery_sensor(sens))
    if CONF_VOLTAGE in config:
        sens = await sensor.new_sensor(config[CONF_VOLTAGE])
        cg.add(device.set_voltage_sensor(sens))
