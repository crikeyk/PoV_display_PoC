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
- The serial console is COM27 on the owner's Windows notes. On this ThinkCentre it is `/dev/ttyACM0` (`2e8a:000b`, Pico 2). Reports are lines starting with `POV>`.

The copy in this repo is `Firmware/device/`. Those files are what get copied onto the drive. `Firmware/debug/` is not part of that copy.

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
- `CALIBRATE` = yes shows three thin bars (left edge of the word, centre, right edge). Moving right lights the top half of the LEDs. Moving left lights the bottom half. Stacked bars mean the passes agree. Leave it off to show the words.
- `SHIFT_MS`: latency compensation, in milliseconds. Positive = draw later in the swing. Hardware value is **6**.
- `ANCHOR` = peaks | zero | auto. The default is **peaks**.
- `SHAPE` is parsed but **v7 does not use it**. The picture is always a sine. A triangle position was measured and rejected.
- `WIDTH` = percent of the full sweep the display uses. The default is **60**.
- `DEBUG` = yes prints a run report after the swing stops. Default is no.

Constants only in `code.py` (near the top): `THRESH` 0.4, `KP` 0.2, `KW` 0.3, `KI` 0.05, `E_MAX` 1.2, `OUT_MAX` 2, `HOLD` 2.5, `STOP_S` 1.0, `PEAK_DROP` 0.7, `MIN_HALF` 0.04, `MAX_HALF` 0.6, `READ_S` 2.5 ms, `PITCH_TEXT` 0.055, `PITCH_IMG` 0.075.

## How the algorithm works (code.py v7)
1. **Model.** One oscillator for both directions. Position = `-cos(phi)`, not a triangle and not a per-direction timer. 0 = left extreme, π/2 = centre moving right, π = right extreme, 3π/2 = centre moving left. Column index = `int((pos/HALF + 1) * 0.5 * N)`, so the same picture appears on both passes. Content spans ±HALF = `min(WIDTH/100, N*pitch*STRETCH/2)`.
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
4. **Auto mode.** Crest factor (peak / rms per half-swing) is still computed. `shape_eff` is no longer used for the picture. With `ANCHOR = auto` the crest still switches between zero-crossing and peaks (peaky if crest > 2.2, back to zero if < 1.8, with hysteresis). The shipped setting is `ANCHOR = peaks`.
5. **Draw.** `put(mask)` only writes changed pins. The live oscillator still moves by `KP` (0.2) and `KW` (0.3) at each peak, but the LEDs do not. While the wand is inside the word, drawing uses a frozen copy of the pace and phase. That copy is kept until the drawn direction reverses, so a peak that is only detected after the turn (signal fallen to `PEAK_DROP`) cannot skip a letter. The updated pace is used on the next pass. Outside the word, drawing follows the live oscillator. Calibration draws three bars at `pos` near `-HALF`, `0`, and `+HALF`. `PASSES` filters by the sign of sin(phi). The idle heartbeat blinks the bottom LED for 40 ms every 2 s, with a double blink meaning a file problem (see `warnings`).
6. **Report.** Only when `DEBUG = yes`, after the wand has been still for `STOP_S`. `POV> ===== run report v7` includes settings, uptime and clock resolution, bias, max |x|, half-swing stats, timing surprise, peak stats, lock counts, loop speed, and columns shown/skipped. The ready line is `POV> ready (v7)`.

## Key findings (hardware, 14 Oct 2026, GPIO cathode wand)

These were watched on the RP2350 wand with top-half / bottom-half calibration bars, then checked against a 27 s raw capture (`Firmware/debug/capture/`). The CH572 board was not part of this.

