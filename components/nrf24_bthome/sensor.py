import esphome.codegen as cg
import esphome.config_validation as cv
import esphome.final_validate as fv
from esphome.components import sensor
from esphome.const import (
    CONF_ID,
    CONF_TIME_ID,
    CONF_VOLTAGE,
    DEVICE_CLASS_BATTERY,
    DEVICE_CLASS_TIMESTAMP,
    DEVICE_CLASS_VOLTAGE,
    ENTITY_CATEGORY_DIAGNOSTIC,
    STATE_CLASS_MEASUREMENT,
    UNIT_PERCENT,
    UNIT_VOLT,
)

from . import CONF_DEVICES, NRF24BTHomeDevice

CONF_NRF24_BTHOME_DEVICE_ID = "nrf24_bthome_device_id"
CONF_BATTERY = "battery"
CONF_LAST_SEEN = "last_seen"

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
        # Epoch of the last unique packet; needs time_id on the hub. float32
        # quantizes the epoch to ~2 minutes, plenty for battery remotes.
        cv.Optional(CONF_LAST_SEEN): sensor.sensor_schema(
            device_class=DEVICE_CLASS_TIMESTAMP,
            accuracy_decimals=0,
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        ),
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
    if CONF_BATTERY in config:
        sens = await sensor.new_sensor(config[CONF_BATTERY])
        cg.add(device.set_battery_sensor(sens))
    if CONF_VOLTAGE in config:
        sens = await sensor.new_sensor(config[CONF_VOLTAGE])
        cg.add(device.set_voltage_sensor(sens))
    if CONF_LAST_SEEN in config:
        sens = await sensor.new_sensor(config[CONF_LAST_SEEN])
        cg.add(device.set_last_seen_sensor(sens))
