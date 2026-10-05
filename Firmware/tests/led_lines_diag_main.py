# Runs ON the RP2350 (MicroPython) as main.py. 74HC595 line-level diagnostic.
# Drives the three control lines as plain GPIO square waves at 1 Hz so each can
# be probed with a multimeter AT THE 595 INPUT PINS to find a broken connection.
#   GP19 -> SER   (595 pin 14, data in)
#   GP22 -> SRCLK (595 pin 11, shift clock)
#   GP25 -> RCLK  (595 pin 12, latch)
# Each should swing 0 <-> ~3.3 V at 1 Hz. If it swings at the RP2350 pad but not
# at the 595 pin, that trace/joint is open.
#
# Also holds GPIO3..GPIO18 LOW (LED cathode sinks), unchanged.
from machine import Pin
import time

sinks = [Pin(n, Pin.OUT, value=0) for n in range(3, 19)]

ser   = Pin(19, Pin.OUT, value=0)   # 595 SER   (pin 14)
srclk = Pin(22, Pin.OUT, value=0)   # 595 SRCLK (pin 11)
rclk  = Pin(25, Pin.OUT, value=0)   # 595 RCLK  (pin 12)

print("# LINE DIAG: GP19(SER)/GP22(SRCLK)/GP25(RCLK) square-waving at 1 Hz")
print("# probe each at the 595 input pin - expect 0 <-> 3.3 V")

level = 0
try:
    while True:
        level ^= 1
        ser(level); srclk(level); rclk(level)
        print("# lines", "HIGH (3.3V)" if level else "LOW  (0V) ")
        time.sleep_ms(500)
except KeyboardInterrupt:
    ser(0); srclk(0); rclk(0)
    print("# stopped")