- **One slow oscillator, not a timer per pass.** Remembering the last left-to-right time and the last right-to-left time made the right-going bars dance. Drawing both passes from `pos = -cos(phi)` with `KP = 0.2` and `KW = 0.3` made them sit together, and a speed change settled after a few swings. Harry asked for that and then confirmed it.
- **`SHIFT_MS = 6`.** At 0 the bottom (left-going) bars sat about 2 cm left of the top. At 3 ms the gap was about 1 cm, top still to the right, so the flash was late. 6 ms with the slow loop looked aligned.
- **`WIDTH = 60`.** The ends of the stroke are where the wand is braking. 70 pulled the Y of MERRY into that zone.
- **The acceleration is a bit more triangular than sinusoidal, and nothing like a square** (fit R² about 0.77, 0.76, and 0.56 on the 13 s capture). Position is the double integral of that, which stays within about 1 ms of `-cos(phi)`. A constant-speed triangle would move the outer bars by about 10 ms. v7 does not draw a triangle.
- **Amplitude is not what garbles the letters.** Placement uses phase only. Faster swinging raised the peaks from about 7 g at 4.1 Hz to about 10 g at 5.9 Hz, and the arc got shorter, so the word shrinks. The same few milliseconds of phase error then cover more columns (about 1.6 ms/column at 4.1 Hz, 1.1 ms at 5.9 Hz).
- **Tell people to swing briskly.** Around 3.5–4.5 Hz fuses. Near 1.5 Hz the picture bunches and the tracker loses it. Preferred test pace on this wand was about 4.3–4.8 Hz.
- **Gravity scale is about 7.77 mg/count** when the board is still for the first 0.5 s. If it is moving, the scale falls back to the nominal 12 mg/count and every g reading is about 1.55× high. Bar positions do not depend on that scale.
- **Peaks line up with the oscillator. The zero crossing does not.** It sits near 57% of the half, not 50%, in both directions. The acceleration stays positive past the centre, then drops. That is the remaining shape error, about a millisecond at the outer bars, smaller than the peak-timing scatter.
- **Phase scatter is still about 9 ms rms** (roughly 6–8 columns) because the loop only looks at the two peaks, which are the flat tops. Mean error of the two directions agreed to within a couple of milliseconds on the 27 s capture (4.7 Hz, no clipping, max |x| 14 g). Skipped columns were 0%. The loop itself is about 0.2 ms.
- **Do not double-integrate the live acceleration.** The running integral drifted (fractions like 0.28, 1.51, 5). A Hackaday wand that tried the same thing reports the same failure.

## Key findings so far
- **Zero crossing is a time, not a place.** The zero crossing of acceleration is the moment of maximum speed. It is the spatial centre only for a pure sine swing. For flick-style swings, wrist rotation (gravity leaking into x) or uneven speed, it wanders, which produced two CAL bars and garbled text.
- **Peaks are the better anchor.** The extremes are where velocity is zero, independent of swing shape. The owner confirmed that peaks looked better on hardware. This needs ±16 g so the spikes are not clipped.
- **Remaining offset is constant latency.** `SHIFT_MS` is then a one-time hardware setting rather than a per-person one. Forward and reverse bars separate by twice the shift.
- **v5 tracker was slow.** In the owner's v5 log, 79 of 109 events were rejected as outliers because `w` was stuck at about 2.2 Hz while he swung at 3 to 4 Hz. v6 fixes this by following measured interval speed directly.
- **Edges were squished.** The swing is slow near its ends. v7 keeps the word in the middle 60% (`WIDTH`).
- **Peak shapes in his trace.** His acceleration lobes are about 120 ms wide at about 4 Hz, with sharp 15 to 19 g peaks (crest about 1.6 to 1.75). `auto` therefore picked zero crossings, which is why `peaks` is now the default.
- **Clipping warning was a false alarm** (peaks reached 19.5 g with round tops).
- **Resting x bias** varies with tilt (0.1 to 0.8 g). Bias tracking handles it (fast when idle, slow when swinging).
- `time.monotonic()` float precision degrades with uptime. The report prints the clock resolution, so reset after hours of uptime.

## Status
The files to put on a wand are in `Firmware/device/`. Copy the contents of that folder onto `CIRCUITPY`. Do not copy `Firmware/debug/`.

