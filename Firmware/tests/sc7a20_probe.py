# Runs ON the RP2350 (MicroPython). Probes the SC7A20 over SPI0.
# Wiring: MOSI=GP19, MISO=GP20, SCK=GP22, CS=GP24 (manual).
from machine import Pin, SPI
import time

# SC7A20 / LIS2DH-compatible registers
WHO_AM_I  = 0x0F   # expect 0x11 (SC7A20) ; 0x33 would be LIS2DH/LIS3DH
CTRL_REG1 = 0x20
CTRL_REG4 = 0x23
OUT_X_L   = 0x28

spi = SPI(0, baudrate=1_000_000, polarity=1, phase=1,
          sck=Pin(22), mosi=Pin(19), miso=Pin(20))
cs = Pin(24, Pin.OUT, value=1)

def read(reg, n=1):
    cs(0)
    spi.write(bytes([reg | 0x80 | (0x40 if n > 1 else 0)]))  # bit7=read, bit6=auto-inc
    data = spi.read(n)
    cs(1)
    return data

def write(reg, val):
    cs(0)
    spi.write(bytes([reg & 0x3F, val]))
    cs(1)

who = read(WHO_AM_I)[0]
print("WHO_AM_I = 0x%02X" % who)
print("  -> SC7A20 (0x11) OK" if who == 0x11 else
      ("  -> LIS2DH/LIS3DH (0x33)" if who == 0x33 else "  -> UNEXPECTED (check wiring/CS/mode)"))

# Configure: 100 Hz, XYZ enabled, high-resolution, +/-2g, block data update
write(CTRL_REG1, 0x57)   # ODR=100Hz, normal, Z/Y/X enable
write(CTRL_REG4, 0x88)   # BDU=1, HR=1, FS=+/-2g
time.sleep_ms(50)
print("CTRL_REG1 = 0x%02X (want 0x57)" % read(CTRL_REG1)[0])
print("CTRL_REG4 = 0x%02X (want 0x88)" % read(CTRL_REG4)[0])

def read_g():
    b = read(OUT_X_L, 6)
    def axis(lo, hi):
        v = (b[hi] << 8) | b[lo]
        if v & 0x8000: v -= 65536
        return (v >> 4) * 0.001   # 12-bit, 1 mg/digit @ +/-2g HR
    return axis(0, 1), axis(2, 3), axis(4, 5)

print("Sampling 5 readings (g):")
for _ in range(5):
    x, y, z = read_g()
    print("  x=%+.3f  y=%+.3f  z=%+.3f  |a|=%.3f" % (x, y, z, (x*x+y*y+z*z) ** 0.5))
    time.sleep_ms(100)
print("PROBE_DONE")
