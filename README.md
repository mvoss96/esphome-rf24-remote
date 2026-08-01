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

`dump_config` reports the FIFO-full count, but do not read too much into it: it
only reflects the FIFO at the moment the driver happens to look, so a receiver
running right at its limit drops frames while rarely being *seen* full.

### How much this receiver can take

Measured with `tests/throughput.yaml` — the driver alone, no BTHome layer, no
per-frame logging — against a sender clocking frames out back to back from
flash, so the air really is saturated and nothing on the sending side is the
limit:

| air rate | frames offered | received | taken |
| --- | --- | --- | --- |
| 250 kbps | 777/s | 99.4% | 771/s |
| 1 Mbps | 3100/s | 45.6% | 1414/s |
| 2 Mbps | 6200/s | 22.8% | 1410/s |

The number that matters is the last column, and it barely moves with the air
rate: **about 1400 frames a second, roughly 44 kB/s of payload**. That is the
receiver's own cost per frame — some 700 µs, of which five SPI transactions at
4 MHz are the smaller part and one pass of the ESPHome loop the larger.

So 250 kbps fits with room to spare even when a sender saturates it, which is
why the traffic this component was built for never comes close. 1 Mbps overruns
it twofold and 2 Mbps fourfold.

Do not read the FIFO-full counter as a loss figure: it reflects the FIFO only at
the moment the driver looks, and at 2 Mbps it stood at 3 while three quarters of
the frames were being dropped.

### Sending a file

Broadcast is right for sensors and wrong for a file. Measured by sending a
43 kB JPEG (1346 frames of 32 bytes) at the receiver:

| | time | throughput | arrived |
| --- | --- | --- | --- |
| 2 Mbps, no ack | 1.16 s | 36.1 kB/s | 99.3% |
| 2 Mbps, `auto_ack` | 1.42 s | 29.6 kB/s | **100%** |
| 250 kbps, `auto_ack` | 6.62 s | 6.3 kB/s | **100%** |

99.3% is not 99.3% of a picture. A JPEG is an entropy-coded stream: it is
readable up to the first missing chunk and noise afterwards, so the ten frames
that went missing cost the image.

`auto_ack: true` (which the chip only offers together with `payload_size:
dynamic`) fixes that, and it is not politeness — the receiving chip
acknowledges only what actually reached its FIFO, so a receiver that falls
behind stops acknowledging and the sender repeats instead of the frame being
lost. The 250 kbps run needed 1352 retransmissions for 1346 frames and still
arrived complete, at a fifth of the speed.

### Where the limit actually sits

Three ceilings, and the file rows above measure the lowest of them rather than
this receiver:

| | limit | set by |
| --- | --- | --- |
| sender over USB | ~36 kB/s | 500 kBaud serial, 680 µs a frame |
| sender from flash | 194 kB/s | 161 µs a frame, true line rate |
| this receiver | ~44 kB/s | ~700 µs a frame, mostly the ESPHome loop |

A sending *node* with the data in its own memory is not on the serial line, so
for that case the receiver is the constraint - not the 36 kB/s a dongle on USB
manages.

With acknowledgements the two settle it between themselves. A sender clocking
from flash at 2 Mbps, which alone would offer 6200 frames a second, ends up at
923 µs a frame against this receiver:

```
OK txtest sent=3000/3000 ack=yes failed=0 retries=750 us_per=923
receiver: 3000/3000 = 100.0%
```

**1083 frames a second, 33.8 kB/s, nothing lost.** The sender was throttled from
161 µs to 923 µs a frame by nothing but the handshake, and the 750
retransmissions are the moments the receiver was not ready. That is what a
stream over this link looks like when it is asked to arrive intact.

## Configuration

```yaml
external_components:
  - source: github://mvoss96/esphome-rf24-remote@v0.5.0
    components: [nrf24, nrf24_bthome]

spi:
  clk_pin: GPIO4
  miso_pin: GPIO5
  mosi_pin: GPIO6

nrf24:
  cs_pin: GPIO8
  ce_pin: GPIO7
  # irq_pin: GPIO9        # optional; without it a frame waits for the next loop
  channel: 100            # 0-125, default 100
  air_data_rate: 250kbps  # 250kbps (default) / 1Mbps / 2Mbps
  pa_level: 0dBm          # -18dBm / -12dBm / -6dBm / 0dBm (default)
  watchdog_timeout: 5min  # 0s disables; keep well above the senders' status interval
  pipes:
    - address: "BTHME"    # 5 chars or "42:54:48:4D:45"

nrf24_bthome:
  devices:
    - sender_id: "B7:4F:E7:7F"   # printed in the remote's boot log
      # encryption_key: "231d39c1d7cc1ab1aee224cd096db932"   # see Encryption
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
      on_command:
        # args: command (std::string: off, on, toggle, step_up,
        # step_down), steps (int, the opcode's argument; 0 for the
        # opcodes that take none). Unsigned - the direction is in the
        # opcode, not in the number.
        - logger.log:
            format: "command %s (%d)"
            args: [command.c_str(), steps]
```

