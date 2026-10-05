# Runs ON the RP2350 (MicroPython) as main.py.
# Two series 74HC595 driving 16 LEDs. Clean, abstracted driver + upward chase.
#
# Wiring: SER=GP19, SRCLK=GP22, RCLK/latch=GP25. Cathodes GPIO3..GPIO18 (LOW sink).
#
# IMPORTANT: this chain behaves as 17 shift stages, not 16 -- the first 595's
# QH' output register is an extra pipeline stage between the two chips. So we
# clock NBITS=17 bits per update; otherwise chip 2's last output never latches
# fresh data. With 17-bit shifting every output is directly addressable.
#
# Output layout (word bit -> hardware):
#   bits 0..7  -> chip 1 Q0..Q7
#   bit  8     -> phantom QH' stage (no LED)
#   bits 9..16 -> chip 2 Q0..Q7
#
# Physical LED map (your board):
#   LED0..7  = chip1 Q0..Q7      LED8..14 = chip2 Q1..Q7      LED15 = chip2 Q0 (top)
from machine import Pin
import time

sinks = [Pin(n, Pin.OUT, value=0) for n in range(3, 19)]   # cathode sinks LOW
ser   = Pin(19, Pin.OUT, value=0)
srclk = Pin(22, Pin.OUT, value=0)
rclk  = Pin(25, Pin.OUT, value=0)

NBITS = 17

# logical LED index (0 = bottom .. 15 = top) -> bit position in the 17-bit word.
#   LED0..7  -> chip1 Q0..Q7 = bits 0..7
#   LED8..14 -> chip2 Q1..Q7 = bits 10..16
#   LED15    -> chip2 Q0     = bit 9
LED_TO_BIT = [0, 1, 2, 3, 4, 5, 6, 7,          # LED0..7
              10, 11, 12, 13, 14, 15, 16,      # LED8..14
              9]                               # LED15 (top)

def set_leds(mask):
    """mask bit i (0=bottom..15=top) -> LED i on. Clocks the whole frame."""
    word = 0
    for i in range(16):
        if mask & (1 << i):
            word |= 1 << LED_TO_BIT[i]
    rclk(0)
    for b in range(NBITS - 1, -1, -1):
        srclk(0); ser((word >> b) & 1); srclk(1)
    rclk(1); rclk(0)

print("# upward chase (17-bit): LED0 bottom -> LED15 top, repeating")
while True:
    for i in range(16):
        set_leds(1 << i)
        time.sleep_ms(120)
