import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation
from esphome.components import nrf24, time
from esphome.const import CONF_ID, CONF_TIME_ID, CONF_TIMEOUT, CONF_TRIGGER_ID

CODEOWNERS = ["@mvoss96"]
DEPENDENCIES = ["nrf24"]
MULTI_CONF = True

nrf24_bthome_ns = cg.esphome_ns.namespace("nrf24_bthome")
NRF24BTHomeHub = nrf24_bthome_ns.class_("NRF24BTHomeHub", cg.Component)
NRF24BTHomeDevice = nrf24_bthome_ns.class_("NRF24BTHomeDevice")
ButtonTrigger = nrf24_bthome_ns.class_(
    "ButtonTrigger", automation.Trigger.template(cg.uint8, cg.std_string)
)
DimmerTrigger = nrf24_bthome_ns.class_(
    "DimmerTrigger", automation.Trigger.template(cg.uint8, cg.int_)
)

CONF_NRF24_ID = "nrf24_id"
CONF_DEVICES = "devices"
CONF_SENDER_ID = "sender_id"
CONF_ON_BUTTON = "on_button"
CONF_ON_DIMMER = "on_dimmer"

BTHOME_CPP_VERSION = "0.4.2"  # PlatformIO registry: mvoss96/bthome-cpp


def _sender_id(value):
    return nrf24.hex_bytes(value, 4, "sender_id")


DEVICE_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(NRF24BTHomeDevice),
        cv.Required(CONF_SENDER_ID): _sender_id,
        # Quiet period after which the connected binary sensor reports
        # offline. Must exceed the sender's periodic status interval;
        # 0s disables the check.
        cv.Optional(CONF_TIMEOUT, default="0s"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_ON_BUTTON): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(ButtonTrigger)}
        ),
        cv.Optional(CONF_ON_DIMMER): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(DimmerTrigger)}
        ),
    }
)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(NRF24BTHomeHub),
        # The radio this receiver listens on; configured via the nrf24 component.
        cv.GenerateID(CONF_NRF24_ID): cv.use_id(nrf24.NRF24Hub),
        # Time source for the devices' last_seen timestamp sensors.
        cv.Optional(CONF_TIME_ID): cv.use_id(time.RealTimeClock),
        cv.Optional(CONF_DEVICES, default=[]): cv.ensure_list(DEVICE_SCHEMA),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    parent = await cg.get_variable(config[CONF_NRF24_ID])
    cg.add(var.set_nrf24_parent(parent))

    rtc = None
    if CONF_TIME_ID in config:
        rtc = await cg.get_variable(config[CONF_TIME_ID])

    for device_config in config[CONF_DEVICES]:
        device = cg.new_Pvariable(device_config[CONF_ID])
        cg.add(device.set_sender_id(device_config[CONF_SENDER_ID]))
        cg.add(device.set_timeout(device_config[CONF_TIMEOUT]))
        if rtc is not None:
            cg.add(device.set_time(rtc))
        cg.add(var.register_device(device))

        for trigger_config in device_config.get(CONF_ON_BUTTON, []):
            trigger = cg.new_Pvariable(trigger_config[CONF_TRIGGER_ID], device)
            await automation.build_automation(
                trigger,
                [(cg.uint8, "button"), (cg.std_string, "event")],
                trigger_config,
            )

        for trigger_config in device_config.get(CONF_ON_DIMMER, []):
            trigger = cg.new_Pvariable(trigger_config[CONF_TRIGGER_ID], device)
            await automation.build_automation(
                trigger,
                [(cg.uint8, "dimmer"), (cg.int_, "steps")],
                trigger_config,
            )

    cg.add_library("mvoss96/bthome-cpp", BTHOME_CPP_VERSION)
