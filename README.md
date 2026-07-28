# esphome-rf24-remote

Two ESPHome external components:

- **`nrf24`** — a generic RX driver for the nRF24L01(+): register-level over
  ESPHome's SPI abstraction (no RF24 library, works with both the `arduino`
  and `esp-idf` frameworks). Up to 5 pipes, dynamic payload lengths,
  configurable air data rate / PA level / channel, optional IRQ pin,
  re-init watchdog. Dispatches received frames to listener components.
- **`nrf24_bthome`** — a listener on top of `nrf24` receiving **BTHome v2
  payloads over nRF24 broadcasts**, for battery remotes (rotary encoders,
  buttons) that talk raw 2.4 GHz instead of BLE. Counterpart of the
  RotRemote_BTHome sender firmware; the legacy protocols this ecosystem
  replaces are documented in [PROTOCOL.md](PROTOCOL.md).

> **Breaking change in v0.2.0:** the radio configuration moved from the
> `nrf24_bthome` block into the new `nrf24` component (see below). v0.1.0
> configs keep working when pinned to `@v0.1.0`.

## How it works

All senders broadcast to one shared 5-byte address (`BTHME` by default),
NO_ACK, each frame repeated a few times. A frame is:

```
[4-byte sender ID][BTHome v2 service data]
```

