import time, math
from leds import Leds
from accel import Accel

leds = Leds("gpio")     # must be created before Accel (frees the SPI pins)
acc = Accel()
acc._write(0x20, 0x77)  # accel rate 100 Hz -> 400 Hz. If x stays at 0, delete this line.

# ---------------- tuning ----------------
TEXT = "HELLO"      # A-Z 0-9 space ! - .   (longer text = harder; keep it short at first)
SIGN = 1            # flip to -1 if the text is mirrored (i.e. +x is not "right")
THRESH = 0.4        # g, minimum peak for a swing to count (auto-rises to ~half your real peaks)
TEXT_WIDTH = 0.8    # how much of the swing the text spans (0.3 .. 0.9)
EDGE_FLASH = 0.0    # 0 = off. 0.04 = flash every LED at each extreme (timing check)
SHIFT_MS = 0.0      # timing nudge; if left/right sweeps don't overlap, adjust this
SMOOTH = 0.4        # how quickly the period estimate follows changes (0.1 slow .. 0.8 fast)
STOP_S = 1.0        # seconds of no swinging before the run report prints
LIVE_PRINT = False  # True = also print every half-swing (can slow the display)
MIN_HALF = 0.04     # seconds; allowed half-swing range when first locking on
MAX_HALF = 0.6
READ_S = 0.0025     # read the accelerometer every 2.5 ms (it updates at 400 Hz)