Stable v6, the program before the frozen-pace change, is git tag `v6`. In that tag it is `Firmware/device_pull_v1/code.py`. Check the tag out, or `git show v6:Firmware/device_pull_v1/code.py`, to get it back. Do not keep a second device folder in the working tree.

v7 shows `MERRY` / `XMAS`, calibration off, `SHIFT_MS = 6`, `WIDTH = 60`, peak anchor, sine position, slow PLL (`KP = 0.2`, `KW = 0.3`). Once a pass is inside the word, the pace is frozen until the wand turns around. Harry waved that build and said it already seemed better. The lock-in phase detector below is not built. The startup gravity measurement is still there; a moving boot falls back to 12 mg/count and does not move the letters.

After a swing has already stopped, v7 appends one line to `/log.txt` (the last 30 swings: pace, timing surprise, peak g, skipped columns). The draw loop does not print and does not record samples. A write is skipped if the drive is mounted on the PC. `DEBUG = yes` still prints the long serial report and is left off.

## Provisioning a new RP2350 wand
CircuitPython for these boards is `Firmware/circuitpython-pico2-10.3.1.uf2` (Pico 2, 10.3.1). A blank chip enumerates as `2e8a:000f` with a volume labelled `RP2350`. Copy the uf2 onto that volume. The board reboots as `2e8a:000b` and a volume labelled `CIRCUITPY`. Mount it with `udisksctl mount -b` (harry can, no sudo). Copy the contents of `Firmware/device/` onto it, `code.py` last, via a temp file then `sync` then `mv`. That folder is:

- `code.py`, `settings.txt`, `message.txt`, `README.txt`
- `lib/leds.py`, `lib/accel.py`
- `image.bmp`, `blank_template.bmp`
- `sd/placeholder.txt`

Leave the board still for the first half-second after the last copy. The ready line is `POV> ready (v7)` and `POV> showing: text (29 columns)`. Do not copy `Firmware/debug/capture_code.py`, the capture files, or anything from the CH572 tree.

A factory Pico 2 already has a tiny program in flash, so it will not offer the `RP2350` drive unless BOOTSEL is held while it is plugged in. Do not copy `code.py` onto a board that has not been given the uf2.

Both new wands, 14 Oct 2026, CircuitPython 10.3.1 then v7, text, 29 columns:

- UID `1B249BCCC34D6D79`, 7.85 mg/count
- UID `6C2B702F4CF72D30`, 7.76 mg/count

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
- **Lock-in phase detector.** Multiply each acceleration sample by the oscillator sine and average over the half. The steep middle then times the swing, instead of the flat peaks. Same slow `KP`/`KW`, still one clock for both directions. This is the change aimed at the 9 ms scatter. Clock recovery does this; it was not loaded.
- A gyro, integrated to angle, is what the Cornell 2025 POV wand and spinning-poi designs use for column spacing. This board has no gyro. A full-revolution gravity PLL (the poi trick) does not apply to a back-and-forth wave.
- Flipbook animation, scrolling long text, a live pace readout, shake or tilt to change messages, playlist mode. Constant physical text size was considered and dropped: amplitude does not set letter spacing.

## This one board: CH572 bring-up (13 Oct 2026)

The GPIO-cathode wand above was tuned to v7 on 14 Oct 2026. This section is a different board, the CH572 bring-up. Do not flash the CH572, and do not change its firmware, unless that work is the task. The CH572 board does **not** use the v7 `code.py`.

This board is the one Harry is using to prove the CH572 path. On it, in hardware only (the KiCad file still shows the old swap):

