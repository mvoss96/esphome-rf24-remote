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
