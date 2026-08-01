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
# No instance index: a second command object in a payload is the next
# instruction, not a second input. See add_command_trigger().
CommandTrigger = nrf24_bthome_ns.class_(
    "CommandTrigger", automation.Trigger.template(cg.std_string, cg.int_)
)

CONF_NRF24_ID = "nrf24_id"
CONF_DEVICES = "devices"
CONF_SENDER_ID = "sender_id"
CONF_ON_BUTTON = "on_button"
CONF_ON_DIMMER = "on_dimmer"
CONF_ON_COMMAND = "on_command"
CONF_ENCRYPTION_KEY = "encryption_key"
CONF_MAC_ADDRESS = "mac_address"

BTHOME_CPP_VERSION = "0.5.0"  # PlatformIO registry: mvoss96/bthome-cpp


def _sender_id(value):
    return nrf24.hex_bytes(value, 4, "sender_id")


def _encryption_key(value):
    # Same format Home Assistant asks for when adding an encrypted BTHome
    # device, and the same the bthome_broadcaster component takes: the 16-byte
    # AES key as 32 hex characters.
    value = cv.string_strict(value)
    if len(value) != 32 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise cv.Invalid(
            "encryption_key must be 32 hexadecimal characters (16 bytes), "
            'e.g. "231d39c1d7cc1ab1aee224cd096db932"'
        )
    return list(bytes.fromhex(value))


def _mac_address(value):
    return nrf24.hex_bytes(value, 6, "mac_address")


def _validate_device(config):
    if CONF_MAC_ADDRESS in config and CONF_ENCRYPTION_KEY not in config:
        raise cv.Invalid(
            "mac_address is only used to build the encryption nonce, so it does "
            "nothing without an encryption_key.",
            path=[CONF_MAC_ADDRESS],
        )
    return config


DEVICE_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(NRF24BTHomeDevice),
            cv.Required(CONF_SENDER_ID): _sender_id,
            # Quiet period after which the connected binary sensor reports
            # offline. Must exceed the sender's periodic status interval;
            # 0s disables the check.
            cv.Optional(
                CONF_TIMEOUT, default="0s"
            ): cv.positive_time_period_milliseconds,
            # The sender's BTHome v2 bindkey. Setting it makes encryption
            # mandatory for this device: plaintext payloads are refused
            # afterwards, since a receiver taking both is not encrypted at all.
            cv.Optional(CONF_ENCRYPTION_KEY): _encryption_key,
            # The six MAC bytes the CCM nonce is built from; see to_code() for
            # what they default to and why one would ever set them.
            cv.Optional(CONF_MAC_ADDRESS): _mac_address,
            cv.Optional(CONF_ON_BUTTON): automation.validate_automation(
                {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(ButtonTrigger)}
            ),
            cv.Optional(CONF_ON_DIMMER): automation.validate_automation(
                {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(DimmerTrigger)}
            ),
            cv.Optional(CONF_ON_COMMAND): automation.validate_automation(
                {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(CommandTrigger)}
            ),
        }
    ),
    _validate_device,
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
        if CONF_ENCRYPTION_KEY in device_config:
            cg.add(device.set_encryption_key(device_config[CONF_ENCRYPTION_KEY]))
            # BTHome builds its CCM nonce from six MAC bytes, taken on BLE from
            # the advertiser address. This transport has no MAC: what identifies
            # a device here is the 4-byte sender id, so that takes the place,
            # zero-extended to six. Both ends must derive it the same way, which
            # is why the rule is written down rather than left to each sender.
            #
            # mac_address overrides it, for the one case the rule cannot cover:
            # a payload built for BLE and only carried over this radio, whose
            # nonce was made with a real advertiser address.
            mac = device_config.get(
                CONF_MAC_ADDRESS, list(device_config[CONF_SENDER_ID]) + [0, 0]
            )
            cg.add(device.set_nonce_mac(mac))
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

        for trigger_config in device_config.get(CONF_ON_COMMAND, []):
            trigger = cg.new_Pvariable(trigger_config[CONF_TRIGGER_ID], device)
            await automation.build_automation(
                trigger,
                # `command` is the opcode name - off, on, toggle, step_up,
                # step_down - and `steps` its argument, 0 for the opcodes that
                # take none. Unsigned: the direction is in the opcode.
                [(cg.std_string, "command"), (cg.int_, "steps")],
                trigger_config,
            )

    # Only when some device actually has a key: the define pulls mbedtls into
    # the component, and a receiver that decrypts nothing should not link a
    # cipher in.
    if any(CONF_ENCRYPTION_KEY in dev for dev in config[CONF_DEVICES]):
        cg.add_define("USE_BTHOME_ENCRYPTION")

    cg.add_library("mvoss96/bthome-cpp", BTHOME_CPP_VERSION)