- The 74HC595 SHCP/STCP swap is fixed. SCK is the shift clock. `CS_SR` / PA11 is the latch (STCP), rising edge.
- The DNP 0 Ω links that make the CH572 the SPI master are fitted: PA7 MOSI (R46), PA6 MISO (R43), PA5 SCK (R45), PA10 `CS_ACC` (R44, active low), PA11 latch (R42).
- The SPI and interrupt resistors from the RP2350 to that bus have been removed, so the RP2350 no longer touches MOSI, MISO, SCK, `CS_ACC`, `CS_SR`, INT1, or INT2. Cathodes GP3..GP18 are still wired. LED i cathode = GP(18−i). Low cathode = LED on, while an anode is high.
- PA4 (INT1, R49) and PA2 (INT2, R50) stay inputs. Do not put UART RX on PA2.
- Crystal is 32 MHz, 12 pF. Firmware must use `HSECap_12p`. Antenna is AE1.
- The CH572D is BLE 5.0 peripheral/broadcaster only. It cannot scan, it cannot be a central, and it has no Wi-Fi. The bring-up advertises the name `POV-CH572`. A phone scanner is the radio check. This ThinkCentre has no BLE dongle.

There is one USB cable. J2 is the RP2350. J4 is the CH572 (PA0 USB D− through R39 22 Ω, PA1 USB D+ through R40 22 Ω). R1 and R34 are 0 Ω, so either connector powers both chips from `+5V_USB`. Moving the cable moves the data connection and keeps the other chip powered.

PA8 is the reset pin the WCH eval-board note asks for, not the USB boot pin. R47 is 1 kΩ from PA8 to `+3V3_WCH`. S3 is the tactile button on the board. It shorts PA8 to ground through R53 (0 Ω). `CFG_RESET_EN` is clear, so that button does not reset the chip, and it is not a bootloader button. Holding PA8 low holds the chip in reset and USB never appears. Do not press S3 to enter the bootloader.

### Programming this chip

This is the section a new agent should follow. The chip already has an application on it. A plain replug of J4 boots that application (`1a86:8040`). It does not enter the bootloader.

#### Tools on this machine

- Toolchain: `/home/harry/opt/Toolchain/RISC-V Embedded GCC12/bin/riscv-wch-elf-gcc`. `make` is not installed. Build with [Firmware/ch572/build.sh](Firmware/ch572/build.sh).
- `-march` must not include both `m` and `zmmul`. The working arch is `rv32i2p0_m2p0_c2p0_zba1p0_zbb1p0_zbc1p0_zbs1p0_xw2p2`.
- `./build.sh A` writes `Firmware/ch572/build/pov-A.bin`. `./build.sh B` writes `pov-B.bin`. The images are the same except the repeating log line says `fw=A` or `fw=B`.
- PyUSB is not installed as a package. It is unpacked at `/home/harry/opt/pyusb-1.2.1`. Run Python tools with `PYTHONPATH=/home/harry/opt/pyusb-1.2.1`.
- Flasher library: `/home/harry/opt/chprog.py` (wagiminator chprog 2.5.3). It knows chip id `0x1372`, 245760 bytes of code flash. Do not use its stock `flash()` and trust the "Verifying" line. It treats write status `0xfe` as success.
- `/home/harry/opt/wchisp-linux-x64/wchisp` is 0.3.0 and does not know the CH572. The nightly at `/home/harry/opt/wchisp-nightly/wchisp-linux-x64/wchisp` does (it still prints version 0.3.0) and has `wchisp config unprotect`.
- Host script: [Firmware/ch572/host_session.py](Firmware/ch572/host_session.py). `flash <bin>` erases, writes, requires status `0x00` on every chunk, verifies, then reboots. If a write returns `0xfe` it sends the unlock below once and retries. `enter` writes `boot\n` to the running CDC device and waits for `1a86:55e0`. `probe` is the old protect experiment. A reboot is sent only after verify has passed.

#### How to load an image

The serial `boot` command does **not** enter the ROM bootloader yet. See the handover below. Until that works, every image load needs the PA1 strap, and a process must already be waiting on `1a86:55e0` before the cable goes in. The bootloader drops off the bus after about 10 seconds if nothing opens it, and the LED chase then starts again. That looks like a failed strap.

Start the writer first:

`PYTHONPATH=/home/harry/opt/pyusb-1.2.1 python3 Firmware/ch572/host_session.py flash Firmware/ch572/build/pov-A.bin`

It polls for `1a86:55e0` and programs as soon as that id appears. Do not wait for the LEDs to look special. A tone or a log line `BOOTLOADER_PRESENT` is the signal that the PC saw it.

Recovery strap, which is also the only path that works today:

1. Unplug the USB cable from both J2 and J4. One cable powers both chips, so leaving it in J2 keeps the CH572 powered.
2. Hold PA1 at 3.3 V while the chip is unpowered. PA1 is USB D+ through R40 (22 Ω). Plug J4, then let go as soon as the connector is seated.
3. Do not keep holding PA1 while the host enumerates. That produces `device descriptor read/64, error -71` and the bootloader never appears. Letting go before the chip is powered produces a clean `1a86:8040` and the old application.
4. A successful entry on this machine was a brief `-71`, then `1a86:55e0` (kernel port `usb 1-4`). The two that worked were 23:06 and 23:21 on 13 Oct 2026. Later plugs the same evening all came back as `1a86:8040`. Harry could not repeat the strap at handover.
5. Do not press S3. That is PA8, and it is not the download pin.
6. `CFG_BOOT_EN` is set, so the ROM bootloader is still there.

`enter` writes `boot\n` to endpoint `0x01` and waits 20 seconds for `1a86:55e0`. On the image in flash today that resets the chip (`ENTER_SENT`, USB drops) and the application enumerates again about one second later (`ENTER_GONE`). It is safe. It does not brick the part. It also does not open the bootloader.

#### The protect-byte failure (13 Oct 2026)

The first programming attempts reached the bootloader, erased, and then verify failed. That was code-flash protection, not USB, not the XOR key, and not the image.

- Identify, config read, the XOR-key checksum, and erase (`0x00`) all worked. Chip CH572, id `0x1372`, family `0x13`, bootloader 2.3.0, UID `ca14f2e566e422df`, XOR key `0000000000000072`.
- Config word 0 was `ffffffff`. In that state every `0xA5` program packet, including the empty commit, returned `fe 00`. Verify of an 8-byte write returned `0x05`. Verify of a 56-byte chunk returned `0x35`. The chip still enumerated as the bootloader afterwards, so nothing was stored.
- `0xfe` means the bootloader rejected the program. chprog treats `0x00`, `0xfe`, and `0xf5` as success, which is why it printed "Verifying" when flash had not changed. On this chip only `0x00` means the bytes were stored.
- The fix is config-write command `0xA8`, mask `0x07`, first two bytes `a5 5a`, leaving the other ten config bytes alone. The next config read began `a55a`. The same 8-byte write then returned `0x00` for the data packet, the empty commit, and the verify, with no power cycle. The 97776-byte image followed in that session.
- Family `0x13` is not in wchisp's code-flash-protect list, and chprog does not unlock it. The unlock still works on this chip and it persisted.
- The same unlock rewrote `USER_CFG` from `0x403a0040` to `0x40ff0040`. `CFG_BOOT_EN` (bit 6) is still set. `CFG_RESET_EN` (bit 3) is still clear. `CFG_ROM_READ` (bits 23..16) is now `0xFF` instead of `0x3A`. The datasheet calls `0xFF` "keep the program secret". USB programming still worked. A working CH570 eval board has been seen with `CFG_ROM_READ = 0xFF` as well. Do not write that word back to `0x3A` unless debug readout is required.
- Three write framings were tried while the chip was still protected (remaining-length byte plus XOR, padding `0` plus XOR, and plaintext). All were rejected the same way. The framing was not the bug. The host script uses padding `0` plus XOR, an empty commit packet, a 1 s pause after erase, and a fresh key exchange before verify.

#### What is on the chip, and what is only built

Built against the openwch/ch570 EVT at `Firmware/third_party/ch570` (a build dependency, not wand source). BLE stack + USB CDC + the application fit in 12 KB RAM.

