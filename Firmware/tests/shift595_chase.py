# Runs ON the RP2350 (MicroPython). LED test for two daisy-chained 74HC595.
# Wiring: SER=MOSI/GP19, SRCLK=SCK/GP22, RCLK(latch)=GP25. 16 LEDs on Q0..Q15.
# Shares SPI0 with the SC7A20 (accel CS/GP24 stays high, so it's undisturbed).
from machine import Pin, SPI
import time

spi = SPI(0, baudrate=1_000_000, polarity=0, phase=0,   # mode 0 for 74HC595
          sck=Pin(22), mosi=Pin(19), miso=Pin(20))
latch = Pin(25, Pin.OUT, value=0)

def write16(val):
    # Send high byte first; it ends up in the far register of the chain.
    latch(0)
    spi.write(bytes([(val >> 8) & 0xFF, val & 0xFF]))
    latch(1)      # rising edge latches shift reg -> outputs
    latch(0)

def clear():
    write16(0x0000)

print("# 595 LED test start (16 outputs)")

# 1) Single-LED forward chase, a couple of passes
for _pass in range(2):
    for i in range(16):
        write16(1 << i)
        time.sleep_ms(60)
print("# forward chase done")

# 2) Reverse chase
for i in range(15, -1, -1):
    write16(1 << i)
    time.sleep_ms(60)
print("# reverse chase done")

# 3) Progressive fill then drain
for i in range(16):
    write16((1 << (i + 1)) - 1)   # 0x1,0x3,0x7,... all-on
    time.sleep_ms(50)
for i in range(16, -1, -1):
    write16((1 << i) - 1)
    time.sleep_ms(50)
print("# fill/drain done")

# 4) All-on / all-off blink (confirms every LED lights)
for _ in range(4):
    write16(0xFFFF); time.sleep_ms(180)
    write16(0x0000); time.sleep_ms(180)
print("# blink done")

clear()
print("# 595 LED test complete, outputs cleared")
