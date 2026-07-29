"""Checks the type tables against the bthome-cpp version the component pins, on
the host, without a radio.

What the component adds to BTHome is meaning: bthome-cpp knows that object 0x02
is two signed bytes scaled by 0.01, but not that this is a temperature in
degrees Celsius shown with two decimals, and it knows 0x21 is one byte without
knowing it is motion. Those mappings live in components/nrf24_bthome/sensor.py
and binary_sensor.py, and nothing in a normal build verifies them - a wrong
object id produces an entity that looks plausible and reads the wrong thing.

So this compiles a small host program against the pinned library, decodes the
shared test vectors with it, and holds the tables to the result:

  * every mapped id has a vector and every vector a mapped id,
  * no id is claimed by two keys,
  * the library knows each id, and knows it as the kind the table assumes,
  * the value bytes are as wide as the library says the object is,
  * the decoded value is the expected physical one, sign and scale included,
  * accuracy_decimals matches the resolution the scale factor allows,
  * ids sharing a key really are the same quantity at the same resolution,
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
from sensor_type_vectors import (  # noqa: E402
    BINARY_VECTORS,
    TEXT_VECTORS,
    all_vectors,
    encoded,
)

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


def parse_table(filename, variable):
    """A table from the component, read as data.

    Parsed rather than imported: those modules pull in esphome codegen and the
    sibling nrf24 component, which only resolve inside an esphome build. The
    names are resolved against esphome.const, so a constant that does not exist
    there fails here too.
    """
    from esphome import const

    tree = ast.parse((COMPONENT / filename).read_text(encoding="utf-8"))
    aliases = {}
    node = None
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign) or not hasattr(stmt.targets[0], "id"):
            continue
        name = stmt.targets[0].id
        if name == variable:
            node = stmt.value
        elif isinstance(stmt.value, (ast.Constant, ast.Name)):
            # Short local aliases (MEAS, TOTAL) so the table stays readable.
            aliases[name] = stmt.value

    if node is None:
        raise SystemExit(f"{variable} not found in {filename}")

    def resolve(expr):
        if isinstance(expr, ast.Constant):
            return expr.value
        if isinstance(expr, ast.Name):
            if expr.id in aliases:
                return resolve(aliases[expr.id])
            if not hasattr(const, expr.id):
                raise SystemExit(f"{expr.id} is not a constant in esphome.const")
            return getattr(const, expr.id)
        if isinstance(expr, ast.Tuple):
            return tuple(resolve(e) for e in expr.elts)
        raise SystemExit(f"unsupported expression in {variable}: {ast.dump(expr)}")

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
            frame = frames.setdefault(
                int(parts[1]),
                {"sensors": [], "binaries": [], "bytes": [], "status": None})
            if parts[2] == "SENSOR":
                frame["sensors"].append(
                    (int(parts[3], 16), int(parts[4]), float(parts[5])))
            elif parts[2] == "BINARY":
                frame["binaries"].append(
                    (int(parts[3], 16), int(parts[4]), parts[5] == "1"))
            elif parts[2] == "BYTES":
                frame["bytes"].append(
                    (int(parts[3], 16), int(parts[4]), "" if parts[5] == "-" else parts[5]))
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
    sensors = parse_table("sensor.py", "SENSOR_TYPES")
    binaries = parse_table("binary_sensor.py", "BINARY_TYPES")
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
    first_binary = len(payloads) + 1
    payloads += [HDR + encoded(oid, b) for _, oid, b, _ in BINARY_VECTORS]
    first_text = len(payloads) + 1
    payloads += [HDR + encoded(oid, b) for _, oid, b, _ in TEXT_VECTORS]
    # Two objects of one id in one payload: the second must be instance 2 rather
    # than overwrite the first.
    instance_frame = len(payloads) + 1
    payloads.append(HDR + encoded(0x02, "2909") + encoded(0x02, "2EFB"))
    # A measurement whose last byte is 0xFF, followed by the padding of a
    # 32-byte slot (28 bytes of service data). Decoding has to reach the value
    # and then stop on the padding, not mistake the value for padding.
    # A frame filled to capacity: twelve single-byte objects are the most the 25
    # bytes a 32-byte slot leaves after the sender id and the header can hold.
    # The instance counter is a fixed array, and an id past its end is never
    # recorded - so the last id is sent twice, and an undersized array answers
    # instance 1 for both. Distinct ids alone would not show it: instance 1 is
    # the right answer for those either way, which is why this frame repeats one.
    full_frame = len(payloads) + 1
    FULL_IDS = [0x01, 0x09, 0x0F, 0x21, 0x2E, 0x2F, 0x46, 0x57, 0x58, 0x60, 0x64, 0x64]
    payloads.append(HDR + "".join(encoded(oid, "01") for oid in FULL_IDS))

    padded_frame = len(payloads) + 1
    padded = HDR + encoded(0x02, "9CFF")
    padded += "FF" * (28 - len(padded) // 2)
    payloads.append(padded)

    layouts, frames = run_probe(exe, payloads)

    sensor_ids = {oid: key for key, entry in sensors.items() for oid in entry[0]}
    binary_ids = {oid: key for key, (oid, _) in binaries.items()}

    # --- V1: the tables and the vectors cover each other -----------------------
    covered = {oid for _, oid, *_ in vectors}
    missing = sorted(f"0x{o:02X} ({sensor_ids[o]})" for o in set(sensor_ids) - covered)
    extra = sorted(f"0x{o:02X}" for o in covered - set(sensor_ids))
    verdict("V1 every mapped measurement id has a vector and every vector an id",
            not missing and not extra,
            f"{len(sensors)} keys over {len(sensor_ids)} ids, {len(covered)} covered"
            + (f", no vector for {missing}" if missing else "")
            + (f", vector without a mapping: {extra}" if extra else ""))

    # --- V2: nothing is claimed twice -----------------------------------------
    # Two keys on one id would publish one object onto two entities, and only
    # one of them can carry the right unit.
    seen, twice = {}, []
    for key, entry in sensors.items():
        for oid in entry[0]:
            if oid in seen:
                twice.append(f"0x{oid:02X}: {seen[oid]} and {key}")
            seen[oid] = key
    for key, (oid, _) in binaries.items():
        if oid in seen:
            twice.append(f"0x{oid:02X}: {seen[oid]} and {key}")
        seen[oid] = key
    for key, oid in parse_table("text_sensor.py", "TEXT_TYPES").items():
        if oid in seen:
            twice.append(f"0x{oid:02X}: {seen[oid]} and {key}")
        seen[oid] = key
    verdict("V2 no object id is claimed by two keys",
            not twice, "; ".join(twice) or f"{len(seen)} ids, each mapped once")

    # --- V3: the library knows every mapped id, as the kind assumed ------------
    wrong_kind = [f"{sensor_ids[o]} (0x{o:02X}): {layouts.get(o, {}).get('kind', 'unknown')}"
                  for o in sorted(sensor_ids)
                  if layouts.get(o, {}).get("kind") != "Sensor"]
    wrong_kind += [f"{binary_ids[o]} (0x{o:02X}): {layouts.get(o, {}).get('kind', 'unknown')}"
                   for o in sorted(binary_ids)
                   if layouts.get(o, {}).get("kind") != "Binary"]
    verdict("V3 the pinned library knows every mapped id and agrees on its kind",
            not wrong_kind,
            "; ".join(wrong_kind)
            or f"{len(sensor_ids)} measurements, {len(binary_ids)} binaries")

    # --- V4: the vectors are as wide as the objects are ------------------------
    bad_width = [f"{key} 0x{oid:02X}: {len(b) // 2} bytes for a "
                 f"{layouts[oid]['width']}-byte object"
                 for key, oid, _, b, *_ in vectors
                 if oid in layouts and len(b) // 2 != layouts[oid]["width"]]
    verdict("V4 each vector carries exactly the object's value bytes",
            not bad_width, "; ".join(bad_width) or "widths match the library's layout")

    # --- V5: raw x factor is the expected value --------------------------------
    # An arithmetic check on the vector itself, independent of the decoder: it
    # keeps a wrong expectation from being blessed by a decoder that shares the
    # same mistake.
    bad_math = [f"{key} 0x{oid:02X}: {raw} x {layouts[oid]['factor']:.6g} != {value}"
                for key, oid, raw, _, value, _, _ in vectors
                if oid in layouts and not close(raw * layouts[oid]["factor"], value)]
    verdict("V5 the expected value is the raw integer times the library's factor",
            not bad_math, "; ".join(bad_math) or "arithmetic holds for every vector")

    # --- V6: the decoder produces the expected value ---------------------------
    bad_value = []
    for n, (key, oid, _, _, value, _, _) in enumerate(vectors, start=1):
        got = [v for i, _, v in frames.get(n, {}).get("sensors", []) if i == oid]
        if len(got) != 1 or not close(got[0], value):
            bad_value.append(f"{key} 0x{oid:02X}: expected {value}, decoded {got or 'nothing'}")
    verdict("V6 every vector decodes to its expected physical value",
            not bad_value,
            "; ".join(bad_value) or f"{len(vectors)} vectors decoded, sign and scale intact")

    # --- V7: every payload ends cleanly ----------------------------------------
    # Every payload but the padded one, which stops on the padding by design.
    bad_status = [f"{payloads[n - 1]}: {frames[n]['status']}"
                  for n in range(1, padded_frame)
                  if frames.get(n, {}).get("status", ("?",))[0] != "End"]
    verdict("V7 no vector leaves bytes over or trips the decoder",
            not bad_status, "; ".join(bad_status) or "all payloads reach End")

    # --- V8: accuracy matches the resolution -----------------------------------
    bad_acc = []
    for key, entry in sensors.items():
        factors = {layouts[o]["factor"] for o in entry[0] if o in layouts}
        if len(factors) != 1:
            continue  # V9's business
        want = decimals_of(factors.pop())
        if entry[3] != want:
            bad_acc.append(f"{key}: table shows {entry[3]}, the factor resolves {want}")
    for key, oid, _, _, _, _, dec in vectors:
        if oid in sensor_ids and dec != sensors[sensor_ids[oid]][3]:
            bad_acc.append(f"{key} 0x{oid:02X}: vector expects {dec} decimals, "
                           f"table shows {sensors[sensor_ids[oid]][3]}")
    verdict("V8 accuracy_decimals matches what the scale factor resolves",
            not bad_acc, "; ".join(bad_acc) or "no type over- or understates its precision")

    # --- V9: ids sharing a key are the same quantity ---------------------------
    # The rule for folding several ids onto one entity: they may differ in width
    # or sign, never in resolution. One entity cannot carry two accuracies, so a
    # key over two factors would show a precision that depends on which id
    # happened to arrive.
    mixed = []
    for key, entry in sensors.items():
        if len(entry[0]) < 2:
            continue
        factors = {f"{layouts[o]['factor']:.6g}" for o in entry[0] if o in layouts}
        if len(factors) != 1:
            mixed.append(f"{key}: factors {sorted(factors)}")
    merged = {k: v[0] for k, v in sensors.items() if len(v[0]) > 1}
    verdict("V9 ids folded onto one key differ in width or sign only",
            not mixed,
            "; ".join(mixed) or
            ", ".join(f"{k} ({len(ids)} ids)" for k, ids in sorted(merged.items())))

    # --- V10: negative measurements keep their sign ----------------------------
    negatives = [(n, v) for n, v in enumerate(vectors, start=1) if v[2] < 0]
    lost_sign = sorted({f"{v[0]} 0x{v[1]:02X}" for n, v in negatives
                        if not any(val < 0
                                   for _, _, val in frames.get(n, {}).get("sensors", []))})
    unsigned = sorted({f"{v[0]} 0x{v[1]:02X}" for _, v in negatives
                       if not layouts.get(v[1], {}).get("signed", False)})
    verdict("V10 negative measurements keep their sign",
            not lost_sign and not unsigned,
            f"{len(negatives)} negative vectors"
            + (f", sign lost on {lost_sign}" if lost_sign else "")
            + (f", library says unsigned: {unsigned}" if unsigned else ""))

    # --- V11: the binary objects ------------------------------------------------
    bad_binary = []
    for offset, (key, oid, _, state) in enumerate(BINARY_VECTORS):
        got = [s for i, _, s in frames.get(first_binary + offset, {}).get("binaries", [])
               if i == oid]
        if got != [state]:
            bad_binary.append(f"{key} 0x{oid:02X}: expected {state}, decoded {got or 'nothing'}")
    covered_bin = {oid for _, oid, _, _ in BINARY_VECTORS}
    no_vector = sorted(f"0x{o:02X} ({binary_ids[o]})" for o in set(binary_ids) - covered_bin)
    verdict("V11 every binary object decodes to the state it was sent as",
            not bad_binary and not no_vector,
            "; ".join(bad_binary + no_vector)
            or f"{len(binaries)} binary types, {len(BINARY_VECTORS)} vectors, both states seen")

    # --- V11b: text and raw -----------------------------------------------------
    # Both are [length][bytes], so what a vector proves is that the announced
    # length is honoured and that the bytes arrive unaltered - a raw value with a
    # zero in the middle is where reading it as a string goes wrong.
    texts = parse_table("text_sensor.py", "TEXT_TYPES")
    bad_text = []
    for offset, (key, oid, _, shown) in enumerate(TEXT_VECTORS):
        got = [b for i, _, b in frames.get(first_text + offset, {}).get("bytes", [])
               if i == oid]
        want = shown.encode().hex().upper() if key == "text" else shown
        if got != [want]:
            bad_text.append(f"{key} 0x{oid:02X}: expected {want}, decoded {got or 'nothing'}")
    wrong_map = [f"{k}: table 0x{v:02X}" for k, v in texts.items()
                 if layouts.get(v, {}).get("kind") != ("Text" if k == "text" else "Raw")]
    verdict("V11b text and raw arrive with their bytes intact",
            not bad_text and not wrong_map,
            "; ".join(bad_text + wrong_map)
            or f"{len(TEXT_VECTORS)} vectors over {sorted(texts)}")

    # --- V12: instances ---------------------------------------------------------
    inst = frames.get(instance_frame, {}).get("sensors", [])
    want_inst = [(0x02, 1, 23.45), (0x02, 2, -12.34)]
    ok_inst = (len(inst) == 2
               and all(i == wi and n == wn and close(v, wv)
                       for (i, n, v), (wi, wn, wv) in zip(inst, want_inst)))
    verdict("V12 a second object of the same id is instance 2, not a replacement",
            ok_inst, f"decoded {[(hex(i), n, round(v, 2)) for i, n, v in inst]}")

    # --- V12b: a frame filled with distinct objects -----------------------------
    full = frames.get(full_frame, {})
    got_ids = [(i, n) for i, n, _ in full.get("sensors", []) + full.get("binaries", [])]
    want_ids = [(oid, 1 + FULL_IDS[:i].count(oid)) for i, oid in enumerate(FULL_IDS)]
    ok_full = (sorted(got_ids) == sorted(want_ids)
               and full.get("status", ("?",))[0] == "End")
    repeated = [n for i, n in got_ids if i == FULL_IDS[-1]]
    verdict("V12b every object of a frame filled to capacity is counted",
            ok_full,
            f"{len(got_ids)}/{len(FULL_IDS)} objects, the repeated id came out as "
            f"{sorted(repeated)} (expected [1, 2]), {full.get('status')}")

    # --- V13: padding -----------------------------------------------------------
    pad_frame = frames.get(padded_frame, {})
    pad_sensors = pad_frame.get("sensors", [])
    pad_status = pad_frame.get("status")
    ok_pad = (len(pad_sensors) == 1 and close(pad_sensors[0][2], -1.0)
              and pad_status == ("UnknownId", 0xFF))
    verdict("V13 a value ending in 0xFF survives the padding of a fixed slot",
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
