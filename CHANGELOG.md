# Changelog

User-facing changes per release. The release workflow publishes the matching
section as the GitHub release notes (the heading, minus the date, becomes the
release title) — every tagged version needs a section here before tagging.

## v0.5.0 — BTHome command events (2026-08-01)

A remote can now tell this receiver what to do, not only what happened at the remote — BTHome's command object, which the decoder already understood and the component stepped over.

```yaml
external_components:
  - source: github://mvoss96/esphome-rf24-remote@v0.5.0
    components: [nrf24, nrf24_bthome]
```

No breaking changes. `on_button` and `on_dimmer` are untouched, and a device that uses neither new feature behaves exactly as in v0.4.0.

### `on_command`

```yaml
nrf24_bthome:
  devices:
    - sender_id: "CB:C7:3E:BF"
      encryption_key: "231d39c1d7cc1ab1aee224cd096db932"
      on_command:
        # command: off | on | toggle | step_up | step_down
        # steps:   the opcode's argument, 0 for those that take none
        - if:
            condition:
              lambda: return command == "toggle";
            then:
              - light.toggle: lamp
```

`on_button` and `on_dimmer` report what a person did and leave the meaning to the receiver. That suits a knob — it genuinely was turned, and what a turn should mean belongs in the automation. It suits a two-button remote much less: holding a button had to be sent as a dimmer object claiming a rotation that never happened. `0x3B` is the object for saying what should happen instead.

Which of the two a remote sends is the remote's design decision, and one hub takes both.

Unlike buttons and dimmers, commands carry no instance index: a second command object in a payload is the next instruction, not a second input. `steps` is unsigned — the direction is in the opcode.

**On encryption.** The specification advises sending commands only in encrypted payloads: an unencrypted one can be recorded off the air and replayed by anyone in range, and a command is acted on where a report might only be logged. Nothing here refuses a plaintext command — that is the deployment's business — but it is worth knowing before choosing between the two triggers.

### Objects nobody asked for are now named

```
AA:01:00:01: object 0x03#1 (humidity) has no entity configured for it
```

Said once per object, at DEBUG. Events were always visible whether or not a trigger took them; measurements were not, because battery and voltage ride along in every frame and belong at VERBOSE. So a remote broadcasting a temperature nobody configured looked exactly like a remote that sends none.

`humidity` is the key you would write under `sensor:` — the names come from the same tables the configuration schema is built from, so a name in that line is a name that works in a config. A test rebuilds the mapping from those tables and fails on anything missing, stale or renamed.

An object id the schema has no key for still gets a line, with `not mapped by this version` where the name would be.

### Tested

The two worked examples from the BTHome specification verbatim (`3B0002` toggle, `3B010305` step up 5), the remaining opcodes, and an opcode this version does not know — which still fires and still names its argument rather than disappearing. The case that used to assert command events were skipped now asserts what it was really there for: a command's length comes from its own argument count, so a misread shifts the rest of the payload.

`tests/esp32c3.yaml` carries an `on_command` block, so CI compiles the path and the codegen's argument names have to stay what the documentation claims.

Verified on the air as well, against an ATmega328P remote sending encrypted commands: clicks arrived as `on` and `off`, holding produced `step_up` and `step_down` at the sender's step rate, and the lamp followed.

## v0.4.0 — encrypted BTHome over nRF24 (2026-07-30)

A sender can now encrypt, and this receiver reads it — BTHome v2 AES-128-CCM with replay protection, verified on the air rather than only against stubs.

```yaml
external_components:
  - source: github://mvoss96/esphome-rf24-remote@v0.4.0
    components: [nrf24, nrf24_bthome]
```

No breaking changes. Devices without an `encryption_key` behave exactly as before, and encrypted and plaintext senders can share one hub.

### Encryption

```yaml
nrf24_bthome:
  devices:
    - id: remote1
      sender_id: "B7:4F:E7:7F"
      encryption_key: "231d39c1d7cc1ab1aee224cd096db932"
```

Setting a key makes encryption **mandatory** for that device: a plaintext payload from the same sender id is refused afterwards. A receiver that accepts both is not encrypted at all — an attacker simply sends the plaintext one.

Three things this transport forced, none of which apply to BTHome over BLE:

**The CCM nonce wants six MAC bytes and there are none here.** BTHome takes them from the BLE advertiser address. What identifies a device on this radio is the 4-byte sender id, so that takes the place, zero-extended: `B7:4F:E7:7F` gives nonce MAC `B7 4F E7 7F 00 00`. Both ends must derive it identically — nothing on the wire carries or checks this agreement, and a mismatch is indistinguishable from a wrong key. `mac_address` overrides it for a payload built for BLE and only carried over this radio.

