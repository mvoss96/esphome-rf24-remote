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
  [RotRemote_BTHome](../../active/RotRemote_BTHome) sender firmware; the
  legacy protocols this ecosystem replaces are documented in
  [PROTOCOL.md](PROTOCOL.md).

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

```yaml
sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: remote1
    battery:
      name: "Remote Battery"
    voltage:
      name: "Remote Voltage"

text_sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: remote1
    device_name:
      name: "Remote Name"
    firmware_version:
      name: "Remote Firmware"
```

Values come from the remotes' periodic status packets; battery/voltage also
piggyback on every event packet. Also available: `last_seen` (timestamp,
requires `time_id` on the `nrf24_bthome` hub), `connected` (binary sensor,
requires `timeout` on the device) and a `sender_id` text sensor.

## Writing your own listener

Any component can consume raw frames by implementing `nrf24::NRF24Listener`:

```cpp
class MyProtocol : public Component, public nrf24::NRF24Listener {
  void setup() override { this->parent_->register_listener(this); }
  void on_nrf24_frame(uint8_t pipe, const uint8_t *data, uint8_t len) override;
};
```

## Status

Hardware-verified end to end (ESP32-C3, esp-idf) against the RotRemote_BTHome
sender: click, rotate (dimmer 1), held-rotate (dimmer 2), periodic status,
per-event battery updates, packet-id dedup of the broadcast repeats.

- [x] bthome-cpp pinned to registry release `mvoss96/bthome-cpp@0.4.0`
- [x] Generic `nrf24` component: multi-pipe, air data rate / PA level,
      optional IRQ pin
