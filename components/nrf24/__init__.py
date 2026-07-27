import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import pins
from esphome.components import spi
from esphome.const import CONF_ADDRESS, CONF_CHANNEL, CONF_ID, CONF_IRQ_PIN

CODEOWNERS = ["@mvoss96"]
DEPENDENCIES = ["spi"]
MULTI_CONF = True

CONF_CE_PIN = "ce_pin"
CONF_AUTO_ACK = "auto_ack"
CONF_PAYLOAD_SIZE = "payload_size"
# Not CONF_DATA_RATE: spi_device_schema() already carries a data_rate option
# (the SPI clock), which would shadow it in the merged schema.
CONF_AIR_DATA_RATE = "air_data_rate"
CONF_PA_LEVEL = "pa_level"
CONF_PIPES = "pipes"
CONF_WATCHDOG_TIMEOUT = "watchdog_timeout"

nrf24_ns = cg.esphome_ns.namespace("nrf24")
NRF24Hub = nrf24_ns.class_("NRF24Hub", cg.Component, spi.SPIDevice)

DataRate = nrf24_ns.enum("DataRate")
DATA_RATES = {
    "250kbps": DataRate.NRF24_RATE_250KBPS,
    "1Mbps": DataRate.NRF24_RATE_1MBPS,
    "2Mbps": DataRate.NRF24_RATE_2MBPS,
}

PALevel = nrf24_ns.enum("PALevel")
PA_LEVELS = {
    "-18dBm": PALevel.NRF24_PA_MIN,
    "-12dBm": PALevel.NRF24_PA_LOW,
    "-6dBm": PALevel.NRF24_PA_HIGH,
    "0dBm": PALevel.NRF24_PA_MAX,
}


def hex_bytes(value, count, what):
    """Accepts 'AA:BB:..' hex notation or a short ASCII (Latin-1) string."""
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


def _pipe_address(value):
    return hex_bytes(value, 5, "pipe address")


def _validate_pipes(pipes):
    """Hardware constraint: pipe 1 has a full 5-byte address; pipes 2-5 share
    all but the FIRST byte (the on-air LSB) with pipe 1."""
    base = pipes[0][CONF_ADDRESS]
    seen_first = set()
    for i, pipe in enumerate(pipes):
        addr = pipe[CONF_ADDRESS]
        first = addr[0]
        if first in seen_first:
            raise cv.Invalid(
                f"pipe {i + 1}: first address byte 0x{first:02X} is already used by "
                "another pipe"
            )
        seen_first.add(first)
        if i > 0 and addr[1:] != base[1:]:
            raise cv.Invalid(
                f"pipe {i + 1}: pipes 2-5 must share all but the first byte with "
                "pipe 1 (nRF24 hardware constraint)"
            )
    return pipes


PIPE_SCHEMA = cv.Schema({cv.Required(CONF_ADDRESS): _pipe_address})

# "dynamic" (the sender decides per packet) or a fixed 1-32 bytes that every
# packet must have.
PAYLOAD_DYNAMIC = "dynamic"


def _payload_size(value):
    if isinstance(value, str) and value.strip().lower() == PAYLOAD_DYNAMIC:
        return PAYLOAD_DYNAMIC
    return cv.int_range(min=1, max=32)(value)


