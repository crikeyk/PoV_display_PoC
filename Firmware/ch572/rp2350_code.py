# Common-sink helper for the CH572 bring-up.
# Holds every LED cathode low and does not touch the SPI pins, so the
# CH572 can drive the 74HC595 anodes and the accelerometer.
import board
import digitalio

sinks = []
for n in range(3, 19):          # GP3 = LED15 ... GP18 = LED0
    pin = digitalio.DigitalInOut(getattr(board, "GP%d" % n))
    pin.direction = digitalio.Direction.OUTPUT
    pin.value = False           # LOW = cathode sink
    sinks.append(pin)

while True:
    pass
