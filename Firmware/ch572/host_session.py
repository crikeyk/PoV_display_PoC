#!/usr/bin/env python3
"""Flash the CH572, or ask the running image to enter the ROM bootloader.

  host_session.py flash <bin>   erase, program, verify, reboot
  host_session.py enter         send "boot" on the CDC port and wait for 1a86:55e0
  host_session.py probe         the original protect/verify experiment

A program packet is stored only when its status is 0x00. Status 0xfe is the
protected-flash rejection. The a5 5a unlock is sent once in that case.
A reboot is sent only after every verify chunk returns 0x00.
"""
import importlib.util
import os
import subprocess
import sys
import time

spec = importlib.util.spec_from_file_location("chprog", "/home/harry/opt/chprog.py")
ch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ch)

IMAGE = "/home/harry/dev/PoV_display_PoC/Firmware/ch572/build/pov-A.bin"
USER_CFG_OK = (
    bytes.fromhex("40003a40"),  # value before the first unlock
    bytes.fromhex("4000ff40"),  # value the unlock left in USER_CFG
)
RAW8 = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
LOG_PATH = "/tmp/ch572_session.log"


def log(msg):
    line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG_PATH, "a") as fh:
        fh.write(line + "\n")


def beep():
    for _ in range(3):
        subprocess.Popen(
            ["pw-play", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.12)


def find_bootloader():
    return ch.usb.core.find(idVendor=0x1A86, idProduct=0x55E0)


def find_cdc():
    return ch.usb.core.find(idVendor=0x1A86, idProduct=0x8040)


def find_pico():
    return ch.usb.core.find(idVendor=0x2E8A, idProduct=0x000B)


def find_bootsel():
    return ch.usb.core.find(idVendor=0x2E8A, idProduct=0x000F)


def wait_for(kind, seconds, announce):
    """kind is 'boot' or 'any'. Returns 'boot', 'cdc', 'pico', or None."""
    if announce:
        log("WAITING_FOR_BOOTLOADER plug J4, do not press the button")
    deadline = time.time() + seconds
    next_note = time.time() + 10
    pico_noted = False
    bootsel_noted = False
    cdc_noted = False
    while time.time() < deadline:
        if find_bootloader() is not None:
            log("BOOTLOADER_PRESENT")
            beep()
            return "boot"
        if find_cdc() is not None:
            if kind != "boot":
                log("CDC_PRESENT")
                return "cdc"
            if not cdc_noted:
                log("CDC_PRESENT application on J4, strap missed")
                cdc_noted = True
        else:
            cdc_noted = False
        if find_pico() is not None and not pico_noted:
            log("SEEN_PICO cable is on J2, the CH572 socket is the other one")
            pico_noted = True
        if find_bootsel() is not None and not bootsel_noted:
            log("SEEN_RP2350_BOOTSEL cable is on J2, the CH572 socket is the other one")
            bootsel_noted = True
        if time.time() >= next_note:
            log("STILL_WAITING")
            next_note = time.time() + 10
        time.sleep(0.2)
    log("WAIT_TIMEOUT")
    return None


def xfer(isp, stream, label, timeout=5000, quiet=False):
    cmd = stream[0]
    try:
        isp.dev.write(ch.CH_USB_EP_OUT, bytes(stream), timeout)
    except ch.usb.core.USBError as ex:
        log("%s WRITE_FAIL %s" % (label, ex))
        return None
    try:
        reply = bytes(isp.dev.read(ch.CH_USB_EP_IN, ch.CH_USB_PACKET_SIZE, timeout))
    except ch.usb.core.USBError as ex:
        log("%s READ_FAIL %s" % (label, ex))
        return None
    status = reply[4] if len(reply) > 4 else None
    echo_ok = bool(reply) and reply[0] == cmd
    if not quiet or status != 0x00 or not echo_ok:
        log("%s %s st=%s %s" % (
            label, reply.hex(),
            "none" if status is None else "%02x" % status,
            "ok" if echo_ok else "ECHO_MISMATCH"))
    return reply


def status_of(reply):
    if reply is None or len(reply) < 5:
        return None
    return reply[4]


def packet(mode, addr, blob, marker):
    body = addr.to_bytes(4, "little") + bytes([marker]) + blob
    return bytes((mode, len(body) & 0xFF, (len(body) >> 8) & 0xFF)) + body


def xor_with(key, blob, addr=0):
    return bytes(b ^ key[(addr + i) % 8] for i, b in enumerate(blob))


def connect():
    isp = ch.Programmer()
    for ep in (ch.CH_USB_EP_OUT, ch.CH_USB_EP_IN):
        try:
            isp.dev.clear_halt(ep)
        except Exception as ex:
            log("clear_halt %02x %s" % (ep, ex))
    isp.detect()
    cfg = bytes(isp.configdata)
    log("chip %s id %04x boot %s" % (isp.chipname, isp.chipid, isp.bootloader))
    log("config %s" % cfg.hex())
    log("uid %s key %s" % (bytes(isp.chipuid).hex(), bytes(isp.xorkey).hex()))
    if cfg[8:12] not in USER_CFG_OK:
        log("CONFIG_UNEXPECTED user word %s" % cfg[8:12].hex())
    return isp


def read_config(isp):
    reply = xfer(isp, bytes(ch.CH_STR_CONFIG_READ), "config_read")
    if reply is None or len(reply) < 18:
        return None
    cfg = bytes(reply[6:18])
    log("config_now %s" % cfg.hex())
    return cfg


def verify_at(isp, addr, raw, marker, label, quiet=False):
    blob = xor_with(isp.xorkey, raw, addr)
    return status_of(xfer(
        isp, packet(ch.CH_CMD_CODE_VERIFY, addr, blob, marker), label, quiet=quiet))


def length_sweep(isp, tag):
    pattern = bytes([0xA5]) * 56
    got = []
    for n in (4, 8, 16, 32, 56):
        st = verify_at(isp, 0, pattern[:n], 0, "sweep_%s_%d" % (tag, n))
        got.append((n, st))
    nums = [st for _, st in got if st is not None]
    if nums and nums == [n - 3 for n, _ in got]:
        log("SWEEP_%s DECODE_N_MINUS_3 %s" % (tag, got))
    else:
        log("SWEEP_%s %s" % (tag, got))
    return got


def ff_oracle(isp, tag):
    raw = bytes([0xFF]) * 56
    st = verify_at(isp, 0, raw, 0, "oracle_%s" % tag)
    log("ORACLE_%s %s" % (tag, "none" if st is None else "%02x" % st))
    return st


def mismatch_probe(isp):
    """After an erase, status versus how many bytes differ from 0xFF."""
    for differ in (0, 4, 8):
        raw = bytearray([0xFF]) * 8
        for i in range(differ):
            raw[i] = 0x00
        st = verify_at(isp, 0, bytes(raw), 0, "mismatch_differ_%d" % differ)
        log("MISMATCH differ=%d st=%s" % (differ, "none" if st is None else "%02x" % st))


def erase_kb(isp, kb, label):
    if kb < 8:
        kb = 8
    stream = (ch.CH_CMD_CODE_ERASE, 0x04, 0x00, kb & 0xFF, (kb >> 8) & 0xFF, 0x00, 0x00)
    reply = xfer(isp, stream, label, timeout=15000)
    return status_of(reply)


def rekey(isp):
    total = 0
    for b in isp.xorkey:
        total = (total + b) & 0xFF
    reply = xfer(isp, bytes((ch.CH_CMD_KEY_SET, 0x1E, 0x00)) + bytes(0x1E), "rekey")
    if reply is None or reply[4] != total:
        log("REKEY_FAIL")
        return False
    return True


def write_chunk(isp, addr, raw, marker, label, quiet=False):
    blob = xor_with(isp.xorkey, raw, addr)
    return status_of(xfer(
        isp, packet(ch.CH_CMD_CODE_WRITE, addr, blob, marker), label, quiet=quiet))


def commit(isp, addr, label):
    return status_of(xfer(isp, packet(ch.CH_CMD_CODE_WRITE, addr, b"", 0), label))


def program_8(isp, tag):
    """Erase, write 8 bytes, commit, verify. Returns the verify status."""
    log("PROGRAM8_%s begin" % tag)
    if erase_kb(isp, 8, "erase_%s" % tag) != 0x00:
        log("PROGRAM8_%s erase_not_accepted" % tag)
        return None
    time.sleep(1.0)
    wrote = write_chunk(isp, 0, RAW8, 0, "write_%s" % tag)
    committed = commit(isp, 8, "commit_%s" % tag)
    time.sleep(0.5)
    if not rekey(isp):
        return None
    verified = verify_at(isp, 0, RAW8, 0, "verify_%s" % tag)
    log("PROGRAM8_%s write=%s commit=%s verify=%s" % (
        tag,
        "none" if wrote is None else "%02x" % wrote,
        "none" if committed is None else "%02x" % committed,
        "none" if verified is None else "%02x" % verified))
    return wrote, verified


def unlock(isp, mask):
    cfg = bytearray(isp.configdata)
    if bytes(cfg[8:12]) not in USER_CFG_OK:
        log("UNLOCK_SKIPPED config word changed under us")
        return None
    cfg[0] = 0xA5
    cfg[1] = 0x5A
    stream = bytes((ch.CH_CMD_CONFIG_WRITE, 0x0E, 0x00, mask, 0x00)) + bytes(cfg)
    reply = xfer(isp, stream, "unlock_%02x" % mask)
    got = read_config(isp)
    if got is not None:
        isp.configdata = bytearray(got)
    return got


def flash_image(isp, path):
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) % 8:
        data += bytes([0xFF]) * (8 - (len(data) % 8))
    kb = (len(data) + 1023) // 1024
    log("FLASH_IMAGE %d bytes erase %d KB" % (len(data), kb))
    if erase_kb(isp, kb, "erase_image") != 0x00:
        log("FLASH_FAIL erase")
        return "fail"
    time.sleep(1.0)
    offset = 0
    shown = 0
    while offset < len(data):
        chunk = data[offset:offset + 56]
        wrote = write_chunk(
            isp, offset, chunk, 0, "img_%08x" % offset, quiet=(shown >= 2))
        if wrote == 0xFE:
            log("FLASH_REJECTED at %08x" % offset)
            return "fe"
        if wrote != 0x00:
            log("FLASH_FAIL write at %08x st=%s" % (
                offset, "none" if wrote is None else "%02x" % wrote))
            return "fail"
        offset += len(chunk)
        shown += 1
        if shown % 400 == 0:
            log("FLASH_PROGRESS %d/%d" % (offset, len(data)))
    committed = commit(isp, offset, "commit_image")
    log("FLASH_COMMIT %s" % ("none" if committed is None else "%02x" % committed))
    time.sleep(0.5)
    if not rekey(isp):
        log("FLASH_FAIL rekey")
        return "fail"
    offset = 0
    while offset < len(data):
        chunk = data[offset:offset + 56]
        verified = verify_at(isp, offset, chunk, 0, "ver_%08x" % offset, quiet=(offset >= 112))
        if verified != 0x00:
            log("FLASH_FAIL verify at %08x st=%s" % (
                offset, "none" if verified is None else "%02x" % verified))
            return "fail"
        offset += len(chunk)
        if offset % (400 * 56) < 56:
            log("VERIFY_PROGRESS %d/%d" % (offset, len(data)))
    log("FLASH_OK %d" % len(data))
    return "ok"


