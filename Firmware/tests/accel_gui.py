#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "mpremote",
#   "pyserial",
#   "matplotlib",
#   "numpy",
# ]
# ///
"""Real-time SC7A20 accelerometer GUI (host side).

Launches tools/device_stream.py on the RP2350 via mpremote, reads the CSV
stream over USB serial, and shows X/Y/Z (g) live: a scrolling plot, a bar
readout, and a 3D orientation cube driven by the measured gravity vector.
Nothing is permanently installed on the board.

Easiest way to run (no venv setup needed, uv handles deps):
    uv run tools/accel_gui.py
    uv run tools/accel_gui.py --port COM26 --seconds 10

Or with an existing Python that has mpremote+pyserial+matplotlib+numpy:
    python tools/accel_gui.py
"""
import argparse
import math
import os
import subprocess
import sys
import threading
from collections import deque

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import serial.tools.list_ports as list_ports

RP2_VIDPID = "2E8A:0005"           # Raspberry Pi, MicroPython USB CDC
RATE_HZ = 50
HERE = os.path.dirname(os.path.abspath(__file__))
DEVICE_SCRIPT = os.path.join(HERE, "device_stream.py")

# colorblind-safe triad
CX, CY, CZ = "#1f77b4", "#ff7f0e", "#2ca02c"


def find_port(explicit=None):
    if explicit:
        return explicit
    for p in list_ports.comports():
        if RP2_VIDPID in (p.hwid or "").upper():
            return p.device
    raise SystemExit(f"No RP2350 ({RP2_VIDPID}) serial port found. Pass --port COMxx.")


class Reader(threading.Thread):
    """Runs mpremote, parses CSV lines, keeps the latest sample + history."""
    def __init__(self, port, maxlen):
        super().__init__(daemon=True)
        self.port = port
        self.lock = threading.Lock()
        self.tx = deque(maxlen=maxlen)
        self.ty = deque(maxlen=maxlen)
        self.tz = deque(maxlen=maxlen)
        self.latest = (0.0, 0.0, 0.0)
        self.banner = ""
        self.proc = None
        self._stop = False

    def run(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "mpremote", "connect", self.port, "run", DEVICE_SCRIPT],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        for line in self.proc.stdout:
            if self._stop:
                break
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                self.banner = line.lstrip("# ").strip()
                continue
            try:
                x, y, z = (float(v) for v in line.split(","))
            except ValueError:
                continue
            with self.lock:
                self.tx.append(x); self.ty.append(y); self.tz.append(z)
                self.latest = (x, y, z)

    def stop(self):
        self._stop = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ---- 3D cube (a PCB-like slab) ----------------------------------------------
_SX, _SY, _SZ = 1.0, 0.7, 0.12
_VERTS = np.array([
    [ _SX,  _SY,  _SZ], [ _SX, -_SY,  _SZ], [-_SX, -_SY,  _SZ], [-_SX,  _SY,  _SZ],
    [ _SX,  _SY, -_SZ], [ _SX, -_SY, -_SZ], [-_SX, -_SY, -_SZ], [-_SX,  _SY, -_SZ],
])
_FACES = [[0, 1, 2, 3],   # top (+Z)  -> highlighted
          [4, 5, 6, 7],   # bottom
          [0, 1, 5, 4], [2, 3, 7, 6], [1, 2, 6, 5], [0, 3, 7, 4]]
_FACE_COLORS = ["#d62728", "#555555", "#9ecae1", "#9ecae1", "#c6dbef", "#c6dbef"]


def _rot(pitch, roll):
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return Rx @ Ry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None)
    ap.add_argument("--seconds", type=float, default=5.0, help="scrolling window width")
    args = ap.parse_args()

    port = find_port(args.port)
    maxlen = int(args.seconds * RATE_HZ)
    reader = Reader(port, maxlen)
    reader.start()

    fig = plt.figure(figsize=(12, 6))
    fig.canvas.manager.set_window_title(f"SC7A20 live  —  {port}")
    gs = fig.add_gridspec(2, 2, width_ratios=[2.0, 1.3], hspace=0.35, wspace=0.2)
    ax = fig.add_subplot(gs[0, 0])
    axb = fig.add_subplot(gs[1, 0])
    ax3d = fig.add_subplot(gs[:, 1], projection="3d")

    (lx,) = ax.plot([], [], color=CX, lw=1.5, label="X")
    (ly,) = ax.plot([], [], color=CY, lw=1.5, label="Y")
    (lz,) = ax.plot([], [], color=CZ, lw=1.5, label="Z")
    ax.set_ylim(-2.2, 2.2)
    ax.set_xlim(-args.seconds, 0)
    ax.set_ylabel("acceleration (g)")
    ax.set_xlabel("time (s)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", ncol=3)
    title = ax.set_title("waiting for data…")

    bars = axb.barh(["X", "Y", "Z"], [0, 0, 0], color=[CX, CY, CZ])
    axb.set_xlim(-2.2, 2.2)
    axb.axvline(0, color="k", lw=0.8)
    axb.set_xlabel("instantaneous (g)")

    # cube setup
    cube = Poly3DCollection([_VERTS[f] for f in _FACES],
                            facecolors=_FACE_COLORS, edgecolors="k",
                            linewidths=0.6, alpha=0.95)
    ax3d.add_collection3d(cube)
    lim = 1.3
    ax3d.set_xlim(-lim, lim); ax3d.set_ylim(-lim, lim); ax3d.set_zlim(-lim, lim)
    ax3d.set_box_aspect((1, 1, 1))
    ax3d.set_xticks([]); ax3d.set_yticks([]); ax3d.set_zticks([])
    ax3d.set_xlabel("X"); ax3d.set_ylabel("Y"); ax3d.set_zlabel("Z")
    ax3d.set_title("orientation (red face = +Z / top)")
    ax3d.view_init(elev=20, azim=-60)

    def update(_):
        with reader.lock:
            xs = list(reader.tx); ys = list(reader.ty); zs = list(reader.tz)
            x, y, z = reader.latest
            banner = reader.banner
        n = len(xs)
        if n:
            t = [(-(n - 1 - i)) / RATE_HZ for i in range(n)]
            lx.set_data(t, xs); ly.set_data(t, ys); lz.set_data(t, zs)
        for bar, v in zip(bars, (x, y, z)):
            bar.set_width(v)
        mag = math.sqrt(x * x + y * y + z * z)
        pitch = math.atan2(x, math.sqrt(y * y + z * z))
        roll = math.atan2(y, math.sqrt(x * x + z * z))
        R = _rot(pitch, roll)
        rv = _VERTS @ R.T
        cube.set_verts([rv[f] for f in _FACES])
        title.set_text(
            f"X={x:+.3f}  Y={y:+.3f}  Z={z:+.3f} g   |a|={mag:.3f} g   "
            f"pitch={math.degrees(pitch):+5.1f}°  roll={math.degrees(roll):+5.1f}°\n{banner}"
        )
        return (lx, ly, lz)

    ani = FuncAnimation(fig, update, interval=33, blit=False, cache_frame_data=False)

    def on_close(_):
        reader.stop()
    fig.canvas.mpl_connect("close_event", on_close)

    try:
        plt.show()
    finally:
        reader.stop()


if __name__ == "__main__":
    main()