Payloads are parsed with
[bthome-cpp](https://github.com/mvoss96/bthome-cpp)'s `BTHome::Decoder`.
Repeats are deduplicated per device via the BTHome packet id. The `nrf24`
watchdog re-initializes the radio after a configurable quiet period (the
nRF24 can wedge silently, especially clones).

A sender on a pipe with a fixed payload size has to fill the slot to the
configured length, and fills it with `0xFF` — an id BTHome defines no object
for. The end of the data is therefore found by walking the objects, never by
trimming trailing `0xFF`: BTHome is little endian, so a signed 16-bit
measurement between −0.01 and −2.56 ends in that same byte. A temperature of
−1.00 °C is `02 9C FF`, and a receiver that trims loses it, going silent exactly
around freezing. `0xFF` is padding where an object id is expected and data
everywhere else.

Without a packet id a payload's repeats cannot be told from new events, so every
copy the sender broadcasts fires again. Measurements are unaffected — the same
reading is simply published a few times — and the receiver warns once per device
when it sees events arrive that way.

### Logging is the throughput limit, not the radio

At 250 kbps a 32-byte frame takes about 1.3 ms on the air, and the chip's RX
FIFO holds three. A `VERBOSE` line per frame written to a serial port at 115200
baud takes longer than that, and the write blocks inside the loop — so the radio
receives frames the receiver then has nowhere to put.

Measured on the lab hub, same 1280 frames from two senders at once:

| | frames received | RX FIFO full |
| --- | --- | --- |
| `VERBOSE` with the serial port on | 631 | 143× |
| `VERBOSE`, `baud_rate: 0` | 1313 | 0 |

So on a device reached over the network, turn the serial logger off:

```yaml
logger:
  level: VERBOSE
  baud_rate: 0    # keeps network logging, drops the blocking serial writes
```

`dump_config` reports the FIFO-full count, which is the number to watch: it says
how often frames were at risk of being dropped.

## Configuration

```yaml
external_components:
  - source: github://mvoss96/esphome-rf24-remote@v0.2.0
    components: [nrf24, nrf24_bthome]

spi:
  clk_pin: GPIO4
  miso_pin: GPIO5
  mosi_pin: GPIO6

nrf24:
  cs_pin: GPIO8
  ce_pin: GPIO7
  # irq_pin: GPIO9        # optional; falls back to FIFO polling without it
  channel: 100            # 0-125, default 100
  air_data_rate: 250kbps  # 250kbps (default) / 1Mbps / 2Mbps
  pa_level: 0dBm          # -18dBm / -12dBm / -6dBm / 0dBm (default)
  watchdog_timeout: 5min  # 0s disables; keep well above the senders' status interval
  pipes:
    - address: "BTHME"    # 5 chars or "42:54:48:4D:45"

nrf24_bthome:
  devices:
    - sender_id: "B7:4F:E7:7F"   # printed in the remote's boot log
      on_button:
        # args: button (uint8_t, 1-based), event (std::string:
        # press, double_press, triple_press, long_press, ...)
        - logger.log:
            format: "button %u: %s"
            args: [button, event.c_str()]
      on_dimmer:
        # args: dimmer (uint8_t, 1-based instance), steps (int,
        # negative = rotate left, positive = rotate right)
        - light.dim_relative:
            id: my_light
            relative_brightness: !lambda return steps * 0.03;
```

Frames from sender IDs without a `devices` entry are logged at DEBUG and
ignored — pairing a remote to a lamp is purely a YAML decision.

Additional pipes (2-5) share all but their **first** address byte (the
on-air LSB) with pipe 1 — an nRF24 hardware constraint, enforced at config
time:

```yaml
nrf24:
  # ...
  pipes:
    - address: "BTHME"
    - address: "XTHME"   # differs only in the first byte
```

## Entities

Every BTHome object is declared by name, one key per quantity:

```yaml
sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: remote1
    battery:
      name: "Remote Battery"
    temperature:
      name: "Remote Temperature"

binary_sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: remote1
    motion:
      name: "Remote Motion"

text_sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: remote1
    device_name:
      name: "Remote Name"
    firmware_version:
      name: "Remote Firmware"
```

Named keys rather than a bare object id, because BTHome carries a value's width,
sign and scale but not its unit or meaning. A generic mapping would make every
user supply unit, device class and accuracy by hand, and a wrong guess produces
an entity that looks correct in Home Assistant and is not.

**Measurements** (`sensor`), 49 keys over all 58 measurement object ids:

`battery`, `temperature`, `humidity`, `pressure`, `illuminance`, `mass`,
`mass_lb`, `dewpoint`, `count`, `energy`, `power`, `voltage`, `pm2_5`, `pm10`,
`co2`, `tvoc`, `moisture`, `humidity_u8`, `moisture_u8`, `rotation`,
`distance_mm`, `distance_m`, `duration`, `current`, `speed`, `temperature_c1`,
`uv_index`, `volume`, `volume_ml`, `volume_flow_rate`, `voltage_centi`, `gas`,
`volume_u32`, `water`, `timestamp`, `acceleration`, `gyroscope`,
`volume_storage`, `conductivity`, `temperature_s8`, `temperature_s8_035`,
`direction`, `precipitation`, `channel`, `rotational_speed`, `speed_s32`,
`acceleration_s32`, `light_level`, `settings_revision`

**Binary objects** (`binary_sensor`), all 28:

`generic`, `power`, `opening`, `battery_low`, `battery_charging`,
`carbon_monoxide`, `cold`, `connectivity`, `door`, `garage_door`, `gas`, `heat`,
`light`, `lock`, `moisture`, `motion`, `moving`, `occupancy`, `plug`,
`presence`, `problem`, `running`, `safety`, `smoke`, `sound`, `tamper`,
`vibration`, `window`

**Text and raw** (`text_sensor`): `text` (0x53) and `raw` (0x54). Raw is
published as uppercase hex without separators — the bytes are not characters, a
zero among them would end a string early, and most values above 0x7F are not
printable.

### Which ids share a key

BTHome states the same quantity several ways. Ids that differ **in width or sign
alone** share one key, because a sender picks one of them and they are the same
measurement at the same resolution:

| Key | Object ids |
| --- | --- |
| `count` | 0x09, 0x3D, 0x3E, 0x59, 0x5A, 0x5B |
| `energy` | 0x0A, 0x4D |
| `power` | 0x0B, 0x5C |
| `current` | 0x43, 0x5D |
| `gas` | 0x4B, 0x4C |

Where the **resolution or the unit** differs the key stays separate, even for
the same quantity, and carries the library's name for the id: `temperature_c1`
(0x45), `temperature_s8` (0x57), `temperature_s8_035` (0x58), `humidity_u8`
(0x2E), `moisture_u8` (0x2F), `voltage_centi` (0x4A), `volume_ml` (0x48),
`volume_u32` (0x4E), `mass_lb` (0x07), `speed_s32` (0x62),
`acceleration_s32` (0x63). One entity has one `accuracy_decimals`, and folding
0x02 (hundredths of a degree) together with 0x57 (whole degrees) would make it
claim a precision that depends on which id happened to arrive.

### Instances

`index:` selects which occurrence of an object in a frame an entity takes — the
k-th object of a type addresses instance k, the convention buttons and dimmers
already follow. A node with two probes of one kind gets an entity for each
instead of the second overwriting the first. A second instance needs its own
platform entry:

```yaml
sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: remote1
    temperature:
      name: "Probe 1"
  - platform: nrf24_bthome
    nrf24_bthome_device_id: remote1
    temperature:
      name: "Probe 2"
      index: 2
```

### Observed rather than received

Three entities come from the receiver's own view rather than from a frame:
`last_seen` (timestamp, requires `time_id` on the `nrf24_bthome` hub),
`connected` (binary sensor, requires `timeout` on the device) and `sender_id`
(text sensor). `connected` is not the same as the BTHome object `connectivity`
(0x19): a sender cannot report over the radio that its radio stopped working.

Encrypted BTHome payloads are refused with a warning. They are not supported and
not planned — the ATmega senders this ecosystem is built around cannot encrypt.

## Writing your own listener

Any component can consume raw frames by implementing `nrf24::NRF24Listener`:

```cpp
class MyProtocol : public Component, public nrf24::NRF24Listener {
  void setup() override { this->parent_->register_listener(this); }
  // `padded` is true when the frame came off a pipe with a fixed payload size,
  // where the tail may be the sender filling the slot rather than data.
  void on_nrf24_frame(uint8_t pipe, const uint8_t *data, uint8_t len, bool padded) override;
};
```

## Status

Hardware-verified end to end (ESP32-C3, esp-idf) against the RotRemote_BTHome
sender: click, rotate (dimmer 1), held-rotate (dimmer 2), periodic status,
per-event battery updates, packet-id dedup of the broadcast repeats.

- [x] bthome-cpp pinned to registry release `mvoss96/bthome-cpp@0.4.2`
- [x] Generic `nrf24` component: multi-pipe, air data rate / PA level,
      optional IRQ pin
- [x] Every BTHome measurement, binary, text and raw object mapped
- [ ] Transmitting (`nrf24.send`) — receive only so far
- [ ] Encryption — not planned, see above

## Tests

Four suites need no hardware and run in CI, alongside a build for the ESP32-C3:

```bash
python tests/validate_config_rules.py   # the combinations the chip cannot do are refused
python tests/test_nrf24_config.py       # the register bits a configuration turns into
python tests/test_sensor_types.py       # the object-id tables against the pinned bthome-cpp
python tests/test_device_logic.py       # the component's own logic, against host stubs
```

The last three build C++ against the bthome-cpp version pinned in
`components/nrf24_bthome/__init__.py` — a check against a different one would
prove nothing about the firmware. `tests/host/stubs/README.md` explains what the
stubs do and do not prove.

Two further benches live in the sniffer repository and drive real radios:
`bench/validate_component.py` for the protocol behaviour and
`bench/validate_sensor_types.py` for every mapped object over the air.
