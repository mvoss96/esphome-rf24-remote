"""Send a real file over the air in one transfer and see what arrives.

The dongle takes the whole blob now (POST /api/send), cuts it into frames and
clocks them out without a serial round trip per frame - so this finally offers
the receiver line-rate traffic with *different* payloads, which a burst of
identical copies could not.
"""
import base64, json, sys, time, urllib.request
sys.path.insert(0, ".")
from upload import hub_counters, command

ADDR = "43:54:48:4D:45"

def send(path, rate, ack, size=32):
    data = open(path, "rb").read()
    cfg = (f"listen ch=90 rate={rate} crc=16 aw=5 pa=low "
           f"ack={1 if ack else 0} dpl={1 if ack else 0}"
           + ("" if ack else " plsize=32")
           + f" pipe1={ADDR.replace(':','')}")
    print(f"dongle: {command(cfg)['reply'][:70]}", flush=True)
    before = hub_counters()
    body = {"address": ADDR, "data": base64.b64encode(data).decode(),
            "size": size, "ack": ack}
    req = urllib.request.Request("http://127.0.0.1:8724/api/send",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    started = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        out = json.load(r)
    elapsed = time.time() - started
    time.sleep(2)
    after = hub_counters()
    got = after[0] - before[0]
    frames = (len(data) + size - 1) // size
    print(f"\nfile      : {len(data)} bytes in {frames} frames of {size}")
    print(f"transfer  : sent={out['sent']}/{out['of']}  means: {out['means']}")
    print(f"firmware  : {out['reply'].strip()}")
    print(f"receiver  : {got} frames = {100.0*got/max(frames,1):.1f}%   "
          f"FIFO full +{after[1]-before[1]}  missed irq +{after[3]-before[3]}")
    print(f"time      : {elapsed:.2f} s = {len(data)/elapsed/1024:.1f} kB/s "
          f"({len(data)*8/elapsed/1000:.0f} kbit/s payload)")
    return got, frames

if __name__ == "__main__":
    send(sys.argv[1], sys.argv[2], sys.argv[3] == "ack")