`on_button` and `on_dimmer` report what happened at the remote and leave the
meaning to the receiver; `on_command` carries BTHome's command object (0x3B),
which says what the receiver should do. Which of the two a remote sends is the
remote's design decision — a knob that reports rotation suits a receiver that
decides what rotation means, a two-button remote wired to one lamp may as well
say `step_up` and be done. The specification advises sending commands only in
encrypted payloads, since an unencrypted one can be observed and replayed by
anyone in range.

Every button, dimmer and command a registered sender broadcasts is logged at
DEBUG whether or not a trigger picks it up, an opcode this version does not
know included — so what a remote sends is visible before anything is wired to
it. Measurements are quieter, because battery and voltage ride along in every
frame: their values need `logger: level: VERBOSE`. What DEBUG does say, once
per object and then never again, is that a value arrived with nowhere to go:

```
AA:01:00:01: object 0x03#1 (humidity) has no entity configured for it
```

`humidity` there is the key you would write under `sensor:` — the name comes
from the same table the configuration schema is built from, so a name in that
line is a name that works in a config.

Unlike buttons and dimmers, commands carry no instance index: a second command
object in a payload is the next instruction, not a second input.

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

### Encryption

A device given an `encryption_key` takes BTHome v2's AES-128-CCM payloads. The
key is the same 32-hex-character bindkey Home Assistant asks for when adding an
encrypted BTHome device, and the same one
[esphome-bthome-broadcaster](https://github.com/mvoss96/esphome-bthome-broadcaster)
takes on the sending side:

```yaml
nrf24_bthome:
  devices:
    - id: remote1
      sender_id: "B7:4F:E7:7F"
      encryption_key: "231d39c1d7cc1ab1aee224cd096db932"
```

Setting it makes encryption **mandatory** for that device: a plaintext payload
from the same sender id is refused afterwards, with a warning. A receiver that
accepts both is not encrypted at all — an attacker simply sends the plaintext
one. Devices without a key are unaffected, and the two kinds can share a hub.

Three things are worth knowing before turning it on.

**The nonce needs six MAC bytes, and this transport has none.** BTHome builds
its CCM nonce from the BLE advertiser address. Here the 4-byte sender id is what
identifies a device, so it takes that place, zero-extended to six — sender id
`B7:4F:E7:7F` gives nonce MAC `B7 4F E7 7F 00 00`. Both ends must derive it the
same way, which is why the rule is written down here rather than left to each
sender. `mac_address` overrides it, for the one case the rule cannot cover: a
payload built for BLE with a real advertiser address and only carried over this
radio.

**Replay protection replaces the packet-id dedup.** Every accepted payload's
counter is remembered, and one that does not exceed it is rejected — so the
sender's broadcast repeats are dropped before the decoder ever sees them, which
is both tighter and quieter than the packet id, and cannot be forged without the
key. The consequence is that a sender must persist its counter and resume above
it across reboots (the broadcaster keeps a 1024 margin for exactly this). One
that restarts from zero is refused, and the receiver says so by name rather than
just going silent. Two limits of the current implementation: the receiver does
*not* persist its counter, so the first payload after a receiver restart is
accepted whatever its counter, and the counter is per device in RAM only.

**Padding and the payload length.** A plaintext payload is found by walking its
objects, which is why the `0xFF` filler of a fixed-size slot is never trimmed.
An encrypted one cannot be walked — where the ciphertext ends is where the
counter begins, and both look like noise — so the padding is what says how long
it is. That is exact unless the MIC itself ends in `0xFF`, about one frame in
256, and for those the next lengths up are tried and the MIC decides which is
right. It costs one extra decrypt on those frames and nothing on the rest, and
it means encryption works on the fixed-size pipes this ecosystem uses rather
than only on dynamic ones.

`dump_config` prints `Encryption: AES-128-CCM` or `none` per device, because a
mismatch between sender and receiver looks from the outside exactly like a radio
that has stopped receiving.

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

Encryption is verified the same way, on the WT32-ETH01 lab hub with frames
played by a sniffer dongle (`tests/wt32-eth01.yaml`, device `dongle_enc`): a
payload authenticates and publishes, the sender's repeats drop out as replays, a
wrong bindkey and a plaintext payload are each refused by name, a counter that
moves backwards is refused and explained, and a frame whose MIC ends in `0xFF`
— where the padding cannot say how long the payload is — still decodes.

- [x] bthome-cpp pinned to registry release `mvoss96/bthome-cpp@0.4.2`
- [x] Generic `nrf24` component: multi-pipe, air data rate / PA level,
      optional IRQ pin
- [x] Every BTHome measurement, binary, text and raw object mapped
- [x] BTHome v2 encryption (AES-128-CCM) with replay protection, verified on the
      air against dongle-played frames — no sender in this ecosystem encrypts
      yet, so that is the only way it gets exercised
- [ ] Transmitting (`nrf24.send`) — receive only so far
- [ ] Persisting the replay counter across a receiver restart

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

`test_device_logic.py` additionally needs mbedtls (`libmbedtls-dev`, the same
CCM backend the firmware uses) and `pip install cryptography`, which builds the
encrypted test frames. Deliberately a different implementation from the one
under test: a round trip through bthome-cpp alone would only show that its two
halves agree with each other, not that either agrees with BTHome.

Two further benches live in the sniffer repository and drive real radios:
`bench/validate_component.py` for the protocol behaviour and
`bench/validate_sensor_types.py` for every mapped object over the air.
