"""Checks every compile-time rule the nrf24 / nrf24_bthome schema is supposed to
enforce, by running `esphome config` on a generated YAML per case and asserting
what it says.

Two kinds of case: `bad` must be refused and the message must contain a given
phrase, `good` must validate. The point is not that the component compiles - it
is that the combinations the chip cannot do are refused with a message that
names the reason, because those failures are silent on the air.

    python tests/validate_config_rules.py
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

COMPONENTS = Path(__file__).resolve().parent.parent / "components"

BASE = """
esphome:
  name: rulecheck
esp32:
  board: esp32-c3-devkitm-1
  framework:
    type: esp-idf
logger:
external_components:
  - source:
      type: local
      path: {components}
spi:
  clk_pin: GPIO4
  miso_pin: GPIO5
  mosi_pin: GPIO6
"""


def run(body):
    text = BASE.format(components=COMPONENTS.as_posix()) + body
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rulecheck.yaml"
        path.write_text(text, encoding="utf-8")
        proc = subprocess.run(["esphome", "config", str(path)],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out


results = []

# "must be refused, and the message is printed rather than asserted" - for the
# generic range and type checks, where the wording is esphome's, not ours.
ANY = object()


def check(name, body, expect=None):
    """expect=None means the config must validate; ANY means it must be refused;
    a string means it must be refused with that phrase in the message."""
    ok, out = run(body)
    if expect is None:
        passed, detail = ok, "validates" if ok else _first_error(out)
    elif expect is ANY:
        passed = not ok
        detail = (f"refused: {_first_error(out)}" if not ok
                  else "accepted, but should have been refused")
    else:
        phrase_seen = re.search(re.escape(expect), out, re.I | re.S) is not None
        passed = (not ok) and phrase_seen
        if ok:
            detail = "accepted, but should have been refused"
        elif not phrase_seen:
            detail = f"refused, but not for '{expect}': {_first_error(out)}"
        else:
            detail = f"refused with '{expect}'"
    results.append((name, passed, detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}\n      {detail}", flush=True)


def _first_error(out):
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    for i, l in enumerate(lines):
        if "Failed config" in l:
            return " / ".join(lines[i + 1:i + 5])[:220]
    return lines[-1][:220] if lines else "(no output)"


HUB = """
nrf24:
  cs_pin: GPIO8
  ce_pin: GPIO7
"""

# ---- the two rules that matter ----------------------------------------------
check("R1 fixed payload size with auto-ack is refused (measured rule)",
      HUB + """  payload_size: 32
  auto_ack: true
  pipes:
    - address: "BTHME"
""", "requires auto_ack: false")

check("R2 dynamic payload size without auto-ack is refused (datasheet rule)",
      HUB + """  payload_size: dynamic
  auto_ack: false
  pipes:
    - address: "BTHME"
""", "requires auto_ack: true")

check("R3 the rule is enforced per pipe, not just at hub level",
      HUB + """  payload_size: 32
  auto_ack: false
  pipes:
    - address: "BTHME"
    - address: "CTHME"
      auto_ack: true
""", "pipe 2")

check("R4 a pipe overriding to dynamic without auto-ack is refused",
      HUB + """  payload_size: 32
  auto_ack: false
  pipes:
    - address: "BTHME"
      payload_size: dynamic
""", "requires auto_ack: true")

# ---- the hardware address constraint ----------------------------------------
check("R5 pipes 2-5 differing in more than the first byte are refused",
      HUB + """  pipes:
    - address: "BTHME"
    - address: "CXHME"
      payload_size: 32
      auto_ack: false
""", "first byte")

check("R6 two pipes with the same first address byte are refused",
      HUB + """  pipes:
    - address: "BTHME"
    - address: "BTHME"
      payload_size: 32
      auto_ack: false
""", "already used")

check("R7 more than five pipes are refused",
      HUB + """  pipes:
    - address: "BTHME"
    - address: "CTHME"
    - address: "DTHME"
    - address: "ETHME"
    - address: "FTHME"
    - address: "GTHME"
""", ANY)

# ---- value ranges and formats -----------------------------------------------
check("R8 payload_size 0 is refused",
      HUB + """  payload_size: 0
  auto_ack: false
  pipes:
    - address: "BTHME"
""", ANY)

check("R9 payload_size 33 is refused (the slot is 32 bytes)",
      HUB + """  payload_size: 33
  auto_ack: false
  pipes:
    - address: "BTHME"
""", ANY)

check("R10 a channel above 125 is refused",
      HUB + """  channel: 126
  pipes:
    - address: "BTHME"
""", ANY)

check("R11 a four-character pipe address is refused",
      HUB + """  pipes:
    - address: "BTHM"
""", "5 hex bytes")

check("R12 a non-hex byte in an address is refused",
      HUB + """  pipes:
    - address: "4Z:54:48:4D:45"
""", "not a hex byte")

check("R13 data_rate instead of air_data_rate does not silently set the air rate",
      HUB + """  data_rate: 250kbps
  pipes:
    - address: "BTHME"
""", ANY)

check("R14 a missing ce_pin is refused",
      """
nrf24:
  cs_pin: GPIO8
  pipes:
    - address: "BTHME"
""", "ce_pin")

# ---- the bthome layer -------------------------------------------------------
GOOD_HUB = HUB + """  channel: 90
  air_data_rate: 250kbps
  pipes:
    - address: "BTHME"
    - address: "CTHME"
      payload_size: 32
      auto_ack: false
