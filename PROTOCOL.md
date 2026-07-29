# RF24 Remote Protocol

Radio protocol used by the nRF24L01-based remotes (`RF-RotRemote`) to control the
`SMART_WIFI-RF24_LAMP` firmware. This document describes the wire format as
implemented by the deployed devices, so a new receiver (e.g. an ESPHome component)
can stay 100% compatible without re-flashing the remotes.

> **Status:** this document describes the *legacy* protocols, which the
> `nrf24_bthome` component does not speak. The wire format in use - BTHome v2
> payloads behind a 4-byte sender id, broadcast NO_ACK to a shared address, in
> a fixed 32-byte slot padded with `0xFF` - is described in the README.

Source of truth:

- Sender: `C:\Repos\archive\RF-RotRemote` (`src/RF/radioMessage.cpp`, `src/RF/radio.cpp`)
- Receiver: `C:\Repos\archive\SMART_WIFI-RF24_LAMP` (`src/RF/radioMessage.cpp`, `src/RF/radio.cpp`)

> Note: there are three protocol generations in the archive. Everything up to
> the appendix sections describes **version 1**, the format the deployed lamps
> and RotRemotes speak. The appendices cover
> [version 0](#protocol-version-0-smart-home-nrf--nrf24smart) (`smart-home-nrf`,
> hub-based, NRFLite) and
> [version 2](#protocol-version-2-rf-sensremote--nrf24-esp32hub)
> (`RF-SensRemote`/`NRF24-ESP32Hub`, TLV-based) — both incompatible with v1 and
> with each other.

## Radio configuration (nRF24L01)

Both sides must use identical settings:

| Parameter        | Value                          |
|------------------|--------------------------------|
| Channel          | 100 (2.500 GHz)                |
| Data rate        | 250 kbps (`RF24_250KBPS`)      |
| CRC              | 16 bit (`RF24_CRC_16`)         |
| Address width    | 5 bytes                        |
| Payload          | Dynamic payloads enabled       |
| Auto-ACK         | Enabled (default)              |
| Retries (sender) | `setRetries(5, 15)`            |
| PA level         | `RF24_PA_LOW` (both sides)     |

The sender transmits with `radio.write()` (ACK expected). The receiver listens on
**pipe 1** with the lamp-specific address. Each remote is hard-coded (flash-time
config) to the address of exactly one lamp; pairing = matching addresses.

The receiver IRQ is configured for `data_ready` only
(`maskIRQ(true, true, false)`), triggered on the falling edge.

## Frame format

Maximum frame size is 32 bytes (nRF24 hardware limit). Minimum frame size is
9 bytes (empty DATA). All multi-byte values are **little-endian**.

| Offset | Size | Field            | Notes                                          |
|--------|------|------------------|------------------------------------------------|
| 0      | 1    | PROTOCOL_VERSION | `0x01`. Receiver does **not** validate it.     |
| 1      | 4    | UUID             | Sender identity, e.g. `4D 56 52 02` (`MVR` + 2)|
| 5      | 1    | MSG_NUM          | Free-running counter, wraps at 255             |
| 6      | 1    | MSG_TYPE         | See message types below                        |
| 7      | n    | DATA             | Type-specific payload, max 23 bytes            |
| 7 + n  | 2    | CHECKSUM         | Little-endian, see below                       |

### Checksum

16-bit sum (unsigned, wrapping) of:

```
PROTOCOL_VERSION + UUID[0..3] + MSG_NUM + DATA[0..n-1]
```

Stored little-endian in the last two bytes of the frame.

**Quirk:** `MSG_TYPE` is *excluded* from the checksum on both sender and
receiver. A compatible implementation must replicate this exactly.

The receiver drops frames with a checksum mismatch (and logs a warning), frames
shorter than 9 bytes, and frames longer than 32 bytes.

## Message types

| Value | Name   | Direction     | Status                    |
|-------|--------|---------------|---------------------------|
| 0     | EMPTY  | –             | Never sent                |
| 1     | REMOTE | remote → lamp | The only type in use      |

Unknown types are logged and ignored by the receiver.

## REMOTE payload (DATA, 4 bytes)

| Offset | Size | Field              | Notes                              |
|--------|------|--------------------|-------------------------------------|
| 0      | 1    | EVENT              | See event codes                     |
| 1      | 1    | BATTERY_PERCENTAGE | 0–100                               |
| 2      | 2    | BATTERY_VOLTAGE_MV | Little-endian, millivolts           |

Total frame size for a REMOTE message: 7 + 4 + 2 = **13 bytes**.

### Event codes

Full enum as defined by the sender:

| Value | Event  | Sent by RF-RotRemote           | Legacy lamp action (CCT mode)   |
|-------|--------|--------------------------------|----------------------------------|
| 0     | EMPTY  | no                             | –                                |
| 1     | ON     | no                             | power on                         |
| 2     | OFF    | no                             | power off                        |
| 3     | TOGGLE | yes — encoder click            | toggle power                     |
| 4     | UP1    | yes — rotate right, btn held   | brightness up                    |
| 5     | DOWN1  | yes — rotate left, btn held    | brightness down                  |
| 6     | UP2    | yes — rotate right             | color temp step (warm→cold dir.) |
| 7     | DOWN2  | yes — rotate left              | color temp step                  |
| 8     | UP3    | no                             | –                                |
| 9     | DOWN3  | no                             | –                                |
| 10    | UP4    | no                             | –                                |
| 11    | DOWN4  | no                             | –                                |
| 12    | UP5    | no                             | –                                |
| 13    | DOWN5  | no                             | –                                |
| 14    | SCENE1 | yes — encoder double-click     | ignored by legacy firmware       |
| 15    | SCENE2 | no                             | –                                |
| 16    | SCENE3 | no                             | –                                |

For non-CCT LED modes the legacy lamp maps UP2/DOWN2 to brightness as well.
Long press on the encoder button sends nothing.

Brightness/color steps in the legacy firmware: 1/16 of full scale (1024/16 = 64)
per event, minimum brightness 5/1024.

## Example frame

`TOGGLE` from remote `MVR2`, MSG_NUM 0, battery 100%, 2960 mV (`0x0B90`):

```
01 4D 56 52 02 00 01 03 64 90 0B FA 01
│  └─UUID────┘ │  │  │  │  └mV─┘ └chk┘
PV          NUM TYPE│ bat%
                  event
```

Checksum: `0x01 + (0x4D+0x56+0x52+0x02) + 0x00 + (0x03+0x64+0x90+0x0B)`
`= 506 = 0x01FA` → bytes `FA 01`.

## Deployed devices (as of 2026-07)

| Device            | Role     | UUID          | Address           | Channel |
|-------------------|----------|---------------|-------------------|---------|
| RF-RotRemote #1   | sender   | `4D 56 52 01` | `99:6C:CA:80:01`  | 100     |
| Mond Lampe        | receiver | –             | `99:6C:CA:80:01`  | 100     |
| RF-RotRemote #2   | sender   | `4D 56 52 02` | `46:36:31:38:00`  | 100     |
| Schreibtischlampe | receiver | –             | `46:36:31:38:00`  | 100     |

Addresses are written MSB-first as configured (`WRITE_ADDRESS` byte order on the
sender / portal format on the lamp). The lamp default address is derived from its
WiFi MAC (bytes 1–5); the moon lamp still uses that default, the desk lamp was
configured manually via the web portal.

## Notes for a new receiver implementation

- **Duplicates:** the legacy receiver ignores MSG_NUM. If the ACK is lost the
  remote's auto-retransmit delivers the same frame again (same MSG_NUM). A new
  implementation should deduplicate on `(UUID, MSG_NUM)` within a short window.
- **Radio lock-up:** the nRF24 occasionally stops delivering IRQs; the legacy
  firmware re-initializes the radio every 30 s as a watchdog. Recommended, but
  reset the watchdog timer on every received frame.
- **Protocol version:** never validated by the legacy receiver. A new receiver
  should accept `0x01` and may log/ignore others (RF-SensRemote sends `0x02`
  frames whose checksum will not match this layout anyway).
- **Battery reporting:** every REMOTE frame carries battery data, so per-UUID
  battery sensors can be updated on each event without extra traffic.

## Protocol version 0 (smart-home-nrf / NRF24Smart)

The oldest generation, from `C:\Repos\archive\smart-home-nrf`. Not a simple
remote protocol but a full hub-and-spoke smart home system:

- **Server**: Python application (device DB, MQTT bridge, web UI) talking to an
  `nrf24USB` dongle (ATmega328 + nRF24) over serial.
- **Clients**: ATmega devices (`LedController3Channel`, `RotRemote`,
  `SensRemote`) built on a shared `RFcomm` library.

**Radio stack: NRFLite, not RF24.** This alone makes v0 wire-incompatible with
v1/v2: NRFLite uses 1-byte radio IDs (it derives the 5-byte pipe addresses
internally from a fixed base) and its own packet handling. Settings: channel
**101**, 250 kbps. Server = radio ID 0, unprovisioned device = ID 255.

**Provisioning:** a new device sends `INIT` (containing its device-type string)
to the server, receives its assigned radio ID + the server UUID, and stores both
in EEPROM. After boot it announces itself with `BOOT`.

**Checksum:** 16-bit sum over all preceding bytes, stored **big-endian** —
opposite byte order to v1/v2.

Message types: `ERROR(0) INIT(1) BOOT(2) SET(3) RESET(4) STATUS(5) REMOTE(6) OK(7)`.

### Packet formats

`ClientPacket` (device → server, 12–32 bytes):

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | ID | Sender radio ID |
| 1 | 4 | UUID | Device UUID |
| 5 | 1 | MSG_TYPE | |
| 6 | 1 | FIRMWARE | Firmware version |
| 7 | 1 | POWER_TYPE | Battery level, or 0 = mains powered |
| 8 | 1 | STATUS_INTERVAL | Seconds between periodic STATUS messages |
| 9 | 1 | MSG_NUM | Free-running counter |
| 10 | n | DATA | ≤ 20 bytes (STATUS = raw device status struct) |
| 10+n | 2 | CHECKSUM | Big-endian |

`ServerPacket` (server → device): `ID, UUID[4], MSG_TYPE, DATA[n], CHECKSUM[2]`.
A `SET` payload is a generic variable write against the device's status struct:
`varIndex, changeType (1=SET 2=TOGGLE 3=INCREASE 4=DECREASE), valueSize, value…`.
Devices ACK a SET by replying with `OK` + full status.

`RemotePacket` (remote → target device, **direct P2P**, 14 bytes): remotes are
paired via the server (which writes target ID/UUID into the remote's status) but
then transmit directly to the target device, bypassing the hub:

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | ID | Remote's radio ID |
| 1 | 4 | UUID | Remote's UUID |
| 5 | 1 | MSG_TYPE | 6 = REMOTE |
| 6 | 4 | TARGET_UUID | Target device UUID |
| 10 | 1 | LAYER | 0 = BUTTONS, 1–9 = AXIS1–9 |
| 11 | 1 | VALUE | Button number / axis direction (0 = up, 1 = down) |
| 12 | 2 | CHECKSUM | Big-endian |

### Lineage

v0 was the most featureful design (bidirectional, provisioning, generic SET API,
periodic status) but required the always-on hub. v1 (lamps/RotRemotes) was a
radical simplification to one-way remote→lamp traffic on raw RF24; v2 re-added
sensor payloads via typed records. No two generations can parse each other's
frames, and all three use different channels (101 / 100 / 105).

## Protocol version 2 (RF-SensRemote / NRF24-ESP32Hub)

A later, experimental iteration of the protocol, used by
`C:\Repos\archive\RF-SensRemote` (sender) and `C:\Repos\archive\NRF24-ESP32Hub`
(receiver). **Not used by the deployed lamps or RotRemotes** — documented here
only in case the ESPHome component should later support SensRemote devices.

Radio configuration is identical to v1 **except** for the experimental
deployment values: channel **105**, receiver address `52:46:4D:00:01`
(`'R','F','M',0x00,0x01`). The SensRemote's address and UUID are configurable
via serial command and stored in EEPROM.

### Frame format (v2)

The fixed `MSG_TYPE` byte is gone; DATA is a sequence of typed records instead.

| Offset | Size | Field            | Notes                                        |
|--------|------|------------------|-----------------------------------------------|
| 0      | 1    | PROTOCOL_VERSION | `0x02`. Receiver **rejects** other versions.  |
| 1      | 4    | UUID             | Sender identity                               |
| 5      | 1    | MSG_NUM          | Free-running counter                          |
| 6      | n    | DATA             | Concatenated records, max 23 bytes            |
| 6 + n  | 2    | CHECKSUM         | Same sum as v1, little-endian                 |

The checksum covers `PROTOCOL_VERSION + UUID + MSG_NUM + DATA` — since DATA now
includes the record type bytes, v2 has no exclusion quirk.

### DATA records

Each record: 1 type byte followed by a fixed-size payload.

| Type | Name                | Payload                                          |
|------|---------------------|--------------------------------------------------|
| 1    | DEVICENAME          | 10 bytes, zero-padded char array                 |
| 2    | REMOTE_BUTTON_EVENT | 1 byte — same event enum as v1                   |
| 3    | SENSOR_DATA         | 1 byte sensor type + uint16 little-endian value  |

Sensor types: 1 = temperature (°C × 1000), 2 = humidity (% × 1000),
3 = battery voltage (mV), 4 = battery percent. A typical SensRemote frame
carries one optional REMOTE_BUTTON_EVENT plus SENSOR_DATA records for battery
voltage, battery percent, and (with AHT20) temperature and humidity.

(Hub-side display quirk: the hub formats battery percent as `100 * value / 255`
although the SensRemote sends 0–100 — a bug in the hub, not part of the wire
format.)

### v1 vs. v2 compatibility

Mutually incompatible by design: a v2 receiver rejects v1 frames on the version
check; a v1 receiver misparses the first record type byte as `MSG_TYPE` and then
fails the checksum (v1 excludes byte 6 from the sum, v2 includes it). The
deployed experiments also used a different channel and address, so the two
protocol generations never see each other's traffic.