**In flash now** (programmed 23:21, verified): the previous `fw=A` image, 98176 bytes. Log line `POV> fw=A who=11 x=… y=… z=… mg`, about 1 g on a still board (`z` near 980, `x` near 515). One LED walks from the bottom (LED 0) to the top (LED 15). Its `boot` sequence writes ROM config `0x80`. Config at that program was `a55affffffffffff4000ff40`. The chip is healthy and enumerates as `1a86:8040`.

**Built, not programmed:** `Firmware/ch572/build/pov-A.bin` and `pov-B.bin`, 98172 bytes, one byte different (`fw=A` vs `fw=B`). The chase walks from the top (LED 15) down to the bottom (LED 0), so a successful write is obvious against the image in flash. The `boot` sequence writes ROM config `0x40`. These files were never sent. The writer that was waiting for them was stopped at handover.

- Column map matches `Firmware/leds.py` `_LED_TO_STAGE`: U4 Q0..Q7 = LEDs 0..7, U5 Q0 = LED 15, U5 Q1..Q7 = LEDs 8..14. Sixteen bits, MSB first, bit 0 lands in U4 Q0. SPI mode 0 for the 595s, mode 3 for the SC7A20. Latch stays high during accelerometer reads.
- BLE scan response name `POV-CH572` (9 characters, AD length `0x0A`). The periodic task in `Firmware/ch572/src/peripheral.c` is started from `Peripheral_Init` and is not stopped on disconnect, so the chase runs with no phone connected.
- USB CDC on J4 prints lines starting `POV>`. The repeating line is `POV> fw=A who=11 x=.. y=.. z=.. mg` (or `fw=B`). `who=11` is the accelerometer. A still board reads about 1 g on one axis. `POV> advertising POV-CH572` is printed once at startup and is missed if the port is opened late. `board_log` gives up on a line if the host never ACKs an IN transfer. The accelerometer line repeats about once a second.
- The line `boot` on the CDC OUT endpoint (CR and LF ignored) is recognized. `board_poll()` in `Firmware/ch572/src/board.c` watches `Ep1DataOUTFlag`. It logs `POV> boot` and resets the chip. It has never come back as `1a86:55e0`.

#### Software reset into the ROM (not working)

Datasheet text for `RB_SOFTWARE_RESET`: boot from ROM only when `RB_WDOG_INT_EN` is 1, `RB_ROM_CODE_WE` is configured as 1, `RB_ROM_DATA_WE` is 0, and `128 <= R8_WDOG_COUNT < 192`. Otherwise the same bit resets into the application. This header has no `RB_ROM_DATA_WE`. Bits 7:6 of `R8_GLOB_ROM_CFG` (`0x40001044`, same address as the read-only reset-status byte, writable only in safe-access mode) are one field:

| Value | Bits 7:6 | Datasheet |
| --- | --- | --- |
| `0x00` / `0x80` | x0 | erase/write protected |
| `0x40` | 01 | erase/program 129–240 KB only |
| `0xC0` | 11 | erase/program 0–240 KB |

On the older CH571/CH573 map, bit 7 is `RB_ROM_CODE_WE` (`0x80`) and bit 6 is `RB_ROM_DATA_WE` (`0x40`). `RB_ROM_CODE_WE` in `CH572SFR.h` is the whole `0xC0` mask. Safe-access mode (`0x57` then `0xA8` to `0x40001040`) lasts about 16 cycles (`CH57x_sys.h`). Write `0` to that register before opening it again. `R8_WDOG_COUNT` is ordinary RW. `R8_RST_WDOG_CTRL` is safe-access: `RB_WDOG_INT_EN` is `0x04`, `RB_SOFTWARE_RESET` is `0x01`.

Two sequences were programmed and both reset into the application within about a second (USB drop, then `1a86:8040`, same `fw=A`):