"""

check("R15 a three-byte sender id is refused",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7"
""", "sender_id must have 4 bytes")

# Without colons the value is read as a Latin-1 string, which is the other
# branch of hex_bytes() and so the other message.
check("R15b a sender id without colons and of the wrong length is refused",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "ABC"
""", "4 hex bytes")

check("R16 a non-hex sender id is refused",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:ZZ"
""", "not a hex byte")

check("R17 nrf24_bthome without an nrf24 hub is refused",
      """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
""", ANY)

check("R18 a sensor platform pointing at an unknown device is refused",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: does_not_exist
    battery:
      name: B
""", ANY)

# ---- encryption -------------------------------------------------------------
# The key is the one value here that cannot be checked at runtime: a wrong one
# does not fail, it simply decrypts nothing, and the receiver reports a sender
# that has gone quiet. So the format is pinned at config time.
check("R32 an encryption key of the wrong length is refused",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
      encryption_key: "231d39c1d7cc1ab1"
""", "32 hexadecimal characters")

check("R33 a non-hex encryption key is refused",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
      encryption_key: "231d39c1d7cc1ab1aee224cd096db9zz"
""", "32 hexadecimal characters")

# It only feeds the nonce, so on its own it changes nothing - and silently
# doing nothing is exactly what a security option must not do.
check("R34 a mac_address without an encryption key is refused",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
      mac_address: "AA:BB:CC:DD:EE:FF"
""", "does nothing without an encryption_key")

check("R35 a five-byte mac_address is refused",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
      encryption_key: "231d39c1d7cc1ab1aee224cd096db932"
      mac_address: "AA:BB:CC:DD:EE"
""", "mac_address must have 6 bytes")

check("R36 an encrypted device validates, with and without a mac_address",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
      encryption_key: "231d39c1d7cc1ab1aee224cd096db932"
    - id: r2
      sender_id: "B7:4F:E7:80"
      encryption_key: "231D39C1D7CC1AB1AEE224CD096DB932"
      mac_address: "AA:BB:CC:DD:EE:FF"
""")

# ---- the combinations that must be accepted ---------------------------------
check("R19 the migration configuration validates (dynamic + fixed side by side)",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
      timeout: 70min
""")

check("R20 a fixed-only receiver validates",
      HUB + """  channel: 90
  payload_size: 32
  auto_ack: false
  pipes:
    - address: "CTHME"
""")

check("R21 a dynamic-only receiver validates",
      HUB + """  channel: 90
  pipes:
    - address: "BTHME"
""")

check("R22 two hubs on one bus validate (MULTI_CONF)", """
nrf24:
  - id: hub_a
    cs_pin: GPIO8
    ce_pin: GPIO7
    channel: 90
    pipes:
      - address: "BTHME"
  - id: hub_b
    cs_pin: GPIO9
    ce_pin: GPIO10
    channel: 95
    payload_size: 32
    auto_ack: false
    pipes:
      - address: "CTHME"
""")

check("R23 watchdog_timeout 0s (disabled) validates",
      HUB + """  watchdog_timeout: 0s
  pipes:
    - address: "BTHME"
""")

# ---- the measurement types --------------------------------------------------
PROBE_DEVICE = GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: r1
"""

check("R24 a measurement type the component does not map is refused",
      PROBE_DEVICE + """    luminous_flux:
      name: X
""", ANY)

check("R25 index 0 is refused - instances are counted from one",
      PROBE_DEVICE + """    temperature:
      name: X
      index: 0
""", ANY)

check("R26 an index past the last countable instance is refused",
      PROBE_DEVICE + """    temperature:
      name: X
      index: 13
""", ANY)

# Every type at once, generated from the same table the benches use. It fails on
# a row whose schema cannot be built at all - which is not hypothetical: passing
# entity_category=None explicitly rather than leaving it out made esphome
# validate None as a string, and only a config run says so.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sensor_type_vectors import BINARY_VECTORS, VECTORS  # noqa: E402

# dict.fromkeys, not set: several ids share a key, and a YAML mapping may not
# repeat one.
SENSOR_KEYS = list(dict.fromkeys(key for key, *_ in VECTORS))
BINARY_KEYS = list(dict.fromkeys(key for key, *_ in BINARY_VECTORS))

check(f"R27 all {len(SENSOR_KEYS)} mapped measurement types validate on one device",
      PROBE_DEVICE + "".join(f'    {key}:\n      name: "P {key}"\n'
                             for key in SENSOR_KEYS))

check(f"R28 all {len(BINARY_KEYS)} binary types validate on one device",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
binary_sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: r1
""" + "".join(f'    {key}:\n      name: "B {key}"\n' for key in BINARY_KEYS))

check("R30 text and raw validate, including a second instance",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
text_sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: r1
    device_name:
      name: N
    text:
      name: T
    raw:
      name: R
  - platform: nrf24_bthome
    nrf24_bthome_device_id: r1
    text:
      name: T2
      index: 2
""")

check("R31 a text key the component does not map is refused",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
text_sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: r1
    comment:
      name: X
""", ANY)

check("R29 a binary type the component does not map is refused",
      GOOD_HUB + """
nrf24_bthome:
  devices:
    - id: r1
      sender_id: "B7:4F:E7:7F"
binary_sensor:
  - platform: nrf24_bthome
    nrf24_bthome_device_id: r1
    tilt:
      name: X
""", ANY)

print("\n--- summary ---")
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(0 if not failed else 1)
