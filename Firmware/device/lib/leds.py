"""16-LED strip driver for the RP2350 PoV board (CircuitPython).

Two interchangeable methods, SAME API (show / set / clear). LEDs are addressed
by logical index 0 = bottom .. 15 = top.

  method="gpio"  (DEFAULT, works today, accel-compatible)
      The two 74HC595 outputs (anodes) are forced permanently HIGH, and each LED
      is switched by its own cathode GPIO:  LED i  ->  GP(18 - i).
      (LED0=GP18 ... LED15=GP3). After forcing the anodes high the shift-register
      data/latch pins are released, so the accelerometer can use the SPI bus.

  method="shift" (for AFTER the PCB fix / standalone LED use; NOT accel-compatible)
      Cathodes are held LOW (common sink) and the 595s drive the anodes.
      Uses the current (pre-fix) wiring: SER=GP19, SHCP/shift=GP25, STCP/latch=GP22.
      NOTE: after you swap SHCP<->STCP on the PCB, change _SHCP_GP/_STCP_GP below
      to 22/25 and you can switch this to hardware SPI.

Quick use:
    from leds import Leds
    leds = Leds()            # gpio method
    leds.show(0b0000000000000001)   # bit i -> LED i
    leds.set(5, True)
    leds.clear()
"""
import board
import digitalio

_OUT = digitalio.Direction.OUTPUT

# LED i cathode is on GP(18 - i):  LED0->GP18, LED1->GP17, ... LED15->GP3
_CATHODE_GP = tuple(18 - i for i in range(16))

# 595 control pins (current wiring)
_SER_GP, _SHCP_GP, _STCP_GP = 19, 25, 22

# logical LED i -> shift stage (reg1 Q0..7 = stage0..7; reg2 Q0 = stage8; reg2 Q1..7 = stage9..15)
_LED_TO_STAGE = (0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 8)


def _out(gp, value):
    d = digitalio.DigitalInOut(getattr(board, "GP%d" % gp))
    d.direction = _OUT
    d.value = value
    return d


class Leds:
    def __init__(self, method="gpio"):
        self.method = method
        self._state = 0
        if method == "gpio":
            self._init_gpio()
        else:
            self._init_shift()
        self.clear()

    # ---------- gpio method (default; frees SPI bus for the accel) ----------
    def _init_gpio(self):
        ser = _out(_SER_GP, False)
        shcp = _out(_SHCP_GP, False)
        stcp = _out(_STCP_GP, False)
        ser.value = True                      # shift in sixteen 1s -> all anodes high
        for _ in range(16):
            shcp.value = False
            shcp.value = True
        stcp.value = True                     # latch all-high
        stcp.value = False
        ser.deinit()
        stcp.deinit()                         # release GP19/GP22 for the accel SPI bus
        self._shcp = shcp                     # keep GP25 owned + LOW so nothing shifts
        self._cath = [_out(_CATHODE_GP[i], True) for i in range(16)]  # True = off

    def _show_gpio(self, mask):
        for i in range(16):
            self._cath[i].value = not bool(mask & (1 << i))   # LOW = LED on

    # ---------- shift method (standalone LED use / after PCB fix) ----------
    def _init_shift(self):
        self._cath = [_out(_CATHODE_GP[i], False) for i in range(16)]  # all sinks LOW
        self._ser = _out(_SER_GP, False)
        self._shcp = _out(_SHCP_GP, False)
        self._stcp = _out(_STCP_GP, False)

    def _show_shift(self, mask):
        stage_bits = 0
        for i in range(16):
            if mask & (1 << i):
                stage_bits |= 1 << _LED_TO_STAGE[i]
        self._stcp.value = False
        for s in range(15, -1, -1):
            self._shcp.value = False
            self._ser.value = bool((stage_bits >> s) & 1)
            self._shcp.value = True
        self._stcp.value = True
        self._stcp.value = False

    # ---------- public API (identical for both methods) ----------
    def show(self, mask):
        """Light LEDs from a 16-bit mask: bit i -> LED i (0=bottom, 15=top)."""
        self._state = mask & 0xFFFF
        if self.method == "gpio":
            self._show_gpio(self._state)
        else:
            self._show_shift(self._state)

    def set(self, i, on=True):
        """Turn a single LED on/off, keeping the others."""
        if on:
            self._state |= (1 << i)
        else:
            self._state &= ~(1 << i)
        self.show(self._state)

    def clear(self):
        """All LEDs off."""
        self.show(0)
