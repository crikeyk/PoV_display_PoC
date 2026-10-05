# Runs ON the RP2350 (MicroPython) as main.py. RAW CALIBRATION SWEEP.
# Mirrors the (working) chase exactly: ONE write per step, value changes each
# step, NO zeros, NO rewrites -- just slowed to ~1.8 s so positions are readable.
# Sweeps bits 0..15. For each announced bit, report which physical LED is lit
# during that window (bottom LED = 0, top LED = 15). Also prints the previous
# bit so a one-write display lag (if any) can be decoded.
from machine import Pin
import time

sinks = [Pin(n, Pin.OUT, value=0) for n in range(3, 19)]
ser   = Pin(19, Pin.OUT, value=0)
srclk = Pin(22, Pin.OUT, value=0)
rclk  = Pin(25, Pin.OUT, value=0)

def write16(val):
    rclk(0)
    for i in range(15, -1, -1):
        srclk(0); ser((val >> i) & 1); srclk(1)
    rclk(1); rclk(0)

print("# RAW SWEEP: bits 0..15, one write each, no zeros/rewrites")
prev = -1
while True:
    for b in range(16):
        write16(1 << b)
        print("# wrote bit %d  (prev was %d) -> which physical LED is lit now?" % (b, prev))
        prev = b
        time.sleep_ms(1800)
