# esphome-rf24-remote

ESPHome external component receiving **BTHome v2 payloads over nRF24L01
broadcasts** — for battery remotes (rotary encoders, buttons) that talk
raw 2.4 GHz instead of BLE. Counterpart of the
[RotRemote_BTHome](../../active/RotRemote_BTHome) sender firmware; the legacy
protocols this ecosystem replaces are documented in [PROTOCOL.md](PROTOCOL.md).

## How it works

All senders broadcast to one shared 5-byte address (`BTHME` by default),
NO_ACK, each frame repeated a few times. A frame is:

```
[4-byte sender ID][BTHome v2 service data]
```

The hub drives the nRF24L01 directly over ESPHome's SPI abstraction
(RX-only register-level driver — no RF24 library, works with both the
`arduino` and `esp-idf` frameworks) and parses payloads with
[bthome-cpp](https://github.com/mvoss96/bthome-cpp)'s `BTHome::Decoder`.
Repeats are deduplicated per device via the BTHome packet id. A watchdog
re-initializes the radio after a configurable quiet period (the nRF24 can
wedge silently, especially clones).

## Configuration

```yaml
external_components:
  - source: github://mvoss96/esphome-rf24-remote
    components: [nrf24_bthome]

spi:
  clk_pin: GPIO4
  miso_pin: GPIO5
  mosi_pin: GPIO6

nrf24_bthome:
  cs_pin: GPIO8
  ce_pin: GPIO7
  channel: 100          # 0-125, default 100
  address: "BTHME"      # 5 chars or "42:54:48:4D:45", default BTHME
  watchdog_timeout: 30s # 0s disables the re-init watchdog
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
piggyback on every event packet.

## Status

Hardware-verified end to end (ESP32-C3, esp-idf) against the RotRemote_BTHome
sender: click, rotate (dimmer 1), held-rotate (dimmer 2), periodic status,
per-event battery updates, packet-id dedup of the broadcast repeats.

- [ ] Pin bthome-cpp to a registry release once `BTHome::Decoder` ships
- [ ] Optional: IRQ-pin support instead of FIFO polling (lamp boards have
      the nRF24 IRQ wired)
