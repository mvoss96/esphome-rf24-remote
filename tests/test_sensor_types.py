"""Checks the sensor-type table against the bthome-cpp version the component
pins, on the host, without a radio.

What the component adds to BTHome is meaning: bthome-cpp knows that object 0x02
is two signed bytes scaled by 0.01, but not that this is a temperature in
degrees Celsius shown with two decimals. That mapping lives in
components/nrf24_bthome/sensor.py and nothing in a normal build verifies it - a
wrong object id produces an entity that looks plausible and reads the wrong
quantity.

So this compiles a small host program against the pinned library, decodes the
shared test vectors with it, and holds the table to the result:

  * every mapped key has a vector and every vector a mapped key,
  * the library knows the id, and knows it as a measurement,
  * the value bytes are as wide as the library says the object is,
  * the decoded value is the expected physical one, sign and scale included,
  * accuracy_decimals matches the resolution the scale factor allows,
  * repeated objects of one id are counted into instances,
  * a payload padded to a fixed slot with 0xFF still yields its measurement.

The library source is taken from the version pinned in __init__.py, not from
whatever happens to be checked out: a check against a different version than
the firmware compiles with proves nothing.

    python tests/test_sensor_types.py [--src <path to bthome-cpp>]
"""
import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sensor_type_vectors import VECTORS, all_vectors, encoded  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
COMPONENT = REPO / "components" / "nrf24_bthome"
PROBE_SRC = Path(__file__).resolve().parent / "host" / "bthome_probe.cpp"
UPSTREAM = "https://github.com/mvoss96/bthome-cpp.git"

# BTHome service uuid (0xFCD2, little endian) and the device-info byte, the
# three bytes every payload starts with.
HDR = "D2FC44"


# ---- reading the component's own declarations --------------------------------
def pinned_version():
    text = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'BTHOME_CPP_VERSION\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("BTHOME_CPP_VERSION not found in the component")
    return m.group(1)


def sensor_types():
    """The SENSOR_TYPES table, read as data.

    Parsed rather than imported: sensor.py pulls in esphome codegen and the
    sibling nrf24 component, which only resolve inside an esphome build. The
    names in the table are resolved against esphome.const, so a constant that
    does not exist there fails here too.
    """
    from esphome import const

    tree = ast.parse((COMPONENT / "sensor.py").read_text(encoding="utf-8"))
    node = None
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and getattr(stmt.targets[0], "id", "") == "SENSOR_TYPES":
            node = stmt.value
            break
    if node is None:
        raise SystemExit("SENSOR_TYPES not found in sensor.py")

    def resolve(expr):
        if isinstance(expr, ast.Constant):
            return expr.value
        if isinstance(expr, ast.Name):
            if not hasattr(const, expr.id):
                raise SystemExit(f"{expr.id} is not a constant in esphome.const")
            return getattr(const, expr.id)
        if isinstance(expr, ast.Tuple):
            return tuple(resolve(e) for e in expr.elts)
        raise SystemExit(f"unsupported expression in SENSOR_TYPES: {ast.dump(expr)}")

    return {resolve(k): resolve(v) for k, v in zip(node.keys, node.values)}


# ---- the pinned library ------------------------------------------------------
def library_source(version, workdir, given=None):
    """A source tree at the pinned version. A local checkout is used through
    `git archive`, which reads the tag without touching the working tree."""
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
        subprocess.run(["git", "-C", str(local), "archive", "-o", str(archive), tag],
                       check=True)
        subprocess.run(["tar", "-xf", str(archive), "-C", str(dest)], check=True)
        return dest

    subprocess.run(["git", "clone", "--depth", "1", "--branch", tag, UPSTREAM, str(dest)],
                   check=True)
    return dest


def build_probe(src, workdir):
    exe = workdir / ("bthome_probe.exe" if os.name == "nt" else "bthome_probe")
    cxx = os.environ.get("CXX", "g++")
    subprocess.run(
        [cxx, "-std=c++17", "-O1", "-Wall", "-Wextra", "-I", str(src / "src"),
         "-o", str(exe), str(PROBE_SRC)],
        check=True)
    return exe


