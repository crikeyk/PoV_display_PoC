# PoV wand - code.py   (v6)
# Most people never need to open this file. To change what the wand shows, edit:
#     message.txt   (the words)      settings.txt   (options)      image.bmp   (a picture)
import time, math, struct, array, gc
from leds import Leds
from accel import Accel

leds = Leds("gpio")     # must be created before Accel (frees the SPI pins)
acc = Accel()

RANGE_G = 16            # accelerometer range: 2, 4, 8 or 16 (g)
acc._write(0x20, 0x77)  # accel rate 400 Hz. If x stays at 0, delete this line.
acc._write(0x23, 0x88 | ({2: 0, 4: 1, 8: 2, 16: 3}[RANGE_G] << 4))   # block update, high-res, range

# ---------------- options that are NOT in settings.txt (change here if you need to) ----------------
THRESH = 0.4        # g, minimum peak for a swing to count (auto-rises to ~half your real peaks)
KP = 0.2            # phase correction per swing event. 0.2 settles over a few swings
KW = 0.3            # how fast the pace follows the measured time between turns
KI = 0.05           # extra speed correction from the phase error
E_MAX = 1.2         # radians; events further off than this are ignored
OUT_MAX = 2         # this many odd events in a row = believe the sensor and re-sync
HOLD = 2.5          # half-swings to keep drawing with no valid event before giving up
STOP_S = 1.0        # seconds of no swinging before the run report prints
PEAK_DROP = 0.7     # a peak is "over" once the signal falls to 70% of it
MIN_HALF = 0.04     # seconds; allowed half-swing range when first locking on
MAX_HALF = 0.6
READ_S = 0.0025     # read the accelerometer every 2.5 ms (it updates at 400 Hz)
PITCH_TEXT = 0.055  # width of one text column, as a fraction of the half-swing
PITCH_IMG = 0.075   # width of one picture column

# ---------------- settings.txt (defaults; the file overrides them) ----------------
SHOW = "text"       # text | image | both
SECONDS = 4.0       # seconds per item when SHOW = both
STRETCH = 1.0       # make everything wider (>1) or narrower (<1)
LIT = "dark"        # image: which pixels light up: dark | light
PASSES = "both"     # both | right | left
FLIP_VERTICAL = False
SIGN = 1            # 1 or -1 : flips left/right
SHIFT_MS = 0.0      # timing nudge. Positive = draw later in the swing
CALIBRATE = False   # True = show one bar at the swing centre
ANCHOR = "peaks"    # auto | zero | peaks   (which swing event keeps time)
WIDTH = 70          # percent of the full swing the display uses (the ends are squashed, so keep this below ~75)
SHAPE = -1.0        # -1 = auto, or 0 = smooth swing (sine) ... 1 = steady speed with sharp turns
DEBUG = True        # True = print run reports (with raw trace) to the serial console
EDGE_FLASH = 0.0    # 0 = off. 0.04 = flash every LED at each extreme

warnings = 0

def warn(msg):
    global warnings
    warnings += 1
    print("POV> PROBLEM: " + msg)

def yes(v):
    return v.strip().lower() in ("yes", "y", "true", "on", "1")

def load_settings():
    global SHOW, SECONDS, STRETCH, LIT, PASSES, FLIP_VERTICAL, SIGN, SHIFT_MS
    global CALIBRATE, ANCHOR, SHAPE, DEBUG, EDGE_FLASH, WIDTH
    try:
        with open("/settings.txt") as f:
            lines = f.read().split("\n")
    except OSError:
        print("POV> no settings.txt found, using defaults")
        return
    except Exception as e:                   # e.g. saved in an odd text format
        warn("settings.txt could not be read (%s) - save it as plain text (UTF-8 / ANSI)" % e)
        return
    for n, ln in enumerate(lines):
        ln = ln.replace("﻿", "").split("#", 1)[0].strip()
        if not ln:
            continue
        if "=" not in ln:
            warn("settings.txt line %d has no '=' : %s" % (n + 1, ln))
            continue
        k, v = ln.split("=", 1)
        k = k.strip().upper().replace(" ", "_")
        v = v.strip()
        lv = v.lower()
        try:
            if k == "SHOW":
                if lv not in ("text", "image", "both"):
                    raise ValueError("use text, image or both")
                SHOW = lv
            elif k == "SECONDS":
                SECONDS = max(0.5, float(v))
            elif k == "STRETCH":
                STRETCH = max(0.2, min(4.0, float(v)))
            elif k == "LIT":
                if lv not in ("dark", "light"):
                    raise ValueError("use dark or light")
                LIT = lv
            elif k == "PASSES":
                if lv not in ("both", "right", "left"):
                    raise ValueError("use both, right or left")
                PASSES = lv
            elif k == "FLIP_VERTICAL":
                FLIP_VERTICAL = yes(v)
            elif k == "SIGN":
                SIGN = -1 if float(v) < 0 else 1
            elif k == "SHIFT_MS":
                SHIFT_MS = float(v)
            elif k == "CALIBRATE":
                CALIBRATE = yes(v)
            elif k == "ANCHOR":
                if lv not in ("auto", "zero", "peaks"):
                    raise ValueError("use auto, zero or peaks")
                ANCHOR = lv
            elif k == "SHAPE":
                SHAPE = -1.0 if lv == "auto" else max(0.0, min(1.0, float(v)))
            elif k == "WIDTH":
                WIDTH = max(20.0, min(95.0, float(v.replace("%", ""))))
            elif k == "DEBUG":
                DEBUG = yes(v)
            elif k == "EDGE_FLASH":
                EDGE_FLASH = max(0.0, min(0.2, float(v)))
            else:
                warn("settings.txt line %d: unknown setting '%s'" % (n + 1, k))
        except ValueError as e:
            warn("settings.txt line %d: could not use '%s' (%s)" % (n + 1, ln, e))

