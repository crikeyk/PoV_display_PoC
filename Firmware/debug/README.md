# Debug tools

Nothing in this folder is copied onto a wand for normal use. The program a wand runs is `Firmware/device/`.

`capture_code.py` is a temporary replacement for `code.py`. Copy it onto `CIRCUITPY` only when you want a raw accelerometer recording, wave the wand, then put `Firmware/device/code.py` back.

`make_capture_html.py` reads that recording from a serial log and writes `capture/capture.csv` and `capture/view.html`. The files already in `capture/` are the 27 second recording from 14 Oct 2026.
