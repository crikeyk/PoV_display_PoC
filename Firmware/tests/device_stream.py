# Runs ON the RP2350 (MicroPython). Streams SC7A20 accel data as CSV over USB.
# Launched by the host GUI via: mpremote run device_stream.py
# Output format (one line per sample):  x,y,z   (units: g)
# Wiring: MOSI=GP19, MISO=GP20, SCK=GP22, CS=GP24 (manual).
from machine import Pin, SPI
import time

WHO_AM_I, CTRL_REG1, CTRL_REG4, OUT_X_L = 0x0F, 0x20, 0x23, 0x28
RATE_HZ = 50

spi = SPI(0, baudrate=1_000_000, polarity=1, phase=1,
          sck=Pin(22), mosi=Pin(19), miso=Pin(20))
cs = Pin(24, Pin.OUT, value=1)

def read(reg, n=1):
    cs(0)
    spi.write(bytes([reg | 0x80 | (0x40 if n > 1 else 0)]))
    data = spi.read(n)
    cs(1)
    return data

def write(reg, val):
    cs(0); spi.write(bytes([reg & 0x3F, val])); cs(1)

who = read(WHO_AM_I)[0]
write(CTRL_REG1, 0x57)   # 100 Hz, XYZ, normal
write(CTRL_REG4, 0x88)   # BDU, high-res, +/-2g
time.sleep_ms(50)

# Banner line the host can key off (starts with '#')
print("# SC7A20 stream  who=0x%02X  rate=%dHz  fmt=x,y,z(g)" % (who, RATE_HZ))

period = 1000 // RATE_HZ
try:
    while True:
        b = read(OUT_X_L, 6)
        def axis(lo, hi):
            v = (b[hi] << 8) | b[lo]
            if v & 0x8000: v -= 65536
            return (v >> 4) * 0.001
        x, y, z = axis(0, 1), axis(2, 3), axis(4, 5)
        print("%.4f,%.4f,%.4f" % (x, y, z))
        time.sleep_ms(period)
except KeyboardInterrupt:
    print("# stream stopped")
