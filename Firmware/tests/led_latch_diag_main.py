# Runs ON the RP2350 (MicroPython) as main.py. LATCH LOCALIZATION TEST.
# Holds single bits steadily (continuous rewrite) to see which chip latches a
# STABLE output. Chip A bits (0..7) vs chip-B-region bits (8..15).
#   If chip A bits show a steady LED but chip-B bits stay dark, chip B's RCLK
#   (storage latch, pin 12) is not wired to the latch line (GP25).
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

# (bit, human label)
TESTS = [(3,  "chip A  bit3  -> expect steady LED3"),
         (5,  "chip A  bit5  -> expect steady LED5"),
         (11, "chip B? bit11 -> steady LED? or dark?"),
         (14, "chip B? bit14 -> steady LED? or dark?")]

print("# LATCH TEST: each pattern HELD 3s. Report which show a STEADY lit LED.")
while True:
    for bit, label in TESTS:
        print("#", label)
        t_end = time.ticks_add(time.ticks_ms(), 3000)
        while time.ticks_diff(t_end, time.ticks_ms()) > 0:
            write16(1 << bit)
            time.sleep_ms(30)
    print("# --- loop ---")