load_settings()
PASS_DIR = 1 if PASSES == "right" else (-1 if PASSES == "left" else 0)

# ---------------- font: 5x7, bit0 = top row ----------------
FONT = {
 " ":(0,0,0,0,0),"!":(0,0,0x5F,0,0),"-":(8,8,8,8,8),".":(0,0x60,0x60,0,0),
 "?":(0x02,0x01,0x51,0x09,0x06),",":(0,0x50,0x30,0,0),":":(0,0x36,0x36,0,0),
 "'":(0,0x05,0x03,0,0),"(":(0,0x1C,0x22,0x41,0),")":(0,0x41,0x22,0x1C,0),
 "+":(8,8,0x3E,8,8),"/":(0x20,0x10,8,4,2),"=":(0x14,0x14,0x14,0x14,0x14),
 "*":(0x14,8,0x3E,8,0x14),"_":(0x40,0x40,0x40,0x40,0x40),
 "~":(0x0C,0x1E,0x3C,0x1E,0x0C),
 "A":(0x7E,0x11,0x11,0x11,0x7E),"B":(0x7F,0x49,0x49,0x49,0x36),"C":(0x3E,0x41,0x41,0x41,0x22),
 "D":(0x7F,0x41,0x41,0x22,0x1C),"E":(0x7F,0x49,0x49,0x49,0x41),"F":(0x7F,0x09,0x09,0x09,0x01),
 "G":(0x3E,0x41,0x49,0x49,0x7A),"H":(0x7F,0x08,0x08,0x08,0x7F),"I":(0x00,0x41,0x7F,0x41,0x00),
 "J":(0x20,0x40,0x41,0x3F,0x01),"K":(0x7F,0x08,0x14,0x22,0x41),"L":(0x7F,0x40,0x40,0x40,0x40),
 "M":(0x7F,0x02,0x0C,0x02,0x7F),"N":(0x7F,0x04,0x08,0x10,0x7F),"O":(0x3E,0x41,0x41,0x41,0x3E),
 "P":(0x7F,0x09,0x09,0x09,0x06),"Q":(0x3E,0x41,0x51,0x21,0x5E),"R":(0x7F,0x09,0x19,0x29,0x46),
 "S":(0x46,0x49,0x49,0x49,0x31),"T":(0x01,0x01,0x7F,0x01,0x01),"U":(0x3F,0x40,0x40,0x40,0x3F),
 "V":(0x1F,0x20,0x40,0x20,0x1F),"W":(0x3F,0x40,0x38,0x40,0x3F),"X":(0x63,0x14,0x08,0x14,0x63),
 "Y":(0x07,0x08,0x70,0x08,0x07),"Z":(0x61,0x51,0x49,0x45,0x43),
 "0":(0x3E,0x51,0x49,0x45,0x3E),"1":(0x00,0x42,0x7F,0x40,0x00),"2":(0x42,0x61,0x51,0x49,0x46),
 "3":(0x21,0x41,0x45,0x4B,0x31),"4":(0x18,0x14,0x12,0x7F,0x10),"5":(0x27,0x45,0x45,0x45,0x39),
 "6":(0x3C,0x4A,0x49,0x49,0x30),"7":(0x01,0x71,0x09,0x05,0x03),"8":(0x36,0x49,0x49,0x49,0x36),
 "9":(0x06,0x49,0x49,0x29,0x1E),
}

def rev16(m):
    r = 0
    for i in range(16):
        if (m >> i) & 1:
            r |= 1 << (15 - i)
    return r

def line_columns(txt):                   # one line of text -> list of 7-bit font columns
    cols = []
    for ch in txt.upper():
        for b in FONT.get(ch, FONT[" "]):
            cols.append(b)
        cols.append(0)                   # gap between letters
    if cols:
        cols.pop()
    return cols

def build_text_frame(raw):
    raw = raw.replace("﻿", "").replace("\r", "")
    lines = [ln.strip() for ln in raw.split("\n")]
    lines = [ln for ln in lines if ln]
    if len(lines) > 2:
        warn("message.txt has %d lines; only the first 2 are shown" % len(lines))
    lines = lines[:2]
    if not lines:
        lines = ["HELLO"]
    cl = [line_columns(ln) for ln in lines]
    width = max(len(c) for c in cl)
    masks = [0] * width
    for li, c in enumerate(cl):
        off = (width - len(c)) // 2      # centre shorter lines
        for i, b in enumerate(c):
            m = 0
            for r in range(7):
                if (b >> r) & 1:
                    if len(cl) == 1:     # one line: full height, each font row is 2 LEDs
                        m |= 3 << (13 - 2 * r)
                    elif li == 0:        # two lines: top line uses LEDs 9..15
                        m |= 1 << (15 - r)
                    else:                # bottom line uses LEDs 0..6
                        m |= 1 << (6 - r)
            masks[off + i] |= m
    return masks, PITCH_TEXT

