# PoV display

A hand-waved persistence-of-vision wand. A strip of 16 LEDs and an accelerometer draw a word or a picture in the air.

## What goes on the wand

`Firmware/device/` is the CircuitPython image for the RP2350 (Pico 2) wand. Copy the files inside that folder onto the `CIRCUITPY` drive. `code.py` there is version 7.

A Pico that has never been used needs CircuitPython first. Hold BOOTSEL while plugging it in so a drive named `RP2350` appears, copy `Firmware/circuitpython-pico2-10.3.1.uf2` onto it, then copy `Firmware/device/`.

`README.txt` inside that folder is the note for whoever changes the words.

## What does not go on the wand

`Firmware/debug/` records a swing and draws it in a browser. `Firmware/tests/` are early hardware checks. `Firmware/ch572/` is a different board.

## Older firmware

Version 6 was the last stable program before version 7 froze the pace for each pass. It is the git tag `v6`. In that tag the program is `Firmware/device_pull_v1/code.py`.

`AGENTS.md` is the longer note for a person or a coding agent picking this up.
