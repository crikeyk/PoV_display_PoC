#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyserial", "matplotlib"]
# ///
"""Host GUI for the RP2350 "rolling ball" demo.

Reads the CircuitPython USB-serial stream ("x,y,z,ball" lines emitted by
code.py) and shows the 16-LED strip with the lit ball, plus live X/Y/Z and the
roll-axis tilt. No mpremote / no board tooling needed - it just reads the
CircuitPython console serial port.

Run (uv handles deps):
    uv run tools/ball_gui.py
    uv run tools/ball_gui.py --port COM27
"""
import argparse
import sys
import threading
from collections import deque

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import matplotlib.patches as mpatches
import serial
import serial.tools.list_ports as list_ports

N = 16
CX, CY, CZ = "#1f77b4", "#ff7f0e", "#2ca02c"


def find_port(explicit=None):
    if explicit:
        return explicit
    for p in list_ports.comports():
        if "2E8A" in (p.hwid or "").upper():      # Raspberry Pi (CircuitPython CDC)
            return p.device
    raise SystemExit("No RP2350 (2E8A) serial port found. Pass --port COMxx.")


class Reader(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.lock = threading.Lock()
        self.latest = (0.0, 0.0, 0.0, 0)
        self.tilt = deque(maxlen=200)
        self._stop = False

    def run(self):
        s = serial.Serial(self.port, 115200, timeout=0.5)
        buf = b""
        while not self._stop:
            buf += s.read(256)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                parts = line.strip().split(b",")
                if len(parts) == 4:
                    try:
                        x, y, z = (float(p) for p in parts[:3])
                        ball = int(parts[3])
                    except ValueError:
                        continue
                    with self.lock:
                        self.latest = (x, y, z, ball)
        s.close()

    def stop(self):
        self._stop = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None)
    args = ap.parse_args()
    port = find_port(args.port)
    reader = Reader(port)
    reader.start()

    fig = plt.figure(figsize=(5, 8))
    fig.canvas.manager.set_window_title(f"Rolling ball - {port}")
    ax = fig.add_subplot(111)
    ax.set_xlim(-1, 1)
    ax.set_ylim(-1, N)
    ax.set_aspect("equal")
    ax.axis("off")

    circles = []
    for i in range(N):
        c = mpatches.Circle((0, i), 0.42, facecolor="#222", edgecolor="#555", lw=1)
        ax.add_patch(c)
        circles.append(c)
    ax.text(0, -0.9, "LED0 (bottom)", ha="center", va="top", fontsize=8, color="#888")
    ax.text(0, N - 0.1, "LED15 (top)", ha="center", va="bottom", fontsize=8, color="#888")
    title = ax.set_title("waiting for data...", fontsize=10)

    def update(_):
        with reader.lock:
            x, y, z, ball = reader.latest
        for i, c in enumerate(circles):
            if i == ball:
                c.set_facecolor("#ffd21e"); c.set_edgecolor("#ffd21e")
            else:
                c.set_facecolor("#222"); c.set_edgecolor("#555")
        title.set_text("X=%+.2f  Y=%+.2f  Z=%+.2f g\nball = LED %d" % (x, y, z, ball))
        return circles + [title]

    ani = FuncAnimation(fig, update, interval=33, blit=False, cache_frame_data=False)
    fig.canvas.mpl_connect("close_event", lambda e: reader.stop())
    try:
        plt.show()
    finally:
        reader.stop()


if __name__ == "__main__":
    main()
