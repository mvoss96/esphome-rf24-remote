"""Checks the register bits the radio's configuration turns into.

radio_init_() verifies its own writes by reading the registers back - but that
check compares against the very variable it computed. A mask that is wrong to
begin with is written wrong, read back wrong, and agrees with itself: the one
failure mode the read-back cannot see, and the one that costs the most, because
EN_AA and DYNPD decide whether a pipe hears anything at all and whether short
payloads arrive twice.

So the arithmetic lives in components/nrf24/nrf24_config.h, free of every
esphome include, and this holds it to expectations spelled out from the
datasheet rather than derived from the same code:

  * pipe n is bit n in EN_RXADDR, EN_AA and DYNPD, and the first configured
    pipe is pipe 1 - pipe 0 belongs to a transmitter's auto-ack path,
  * EN_DPL in FEATURE is chip-wide and goes on as soon as one pipe is dynamic,
  * the data rate sits in two bits that are not adjacent, so 1 Mbps is the value
    that comes out of setting neither,
  * a sixth pipe is dropped rather than wrapped into a neighbouring field.

    python tests/test_nrf24_config.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROBE_SRC = Path(__file__).resolve().parent / "host" / "nrf24_config_probe.cpp"
INCLUDE = REPO / "components" / "nrf24"

# rate, pa, [(payload_size, auto_ack)], EN_RXADDR, EN_AA, DYNPD, FEATURE, RF_SETUP
CASES = [
    # The lab and migration configuration: one dynamic pipe with auto-ack for
    # senders not yet converted, one fixed 32-byte pipe without it.
    ("migration hub", 250, 1, [(0, True), (32, False)], 0x06, 0x02, 0x02, 0x04, 0x22),
    # A fixed-length receiver. No pipe wants dynamic lengths, so EN_DPL stays
    # off - and with it the whole feature the chip would otherwise apply.
    ("fixed only", 250, 1, [(32, False)], 0x02, 0x00, 0x00, 0x00, 0x22),
    ("dynamic only", 250, 1, [(0, True)], 0x02, 0x02, 0x02, 0x04, 0x22),
    # Every pipe the chip has.
    ("five dynamic pipes", 250, 3, [(0, True)] * 5, 0x3E, 0x3E, 0x3E, 0x04, 0x26),
    ("five fixed pipes", 250, 3, [(8, False)] * 5, 0x3E, 0x00, 0x00, 0x00, 0x26),
    # Alternating, so a mask that is right only when all pipes agree fails here.
    ("alternating", 1000, 0,
     [(0, True), (32, False), (0, True), (16, False), (0, True)],
     0x3E, 0x2A, 0x2A, 0x04, 0x00),
    # A sixth pipe has no bit of its own. Dropping it keeps it out of the
    # registers; shifting it further would set bit 6, which in EN_RXADDR is
    # reserved and in DYNPD does not exist.
    ("six pipes, the sixth dropped", 250, 1, [(0, True)] * 6, 0x3E, 0x3E, 0x3E, 0x04, 0x22),
    ("no pipes at all", 250, 1, [], 0x00, 0x00, 0x00, 0x00, 0x22),
]

# Both rate bits are in RF_SETUP but not next to each other: RF_DR_LOW is bit 5
# and RF_DR_HIGH is bit 3, so 1 Mbps is "neither set" rather than a value of
# its own. The PA field is bits 2:1.
RF_SETUP = {
    (250, 0): 0x20, (250, 1): 0x22, (250, 2): 0x24, (250, 3): 0x26,
    (1000, 0): 0x00, (1000, 1): 0x02, (1000, 2): 0x04, (1000, 3): 0x06,
    (2000, 0): 0x08, (2000, 1): 0x0A, (2000, 2): 0x0C, (2000, 3): 0x0E,
}

results = []


def verdict(name, ok, detail):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}\n      {detail}", flush=True)


def line(rate, pa, pipes):
    return " ".join([str(rate), str(pa)] + [f"{size}:{1 if ack else 0}" for size, ack in pipes])


def main():
    workdir = Path(tempfile.mkdtemp(prefix="nrf24-config-"))
    exe = workdir / ("probe.exe" if os.name == "nt" else "probe")
    subprocess.run(
        [os.environ.get("CXX", "g++"), "-std=c++17", "-O1", "-Wall", "-Wextra",
         "-I", str(INCLUDE), "-o", str(exe), str(PROBE_SRC)],
        check=True)

    inputs = [line(rate, pa, pipes) for _, rate, pa, pipes, *_ in CASES]
    inputs += [line(rate, pa, [(0, True)]) for rate, pa in sorted(RF_SETUP)]
    out = subprocess.run([str(exe)], input="\n".join(inputs) + "\n",
                         capture_output=True, text=True, check=True).stdout
    got = [tuple(int(v, 16) for v in row.split()[1:])
           for row in out.splitlines() if row.startswith("MASKS")]

    verdict("C0 every configuration produced a result",
            len(got) == len(inputs), f"{len(got)} of {len(inputs)} lines came back")

    for i, (name, rate, pa, pipes, *want) in enumerate(CASES):
        actual = list(got[i])
        names = ("EN_RXADDR", "EN_AA", "DYNPD", "FEATURE", "RF_SETUP")
        wrong = [f"{n}: expected {w:02X}, got {a:02X}"
                 for n, w, a in zip(names, want, actual) if w != a]
        verdict(f"C {name}", not wrong,
                "; ".join(wrong) or " ".join(f"{n}={v:02X}" for n, v in zip(names, actual)))

    wrong_rf = []
    for j, (rate, pa) in enumerate(sorted(RF_SETUP)):
        actual = got[len(CASES) + j][4]
        if actual != RF_SETUP[(rate, pa)]:
            wrong_rf.append(f"{rate}kbps/pa{pa}: expected "
                            f"{RF_SETUP[(rate, pa)]:02X}, got {actual:02X}")
    verdict("C RF_SETUP over every data rate and PA level",
            not wrong_rf, "; ".join(wrong_rf) or f"{len(RF_SETUP)} combinations correct")

    shutil.rmtree(workdir, ignore_errors=True)

    print("\n--- summary ---")
    for name, ok, _ in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
