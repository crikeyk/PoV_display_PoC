"""SC7A20 accelerometer driver for the RP2350 PoV board (CircuitPython).

Uses hardware SPI on GP19(MOSI)/GP20(MISO)/GP22(SCK) with CS on GP24. These
MOSI/SCK pins are shared with the 595s, which is harmless once Leds(method="gpio")
has forced the anodes high: the accel's clocking only re-latches the same all-high
595 frame. ALWAYS create Leds("gpio") BEFORE Accel() so the SPI pins are free.

SC7A20 is register-compatible with the ST LIS2DH (WHO_AM_I = 0x11).

Quick use:
    from accel import Accel
    acc = Accel()
    x, y, z = acc.xyz()      # acceleration in g
"""
import board
import busio
import digitalio

_WHO_AM_I = 0x0F
_CTRL1 = 0x20
_CTRL4 = 0x23
_OUT_X_L = 0x28


class Accel:
    def __init__(self):
        self._spi = busio.SPI(clock=board.GP22, MOSI=board.GP19, MISO=board.GP20)
        while not self._spi.try_lock():
            pass
        self._spi.configure(baudrate=1_000_000, polarity=1, phase=1)  # SPI mode 3
        self._cs = digitalio.DigitalInOut(board.GP24)
        self._cs.direction = digitalio.Direction.OUTPUT
        self._cs.value = True
        self._write(_CTRL1, 0x57)   # 100 Hz, X/Y/Z enabled, normal mode
        self._write(_CTRL4, 0x88)   # block-data-update, high-res, +/-2g

    def _write(self, reg, val):
        self._cs.value = False
        self._spi.write(bytes([reg & 0x3F, val]))
        self._cs.value = True

    def _read(self, reg, n):
        self._cs.value = False
        self._spi.write(bytes([reg | 0x80 | (0x40 if n > 1 else 0)]))  # read + auto-inc
        buf = bytearray(n)
        self._spi.readinto(buf)
        self._cs.value = True
        return buf

    def who_am_i(self):
        return self._read(_WHO_AM_I, 1)[0]

    def xyz(self):
        """Return (x, y, z) acceleration in g."""
        b = self._read(_OUT_X_L, 6)

        def axis(lo, hi):
            v = (b[hi] << 8) | b[lo]
            if v & 0x8000:
                v -= 65536
            return (v >> 4) * 0.001   # 12-bit, 1 mg/digit @ +/-2g high-res

        return axis(0, 1), axis(2, 3), axis(4, 5)
