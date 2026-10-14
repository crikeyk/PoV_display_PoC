# Hold every LED cathode low so the CH572 can drive the anodes.
import board
import digitalio

cathodes = []
for i in range(16):
    pin = digitalio.DigitalInOut(getattr(board, "GP%d" % (18 - i)))
    pin.direction = digitalio.Direction.OUTPUT
    pin.value = False  # low = sink
    cathodes.append(pin)

while True:
    pass