# ---------------- font: 5x7, bit0 = top row ----------------
FONT = {
 " ":(0,0,0,0,0),"!":(0,0,0x5F,0,0),"-":(8,8,8,8,8),".":(0,0x60,0x60,0,0),
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

def colmask(b):                      # 7 font rows -> LEDs 1..14, each row 2 LEDs tall
    m = 0
    for r in range(7):
        if (b >> r) & 1:
            m |= 3 << (13 - 2 * r)
    return m

COLS = []
for ch in TEXT.upper():
    for b in FONT.get(ch, FONT[" "]):
        COLS.append(colmask(b))
    COLS.append(0)                   # gap between letters
COLS.pop()
N = len(COLS)

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

def read_x():                        # x acceleration in g (same maths as accel.py)
    _cs.value = False
    _spi.write(_cmd)
    _spi.readinto(_buf)
    _cs.value = True
    v = (_buf[1] << 8) | _buf[0]
    if v & 0x8000:
        v -= 65536
    return (v >> 4) * 0.001

# ---------------- run statistics (printed as a report when you stop swinging) ----------------
Ts = []; peaks = []
n_locks = n_drops = n_loops = n_cols = n_skips = 0
n_odd = n_same = n_long = n_to = n_g1 = n_g2 = 0
first_lock_ms = None
t_locked = max_gap = xmax = pk = avg_pk = 0.0
sess_t0 = 0.0

def reset_stats():
    global Ts, peaks, n_locks, n_drops, n_loops, n_cols, n_skips
    global n_odd, n_same, n_long, n_to, n_g1, n_g2
    global first_lock_ms, t_locked, max_gap, xmax, pk, avg_pk
    Ts = []; peaks = []
    n_locks = n_drops = n_loops = n_cols = n_skips = 0
    n_odd = n_same = n_long = n_to = n_g1 = n_g2 = 0
    first_lock_ms = None
    t_locked = max_gap = xmax = pk = avg_pk = 0.0

def report(now, bias):
    n = len(Ts)
    print("POV> ===== run report v2: copy everything from here =====")
    print("POV> text=%s cols=%d SIGN=%d THRESH=%.2f WIDTH=%.2f SMOOTH=%.2f SHIFT=%.1fms EDGE=%.2f"
          % (TEXT, N, SIGN, THRESH, TEXT_WIDTH, SMOOTH, SHIFT_MS, EDGE_FLASH))
    print("POV> uptime=%.0fs (clock resolution ~%.2f ms)  bias=%+.3f g  max|x|=%.2f g%s"
          % (now, now / 4194.3, bias, xmax, "  ** CLIPPING (sensor range is +/-2 g) **" if xmax > 1.9 else ""))
    if n:
        mean = sum(Ts) / n
        sd = math.sqrt(sum((t - mean) ** 2 for t in Ts) / n)
        print("POV> half-swings=%d  T mean=%.1f ms (about %.1f Hz)  min=%.1f  max=%.1f  sd=%.1f ms"
              % (n, mean, 500.0 / mean, min(Ts), max(Ts), sd))
        print("POV> text column lasts ~%.2f ms at the swing centre" % (2 * TEXT_WIDTH / N * mean / math.pi))
    if peaks:
        print("POV> swing peak |a|: mean=%.2f g  min=%.2f g  arm level now=%.2f g"
              % (sum(peaks) / len(peaks), min(peaks), max(THRESH, 0.5 * avg_pk)))
    if first_lock_ms is not None:
        print("POV> locked after %.0f ms (first swing centre -> display on)" % first_lock_ms)
    print("POV> locks=%d  lost: same-direction=%d timeout=%d | ignored: too-close=%d  late=%d"
          % (n_locks, n_same, n_to, n_odd, n_long))
    if n_loops and t_locked > 0:
        print("POV> loop: %.0f loops/s, avg %.2f ms, worst gap %.1f ms, gaps >1ms=%d >2ms=%d (of %d)"
              % (n_loops / t_locked, 1000 * t_locked / n_loops, max_gap * 1000, n_g1, n_g2, n_loops))
    tot = n_cols + n_skips
    if tot:
        print("POV> columns shown=%d skipped=%d (%.0f%% missed)" % (n_cols, n_skips, 100.0 * n_skips / tot))
    print("POV> ===== end of report =====")

# ---------------- startup: hold still for 0.5 s to measure the resting x offset ----------------
t0 = time.monotonic()
tot = 0.0
cnt = 0
while time.monotonic() - t0 < 0.5:
    tot += read_x()
    cnt += 1
bias = SIGN * tot / cnt
print("POV> ready (v2). resting x offset %+.3f g. Wiggle left-right now." % bias)

armed = 0            # +1 after a strong +x peak, -1 after a strong -x peak
d = 0                # sweep direction: +1 = moving right, -1 = moving left
locked = False       # True once we trust the period estimate
sess_active = False
t_c = 0.0            # time the swing last passed through its centre
T = 0.15             # estimated half-period (extreme to extreme), seconds
prev_a = 0.0
prev_t = t_rd = prev_now = time.monotonic()
prev_locked = False
last_col = -1
last_mask = -1

while True:
    now = time.monotonic()

    # ---------- read the accelerometer and watch for the swing centre ----------
    if now - t_rd >= READ_S:
        xr = read_x()
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

        arm = 0.5 * avg_pk                       # a peak must reach half the typical peak
        if arm < THRESH:
            arm = THRESH
        if a > arm:
            armed = 1
        elif a < -arm:
            armed = -1
        cross = 0
        if armed == 1 and a <= 0:
            cross = 1                            # strong +, now through zero: centre, moving RIGHT
            armed = 0
        elif armed == -1 and a >= 0:
            cross = -1                           # centre, moving LEFT
            armed = 0

        if cross:
            den = prev_a - a
            tc = prev_t + (now - prev_t) * (prev_a / den if den else 0.0)
            if not sess_active:
                sess_active = True
                reset_stats()
                sess_t0 = tc
            accept = True
            if d != 0 and cross != d:
                half = tc - t_c
                if locked:
                    lo = 0.5 * T
                    hi = 1.6 * T
                else:
                    lo = MIN_HALF
                    hi = MAX_HALF
                if half < lo:
                    n_odd += 1                   # too close to the last centre: ripple, ignore it
                    accept = False
                elif half < hi:
                    if locked:
                        T += (half - T) * SMOOTH
                    else:
                        T = half                 # first good half-swing: trust it fully
                        locked = True
                        n_locks += 1
                        if first_lock_ms is None:
                            first_lock_ms = (tc - sess_t0) * 1000
                    if len(Ts) < 400:
                        Ts.append(half * 1000)
                        peaks.append(pk)
                    avg_pk = pk if avg_pk == 0.0 else avg_pk + (pk - avg_pk) * 0.3
                    if LIVE_PRINT:
                        print("POV> centre %s half=%.0f ms T=%.0f ms" % ("->" if cross == 1 else "<-", half * 1000, T * 1000))
                else:
                    n_long += 1                  # a swing was missed: keep T, just re-sync to this one
            else:
                if locked:
                    n_same += 1                  # two same-direction centres in a row: lost the beat
                    n_drops += 1
                locked = False
            if accept:
                pk = 0.0
                t_c = tc
                d = cross
        prev_a = a
        prev_t = now

    # ---------- housekeeping ----------
    if locked and now - t_c > 2.5 * T:
        locked = False                           # swinging stopped / lost it
        n_to += 1
        n_drops += 1
        avg_pk = 0.0                             # forget the old amplitude
    if sess_active and now - t_c > STOP_S:
        report(now, bias)
        sess_active = False
        locked = False
        d = 0
        armed = 0
        avg_pk = 0.0

    # ---------- draw: model the swing as a sine centred on the last crossing ----------
    mask = 0
    col = -1
    if locked:
        s = now - t_c + SHIFT_MS / 1000.0        # time since the swing centre
        if -0.3 * T < s < 1.3 * T:
            pos = d * math.sin(math.pi * s / T)  # -1 = left extreme, +1 = right extreme
            if EDGE_FLASH and abs(s - T / 2) < EDGE_FLASH * T:
                mask = 0xFFFF
            elif -TEXT_WIDTH <= pos < TEXT_WIDTH:
                col = int((pos / TEXT_WIDTH + 1) * 0.5 * N)
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
    