"""Send a file over the air in 32-byte frames and see how much of it arrives.

The dongle transmits sixteen frames back to back with no gap, which is line rate
for as long as the burst lasts - at 2 Mbps that is 165 microseconds per frame,
and the receiver's FIFO holds three. So each burst asks the same question: can
the receiver keep up while the air is saturated?

Counted at the receiver rather than inferred: the hub's own frame counter, read
out of dump_config before and after.

    python upload.py <rate> [kilobytes]
"""
import json
import re
import subprocess
import threading
import sys
import time
import urllib.request

DONGLE = "http://127.0.0.1:8724"
HUB_YAML = r"C:\Repos\libs\esphome-rf24-remote\tests\throughput.yaml"
HUB_IP = "192.168.2.70"
ADDR = "4354484D45"  # CTHME


def command(line, wait=True):
    req = urllib.request.Request(
        DONGLE + "/api/command",
        data=json.dumps({"line": line, "wait": wait}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def hub_counters():
    """Frames, FIFO-full and missed interrupts, straight from the receiver.

    `esphome logs` streams and never returns, so the config dump it replays on
    connect is read line by line and the process stopped as soon as the counters
    have gone past.
    """
    proc = subprocess.Popen(
        ["esphome", "logs", HUB_YAML, "--device", HUB_IP],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1)
    # A timer, not a check inside the read loop: reading blocks, so a deadline
    # tested per line is never reached when no line comes.
    threading.Timer(40, proc.terminate).start()
    deadline = time.time() + 40
    try:
        for line in proc.stdout:
            m = re.search(r"Frames: (\d+) .*?FIFO full: (\d+), watchdog: (\d+), "
                          r"missed interrupts: (\d+)", line)
            if m:
                return tuple(int(g) for g in m.groups())
            if time.time() > deadline:
                return None
    finally:
        proc.terminate()
    return None


def main():
    rate = sys.argv[1] if len(sys.argv) > 1 else "250"
    kilobytes = int(sys.argv[2]) if len(sys.argv) > 2 else 32

    frames = kilobytes * 1024 // 32
    bursts = frames // 16

    print(f"configuring the dongle for {rate} kbps ...", flush=True)
    reply = command(f"listen ch=90 rate={rate} crc=16 aw=5 pa=low ack=0 dpl=0 "
                    f"plsize=32 pipe1={ADDR}")
    if not reply.get("ok"):
        sys.exit(f"dongle refused: {reply}")

    before = hub_counters()
    if before is None:
        sys.exit("could not read the receiver's counters")
    print(f"receiver before: frames={before[0]} fifo_full={before[1]} missed_irq={before[3]}",
          flush=True)

    # A recognisable payload rather than filler: every frame carries its own
    # number, so a capture can be read by eye and a gap named.
    print(f"sending {frames} frames = {kilobytes} kB in {bursts} bursts of 16 ...", flush=True)
    sent = 0
    started = time.time()
    for n in range(bursts):
        body = (f"{n:04X}" + "".join(f"{(n + i) & 0xFF:02X}" for i in range(30)))
        reply = command(f"tx {ADDR} {body} noack x16 gap=0")
        if reply.get("ok"):
            sent += 16
        else:
            print(f"  burst {n} refused: {reply.get('reply')}", flush=True)
    elapsed = time.time() - started

    time.sleep(2)
    after = hub_counters()
    got = after[0] - before[0]
    print()
    print(f"sent      : {sent} frames ({sent * 32 / 1024:.1f} kB)")
    print(f"received  : {got} frames ({got * 32 / 1024:.1f} kB)  "
          f"= {100.0 * got / max(sent, 1):.1f}%")
    print(f"FIFO full : +{after[1] - before[1]}   missed interrupts: +{after[3] - before[3]}")
    print(f"wall clock: {elapsed:.1f} s including the HTTP round trips "
          f"({sent * 32 / elapsed / 1024:.1f} kB/s end to end)")


if __name__ == "__main__":
    main()
