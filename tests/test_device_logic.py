"""The component's own logic, on the host, without a radio.

Everything between "a frame arrived" and "an entity was published" used to be
checkable only in the lab - a hub on the network and two dongles on the air. So
the paths beside the measurement mapping went untested: of seven button events
exactly one was ever fired, the command event was never sent, and a timeout cost
eighteen seconds of waiting per run, which is why the millis() wraparound behind
it was never tried at all.

tests/host/device_probe.cpp runs the real component against the stubs in
tests/host/stubs. Each case here is a stretch of scenario and what the component
has to answer with. See tests/host/stubs/README.md for what the stubs do and do
not prove.

    python tests/test_device_logic.py [--src <path to bthome-cpp>]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMPONENT = REPO / "components" / "nrf24_bthome"
PROBE_SRC = Path(__file__).resolve().parent / "host" / "device_probe.cpp"
STUBS = Path(__file__).resolve().parent / "host" / "stubs"
UPSTREAM = "https://github.com/mvoss96/bthome-cpp.git"

A = "AA010001"
B = "AA010002"
UNKNOWN = "DEADBEEF"
HDR = "D2FC44"          # service uuid 0xFCD2 little endian, then device info
HDR_ENCRYPTED = "D2FC45"  # the same, with the encrypted bit set


def frame(sender, objects, header=HDR):
    return f"FRAME {sender}{header}{objects}"


_pid = [0]


def pid():
    """A fresh packet id, so a case is never suppressed by the one before it."""
    _pid[0] = (_pid[0] + 1) & 0xFF or 1
    return f"00{_pid[0]:02X}"


# name, scenario lines, lines that must appear, lines that must not
CASES = [
    # --- events ---------------------------------------------------------------
    ("all seven button events reach their names",
     [frame(A, pid() + f"3A{code:02X}") for code in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x80)]
     + [frame(A, pid() + "3A07")],
     [r"TRIGGER A button 1 press$", r"TRIGGER A button 1 double_press$",
      r"TRIGGER A button 1 triple_press$", r"TRIGGER A button 1 long_press$",
      r"TRIGGER A button 1 long_double_press$", r"TRIGGER A button 1 long_triple_press$",
      # 0x80, not 0x07 - the one code that is not simply the next number up.
      r"TRIGGER A button 1 hold_press$",
      # An event code this version does not know must still name a button.
      r"TRIGGER A button 1 unknown$"],
     []),

    ("a None entry addresses the button behind it",
     [frame(A, pid() + "3A003A01")],
     [r"TRIGGER A button 2 press$"],
     [r"TRIGGER A button 1 "]),

    ("dimmer direction, step count and instance",
     [frame(A, pid() + "3C0205"), frame(A, pid() + "3C0103"),
      frame(A, pid() + "3C00003C0202"), frame(A, pid() + "3C0000")],
     [r"TRIGGER A dimmer 1 5$", r"TRIGGER A dimmer 1 -3$", r"TRIGGER A dimmer 2 2$"],
     # A lone None fires nothing at all - it is a placeholder, not an event.
     [r"TRIGGER A dimmer 1 0$"]),

    # --- the objects the component passes over --------------------------------
    ("a command event is stepped over, whatever its argument count",
     [frame(A, pid() + "01503B027F0102" + "0C800D"),
      frame(A, pid() + "3B017F05" + "3A01"),
      frame(A, pid() + "3B007F" + "029C09")],
     [r"PUBLISH A.battery 80", r"PUBLISH A.voltage 3.456",
      r"TRIGGER A button 1 press$", r"PUBLISH A.temperature 24.6"],
     # Its length is its own argument count, so a wrong reading would shift the
     # rest of the payload and show up as a malformed frame.
     [r"malformed BTHome payload"]),

    ("an encrypted payload is refused, nothing is published",
     [frame(A, pid() + "01503A01", header=HDR_ENCRYPTED)],
     [r"LOG W AA:01:00:01: encrypted BTHome payload not supported"],
     [r"PUBLISH A\.", r"TRIGGER A "]),

    # --- the text sensors -----------------------------------------------------
    ("firmware version, both widths",
     [frame(A, pid() + "F2030201"), frame(A, pid() + "F104030201")],
     [r"PUBLISH A.firmware '1\.2\.3'$", r"PUBLISH A.firmware '1\.2\.3\.4'$"],
     []),

    ("the first text object is the device name, the second its own entity",
     [frame(A, pid() + "5303616263"),
      frame(A, pid() + "53036C616253037A7A7A")],
     [r"PUBLISH A.device_name 'abc'$", r"PUBLISH A.text 'abc'$",
      r"PUBLISH A.text 'lab'$", r"PUBLISH A.text2 'zzz'$"],
     # The name follows instance 1 only; the second object is not the device
     # renaming itself.
     [r"PUBLISH A.device_name 'zzz'"]),

    ("an unchanged text is not published again",
     [frame(A, pid() + "530378797A"), frame(A, pid() + "530378797A")],
     [r"PUBLISH A.text 'xyz'$"],
     []),  # exactly once, counted below

    # --- last_seen ------------------------------------------------------------
    # The epoch is a multiple of 128 on purpose: last_seen is a float32, whose
    # mantissa runs out around 2^31, so it quantizes an epoch to about two
    # minutes. A round-looking number would come back rounded and read like a
    # fault in the clock.
    ("last_seen follows a new packet, not a repeat and not a discarded payload",
     ["EPOCH 1700000128", frame(A, "0050" + "3A01"),
      frame(A, "0050" + "3A01"),          # the same id again: a repeat
      frame(A, "0051" + "5320")],         # a text object announcing 32 bytes
     [r"PUBLISH A.last_seen 1700000128"],
     []),  # exactly once, counted below

    ("last_seen stays quiet while the clock is unset",
     ["EPOCH none", frame(A, pid() + "3A01"), "EPOCH 1700000200"],
     [r"TRIGGER A button 1 press$"],
     [r"PUBLISH A.last_seen"]),

    # --- the dedup ------------------------------------------------------------
    ("a repeated packet id is suppressed, a fresh one is not",
     [frame(A, "0060" + "3A01"), frame(A, "0060" + "3A01"), frame(A, "0061" + "3A01")],
     [],
     []),  # counted below rather than matched

    ("the packet id may sit behind the event it belongs to",
     [frame(A, "3A01" + "0062"), frame(A, "3A01" + "0062")],
     [],
     []),  # counted below

    ("a discarded payload does not burn its packet id",
     [frame(A, "0070" + "3A01" + "5320"), frame(A, "0070" + "3A01")],
     [r"LOG W AA:01:00:01: malformed BTHome payload, discarded \(truncated\)",
      r"TRIGGER A button 1 press$"],
     []),

    ("a payload without a packet id cannot be deduplicated",
     [frame(A, "3A01"), frame(A, "3A01"), frame(A, "3A01")],
     # The warning says so once, rather than leaving three events from one press
     # to be discovered in an automation.
     [r"LOG W AA:01:00:01: event objects without a packet id"],
     []),  # the three events are counted below

    # --- the frames that are not for this receiver ----------------------------
    ("the hub turns away what is not addressed to it",
     ["FRAME AA0100", frame(UNKNOWN, pid() + "3A01"),
      frame(A, pid() + "3A01", header="AAAA44")],
     [r"LOG V Frame too short \(3 bytes\)",
      r"LOG D Frame from unregistered sender DE:AD:BE:EF",
      r"LOG W AA:01:00:01: invalid BTHome service data"],
     [r"TRIGGER "]),

    ("one sender's event does not reach the other device",
     [frame(A, pid() + "01503A01"), frame(B, pid() + "01643A01")],
     [r"TRIGGER A button 1 press$", r"TRIGGER B button 1 press$",
      r"PUBLISH A.battery 80", r"PUBLISH B.battery 100"],
     []),

    # --- instances at the capacity of a frame ---------------------------------
    ("a frame filled to capacity counts every object",
     # Twelve single-byte objects, the last id twice: the instance counter is a
     # fixed array, and one sized for fewer would answer instance 1 for both.
     [frame(A, "".join(f"{oid:02X}01" for oid in
                       (0x01, 0x09, 0x0F, 0x21, 0x2E, 0x2F, 0x46, 0x57, 0x58, 0x60, 0x64, 0x64)))],
     [r"LOG V AA:01:00:01: sensor 0x64#1: ", r"LOG V AA:01:00:01: sensor 0x64#2: ",
      r"LOG V AA:01:00:01: binary 0x21#1: on"],
     [r"malformed BTHome payload"]),
]

# --- the timeout, which on hardware costs eighteen seconds per run ------------
# The device's quiet period is 15 s. Nothing here waits: the clock is a value a
# scenario sets.
TIMEOUT_CASES = [
    ("the offline transition after the quiet period",
     ["CLOCK 1000", frame(A, "0080" + "3A01"), "CLOCK 20000", "TICK"],
     [r"LOG W AA:01:00:01: offline", r"PUBLISH A.connected OFF"],
     []),

    # The ageing that comes with going offline, and the reason for it: a sender
    # that reboots starts its packet ids over, and a stale one would swallow its
    # first frame.
    ("after the quiet period the same packet id counts as new again",
     [frame(A, "0080" + "3A01")],
     [r"TRIGGER A button 1 press$", r"PUBLISH A.connected ON"],
     []),

    # millis() runs out after about 49 days and starts over. The difference is
    # computed in unsigned arithmetic, which carries across that point - but
    # nothing had ever tried it, because no hardware run lasts seven weeks.
    ("a device stays online across the millis() wraparound",
     ["CLOCK 4294960000", frame(A, "0081" + "3A01"), "CLOCK 5000", "TICK"],
     [r"TRIGGER A button 1 press$"],
     [r"LOG W AA:01:00:01: offline"]),

    ("and goes offline once the quiet period has passed on the far side",
     ["CLOCK 20000", "TICK"],
     [r"LOG W AA:01:00:01: offline", r"PUBLISH A.connected OFF"],
     []),
]

CASES += TIMEOUT_CASES

# What the receiver says about itself at boot. Both halves are misconfigurations
# that look like a dead radio from the outside: a timeout shorter than the
# sender's status interval reports it offline between broadcasts, and a platform
# entry that never attached shows up as a device with no entities.
CASES.append(
    ("dump_config says what each device is set up to receive",
     ["DUMP"],
     [r"LOG C nRF24 BTHome receiver:",
      r"LOG C   Device: AA:01:00:01",
      r"LOG C     Timeout: 15000 ms",
      r"LOG C     Entities: 5 sensor, 2 binary sensor, 6 text sensor",
      r"LOG C     Triggers: 1 on_button, 1 on_dimmer",
      r"LOG C   Device: AA:01:00:02",
      r"LOG C     Entities: 1 sensor, 1 binary sensor, 0 text sensor",
      r"LOG C     Triggers: 1 on_button, 0 on_dimmer"],
     []))

# Cases whose point is how many times something happened, not whether it did at
# all: case name, pattern, expected count.
COUNTS = [
    ("an unchanged text is not published again", r"PUBLISH A\.text ", 1),
    ("last_seen follows a new packet, not a repeat and not a discarded payload",
     r"PUBLISH A\.last_seen ", 1),
    ("a repeated packet id is suppressed, a fresh one is not",
     r"TRIGGER A button 1 press", 2),
    ("the packet id may sit behind the event it belongs to",
     r"TRIGGER A button 1 press", 1),
    ("a discarded payload does not burn its packet id",
     r"TRIGGER A button 1 press", 1),
    ("a payload without a packet id cannot be deduplicated",
     r"TRIGGER A button 1 press", 3),
    ("a payload without a packet id cannot be deduplicated",
     r"LOG W AA:01:00:01: event objects without a packet id", 1),
]


# ---- building the probe ------------------------------------------------------
def pinned_version():
    text = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'BTHOME_CPP_VERSION\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("BTHOME_CPP_VERSION not found in the component")
    return m.group(1)


def library_source(version, workdir, given=None):
    tag = f"v{version}"
    if given:
        return Path(given)
    env_src = os.environ.get("BTHOME_CPP_SRC")
    if env_src:
        return Path(env_src)

    local = REPO.parent / "bthome-cpp"
    dest = workdir / "bthome-cpp"
    dest.mkdir(parents=True, exist_ok=True)
    if (local / ".git").exists():
        archive = workdir / "bthome.tar"
        subprocess.run(["git", "-C", str(local), "archive", "-o", str(archive), tag], check=True)
        subprocess.run(["tar", "-xf", str(archive), "-C", str(dest)], check=True)
        return dest
    subprocess.run(["git", "clone", "--depth", "1", "--branch", tag, UPSTREAM, str(dest)],
                   check=True)
    return dest


def build_probe(src, workdir):
    exe = workdir / ("device_probe.exe" if os.name == "nt" else "device_probe")
    subprocess.run(
        [os.environ.get("CXX", "g++"), "-std=c++17", "-O1", "-Wall", "-Wextra",
         "-I", str(STUBS), "-I", str(REPO), "-I", str(src / "src"),
         "-o", str(exe), str(PROBE_SRC), str(COMPONENT / "nrf24_bthome.cpp")],
        check=True)
    return exe


# ---- verdicts ----------------------------------------------------------------
results = []


def verdict(name, ok, detail):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}\n      {detail}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="path to a bthome-cpp checkout to build against")
    ap.add_argument("--show", help="print the output of the case with this name")
    args = ap.parse_args()

    version = pinned_version()
    workdir = Path(tempfile.mkdtemp(prefix="bthome-device-"))
    src = library_source(version, workdir, args.src)
    manifest = json.loads((src / "library.json").read_text(encoding="utf-8"))
    verdict("D0 the library built against is the version the component pins",
            manifest["version"] == version,
            f"pinned {version}, source tree reports {manifest['version']}")
    exe = build_probe(src, workdir)
    print(f"built {exe.name} against {src}\n", flush=True)

    # One process for the whole run: the component keeps state between frames -
    # dedup, entity values, the clock - and a case that depends on what came
    # before it is exactly what should be exercised.
    scenario = []
    for name, lines, _expect, _forbid in CASES:
        scenario.append(f"MARK {name}")
        scenario += lines
    out = subprocess.run([str(exe)], input="\n".join(scenario) + "\n",
                         capture_output=True, text=True, check=True).stdout

    sections, current = {}, None
    for line in out.splitlines():
        if line.startswith("MARK "):
            current = line[5:]
            sections[current] = []
        elif current is not None:
            sections[current].append(line)

    for name, _lines, expect, forbid in CASES:
        body = sections.get(name, [])
        if args.show == name:
            print("\n".join(f"      | {line}" for line in body), flush=True)
        missing = [p for p in expect if not any(re.search(p, line) for line in body)]
        present = [p for p in forbid if any(re.search(p, line) for line in body)]
        faults = ([f"missing: {p}" for p in missing] + [f"unwanted: {p}" for p in present])

        for case_name, pattern, want in COUNTS:
            if case_name != name:
                continue
            seen = sum(1 for line in body if re.search(pattern, line))
            if seen != want:
                faults.append(f"{pattern!r} seen {seen}x, expected {want}x")

        verdict(f"D {name}", not faults,
                "; ".join(faults) or f"{len(body)} lines, all expectations met")

    shutil.rmtree(workdir, ignore_errors=True)

    print("\n--- summary ---")
    for name, ok, _ in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
