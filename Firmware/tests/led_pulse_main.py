# Runs ON the RP2350 (MicroPython), intended to be installed as main.py so it
# runs standalone (survives USB unplug) for multimeter probing.
#
# LED anodes  : 74HC595 outputs Q0..Q15  (SER=GP19/MOSI, SRCLK=GP22/SCK, RCLK=GP25)
# LED cathodes: GPIO3..GPIO18, driven LOW so each pin acts as a current sink.
#
# Behaviour: hold all 16 cathodes low, then pulse all 16 anodes ON/OFF at 1 Hz.
from machine import Pin, SPI
import time

# Cathodes on GPIO3..GPIO18 (16 pins) -> OUTPUT LOW = current sink
SINK_PINS = list(range(3, 19))          # 3,4,...,18 inclusive
sinks = [Pin(n, Pin.OUT, value=0) for n in SINK_PINS]

# 74HC595 chain on SPI0 (mode 0), latch on GP25
spi = SPI(0, baudrate=1_000_000, polarity=0, phase=0,
          sck=Pin(22), mosi=Pin(19), miso=Pin(20))
latch = Pin(25, Pin.OUT, value=0)

def write16(val):
    latch(0)
    spi.write(bytes([(val >> 8) & 0xFF, val & 0xFF]))
    latch(1)            # rising edge latches shift register -> outputs
    latch(0)

print("# GPIO3-18 held LOW as current sinks; pulsing all 16 LEDs at 1 Hz")
print("# cathode pins:", SINK_PINS)

state = 0
try:
    while True:
        state ^= 1
        write16(0xFFFF if state else 0x0000)
        print("# LEDs", "ON " if state else "OFF")
        time.sleep_ms(500)      # 500 ms on + 500 ms off = 1 Hz
except KeyboardInterrupt:
    write16(0x0000)
    print("# stopped, LEDs off")