**Padding versus encryption.** The senders this is built for use a fixed 32-byte slot padded with `0xFF`, so the frame is longer than the data in it. A plaintext payload is found by walking its objects; an encrypted one cannot be walked, because where the ciphertext ends is where the counter begins and both look like noise. The padding bounds the search and the MIC decides which length is right — one candidate 255 times in 256, the next lengths up when the MIC itself ends in `0xFF`. Without this, encryption would work only on `payload_size: dynamic` pipes, which is not what this ecosystem uses.

**Replay protection replaces the packet-id dedup** for encrypted devices. The sender's broadcast repeats are dropped before the decoder sees them and cannot be forged without the key. A counter that moves backwards is refused and named, because senders here persist theirs and resume above it — so one that does not is worth reporting rather than leaving as a remote gone silent.

`dump_config` prints `Encryption: AES-128-CCM` or `none` per device, because a mismatch between sender and receiver looks from the outside exactly like a radio that has stopped receiving.

Not solved, and documented as such: the receiver does not persist its replay counter, so the first payload after a receiver restart is accepted whatever its counter.

### Verified on the air

On the WT32-ETH01 lab hub with frames played by a sniffer dongle:

| case | result |
|---|---|
| valid frame | decrypts, publishes, fires the trigger |
| three identical copies | one event, the rest dropped as replays |
| wrong bindkey | one warning, repeats quiet afterwards |
| plaintext to an encrypted device | refused by name |
| counter backwards | refused, with what to do about it |
| MIC ending in `0xFF` | decodes — the length search does its job |

Host-side, the encrypted test frames are built with python-cryptography, deliberately a different implementation from the bthome-cpp under test, so the nonce layout and field order are checked in the absolute rather than round-tripping through one library. 95 checks in total; `tests/esp32c3.yaml` gained an encrypted device so CI compiles the path at all.

### Also

- bthome-cpp pinned to `0.5.0`, whose `build_encrypted_service_data()` is what lets a sender on this transport encrypt without building a BLE advertisement it never wanted.

## v0.3.0 — every BTHome object, tested logic, and a receiver that stays awake (2026-07-29)

Everything BTHome sends now reaches an entity, the component's own logic runs under test without a radio, and a receiver that could fall silent for good no longer can.

```yaml
external_components:
  - source: github://mvoss96/esphome-rf24-remote@v0.3.0
    components: [nrf24, nrf24_bthome]
```

No breaking changes. Existing configurations keep working — `battery`, `voltage`, `on_button` and `on_dimmer` are unchanged; everything new is additive.

### Every BTHome object reaches an entity

Before this release 27 of 58 measurement ids were mapped, binary objects were not handled at all (`ObjectKind::Binary` had no case in the parse loop), and raw was dropped.

- **58 measurement ids over 49 keys** — `sensor`
- **all 28 binary objects** — `binary_sensor`
- **text and raw** — `text_sensor`, raw as uppercase hex, because the bytes are not characters

Ids that differ in width or sign alone share a key: `count` takes six of them, `energy`, `gas`, `power` and `current` two each. Where the resolution or the unit differs the key stays separate — `temperature_c1`, `temperature_s8`, `humidity_u8`, `voltage_centi`, `volume_ml` and the rest — because one entity has one `accuracy_decimals`, and folding hundredths of a degree together with whole degrees would make it claim a precision that depends on which id happened to arrive.

`index:` selects which occurrence of an object a sensor takes, now up to 12, matching what a frame can hold.

### A receiver that fell silent for good

Twice the lab receiver stopped receiving entirely, with every register reading back exactly as configured and a watchdog re-init making no difference. Measured under load:

```
No interrupt for a waiting payload: FIFO_STATUS=12 STATUS=42 IRQ pin=0
```

The RX FIFO full, `RX_DR` set, the interrupt line still down. The nRF24 holds IRQ low for as long as `RX_DR` is set while the pin is watched for falling edges, so anything that leaves `RX_DR` standing takes the edge away for good — and the drain loop's own iteration guard did exactly that, yielding after eight payloads without arranging to be called again.

**The FIFO is now read on every loop.** The interrupt decides how soon that happens, never whether it happens, and the handler wakes the main loop — which is what an interrupt that does no work of its own is actually for. Same 1280 frames from two senders:

| | frames received | RX FIFO full |
| --- | --- | --- |
| before | 479 | 181× |
| after | 631 | 143× |
| after, serial logger off | 1313 | 0 |

### Set `baud_rate: 0` when logging at VERBOSE

That last row is its own finding and needs no code. At 250 kbps a 32-byte frame takes 1.3 ms on the air; a `VERBOSE` line per frame at 115200 baud takes longer, and the write blocks inside the loop. On a device reached over the network the serial port carries nothing anyone reads:

```yaml
logger:
  level: VERBOSE
  baud_rate: 0
```

### What the new tests turned up

