# PoV wand: project context for an agent

## What this is
A persistence-of-vision (PoV) wand. A vertical strip of 16 LEDs is waved left and right by hand. An accelerometer detects the swing, and the LEDs draw one column of an image or text at the right moment so the viewer sees a picture floating in the air. The owner (Harry) is not working in Claude Code. He edits `code.py` directly on the `CIRCUITPY` USB drive in VS Code and pastes serial-console output back into chat. Nothing is ever compiled.

## Hardware
- Board: RP2350 running CircuitPython 10.3.1.
- LEDs: 16 LEDs driven by cathode GPIO. `Leds("gpio")`, LED i = GP(18-i). LED 0 is the bottom and LED 15 is the top. `leds._cath` is the pin list. The two 74HC595 anode drivers are parked with all anodes high (the PCB has SHCP and STCP swapped, so they are not used).
- Accelerometer: SC7A20 on SPI GP19/20/22, CS GP24, SPI mode 3, 1 MHz, WHO_AM_I = 0x11.
  - Create `Leds` BEFORE `Accel`. `Leds` frees the SPI pins.
  - Registers: CTRL1 0x20 = 0x77 (400 Hz), CTRL4 0x23 = 0x88 | (FS << 4), with FS 0..3 = ±2/4/8/16 g.
  - Reads use the command byte 0x28|0xC0 with auto-increment. Value = signed 16-bit >> 4, times g per count.
  - `code.py` uses `acc._spi`, `acc._cs` and `acc._write` for a fast read path.
- Range is ±16 g. The nominal scale is about 12 mg/count, and it is re-measured from gravity at startup (accepted only if the board is still and 0.0003 < g/count < 0.05).
- Hand swings reach 15 to 20 g at the extremes. At ±2 g they clip, which is why the range was raised to 16 g.
- The serial console is COM27. Reports are lines starting with `POV>`.

## Device files (CIRCUITPY root)
| File | Purpose |
|---|---|
| `code.py` | All logic (about 730 lines). This is the only code file normally edited. |
| `lib/leds.py`, `lib/accel.py` | Hardware drivers. Do not change them unless asked. |
| `settings.txt` | User options as `KEY = value`, with `#` comments. Parsed tolerantly (BOM, case, bad lines produce warnings). |
| `message.txt` | Text to show. One line = full-height big letters. Two lines = half-height letters, one row above the other (top line LEDs 9..15, bottom line LEDs 0..6, shorter line centred). Only 2 lines are used. `~` draws a heart. |
| `image.bmp` | Black and white picture drawn in MS Paint. Loader handles 1/4/8/24/32 bpp uncompressed, bottom-up and top-down. Height is resampled to 16 rows keeping aspect ratio. Luminance threshold; `LIT = dark` lights the black pixels. |
| `blank_template.bmp`, `README.txt` | For non-coders. |

Saving any file on the drive reloads `code.py`. The board must be still for about 0.5 s afterwards, because that is when it measures gravity.

Code cannot write to the drive while the PC has it mounted. Diagnostics are printed to the serial console, and the owner pastes them back.

## Settings (settings.txt)
- `SHOW` = text | image | both. `both` alternates every `SECONDS`.
- `STRETCH`, `LIT`, `PASSES` = both | right | left, `FLIP_VERTICAL`, `SIGN` (1 or -1, flips left/right).
- `CALIBRATE` = yes shows a single bar at the swing centre. Two bars means the forward and reverse passes are misaligned.
- `SHIFT_MS`: latency compensation. Positive = draw later in the swing.
- `ANCHOR` = peaks | zero | auto. The default is **peaks** (since v6).
- `SHAPE` = auto or 0..1: blends the sine (0) and triangle (1) position models.
- `WIDTH` = percent of the full sweep the display uses. The default is 70.
- `DEBUG` = yes prints run reports.

Constants only in `code.py` (near the top): `THRESH` 0.4, `KP` 0.8, `KW` 0.6, `KI` 0.05, `E_MAX` 1.2, `OUT_MAX` 2, `HOLD` 2.5, `STOP_S` 1.0, `PEAK_DROP` 0.7, `MIN_HALF` 0.04, `MAX_HALF` 0.6, `READ_S` 2.5 ms, `PITCH_TEXT` 0.055, `PITCH_IMG` 0.075.

## How the algorithm works (code.py v6)
1. **Model.** The swing is a phase `phi`. Position = `-cos(phi)` (blended with a triangle by `shape_eff`). 0 = left extreme, π/2 = centre moving right, π = right extreme, 3π/2 = centre moving left. Column index = `int((pos/HALF + 1) * 0.5 * N)`, so the same picture appears on both passes. Content spans ±HALF = `min(WIDTH/100, N*pitch*STRETCH/2)`.
2. **Event detectors.**
   - Zero-crossing of de-biased acceleration after being armed by a peak above `arm`, with linear interpolation. Event codes +1/-1 (centre moving right/left).
   - Peak detector. A peak is "over" when the signal falls to `PEAK_DROP` of its maximum. Parabolic sub-sample refinement. +peak = left extreme (code +2), -peak = right extreme (code -2).
   - `arm = 0.4 * avg_pk`, never below `THRESH`.
   - `TARGET = {1: π/2, -1: 3π/2, 2: 0, -2: π}`.