def run_probe(exe, payloads):
    out = subprocess.run([str(exe)], input="\n".join(payloads) + "\n",
                         capture_output=True, text=True, check=True).stdout
    layouts, frames = {}, {}
    for line in out.splitlines():
        parts = line.split()
        if parts[0] == "LAYOUT":
            layouts[int(parts[1], 16)] = {
                "kind": parts[2], "width": int(parts[3]),
                "signed": parts[4] == "1", "factor": float(parts[5])}
        elif parts[0] == "FRAME":
            frame = frames.setdefault(int(parts[1]), {"sensors": [], "status": None})
            if parts[2] == "SENSOR":
                frame["sensors"].append(
                    (int(parts[3], 16), int(parts[4]), float(parts[5])))
            else:
                frame["status"] = (parts[3], int(parts[4], 16))
    return layouts, frames


def decimals_of(factor):
    """How many decimals the scale factor can actually resolve. 0.01 gives two
    meaningful places; showing three would invent precision the sender did not
    send, and showing one would throw a place away.

    The factor arrives as a float32, so it is rounded back to the decimal it was
    written as before being read: 0.1f is 0.100000001, and counting the places
    of that answers nine.
    """
    return max(0, -Decimal(f"{factor:.6g}").as_tuple().exponent)


def close(a, b):
    return abs(a - b) <= max(1e-4, abs(b) * 1e-6)


# ---- verdicts ----------------------------------------------------------------
results = []