- `volume` showed three decimals for an object scaled by 0.1.
- The per-payload instance counter was an array of eight; twelve fit in a frame, so past the eighth every further occurrence came out as instance 1 and a second reading overwrote the first — silently.
- A payload carrying events but no packet id cannot be deduplicated: three button events from one press. The receiver now warns once per device.
- `dump_config` listed sender ids and nothing else; it now names each device's timeout and how many entities and triggers attached, which is where a platform entry that never attached shows up.

### Tests

The repository had no CI. It now runs four suites without hardware, plus a build for the ESP32-C3 and a config check on both lab configurations:

| | |
| --- | --- |
| `test_device_logic.py` | 23/23 — the real `nrf24_bthome.cpp` against host stubs |
| `test_sensor_types.py` | 16/16 over 88 objects, against the pinned bthome-cpp |
| `test_nrf24_config.py` | 10/10 register masks |
| `validate_config_rules.py` | 32/32 |

The host harness reached paths the lab never had: all seven button event types (`HoldPress` is 0x80, not the next number up), the command event whose length is its own argument count, both firmware-version widths, and the `millis()` wraparound, which no hardware run can reach because none lasts seven weeks.

Over the air, against a WT32-ETH01 with two sniffer dongles: 22/22 and 107/107.

### How much this receiver can take

Measured against a sender clocking frames out of flash, so the air is genuinely saturated:

| air rate | offered | received | taken |
| --- | --- | --- | --- |
| 250 kbps | 777/s | 99.4% | 771/s |
| 1 Mbps | 3100/s | 45.6% | 1414/s |
| 2 Mbps | 6200/s | 22.8% | 1410/s |

About **1400 frames a second, roughly 44 kB/s** — the receiver's own cost per frame, some 700 µs, of which one pass of the ESPHome loop is the larger part. 250 kbps fits with room to spare even when a sender saturates it.

For a transfer that has to arrive intact, `auto_ack: true` (which the chip offers only with `payload_size: dynamic`) turns loss into backpressure: a 43 kB JPEG arrived complete at 2 Mbps in 1.42 s, where the same file broadcast without acknowledgements lost ten chunks.

### Also in this release

bthome-cpp moves to 0.4.2. Padding is no longer trimmed from a fixed-length frame — a temperature of −1.00 °C is `02 9C FF` and a receiver that cuts trailing `0xFF` loses it, going silent exactly around freezing. Encryption is documented as unsupported and not planned: the ATmega senders this ecosystem is built around cannot encrypt.

Transmitting (`nrf24.send`) is still out of scope; this is a receiver.

## v0.2.0 (2026-07-26)

### Breaking change

The radio configuration moved out of `nrf24_bthome` into a new generic `nrf24` component. Update configs as follows or stay pinned to `@v0.1.0`:

```yaml
external_components:
  - source: github://mvoss96/esphome-rf24-remote@v0.2.0
    components: [nrf24, nrf24_bthome]

nrf24:                    # new: owns the radio
  cs_pin: GPIO8
  ce_pin: GPIO7
  channel: 100
  pipes:
    - address: "BTHME"

nrf24_bthome:             # now radio-less: devices + time_id only
  devices: [...]
```

### New: generic `nrf24` component

Reusable RX driver for other ESPHome + nRF24L01 projects:

- Up to 5 RX pipes with dynamic payload lengths (pipe 1 full 5-byte address; pipes 2-5 share all but the on-air LSB, validated at config time)
- `air_data_rate` (250kbps/1Mbps/2Mbps) and `pa_level` (-18 to 0 dBm) options
- Optional `irq_pin`: RX_DR interrupt instead of per-loop SPI polling, with the re-init watchdog as fallback
- Frame dispatch to any component implementing `nrf24::NRF24Listener` (see README)

Hardware-verified against the v0.1.0 receiver running in parallel: identical frames, identical entity states, live rotation events with packet-id dedup intact.

## v0.1.0 (2026-07-26)

Initial release of the `nrf24_bthome` ESPHome component: receives BTHome-v2-over-nRF24 broadcasts (e.g. from RotRemote senders) and exposes them as ESPHome triggers and entities.

### Features

- Register-level nRF24L01(+) RX driver on ESPHome SPI (no RF24 library dependency, arduino + esp-idf)
- BTHome v2 decoding via [bthome-cpp](https://github.com/mvoss96/bthome-cpp) 0.4.0 (pinned from the PlatformIO registry)
- Per-device registry keyed on the 4-byte sender ID with `on_button` / `on_dimmer` automations
- Dedup of NO_ACK broadcast repeats via the BTHome packet id, with aging after the device quiet period
- Entities: battery, voltage, last_seen (needs `time_id`), connected, device name, firmware version, sender ID
- Radio watchdog with periodic re-init; config validation for addresses, sender IDs and entity prerequisites

Hardware-verified end to end on ESP32-C3 (esp-idf) against ATmega328 RotRemote senders: click, rotate, held-rotate, periodic status, repeat dedup.
