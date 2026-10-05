#!/usr/bin/env python3
"""RP2350 proof-of-life check (Windows).

Enumerates USB to find a Raspberry Pi RP2350 in either BOOTSEL (bootloader)
mode or running a USB-serial app, prints its serial number and whatever
identifying info the device exposes.

RP2350 USB IDs:
  VID 0x2E8A (Raspberry Pi)
  PID 0x000F -> RP2350 BOOTSEL / bootloader
"""
import subprocess
import sys

RPI_VID = "2E8A"
BOOTSEL_PID = "000F"


def ps(cmd):
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", cmd],
        capture_output=True, text=True,
    )
    return out.stdout.strip()


def find_rp_usb():
    """Return list of RP USB InstanceIds (contain the board serial)."""
    raw = ps(
        "Get-PnpDevice -PresentOnly | "
        f"Where-Object {{ $_.InstanceId -match 'VID_{RPI_VID}' }} | "
        "Select-Object -ExpandProperty InstanceId"
    )
    return [l.strip() for l in raw.splitlines() if l.strip()]


def find_bootsel_drive():
    """Return (letter, label) for a mounted RP2350 bootloader volume, if any."""
    raw = ps(
        "Get-Volume | Where-Object { $_.FileSystemLabel -match 'RP2|RPI-RP' } | "
        "ForEach-Object { \"$($_.DriveLetter)|$($_.FileSystemLabel)\" }"
    )
    for line in raw.splitlines():
        if "|" in line:
            letter, label = line.split("|", 1)
            return letter.strip(), label.strip()
    return None, None


def read_info(letter):
    import pathlib
    p = pathlib.Path(f"{letter}:/INFO_UF2.TXT")
    try:
        return p.read_text(errors="replace").strip()
    except OSError:
        return None


def main():
    print("=== RP2350 proof-of-life ===\n")

    ids = find_rp_usb()
    if not ids:
        print("NO RP2350 FOUND on USB (VID 2E8A not present).")
        print("If the board is running app firmware with no USB, hold QSPI_SS")
        print("low and tap RUN to enter BOOTSEL, then re-run.")
        return 1

    print(f"Found {len(ids)} Raspberry Pi USB interface(s):")
    serials = set()
    in_bootsel = False
    for iid in ids:
        print(f"  {iid}")
        if f"PID_{BOOTSEL_PID}" in iid:
            in_bootsel = True
        # Serial is the trailing token on the composite parent, e.g. ...PID_000F\<SERIAL>
        tail = iid.split("\\")[-1]
        if tail and "&" not in tail and "MI_" not in iid.split("\\")[1]:
            serials.add(tail)

    print()
    print(f"Mode: {'BOOTSEL (USB bootloader)' if in_bootsel else 'application / runtime'}")
    if serials:
        print(f"Board serial number: {', '.join(sorted(serials))}")

    letter, label = find_bootsel_drive()
    if letter:
        print(f"\nBootloader drive: {letter}: (label '{label}')")
        info = read_info(letter)
        if info:
            print("INFO_UF2.TXT:")
            for line in info.splitlines():
                print(f"  {line}")

    print("\n==> Device is powered and responding. Proof of life CONFIRMED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