3. **Tracker (`handle_event`).**
   - Events alternate, so the time since the previous event (accepted or not) is exactly half a swing. The tracker measures `wm = π/half` directly and moves `w` toward it by `KW` (only if 0.5·w < wm < 2·w).
   - The phase error `e` is measured after that speed update. `phi = ph + KP*e` and `w += KI*e*w/π`.
   - Events with |e| > `E_MAX` are outliers. After `OUT_MAX` in a row the tracker snaps to the sensor and re-syncs.
   - Holdover: after `HOLD` half-swings with no valid event it stops drawing. After `STOP_S` idle it prints the session report.
   - The "timing surprise" stat uses the error measured BEFORE adapting.
4. **Auto mode.** Crest factor (peak / rms per half-swing) is computed for all non-zero anchors. It sets `shape_eff = clamp((crest - 1.4)/2, 0, 1)` when `SHAPE = auto`. With `ANCHOR = auto` it also switches between zero-crossing and peaks (peaky if crest > 2.2, back to zero if < 1.8, with hysteresis).
5. **Draw.** `put(mask)` only writes changed pins. The CAL bar is shown for |pos| < 0.04. `PASSES` filters by the sign of sin(phi). The idle heartbeat blinks the bottom LED for 40 ms every 2 s, with a double blink meaning a file problem (see `warnings`).
6. **Report.** `POV> ===== run report v6` includes settings, mode, uptime and clock resolution, bias, max |x| (with a clipping flag against the raw count limit), half-swing stats, timing surprise, peak stats, lock time, lock/re-acquire/holdover/outlier counts, loop speed and gaps, and columns shown/skipped. With `DEBUG = yes` it also prints 600 raw samples (`POV> S t_ms:x_mg`) and the event list (`POV> C t_ms:code:used`).

## Key findings so far
- **Zero crossing is a time, not a place.** The zero crossing of acceleration is the moment of maximum speed. It is the spatial centre only for a pure sine swing. For flick-style swings, wrist rotation (gravity leaking into x) or uneven speed, it wanders, which produced two CAL bars and garbled text.
- **Peaks are the better anchor.** The extremes are where velocity is zero, independent of swing shape. The owner confirmed that peaks looked better on hardware. This needs ±16 g so the spikes are not clipped.
- **Remaining offset is constant latency.** `SHIFT_MS` is then a one-time hardware setting rather than a per-person one. Forward and reverse bars separate by twice the shift.
- **v5 tracker was slow.** In the owner's v5 log, 79 of 109 events were rejected as outliers because `w` was stuck at about 2.2 Hz while he swung at 3 to 4 Hz. v6 fixes this by following measured interval speed directly.
- **Edges were squished.** The swing is slow near its ends, so content is limited to the middle 70% (`WIDTH`).
- **Peak shapes in his trace.** His acceleration lobes are about 120 ms wide at about 4 Hz, with sharp 15 to 19 g peaks (crest about 1.6 to 1.75). `auto` therefore picked zero crossings, which is why `peaks` is now the default.
- **Clipping warning was a false alarm** (peaks reached 19.5 g with round tops).
- **Resting x bias** varies with tilt (0.1 to 0.8 g). Bias tracking handles it (fast when idle, slow when swinging).
- `time.monotonic()` float precision degrades with uptime. The report prints the clock resolution, so reset after hours of uptime.

## Status
v6 was verified only in simulation. It has not yet been run on hardware. Waiting on the owner: a `CALIBRATE = yes` run at steady speed, and one with deliberate speed changes. If bars still split, tune `SHIFT_MS` in 2 ms steps. If edges still squeeze, lower `WIDTH` to about 60. Whether the ±16 g register behaviour and the 12 mg/count scale are exact is unconfirmed (the ready line prints the measured value).

## Simulation harness (agent workspace only)
Not on the device. In the scratchpad `v6/` directory: `sim5.py` runs a copy of `code.py` in CPython with stubbed `leds`/`accel` modules and a generated swing signal. It takes the swing shape (sine or flick), jitter `J`, ripple, latency `LAT_MS`, an optional frequency profile `fprof` and amplitude `Ag`. Scoring scripts: `t_anchor.py` (pass separation), `t_tempo.py` (speed-change test), `t_retina.py`, `t_bmp.py`, `t_frames.py`.
- The harness replaces the `/settings.txt`, `/message.txt` and `/image.bmp` paths with a temp dir.
- It uses `contextlib.redirect_stdout` process-wide, so write your own output to `sys.__stdout__`.
- Runs take real time (about 8 to 15 s each) and can be run in parallel.
- Sim caveat: the pure-sine case scores poorly with every anchor, so treat the flick results as the relevant ones.

## Working conventions
- Only change `code.py` (and the text and settings files). Keep `lib/` separate unless asked.
- Output must be plain CircuitPython the owner can copy straight onto the drive. Never ask him to compile.
- The owner is not a coder. Keep user-facing instructions short and concrete. Update `README.txt` and `settings.txt` when adding options.
- Hardening is deliberate: bad settings lines, missing or corrupt files, and odd encodings fall back with warnings and never crash.
- Be honest about what is simulated versus hardware-verified.

## Ideas not built yet
Flipbook animation (multiple BMPs, advance per swing), scrolling long text across swings, live swing-speed or peak-g readout as digits, shake or tilt to change messages, playlist mode, constant physical text size by estimating swing amplitude, and double-integrating acceleration with zero-velocity resets at the extremes for true position if blur persists.
