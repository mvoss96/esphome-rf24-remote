"""Offer the receiver line-rate traffic for a sustained run and count what it took.

txtest takes the payload from flash, so the serial line is out of the path and
the frames really do go out back to back - 161 us apart at 2 Mbps, which is the
packet time. Anything the receiver does not take is its own limit.
"""
import re, sys, time
sys.path.insert(0, ".")
from upload import command, hub_counters

def run(count):
    before = hub_counters()
    reply = command(f"txtest 4354484D45 {count} noack size=32")["reply"]
    us_per = int(re.search(r"us_per=(\d+)", reply).group(1))
    us_total = int(re.search(r"us=(\d+)", reply).group(1))
    time.sleep(2)
    after = hub_counters()
    got = after[0] - before[0]
    offered = 1e6 / us_per
    taken = got / (us_total / 1e6)
    print(f"{count:>5} frames  angeboten {offered:6.0f}/s  "
          f"angekommen {got:>5} = {100.0*got/count:5.1f}%  "
          f"= {taken:6.0f}/s = {taken*32/1024:5.1f} kB/s   "
          f"fifo_full +{after[1]-before[1]}")
    return taken

if __name__ == "__main__":
    for n in (int(x) for x in sys.argv[1:] or [1000, 3000]):
        run(n)