def _validate_radio(config):
    """Rejects the one combination the chip does not implement.

    Dynamic payload length is not a free-standing feature: the datasheet makes it
    part of Enhanced ShockBurst, and Enhanced ShockBurst acknowledges. Getting
    this wrong does not fail loudly on the air - the receiver simply starts
    handing out short payloads twice, the second copy carrying an older payload,
    which arrives as an event that never happened. Cheaper to refuse at compile
    time than to debug at 3am.
    """
    if config[CONF_PAYLOAD_SIZE] == PAYLOAD_DYNAMIC and not config[CONF_AUTO_ACK]:
        raise cv.Invalid(
            "payload_size: dynamic requires auto_ack: true.\n"
            "\n"
            "nRF24L01+ Product Specification v1.0, Table 28, register 0x1C "
            "(DYNPD), page 63\n"
            "(https://cdn.sparkfun.com/assets/3/d/8/5/1/"
            "nRF24L01P_Product_Specification_1_0.pdf):\n"
            '    "DPL_P1  Enable dynamic payload length data pipe 1. '
            '(Requires EN_DPL and ENAA_P1)"\n'
            "\n"
            "ENAA_Pn is the per-pipe auto acknowledgement bit, so turning "
            "auto_ack off while asking for dynamic payloads asks the chip for a "
            "state it does not support. Measured consequence on these modules: "
            "payloads shorter than 32 bytes are delivered twice, the second copy "
            "carrying an older payload.\n"
            "\n"
            "Either keep auto_ack: true, or set a fixed payload_size (e.g. 32) - "
            "static payload length is independent of auto acknowledgement "
            "(spec section 7.3.4, page 29).",
            path=[CONF_PAYLOAD_SIZE],
        )
    return config

CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(NRF24Hub),
            cv.Required(CONF_CE_PIN): pins.gpio_output_pin_schema,
            cv.Optional(CONF_IRQ_PIN): pins.internal_gpio_input_pin_schema,
            cv.Optional(CONF_CHANNEL, default=100): cv.int_range(min=0, max=125),
            cv.Optional(CONF_AIR_DATA_RATE, default="250kbps"): cv.enum(DATA_RATES),
            cv.Optional(CONF_PA_LEVEL, default="0dBm"): cv.enum(PA_LEVELS),
            # Auto acknowledgement. A receiver in a broadcast network has nobody
            # to answer and its answers collide with the traffic other receivers
            # are hearing - but see _validate_radio() for why it cannot simply be
            # turned off while payload_size is dynamic.
            cv.Optional(CONF_AUTO_ACK, default=True): cv.boolean,
            # "dynamic" or a fixed size every packet must have. Fixed size is set
            # on the receiver in RX_PW_Pn and must match what the sender clocks
            # into its TX FIFO (spec section 7.3.4).
            cv.Optional(CONF_PAYLOAD_SIZE, default=PAYLOAD_DYNAMIC): _payload_size,
            cv.Required(CONF_PIPES): cv.All(
                cv.ensure_list(PIPE_SCHEMA), cv.Length(min=1, max=5), _validate_pipes
            ),
            # Re-init the radio after this quiet period; nRF24 modules
            # (clones especially) can wedge silently. Keep it comfortably
            # above the expected traffic interval. 0s disables.
            cv.Optional(
                CONF_WATCHDOG_TIMEOUT, default="5min"
            ): cv.positive_time_period_milliseconds,
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
    .extend(spi.spi_device_schema(cs_pin_required=True)),
    _validate_radio,
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await spi.register_spi_device(var, config)

    ce_pin = await cg.gpio_pin_expression(config[CONF_CE_PIN])
    cg.add(var.set_ce_pin(ce_pin))
    if CONF_IRQ_PIN in config:
        irq_pin = await cg.gpio_pin_expression(config[CONF_IRQ_PIN])
        cg.add(var.set_irq_pin(irq_pin))
    cg.add(var.set_channel(config[CONF_CHANNEL]))
    cg.add(var.set_data_rate(config[CONF_AIR_DATA_RATE]))
    cg.add(var.set_pa_level(config[CONF_PA_LEVEL]))
    cg.add(var.set_auto_ack(config[CONF_AUTO_ACK]))
    # 0 carries "dynamic" to the driver; a real length is 1-32.
    payload_size = config[CONF_PAYLOAD_SIZE]
    cg.add(var.set_payload_size(0 if payload_size == PAYLOAD_DYNAMIC else payload_size))
    cg.add(var.set_watchdog_timeout(config[CONF_WATCHDOG_TIMEOUT]))
    for pipe in config[CONF_PIPES]:
        cg.add(var.add_pipe(pipe[CONF_ADDRESS]))