1. `R8_GLOB_ROM_CFG = 0xC0`, then `RB_WDOG_INT_EN`, then count 160, then a second safe-access window for `RB_WDOG_INT_EN | RB_SOFTWARE_RESET`. The second window was opened without writing `0` first, so the `0xC0` write is not a clean test.
2. What is in flash now. `FLASH_ROM_SW_RESET()`, count 160, then one window of consecutive `sb` instructions in `.highcode`: signature, signature, ROM config `0x80`, watchdog `0x04`, watchdog `0x05`. The reset store did execute. `0x80` is the protected encoding, so the boot test would not see the field as 1.

Not flashed: the same tight window with ROM config `0x40` (field value 1, the literal reading of "configured as 1"). That is the source and the `pov-A.bin` / `pov-B.bin` on disk. If `0x40` also returns as `1a86:8040`, stop guessing at this sentence. A loader in the application that receives the next image on the CDC port and calls the flash ROM write is the reliable software path. A dead image still needs PA1.

Do not leave the chip mid-write. `host_session.py` reboots only after every verify chunk returns `0x00`. A non-blank chip will not re-enter the bootloader on a replug.

#### Host access

Host is `harry-ThinkCentre-M900`, user `harry`. `sudo` needs a password and cannot be used from the agent. These root-installed rules already work:

- `/etc/polkit-1/rules.d/50-udisks-harry.rules` lets `harry` `udisksctl mount` removable disks with no password. `CIRCUITPY` was mounted at `/run/media/harry/CIRCUITPY`.
- `/etc/udev/rules.d/99-pico-plugdev.rules` puts Pico serial ports (`2e8a` and `239a`) in group `plugdev`.
- `/etc/udev/rules.d/99-wch-boot.rules` puts USB devices `1a86:55e0`, `4348:55e0`, and `1a86:8040` in group `plugdev`, mode `0660`. It does not change `/dev/ttyACM0`.

`/dev/ttyACM0` stays `root:dialout`. `harry` is in `dialout`, but this agent process will not see that group until Cursor is restarted, so the agent reads and writes the CDC port with pyusb on the USB device node (OUT `0x01`, IN `0x81`) after detaching `cdc-acm` from the data interface. Detaching drops the tty node until something rebinds the driver. A replug of J4 restores a normal dialout tty and boots the application, not the bootloader.

The CH572 is on kernel port `usb 1-4`. After a failed ISP command the IN endpoint often stalls. `lsusb` can still show `1a86:55e0` while pyusb reads time out. `clear_halt` does not recover that. Replug J4. Do not press S3.

On J2 the RP2350 enumerates as `2e8a:000b` "Pico 2" and exposes a 1 MB FAT volume labelled `CIRCUITPY` plus a serial port. CircuitPython is 10.3.1. The drive's `code.py` is the sink script also saved as `Firmware/ch572/rp2350_blink.py`: GP3..GP18 outputs held low, then `while True: pass`. That keeps the LED cathodes low while the CH572 drives the anodes. It keeps running when the cable moves to J4, because the 5 V rail is shared. `code_v6.bak.py` on that drive is the old wand program. Do not change the other wands' firmware while finishing this board.

#### Handover (13 Oct 2026, 23:38)

No flasher and no beep watcher are running. Do not start one until Harry has a strap that actually produces `1a86:55e0`. He asked to stop after several plugs that all came back as the application.

Next agent:

1. Read this section before touching the chip. The part is not blank and not bricked.
2. The image to flash, once the bootloader is up, is `Firmware/ch572/build/pov-A.bin` (top-to-bottom LEDs, `boot` uses `0x40`). Then `enter`, and if `1a86:55e0` appears, flash `pov-B.bin` and confirm `fw=B`. That is the proof the serial path works.
3. If `boot` on that new image still returns as `1a86:8040`, do not try more ROM-config bytes without a new reason. Switch to an in-application loader over CDC.
4. Log of the sessions is `/tmp/ch572_session.log`. Kernel USB messages for port `usb 1-4` are the ground truth for which id enumerated. `lsusb` at handover was not rechecked after the last `8040` at 23:33.