def verdict(name, ok, detail):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}\n      {detail}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="path to a bthome-cpp checkout to build against")
    ap.add_argument("--keep", action="store_true", help="keep the build directory")
    args = ap.parse_args()

    version = pinned_version()
    table = sensor_types()
    workdir = Path(tempfile.mkdtemp(prefix="bthome-types-"))
    print(f"component pins bthome-cpp {version}", flush=True)

    src = library_source(version, workdir, args.src)
    manifest = json.loads((src / "library.json").read_text(encoding="utf-8"))
    verdict("V0 the library built against is the version the component pins",
            manifest["version"] == version,
            f"pinned {version}, source tree reports {manifest['version']}")

    exe = build_probe(src, workdir)
    print(f"built {exe.name} against {src}\n", flush=True)

    vectors = all_vectors()
    payloads = [HDR + encoded(oid, b) for _, oid, _, b, _, _, _ in vectors]
    # Two objects of one id in one payload: the second must be instance 2 rather
    # than overwrite the first.
    instance_payload = HDR + encoded(0x02, "2909") + encoded(0x02, "2EFB")
    payloads.append(instance_payload)
    # A measurement whose last byte is 0xFF, followed by the padding of a
    # 32-byte slot (28 bytes of service data). Decoding has to reach the value
    # and then stop on the padding, not mistake the value for padding.
    padded = HDR + encoded(0x02, "9CFF")
    padded += "FF" * (28 - len(padded) // 2)
    payloads.append(padded)

    layouts, frames = run_probe(exe, payloads)

    # --- V1: the table and the vectors cover each other ------------------------
    covered = {key for key, *_ in vectors}
    missing = sorted(set(table) - covered)
    extra = sorted(covered - set(table))
    verdict("V1 every mapped type has a vector and every vector a mapped type",
            not missing and not extra,
            f"{len(table)} types mapped, {len(covered)} covered"
            + (f", no vector for {missing}" if missing else "")
            + (f", vector without a mapping: {extra}" if extra else ""))

    # --- V2: the object ids agree ---------------------------------------------
    wrong_id = [f"{key}: table 0x{table[key][0]:02X} vs vector 0x{oid:02X}"
                for key, oid, *_ in vectors if key in table and table[key][0] != oid]
    verdict("V2 the object id in the table is the one the vector encodes",
            not wrong_id, "; ".join(wrong_id) or f"all {len(vectors)} vectors agree")

    # --- V3: the library knows every mapped id, as a measurement ---------------
    unknown = [f"{key} (0x{oid:02X})" for key, oid, *_ in vectors
               if oid not in layouts or layouts[oid]["kind"] != "Sensor"]
    verdict("V3 the pinned library knows every mapped id and treats it as a sensor",
            not unknown, "; ".join(unknown) or f"all {len(set(table))} ids known as Sensor")

    # --- V4: the vectors are as wide as the objects are ------------------------
    bad_width = [f"{key}: {len(b) // 2} bytes for a {layouts[oid]['width']}-byte object"
                 for key, oid, _, b, *_ in vectors
                 if oid in layouts and len(b) // 2 != layouts[oid]["width"]]
    verdict("V4 each vector carries exactly the object's value bytes",
            not bad_width, "; ".join(bad_width) or "widths match the library's layout")

    # --- V5: raw x factor is the expected value --------------------------------
    # An arithmetic check on the vector itself, independent of the decoder: it
    # keeps a wrong expectation from being blessed by a decoder that shares the
    # same mistake.
    bad_math = [f"{key}: {raw} x {layouts[oid]['factor']:.6g} != {value}"
                for key, oid, raw, _, value, _, _ in vectors
                if oid in layouts and not close(raw * layouts[oid]["factor"], value)]
    verdict("V5 the expected value is the raw integer times the library's factor",
            not bad_math, "; ".join(bad_math) or "arithmetic holds for every vector")

    # --- V6: the decoder produces the expected value ---------------------------
    bad_value = []
    for n, (key, oid, _, _, value, _, _) in enumerate(vectors, start=1):
        sensors = frames.get(n, {}).get("sensors", [])
        got = [v for i, _, v in sensors if i == oid]
        if len(got) != 1 or not close(got[0], value):
            bad_value.append(f"{key}: expected {value}, decoded {got or 'nothing'}")
    verdict("V6 every vector decodes to its expected physical value",
            not bad_value,
            "; ".join(bad_value) or f"{len(vectors)} vectors decoded, sign and scale intact")

    # --- V7: every payload ends cleanly ----------------------------------------
    bad_status = [f"{vectors[n - 1][0]}: {frames[n]['status']}"
                  for n in range(1, len(vectors) + 1)
                  if frames.get(n, {}).get("status", ("?",))[0] != "End"]
    verdict("V7 no vector leaves bytes over or trips the decoder",
            not bad_status, "; ".join(bad_status) or "all payloads reach End")

    # --- V8: accuracy matches the resolution -----------------------------------
    bad_acc = []
    for key, oid, _, _, _, _, dec in vectors:
        if oid not in layouts or key not in table:
            continue
        want = decimals_of(layouts[oid]["factor"])
        if table[key][3] != want:
            bad_acc.append(f"{key}: table shows {table[key][3]}, "
                           f"factor {layouts[oid]['factor']:.6g} resolves {want}")
        elif dec != want:
            bad_acc.append(f"{key}: vector expects {dec} decimals, factor resolves {want}")
    verdict("V8 accuracy_decimals matches what the scale factor resolves",
            not bad_acc, "; ".join(bad_acc) or "no type over- or understates its precision")

    # --- V9: signed types decode below zero ------------------------------------
    negatives = [(n, v) for n, v in enumerate(vectors, start=1) if v[2] < 0]
    lost_sign = sorted({v[0] for n, v in negatives
                        if not any(val < 0
                                   for _, _, val in frames.get(n, {}).get("sensors", []))})
    unsigned = sorted({v[0] for _, v in negatives
                       if not layouts.get(v[1], {}).get("signed", False)})
    verdict("V9 negative measurements keep their sign",
            not lost_sign and not unsigned,
            f"{len(negatives)} negative vectors on "
            f"{sorted({v[0] for _, v in negatives})}"
            + (f", sign lost on {lost_sign}" if lost_sign else "")
            + (f", library says unsigned: {unsigned}" if unsigned else ""))

    # --- V10: instances ---------------------------------------------------------
    inst = frames.get(len(vectors) + 1, {}).get("sensors", [])
    want_inst = [(0x02, 1, 23.45), (0x02, 2, -12.34)]
    ok_inst = (len(inst) == 2
               and all(i == wi and n == wn and close(v, wv)
                       for (i, n, v), (wi, wn, wv) in zip(inst, want_inst)))
    verdict("V10 a second object of the same id is instance 2, not a replacement",
            ok_inst, f"decoded {[(hex(i), n, round(v, 2)) for i, n, v in inst]}")

    # --- V11: padding -----------------------------------------------------------
    pad_frame = frames.get(len(vectors) + 2, {})
    pad_sensors = pad_frame.get("sensors", [])
    pad_status = pad_frame.get("status")
    ok_pad = (len(pad_sensors) == 1 and close(pad_sensors[0][2], -1.0)
              and pad_status == ("UnknownId", 0xFF))
    verdict("V11 a value ending in 0xFF survives the padding of a fixed slot",
            ok_pad,
            f"decoded {[(hex(i), n, v) for i, n, v in pad_sensors]}, stopped at {pad_status}"
            " (0xFF is not an object id, so this is the end of the data)")

    if not args.keep:
        shutil.rmtree(workdir, ignore_errors=True)

    print("\n--- summary ---")
    for name, ok, _ in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
