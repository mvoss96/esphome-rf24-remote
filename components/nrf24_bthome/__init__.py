import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation, pins
from esphome.components import spi, time
from esphome.const import (
    CONF_ADDRESS,
    CONF_CHANNEL,
    CONF_ID,
    CONF_TIME_ID,
    CONF_TIMEOUT,
    CONF_TRIGGER_ID,
)

CODEOWNERS = ["@mvoss96"]
DEPENDENCIES = ["spi"]
MULTI_CONF = True

nrf24_bthome_ns = cg.esphome_ns.namespace("nrf24_bthome")
NRF24BTHomeHub = nrf24_bthome_ns.class_(
    "NRF24BTHomeHub", cg.Component, spi.SPIDevice
)
NRF24BTHomeDevice = nrf24_bthome_ns.class_("NRF24BTHomeDevice")
ButtonTrigger = nrf24_bthome_ns.class_(
    "ButtonTrigger", automation.Trigger.template(cg.uint8, cg.std_string)
)
DimmerTrigger = nrf24_bthome_ns.class_(
    "DimmerTrigger", automation.Trigger.template(cg.uint8, cg.int_)
)

CONF_CE_PIN = "ce_pin"
CONF_DEVICES = "devices"
CONF_SENDER_ID = "sender_id"
CONF_ON_BUTTON = "on_button"
CONF_ON_DIMMER = "on_dimmer"
CONF_WATCHDOG_TIMEOUT = "watchdog_timeout"

BTHOME_CPP_VERSION = "0.4.0"  # PlatformIO registry: mvoss96/bthome-cpp


def _hex_bytes(value, count, what):
    """Accepts 'AA:BB:..' hex notation or, for the address, a short ASCII string."""
    value = cv.string_strict(value)
    if ":" in value:
        parts = value.split(":")
        if len(parts) != count:
            raise cv.Invalid(f"{what} must have {count} bytes")
        # Plain 1-2 hex digits only: int(p, 16) alone would also accept
        # signs, '0x' prefixes, whitespace and values > 0xFF, deferring the
        # failure to a narrowing error in the generated C++.
        for p in parts:
            if not 1 <= len(p) <= 2 or any(c not in "0123456789abcdefABCDEF" for c in p):
                raise cv.Invalid(f"{what}: '{p}' is not a hex byte (00-FF)")
        return [int(p, 16) for p in parts]
    if len(value) == count:
        if any(ord(c) > 255 for c in value):
            raise cv.Invalid(f"{what}: only single-byte (Latin-1) characters allowed")
        return [ord(c) for c in value]
    raise cv.Invalid(
        f"{what} must be {count} hex bytes ('AA:BB:...') or a {count}-char string"
    )


def _sender_id(value):
    return _hex_bytes(value, 4, "sender_id")


def _address(value):
    return _hex_bytes(value, 5, "address")


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

CONFIG_SCHEMA = (
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(NRF24BTHomeHub),
            cv.Required(CONF_CE_PIN): pins.gpio_output_pin_schema,
            cv.Optional(CONF_CHANNEL, default=100): cv.int_range(min=0, max=125),
            cv.Optional(CONF_ADDRESS, default="BTHME"): _address,
            # Should comfortably exceed the senders' status interval, or the
            # radio re-inits (harmlessly but pointlessly) between packets.
            cv.Optional(
                CONF_WATCHDOG_TIMEOUT, default="5min"
            ): cv.positive_time_period_milliseconds,
            # Time source for the devices' last_seen timestamp sensors.
            cv.Optional(CONF_TIME_ID): cv.use_id(time.RealTimeClock),
            cv.Optional(CONF_DEVICES, default=[]): cv.ensure_list(DEVICE_SCHEMA),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
    .extend(spi.spi_device_schema(cs_pin_required=True))
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await spi.register_spi_device(var, config)

    ce_pin = await cg.gpio_pin_expression(config[CONF_CE_PIN])
    cg.add(var.set_ce_pin(ce_pin))
    cg.add(var.set_channel(config[CONF_CHANNEL]))
    cg.add(var.set_address(config[CONF_ADDRESS]))
    cg.add(var.set_watchdog_timeout(config[CONF_WATCHDOG_TIMEOUT]))

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