def restore_blank(isp):
    """Best effort: put the user area back to erased so the next plug boots the ROM."""
    log("RESTORE_BLANK")
    if erase_kb(isp, 240, "erase_restore") != 0x00:
        log("RESTORE_FAIL erase")
        return False
    time.sleep(1.0)
    if not rekey(isp):
        return False
    st = ff_oracle(isp, "restore")
    if st == 0x00:
        log("RESTORE_OK")
        return True
    log("RESTORE_UNCONFIRMED")
    return False


def reboot(isp):
    xfer(isp, bytes(ch.CH_STR_REBOOT), "reboot")


def read_cdc(seconds=8):
    deadline = time.time() + 5
    path = None
    while time.time() < deadline:
        for name in ("/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB0"):
            if os.path.exists(name):
                path = name
                break
        if path:
            break
        time.sleep(0.2)
    if path is None:
        log("CDC_NO_TTY")
        return
    log("CDC_OPEN %s" % path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    except OSError as ex:
        log("CDC_OPEN_FAIL %s" % ex)
        return
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        try:
            chunk = os.read(fd, 256)
        except BlockingIOError:
            time.sleep(0.05)
            continue
        except OSError as ex:
            log("CDC_READ_FAIL %s" % ex)
            break
        if chunk:
            buf += chunk
            if len(buf) > 4096:
                break
        else:
            time.sleep(0.05)
    os.close(fd)
    text = buf.decode("utf-8", "replace")
    log("CDC_TEXT %s" % text.replace("\n", " | "))
    if "POV>" in text:
        log("CDC_HIT")
    else:
        log("CDC_MISS")


def run_session(tag, allow_flash):
    """Returns (status, isp). isp is set only when a later reset is still safe."""
    try:
        isp = connect()
    except Exception as ex:
        log("CONNECT_FAIL %s %s" % (tag, ex))
        return "dead", None
    if isp.chipid != 0x1372:
        log("UNEXPECTED_CHIP %04x" % isp.chipid)
        return "dead", None

    length_sweep(isp, tag)
    xfer(isp, packet(ch.CH_CMD_CODE_VERIFY, 0x00100000, bytes(8), 0), "verify_bad_addr")
    if erase_kb(isp, 8, "erase_oracle_%s" % tag) == 0x00:
        time.sleep(1.0)
        ff_oracle(isp, tag)
        mismatch_probe(isp)

    outcome = program_8(isp, tag + "_before_unlock")
    if outcome is None:
        return "dead", None
    wrote, verified = outcome
    accepted = wrote == 0x00 or verified == 0x00
    if verified == 0x00 and allow_flash:
        return finish_flash(isp), None

    if not accepted:
        got = unlock(isp, 0x07)
        if got is None or got[0] != 0xA5 or got[1] != 0x5A:
            log("UNLOCK_07_NOT_VISIBLE")
            got = unlock(isp, 0x1F)
        if got is not None and got[0] == 0xA5 and got[1] == 0x5A:
            log("UNLOCK_VISIBLE")
        else:
            log("UNLOCK_NOT_VISIBLE")
        outcome = program_8(isp, tag + "_after_unlock")
        if outcome is None:
            return "dead", None
        wrote, verified = outcome
        accepted = wrote == 0x00 or verified == 0x00
        if verified == 0x00 and allow_flash:
            return finish_flash(isp), None

    if accepted:
        log("DIRTY_FLASH write was accepted but verify did not pass; erasing")
        restore_blank(isp)
        log("SESSION_%s NO_REBOOT" % tag)
        return "dirty", None

    log("SESSION_%s REJECTED" % tag)
    return "rejected", isp


def finish_flash(isp):
    if flash_image(isp, IMAGE) == "ok":
        reboot(isp)
        log("SESSION_FLASHED")
        return "flashed"
    log("IMAGE_FAILED erasing back to blank, no reboot")
    restore_blank(isp)
    log("SESSION_IMAGE_FAILED")
    return "dirty"


def open_cdc_data():
    """Claim the CDC data interface. Returns (dev, interface) or (None, None)."""
    dev = find_cdc()
    if dev is None:
        return None, None
    cfg = dev.get_active_configuration()
    iface = None
    for intf in cfg:
        if any(ep.bEndpointAddress == 0x01 for ep in intf):
            iface = intf.bInterfaceNumber
            break
    if iface is None:
        log("CDC_NO_OUT_EP")
        return None, None
    try:
        if dev.is_kernel_driver_active(iface):
            dev.detach_kernel_driver(iface)
            log("CDC_DETACHED %d" % iface)
    except Exception as ex:
        log("CDC_DETACH %s" % ex)
    try:
        dev.set_configuration()
        ch.usb.util.claim_interface(dev, iface)
    except ch.usb.core.USBError as ex:
        log("CDC_CLAIM_FAIL %s" % ex)
        return None, None
    return dev, iface


def read_cdc_usb(seconds=4):
    dev, _iface = open_cdc_data()
    if dev is None:
        log("CDC_NO_DEV")
        return ""
    buf = b""
    end = time.time() + seconds
    while time.time() < end and len(buf) < 2048:
        try:
            chunk = bytes(dev.read(0x81, 64, 200))
        except ch.usb.core.USBError:
            continue
        if chunk:
            buf += chunk
    text = buf.decode("utf-8", "replace")
    log("CDC_TEXT %s" % text.replace("\n", " | "))
    if "POV>" in text:
        log("CDC_HIT")
    else:
        log("CDC_MISS")
    return text


def program_file(path):
    """Erase, write, verify. Unlock once if the bootloader rejects the write."""
    try:
        isp = connect()
    except Exception as ex:
        log("CONNECT_FAIL %s" % ex)
        return "dead"
    result = flash_image(isp, path)
    if result == "fe":
        got = unlock(isp, 0x07)
        if got is None or got[0] != 0xA5 or got[1] != 0x5A:
            log("UNLOCK_07_NOT_VISIBLE")
            got = unlock(isp, 0x1F)
        if got is not None and got[0] == 0xA5 and got[1] == 0x5A:
            log("UNLOCK_VISIBLE")
        result = flash_image(isp, path)
    if result == "ok":
        reboot(isp)
        return "flashed"
    if result == "fe":
        return "rejected"
    restore_blank(isp)
    return "dirty"


def cmd_flash(path):
    log("HOST_FLASH %s" % path)
    kind = wait_for("boot", 900, True)
    if kind != "boot":
        log("RESULT_NO_BOOTLOADER")
        return 1
    result = program_file(path)
    if result != "flashed":
        log("RESULT_%s" % result.upper())
        return 1
    time.sleep(1.5)
    kind = wait_for("any", 20, False)
    if kind == "cdc":
        read_cdc_usb()
        log("RESULT_FLASHED_CDC")
    elif kind == "boot":
        log("RESULT_FLASHED_STILL_BOOTLOADER")
    else:
        log("RESULT_FLASHED_NO_USB")
    return 0


def cmd_enter():
    log("HOST_ENTER")
    dev, _iface = open_cdc_data()
    if dev is None:
        log("ENTER_NO_CDC")
        log("RESULT_ENTER_FAIL")
        return 1
    try:
        dev.write(0x01, b"boot\n", 1000)
        log("ENTER_SENT")
    except ch.usb.core.USBError as ex:
        # The chip may reset before the status stage finishes.
        log("ENTER_WRITE %s" % ex)
    deadline = time.time() + 20
    saw_gap = False
    while time.time() < deadline:
        if find_bootloader() is not None:
            log("ENTER_OK")
            log("RESULT_BOOTLOADER")
            return 0
        if find_cdc() is None:
            saw_gap = True
        time.sleep(0.2)
    if saw_gap:
        log("ENTER_GONE")
    else:
        log("ENTER_STILL_APP")
    log("RESULT_ENTER_FAIL")
    return 1


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "flash":
        if len(sys.argv) != 3:
            sys.stderr.write("usage: host_session.py flash <bin>\n")
            return 1
        return cmd_flash(sys.argv[2])
    if len(sys.argv) == 2 and sys.argv[1] == "enter":
        return cmd_enter()
    if not (len(sys.argv) == 2 and sys.argv[1] == "probe"):
        sys.stderr.write("usage: host_session.py flash <bin> | enter | probe\n")
        return 1
    log("HOST_SESSION_START")
    kind = wait_for("boot", 900, True)
    if kind != "boot":
        log("RESULT_NO_BOOTLOADER")
        return 1
    first, held = run_session("s1", True)
    if first == "flashed":
        time.sleep(1.5)
        kind = wait_for("any", 20, False)
        if kind == "cdc":
            read_cdc()
            log("RESULT_FLASHED_CDC")
        elif kind == "boot":
            log("RESULT_FLASHED_STILL_BOOTLOADER")
        else:
            log("RESULT_FLASHED_NO_USB")
        return 0
    if first == "dead":
        log("RESULT_DEAD")
        return 1
    if first == "dirty":
        log("RESULT_DIRTY_LEFT_IN_BOOTLOADER")
        return 1

    # Program commands were rejected. A reset lets a config write take effect.
    try:
        if held is None:
            raise Exception("no open bootloader")
        reboot(held)
        log("REBOOTED_FOR_CONFIG")
    except Exception as ex:
        log("REBOOT_FAIL %s" % ex)
        log("NEED_REPLUG")
        kind = wait_for("boot", 900, False)
        if kind != "boot":
            log("RESULT_NO_SECOND_SESSION")
            return 1
    else:
        time.sleep(0.5)
        kind = wait_for("boot", 25, False)
        if kind != "boot":
            log("NEED_REPLUG")
            kind = wait_for("boot", 900, False)
            if kind != "boot":
                log("RESULT_NO_SECOND_SESSION")
                return 1

    second, _held2 = run_session("s2", True)
    if second == "flashed":
        time.sleep(1.5)
        kind = wait_for("any", 20, False)
        if kind == "cdc":
            read_cdc()
            log("RESULT_FLASHED_CDC")
        elif kind == "boot":
            log("RESULT_FLASHED_STILL_BOOTLOADER")
        else:
            log("RESULT_FLASHED_NO_USB")
        return 0
    if second == "dirty":
        log("RESULT_DIRTY_LEFT_IN_BOOTLOADER")
        return 1
    log("RESULT_STILL_REJECTED")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        log("RESULT_CRASH %s" % ex)
        sys.exit(1)