def load_bmp(path):
    with open(path, "rb") as f:
        hdr = f.read(54)
        if len(hdr) < 54 or hdr[0:2] != b"BM":
            raise ValueError("not a .bmp file")
        data_off = struct.unpack_from("<I", hdr, 10)[0]
        dib = struct.unpack_from("<I", hdr, 14)[0]
        w, h = struct.unpack_from("<ii", hdr, 18)
        bpp = struct.unpack_from("<H", hdr, 28)[0]
        comp = struct.unpack_from("<I", hdr, 30)[0]
        ncol = struct.unpack_from("<I", hdr, 46)[0]
        if comp not in (0, 3) or bpp not in (1, 4, 8, 24, 32):
            raise ValueError("unsupported bmp type (save as Monochrome or 24-bit Bitmap)")
        top_down = h < 0
        h = abs(h)
        if w < 1 or h < 1:
            raise ValueError("empty picture")
        pal = []
        if bpp <= 8:
            n = ncol if ncol else (1 << bpp)
            f.seek(14 + dib)
            praw = f.read(4 * n)
            for i in range(n):
                b_, g_, r_ = praw[4 * i], praw[4 * i + 1], praw[4 * i + 2]
                pal.append((r_ * 30 + g_ * 59 + b_ * 11) // 100)
        row_bytes = ((w * bpp + 31) // 32) * 4
        # sample the picture down/up to 16 rows (keeping its shape)
        out_h = 16
        out_w = max(1, (w * out_h + h // 2) // h) if h != out_h else w
        if out_w > 256:
            out_w = 256
        src_x = [min(w - 1, int((c + 0.5) * w / out_w)) for c in range(out_w)]
        cols = [0] * out_w
        for r in range(out_h):
            sy = min(h - 1, int((r + 0.5) * h / out_h))
            fy = sy if top_down else (h - 1 - sy)
            f.seek(data_off + fy * row_bytes)
            row = f.read(row_bytes)
            if len(row) < row_bytes:
                raise ValueError("picture data is cut short")
            for c in range(out_w):
                x = src_x[c]
                if bpp == 1:
                    lum = pal[(row[x >> 3] >> (7 - (x & 7))) & 1] if pal else (255 if (row[x >> 3] >> (7 - (x & 7))) & 1 else 0)
                elif bpp == 4:
                    v = row[x >> 1]
                    lum = pal[(v >> 4) if (x & 1) == 0 else (v & 15)]
                elif bpp == 8:
                    lum = pal[row[x]]
                else:
                    o = x * (bpp >> 3)
                    lum = (row[o + 2] * 30 + row[o + 1] * 59 + row[o] * 11) // 100
                on = (lum < 128) if LIT == "dark" else (lum >= 128)
                if on:
                    cols[c] |= 1 << (15 - r)       # row 0 is the top LED (15)
        return cols

def build_frames():
    frames = []
    names = []
    if SHOW in ("text", "both"):
        try:
            with open("/message.txt") as f:
                raw = f.read()
        except OSError:
            warn("message.txt not found - showing HELLO")
            raw = "HELLO"
        except Exception as e:
            warn("message.txt could not be read (%s) - save it as plain text (UTF-8 / ANSI)" % e)
            raw = "HELLO"
        masks, pitch = build_text_frame(raw)
        frames.append((masks, pitch))
        names.append("text")
    if SHOW in ("image", "both"):
        try:
            masks = load_bmp("/image.bmp")
            frames.append((masks, PITCH_IMG))
            names.append("image")
        except Exception as e:
            warn("image.bmp: %s" % e)
    if not frames:
        masks, pitch = build_text_frame("HELLO")
        frames.append((masks, pitch))
        names.append("text")
    out = []
    for masks, pitch in frames:
        if FLIP_VERTICAL:
            masks = [rev16(m) for m in masks]
        n = len(masks)
        half = n * pitch * STRETCH / 2
        if half > WIDTH / 100.0:
            half = WIDTH / 100.0
        out.append((masks, n, half))
    return out, names

FRAMES, FRAME_NAMES = build_frames()
cur_frame = 0
COLS, N, HALF = FRAMES[0]
print("POV> showing: %s  (%s)" % (", ".join(FRAME_NAMES), ", ".join("%d columns" % fr[1] for fr in FRAMES)))

PI = math.pi
TWO_PI = 2 * math.pi
EDGE_POS = math.cos(PI * EDGE_FLASH)
TARGET = {1: PI / 2, -1: 3 * PI / 2, 2: 0.0, -2: PI}

def wrap(e):                         # wrap an angle into -pi..pi
    while e > PI:
        e -= TWO_PI
    while e < -PI:
        e += TWO_PI
    return e

shape_eff = SHAPE if SHAPE >= 0.0 else 0.0

def swing_pos(ph):                   # -1 = left extreme, +1 = right extreme
    p = -math.cos(ph)
    if shape_eff > 0.02:
        u = ph % TWO_PI
        if u > PI:
            u = TWO_PI - u
        p = (1.0 - shape_eff) * p + shape_eff * (2.0 * u / PI - 1.0)
    return p

# ---------------- fast LED + accel access (uses the lib objects, without their overhead) ----------------
cath = leds._cath                    # the 16 cathode pins created by Leds("gpio")
shown = 0

def put(mask):                       # only touch the pins that change
    global shown
    dif = mask ^ shown
    i = 0
    while dif:
        if dif & 1:
            cath[i].value = not ((mask >> i) & 1)
        dif >>= 1
        i += 1
    shown = mask

_spi = acc._spi
_cs = acc._cs
_cmd = bytes([0x28 | 0xC0])          # read OUT_X_L.. with auto-increment
_buf = bytearray(2)
_buf6 = bytearray(6)
G = 0.001                            # g per count; measured from gravity at startup

def _s16(lo, hi):
    v = (hi << 8) | lo
    if v & 0x8000:
        v -= 65536
    return v >> 4                    # 12-bit count

def read_x_counts():                 # raw 12-bit x count, before scale or bias
    _cs.value = False
    _spi.write(_cmd)
    _spi.readinto(_buf)
    _cs.value = True
    return _s16(_buf[0], _buf[1])

def read_x():                        # x acceleration in g
    return read_x_counts() * G

def read_xyz_counts():
    _cs.value = False
    _spi.write(_cmd)
    _spi.readinto(_buf6)
    _cs.value = True
    return _s16(_buf6[0], _buf6[1]), _s16(_buf6[2], _buf6[3]), _s16(_buf6[4], _buf6[5])

# ---------------- run statistics (printed as a report when you stop swinging) ----------------
Ts = []; peaks = []; errs = []
n_locks = n_loops = n_cols = n_skips = 0
n_out = n_reacq = n_odd = n_to = n_g1 = n_g2 = 0
first_lock_ms = None
t_locked = max_gap = xmax = pk = avg_pk = 0.0
sess_t0 = 0.0

# One record per accepted peak-to-peak half. Printed only after the swing stops.
SEG_MAX = 80
seg_ev = []        # +2 = arrived at left end (closes right-to-left), -2 = right end
seg_half = []      # measured half, ms
seg_err = []       # signed phase error at that peak, ms, or None
seg_zc = []        # accel zero-cross as percent of the half, or None
seg_integ = []     # integrated-travel fraction at the drawn centre, or None
bias0 = None
iv = 0.0           # integrated velocity since the last peak, g*s
ip = 0.0           # integrated position since the last peak
ip_mid = None      # ip at the sample where the drawn position crosses 0
izc = None         # time of the first accel zero-cross in this half
iseg_t = 0.0
have_peak = False
seg_sign = 0       # sign of acceleration at the peak that opened this half
dbg_prev_pos = None
wf_t = []
wf_x = []
last_wf_t = []
last_wf_x = []
WF_KEEP = 40
WF_RAW_MAX = 240
# Drawing uses the last completed half of the SAME direction, not the phase loop.
draw_half = 0.0
draw_t = 0.0
draw_sign = 1
half_lr = 0.0       # last left-to-right duration, seconds
half_rl = 0.0       # last right-to-left duration, seconds

def reset_stats():
    global Ts, peaks, errs, n_locks, n_loops, n_cols, n_skips
    global n_out, n_reacq, n_odd, n_to, n_g1, n_g2
    global first_lock_ms, t_locked, max_gap, xmax, pk, avg_pk
    global seg_ev, seg_half, seg_err, seg_zc, seg_integ, bias0
    global iv, ip, ip_mid, izc, have_peak, seg_sign, dbg_prev_pos
    global wf_t, wf_x, last_wf_t, last_wf_x
    global draw_half, draw_t, draw_sign, half_lr, half_rl
    global cap_i, cap_n, cap_total, cap_prev, ev_i, ev_n
    Ts = []; peaks = []; errs = []
    n_locks = n_loops = n_cols = n_skips = 0
    n_out = n_reacq = n_odd = n_to = n_g1 = n_g2 = 0
    first_lock_ms = None
    t_locked = max_gap = xmax = pk = avg_pk = 0.0
    seg_ev = []; seg_half = []; seg_err = []; seg_zc = []; seg_integ = []
    bias0 = bias
    iv = 0.0
    ip = 0.0
    ip_mid = None
    izc = None
    have_peak = False
    seg_sign = 0
    dbg_prev_pos = None
    wf_t = []; wf_x = []
    last_wf_t = []; last_wf_x = []
    draw_half = 0.0
    draw_t = 0.0
    draw_sign = 1
    half_lr = 0.0
    half_rl = 0.0
    cap_i = 0
    cap_n = 0
    cap_total = 0
    cap_prev = 0.0
    ev_i = 0
    ev_n = 0

def report(now, bias):
    n = len(Ts)
    print("POV> ===== run report v6: copy everything from here =====")
    print("POV> show=%s cols=%d ANCHOR=%s SHAPE=%.1f(now %.2f) SIGN=%d SHIFT=%.1fms CAL=%d PASSES=%s STRETCH=%.2f WIDTH=%d%% RANGE=%dg %.2fmg/count KP=%.2f KW=%.2f KI=%.2f"
          % (",".join(FRAME_NAMES), N, ANCHOR, SHAPE, shape_eff, SIGN, SHIFT_MS, CALIBRATE, PASSES, STRETCH, WIDTH, RANGE_G, G * 1000, KP, KW, KI))
    if ANCHOR == "auto":
        print("POV> swing sharpness (crest) = %.2f -> using %s" % (crest_avg, "PEAKS" if peaky else "ZERO CROSSINGS"))
    print("POV> uptime=%.0fs (clock resolution ~%.2f ms)  bias=%+.3f g  max|x|=%.2f g%s"
          % (now, now / 4194.3, bias, xmax, "  ** CLIPPING **" if xmax > 0.95 * 2047 * G else ""))
    if n:
        mean = sum(Ts) / n
        sd = math.sqrt(sum((t - mean) ** 2 for t in Ts) / n)
        col_ms = 2 * HALF / N * mean / PI
        print("POV> swing events=%d  tracked half-swing=%.1f ms (about %.1f Hz)  min=%.1f max=%.1f sd=%.1f ms"
              % (n, mean, 500.0 / mean, min(Ts), max(Ts), sd))
        print("POV> one column lasts ~%.2f ms at the swing centre" % col_ms)
        if errs:
            rms = math.sqrt(sum(e * e for e in errs) / len(errs))
            print("POV> timing surprise per event: rms=%.1f ms = about %.1f columns (this is the blur limit)"
                  % (rms, rms / col_ms))
    if peaks:
        print("POV> swing peak |a|: mean=%.2f g  min=%.2f g  arm level now=%.2f g"
              % (sum(peaks) / len(peaks), min(peaks), max(THRESH, 0.5 * avg_pk)))
    if first_lock_ms is not None:
        print("POV> locked after %.0f ms (first event -> display on)" % first_lock_ms)
    print("POV> locks=%d  re-acquired=%d  gave up (holdover)=%d | ignored: outliers=%d too-close=%d"
          % (n_locks, n_reacq, n_to, n_out, n_odd))
    if n_loops and t_locked > 0:
        print("POV> loop: %.0f loops/s, avg %.2f ms, worst gap %.1f ms, gaps >1ms=%d >2ms=%d (of %d)"
              % (n_loops / t_locked, 1000 * t_locked / n_loops, max_gap * 1000, n_g1, n_g2, n_loops))
    tot = n_cols + n_skips
    if tot:
        print("POV> columns shown=%d skipped=%d (%.0f%% missed)" % (n_cols, n_skips, 100.0 * n_skips / tot))
    print_dbg(bias)
    dump_capture()
    print("POV> ===== end of report =====")

def _mean(xs):
    return sum(xs) / len(xs)

def _rms(xs):
    return math.sqrt(sum(x * x for x in xs) / len(xs))

def save_wf():
    global last_wf_t, last_wf_x, wf_t, wf_x
    n = len(wf_t)
    last_wf_t = []
    last_wf_x = []
    if n:
        step = n / float(WF_KEEP)
        if step < 1.0:
            step = 1.0
        i = 0.0
        while int(i) < n and len(last_wf_t) < WF_KEEP:
            k = int(i)
            last_wf_t.append(int(wf_t[k]))
            last_wf_x.append(int(wf_x[k]))
            i += step
    wf_t = []
    wf_x = []

def close_half(tc, ev, err_ms, accept):
    """A peak just happened. Store the half that ended, then start the next one."""
    global iv, ip, ip_mid, izc, iseg_t, have_peak, seg_sign, dbg_prev_pos, wf_t, wf_x
    global draw_half, draw_t, draw_sign, half_lr, half_rl
    if have_peak and accept:
        half = tc - iseg_t
        if 0.02 < half < 1.0:
            # Next pass is the opposite direction, so reuse that direction's last timing.
            if ev < 0:
                draw_half = half_rl if half_rl > 0.0 else half
                half_lr = half
            else:
                draw_half = half_lr if half_lr > 0.0 else half
                half_rl = half
            draw_t = tc
            draw_sign = 1 if ev > 0 else -1
            zc = None
            if izc is not None:
                zc = (izc - iseg_t) / half * 100.0
            integ = None
            if ip_mid is not None and ip * ip_mid > 0.0 and abs(ip) > 1e-4:
                integ = ip_mid / ip
            if len(seg_half) >= SEG_MAX:
                seg_ev.pop(0)
                seg_half.pop(0)
                seg_err.pop(0)
                seg_zc.pop(0)
                seg_integ.pop(0)
            seg_ev.append(ev)
            seg_half.append(half * 1000.0)
            seg_err.append(err_ms)
            seg_zc.append(zc)
            seg_integ.append(integ)
            save_wf()
        else:
            wf_t = []
            wf_x = []
    else:
        wf_t = []
        wf_x = []
    iv = 0.0
    ip = 0.0
    ip_mid = None
    izc = None
    iseg_t = tc
    have_peak = True
    seg_sign = 1 if ev > 0 else -1
    dbg_prev_pos = None

def print_dbg(bias_now):
    if not seg_half:
        print("POV> DBG no completed half-swings")
        return
    mean = _mean(seg_half)
    sd = math.sqrt(sum((t - mean) ** 2 for t in seg_half) / len(seg_half))
    freq = 500.0 / mean
    if freq < 1.5:
        label = "SLOW"
    elif freq > 3.0:
        label = "FAST"
    else:
        label = "MED"
    col_ms = (2 * HALF / N * mean / PI) if N else 0.0
    tot = n_cols + n_skips
    skip_pct = (100.0 * n_skips / tot) if tot else 0.0
    print("POV> DBG draw=pll")
    print("POV> DBG %s halves=%d half=%.1fms sd=%.1f freq=%.2fHz col=%.2fms skips=%.0f%% gap=%.1fms outliers=%d reacq=%d"
          % (label, len(seg_half), mean, sd, freq, col_ms, skip_pct, max_gap * 1000.0, n_out, n_reacq))

    def side(code, name):
        es = []
        i = 0
        while i < len(seg_ev):
            if seg_ev[i] == code and seg_err[i] is not None:
                es.append(seg_err[i])
            i += 1
        if not es:
            print("POV> DBG phase %s n=0" % name)
        else:
            cols = (_rms(es) / col_ms) if col_ms else 0.0
            print("POV> DBG phase %s n=%d mean=%+.1fms rms=%.1fms (%.1f col)"
                  % (name, len(es), _mean(es), _rms(es), cols))

    side(-2, "L->R")
    side(2, "R->L")
    zcs = [z for z in seg_zc if z is not None]
    igs = [g for g in seg_integ if g is not None]
    zc_s = ("%.0f%%" % _mean(zcs)) if zcs else "n/a"
    ig_s = ("%.2f" % _mean(igs)) if igs else "n/a"
    drift = 0.0 if bias0 is None else (bias_now - bias0)
    clip = "YES" if xmax > 0.95 * 2047 * G else "no"
    pk_mean = (sum(peaks) / len(peaks)) if peaks else 0.0
    print("POV> DBG zero-cross=%s of half (sine=50) integral-middle=%s (match=0.50) n_zc=%d n_int=%d"
          % (zc_s, ig_s, len(zcs), len(igs)))
    print("POV> DBG peak_mean=%.2fg max|x|=%.2fg clip=%s bias_drift=%+.3fg"
          % (pk_mean, xmax, clip, drift))
    if last_wf_t:
        print("POV> last half waveform t_ms:x_mg %d points" % len(last_wf_t))
        line = "POV> W"
        k = 0
        while k < len(last_wf_t):
            line += " %d:%d" % (last_wf_t[k], last_wf_x[k])
            if k % 9 == 8:
                print(line)
                line = "POV> W"
            k += 1
        if len(line) > 6:
            print(line)

# ---------------- raw capture: last N seconds of counts + oscillator, dumped when you stop ----------------
# Filled only while a swing is in progress. Nothing is printed until you hold still.
CAP_N = 0
EV_N = 0
cap_dt = cap_x = cap_ph = cap_w = None
ev_at = ev_code = ev_ok = None
cap_i = cap_n = cap_total = 0
cap_prev = 0.0
ev_i = ev_n = 0

def alloc_capture():
    """Preallocate a ring of raw samples. Size comes from whatever RAM is left."""
    global CAP_N, EV_N, cap_dt, cap_x, cap_ph, cap_w, ev_at, ev_code, ev_ok
    gc.collect()
    free = gc.mem_free()
    n = int((free - 70000) / 8)
    if n > 20000:
        n = 20000
    if n < 1500:
        n = 1500
    while n >= 800:
        try:
            cap_dt = array.array("H", [0]) * n   # gap before this sample, in 10 us steps
            cap_x = array.array("h", [0]) * n    # raw x counts
            cap_ph = array.array("H", [0]) * n   # draw phase, milliradians; 0 and w=0 means unlocked
            cap_w = array.array("H", [0]) * n    # rad/s * 100; 0 = oscillator not locked
            CAP_N = n
            break
        except MemoryError:
            n = n // 2
            CAP_N = 0
    evn = 600
    while evn >= 50 and CAP_N:
        try:
            ev_at = array.array("I", [0]) * evn
            ev_code = array.array("b", [0]) * evn
            ev_ok = array.array("B", [0]) * evn
            EV_N = evn
            break
        except MemoryError:
            evn = evn // 2
            EV_N = 0
    gc.collect()
    secs = CAP_N / 400.0
    print("POV> capture buffer %d samples, about %.0f s of the most recent swing (raw x + oscillator)"
          % (CAP_N, secs))

def note_cap_event(ev, accept):
    global ev_i, ev_n
    if not EV_N:
        return
    ev_at[ev_i] = cap_total          # absolute index of the sample recorded just after this
    ev_code[ev_i] = ev
    ev_ok[ev_i] = 1 if accept else 0
    ev_i += 1
    if ev_i >= EV_N:
        ev_i = 0
    if ev_n < EV_N:
        ev_n += 1

def dump_capture():
    if not CAP_N or cap_n <= 0:
        print("POV> CAPTURE none")
        return
    oldest = 0 if cap_total <= CAP_N else cap_i
    print("POV> CAPTURE kept=%d total=%d mg=%.4f bias=%.4f sign=%d shift=%.2f"
          % (cap_n, cap_total, G * 1000.0, bias, SIGN, SHIFT_MS))
    k = 0
    line = "POV> D"
    n_in_line = 0
    while k < cap_n:
        j = oldest + k
        if j >= CAP_N:
            j -= CAP_N
        line += " %d,%d,%d,%d" % (cap_dt[j], cap_x[j], cap_ph[j], cap_w[j])
        n_in_line += 1
        if n_in_line >= 8:
            print(line)
            line = "POV> D"
            n_in_line = 0
        k += 1
    if n_in_line:
        print(line)
    if ev_n:
        start = 0 if ev_n < EV_N else ev_i
        base = cap_total - cap_n
        k = 0
        line = "POV> E"
        n_in_line = 0
        while k < ev_n:
            j = start + k
            if j >= EV_N:
                j -= EV_N
            abs_i = ev_at[j]
            if base <= abs_i < cap_total:
                line += " %d,%d,%d" % (abs_i - base, ev_code[j], ev_ok[j])
                n_in_line += 1
                if n_in_line >= 10:
                    print(line)
                    line = "POV> E"
                    n_in_line = 0
            k += 1
        if n_in_line:
            print(line)
    print("POV> CAPTURE end")

# ---------------- startup: hold still for 0.5 s -> measure gravity (sets the scale) and resting x ----------------
NOMINAL = {2: 1.0, 4: 2.0, 8: 4.0, 16: 12.0}[RANGE_G] * 0.001     # typical g per count for this range
t0 = time.monotonic()
sx = sy = sz = 0
sxx = syy = szz = 0
cnt = 0
while time.monotonic() - t0 < 0.5:
    cx, cy, cz = read_xyz_counts()
    sx += cx; sy += cy; sz += cz
    sxx += cx * cx; syy += cy * cy; szz += cz * cz
    cnt += 1
mx = sx / cnt; my = sy / cnt; mz = sz / cnt
norm = math.sqrt(mx * mx + my * my + mz * mz)
jitter = math.sqrt(max(0.0, sxx / cnt - mx * mx) + max(0.0, syy / cnt - my * my) + max(0.0, szz / cnt - mz * mz))
G = NOMINAL
scale_note = "nominal"
if norm > 5 and jitter < 0.05 * norm:
    g_meas = 1.0 / norm
    if 0.0003 < g_meas < 0.05:                    # gravity is 1 g, so this is the real scale
        G = g_meas
        scale_note = "measured from gravity"
    else:
        scale_note = "NOMINAL (gravity reading %.0f counts looked wrong)" % norm
elif norm > 5:
    scale_note = "NOMINAL (the board was moving at startup - keep it still after saving)"
bias = SIGN * mx * G
print("POV> ready (v6 dbg half). range +/-%d g, %.2f mg/count (%s). resting x %+.3f g. Wiggle left-right now."
      % (RANGE_G, G * 1000, scale_note, bias))

# The "oscillator": phase phi (radians) advances at w rad/s.
#   phase 0 = left extreme, pi/2 = centre moving right, pi = right extreme, 3pi/2 = centre moving left.
# Each swing event nudges phi and w a little (a PI loop) instead of replacing them.
armed = 0            # +1 after a strong +x peak, -1 after a strong -x peak
d = 0                # code of the last accepted event
locked = False
sess_active = False
phi = 0.0
w = PI / 0.15        # rad/s (half-swing of 150 ms to start)
t_phi = 0.0          # time at which phi was last valid
t_c = 0.0            # time of the last accepted event
out_run = 0          # consecutive outliers
prev_a = 0.0
prev_t = t_rd = prev_now = time.monotonic()
prev_locked = False
last_col = -1
last_mask = -1
# peak detector state
ptrack = 0; pdir = 0; pmax = 0.0; pt = 0.0; pprev_v = 0.0; pprev_t = 0.0
pnext_v = None; pnext_t = 0.0
acc_a2 = 0.0; acc_n = 0; crest_avg = 0.0; peaky = False
t_last = 0.0; ev_last = 0
alloc_capture()

def handle_event(tc, ev):
    """A swing event happened at time tc. ev: +1/-1 = centre moving right/left, +2/-2 = left/right extreme."""
    global sess_active, sess_t0, locked, phi, w, t_phi, t_c, d, out_run, avg_pk, pk, first_lock_ms
    global n_out, n_reacq, n_odd, n_locks, t_last, ev_last
    if not sess_active:
        sess_active = True
        reset_stats()
        sess_t0 = tc
    target = TARGET[ev]
    accept = True
    # Events alternate, so the time since the previous one (accepted or not) is exactly half a swing.
    half = tc - t_last
    wm = 0.0
    if ev_last != 0 and ev != ev_last and MIN_HALF <= half <= MAX_HALF:
        wm = PI / half
    t_last = tc
    ev_last = ev
    err_ms = None
    if locked:
        ph = phi + w * (tc - t_phi)          # where the oscillator thought we were
        e0 = wrap(target - ph)               # surprise (radians), measured before adapting
        err_ms = e0 / w * 1000.0
        wn = w
        if wm and 0.5 * w < wm < 2.0 * w:
            wn = w + KW * (wm - w)           # follow the measured speed quickly
        ph = phi + wn * (tc - t_phi)
        e = wrap(target - ph)
        if e > E_MAX or e < -E_MAX:
            n_out += 1
            out_run += 1
            accept = False
            if out_run >= OUT_MAX:           # a few odd ones in a row: believe the sensor
                phi = target
                t_phi = tc
                t_c = tc
                d = ev
                if wm:
                    w = wm
                out_run = 0
                n_reacq += 1
        else:
            out_run = 0
            phi = (ph + KP * e) % TWO_PI
            w = wn + KI * e * wn / PI
            if w > PI / MIN_HALF:
                w = PI / MIN_HALF
            elif w < PI / MAX_HALF:
                w = PI / MAX_HALF
            t_phi = tc
            if len(Ts) < 400:
                Ts.append(PI / w * 1000)
                errs.append(e0 / w * 1000)
                peaks.append(pk)
            avg_pk = pk if avg_pk == 0.0 else avg_pk + (pk - avg_pk) * 0.5
    elif d != 0 and ev != d:
        half = tc - t_c
        if half < MIN_HALF:
            n_odd += 1                       # too close to the last event: ripple, ignore it
            accept = False
        elif half < MAX_HALF:
            w = PI / half                    # first good half-swing: start the oscillator
            phi = target
            t_phi = tc
            locked = True
            out_run = 0
            n_locks += 1
            if first_lock_ms is None:
                first_lock_ms = (tc - sess_t0) * 1000
            avg_pk = pk if avg_pk == 0.0 else avg_pk + (pk - avg_pk) * 0.5
    if ev == 2 or ev == -2:
        close_half(tc, ev, err_ms, accept)
    if accept:
        pk = 0.0
        t_c = tc
        d = ev
    note_cap_event(ev, accept)

while True:
    now = time.monotonic()

    # ---------- read the accelerometer and watch for swing events ----------
    if now - t_rd >= READ_S:
        xc = read_x_counts()
        xr = xc * G
        now = t_rd = time.monotonic()
        x = xr * SIGN
        if sess_active and abs(xr) > xmax:
            xmax = abs(xr)
        rate = 0.3
        if not sess_active and abs(x - bias) < 0.5 * THRESH:
            rate = 3.0                           # idle: follow tilt changes quickly
        bias += (x - bias) * min(1.0, (now - prev_t) * rate)
        a = x - bias
        if abs(a) > pk:
            pk = abs(a)

        # Between peaks: integrate acceleration, and remember the zero-cross and the
        # drawn centre. Nothing is printed here.
        if have_peak:
            dt = now - prev_t
            if 0.0 < dt < 0.05:
                iv += a * dt
                ip += iv * dt
                if izc is None and seg_sign != 0 and prev_a * seg_sign > 0.0 and a * seg_sign <= 0.0:
                    den = prev_a - a
                    izc = prev_t + dt * (prev_a / den if den else 0.0)
            if len(wf_t) < WF_RAW_MAX:
                wf_t.append((now - iseg_t) * 1000.0)
                wf_x.append(xr * 1000.0)
            if locked and ip_mid is None:
                phm = phi + w * (now - t_phi + SHIFT_MS / 1000.0)
                posm = swing_pos(phm)
                if dbg_prev_pos is not None and dbg_prev_pos * posm < 0.0:
                    ip_mid = ip
                dbg_prev_pos = posm

        arm = 0.4 * avg_pk                       # a peak must reach 40% of the typical peak
        if arm < THRESH:
            arm = THRESH

        run_zero = ANCHOR == "zero" or (ANCHOR == "auto" and not peaky)
        if run_zero:
            # ---- swing centre = acceleration crossing zero after a strong peak ----
            if a > arm:
                armed = 1
            elif a < -arm:
                armed = -1
            cross = 0
            if armed == 1 and a <= 0:
                cross = 1                        # strong +, now through zero: centre, moving RIGHT
                armed = 0
            elif armed == -1 and a >= 0:
                cross = -1                       # centre, moving LEFT
                armed = 0
            if cross:
                den = prev_a - a
                handle_event(prev_t + (now - prev_t) * (prev_a / den if den else 0.0), cross)
        else:
            armed = 0
        if ANCHOR != "zero":
            # ---- swing extremes = the acceleration peaks (+ = left end, - = right end) ----
            acc_a2 += a * a
            acc_n += 1
            if ptrack == 0:
                if a > arm and pdir != 1:
                    ptrack = 1
                elif a < -arm and pdir != -1:
                    ptrack = -1
                if ptrack:
                    pmax = a * ptrack
                    pt = now
                    pprev_v = prev_a * ptrack
                    pprev_t = prev_t
                    pnext_v = None
            else:
                v = a * ptrack
                if v > pmax:
                    pmax = v
                    pt = now
                    pprev_v = prev_a * ptrack
                    pprev_t = prev_t
                    pnext_v = None
                else:
                    if pnext_v is None:
                        pnext_v = v
                        pnext_t = now
                    if v < pmax * PEAK_DROP:
                        tp = pt                  # refine the peak time between samples (parabola)
                        den = pprev_v - 2 * pmax + pnext_v
                        if den < -1e-9:
                            dl = 0.5 * (pprev_v - pnext_v) / den
                            if dl > 0.5:
                                dl = 0.5
                            elif dl < -0.5:
                                dl = -0.5
                            tp = pt + dl * ((pnext_t - pt) if dl > 0 else (pt - pprev_t))
                        ev = 2 * ptrack          # +2 = left extreme, -2 = right extreme
                        pdir = ptrack
                        ptrack = 0
                        if acc_n > 3 and acc_a2 > 0.0:   # how sharp is the swing? (peak / rms of the half-swing)
                            crest = pmax / math.sqrt(acc_a2 / acc_n)
                            crest_avg = crest if crest_avg == 0.0 else crest_avg + (crest - crest_avg) * 0.4
                            if SHAPE < 0.0:
                                shape_eff = min(1.0, max(0.0, (crest_avg - 1.4) / 2.0))
                            if ANCHOR == "auto":
                                if peaky and crest_avg < 1.8:
                                    peaky = False
                                    locked = False; d = 0; armed = 0
                                elif (not peaky) and crest_avg > 2.2:
                                    peaky = True
                                    locked = False; d = 0; armed = 0
                        acc_a2 = 0.0
                        acc_n = 0
                        if ANCHOR == "peaks" or (ANCHOR == "auto" and peaky):
                            handle_event(tp, ev)
        if CAP_N and sess_active:
            if cap_prev > 0.0:
                dt10 = int((now - cap_prev) * 100000.0 + 0.5)
                if dt10 < 0:
                    dt10 = 0
                elif dt10 > 65535:
                    dt10 = 65535
            else:
                dt10 = 0
            cap_prev = now
            if locked and w > 0.0:
                phs = (phi + w * (now - t_phi + SHIFT_MS / 1000.0)) % TWO_PI
                pm = int(phs * 1000.0 + 0.5)
                if pm < 0:
                    pm = 0
                elif pm >= 6283:
                    pm = 0
                ww = int(w * 100.0 + 0.5)
                if ww < 1:
                    ww = 1
                elif ww > 65535:
                    ww = 65535
            else:
                pm = 0
                ww = 0
            cap_dt[cap_i] = dt10
            cap_x[cap_i] = xc
            cap_ph[cap_i] = pm
            cap_w[cap_i] = ww
            cap_i += 1
            if cap_i >= CAP_N:
                cap_i = 0
            cap_total += 1
            if cap_n < CAP_N:
                cap_n += 1
        prev_a = a
        prev_t = now

    # ---------- housekeeping ----------
    if locked and now - t_c > HOLD * PI / w:
        locked = False                           # no valid event for too long: stop drawing
        n_to += 1
        avg_pk = 0.0                             # forget the old amplitude
        pdir = 0; ptrack = 0
    if sess_active and now - t_c > STOP_S:
        if DEBUG:
            report(now, bias)
        sess_active = False
        locked = False
        d = 0
        armed = 0
        avg_pk = 0.0
        pdir = 0; ptrack = 0
    if len(FRAMES) > 1:                          # SHOW = both: alternate every SECONDS
        fi = int(now / SECONDS) % len(FRAMES)
        if fi != cur_frame:
            cur_frame = fi
            COLS, N, HALF = FRAMES[fi]
            last_col = -1

    # ---------- draw ----------
    mask = 0
    col = -1
    if locked:
        ph = phi + w * (now - t_phi + SHIFT_MS / 1000.0)
        pos = -math.cos(ph)
        if CALIBRATE:
            # Three thin bars: left edge of the word, centre, right edge.
            # Moving right lights the top half. Moving left lights the bottom half.
            # The two halves stacking into one bar means the passes agree.
            if abs(pos) < 0.03 or abs(pos - HALF) < 0.03 or abs(pos + HALF) < 0.03:
                mask = 0xFF00 if math.sin(ph) > 0.0 else 0x00FF
        elif PASS_DIR and math.sin(ph) * PASS_DIR <= 0:
            pass                                 # wrong direction: stay dark
        elif EDGE_FLASH and (pos > EDGE_POS or pos < -EDGE_POS):
            mask = 0xFFFF
        elif -HALF <= pos < HALF:
            col = int((pos / HALF + 1) * 0.5 * N)
            mask = COLS[col]
        if prev_locked:                          # loop-speed statistics
            g = now - prev_now
            n_loops += 1
            t_locked += g
            if g > max_gap:
                max_gap = g
            if g > 0.001:
                n_g1 += 1
                if g > 0.002:
                    n_g2 += 1
    else:
        ph_ = now % 2.0                          # idle heartbeat: the bottom LED blinks (twice if a file had a problem)
        if ph_ < 0.04 or (warnings and 0.2 < ph_ < 0.24):
            mask = 1
    if col != last_col:
        if col >= 0:
            n_cols += 1
            if last_col >= 0 and abs(col - last_col) > 1:
                n_skips += abs(col - last_col) - 1
        last_col = col
    if mask != last_mask:
        put(mask)
        last_mask = mask
    prev_locked = locked
    prev_now = now
