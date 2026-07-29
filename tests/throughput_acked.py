import re, sys, time
sys.path.insert(0, ".")
from upload import command, hub_counters

print(command("listen ch=90 rate=2000 crc=16 aw=5 pa=low ack=1 dpl=1 "
              "pipe1=4354484D45")["reply"][:55])
before = hub_counters()
reply = command("txtest 4354484D45 3000 ack size=32")["reply"]
print("firmware  :", reply)
time.sleep(2)
after = hub_counters()
got = after[0] - before[0]
us_per = int(re.search(r"us_per=(\d+)", reply).group(1))
us_total = int(re.search(r"\bus=(\d+)", reply).group(1))
print(f"empfaenger: {got}/3000 = {100.0*got/3000:.1f}%   fifo_full +{after[1]-before[1]}")
print(f"angeboten : {1e6/us_per:.0f} Frames/s")
print(f"geliefert : {got/(us_total/1e6):.0f} Frames/s = {got/(us_total/1e6)*32/1024:.1f} kB/s")
