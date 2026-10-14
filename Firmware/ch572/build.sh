#!/bin/sh
# Same build as the Makefile. This host does not have GNU make installed.
set -e
cd "$(dirname "$0")"
MARK="${1:-A}"
case "$MARK" in
  A|B) ;;
  *)
    echo "usage: build.sh [A|B]" >&2
    exit 1
    ;;
esac
EVT="../third_party/ch570/EVT/EXAM"
TOOL="/home/harry/opt/Toolchain/RISC-V Embedded GCC12/bin/riscv-wch-elf-"
CC="${TOOL}gcc"
BUILD=build
mkdir -p "$BUILD"

CFLAGS="-march=rv32i2p0_m2p0_c2p0_zba1p0_zbb1p0_zbc1p0_zbs1p0_xw2p2 -mabi=ilp32 -mcmodel=medlow -msmall-data-limit=8 \
 -Os -fmessage-length=0 -fsigned-char -ffunction-sections -fdata-sections \
 -fno-common -std=gnu99 --param=highcode-gen-section-name=1 \
 -Wall -Wno-unused-function -Wno-unused-variable \
 -Isrc \
 -I$EVT/BLE/Peripheral/APP/include \
 -I$EVT/BLE/Peripheral/Profile/include \
 -I$EVT/BLE/HAL/include \
 -I$EVT/BLE/LIB \
 -I$EVT/SRC/StdPeriphDriver/inc \
 -I$EVT/SRC/RVMSIS \
 -I$EVT/SRC/Ld \
 -DFW_MARK='$MARK'"

SRCS="
 src/peripheral_main.c
 src/peripheral.c
 src/board.c
 $EVT/BLE/Peripheral/Profile/gattprofile.c
 $EVT/BLE/HAL/MCU.c
 $EVT/BLE/HAL/RTC.c
 $EVT/BLE/HAL/SLEEP.c
 $EVT/SRC/StdPeriphDriver/CH57x_clk.c
 $EVT/SRC/StdPeriphDriver/CH57x_cmp.c
 $EVT/SRC/StdPeriphDriver/CH57x_flash.c
 $EVT/SRC/StdPeriphDriver/CH57x_gpio.c
 $EVT/SRC/StdPeriphDriver/CH57x_pwr.c
 $EVT/SRC/StdPeriphDriver/CH57x_spi.c
 $EVT/SRC/StdPeriphDriver/CH57x_sys.c
 $EVT/SRC/StdPeriphDriver/CH57x_timer.c
 $EVT/SRC/StdPeriphDriver/CH57x_uart.c
 $EVT/SRC/Startup/startup_CH572.S
"

OBJS=""
for s in $SRCS; do
  obj="$BUILD/$(echo "$s" | tr '/' '_').o"
  echo "CC $s"
  "$CC" $CFLAGS -c "$s" -o "$obj"
  OBJS="$OBJS $obj"
done

echo "CC usb"
"$CC" $CFLAGS -Dmain=usb_demo_unused -c "$EVT/USB/Device/COM/src/Main.c" -o "$BUILD/usb_com.o"
OBJS="$OBJS $BUILD/usb_com.o"

echo "LD"
"$CC" $CFLAGS $OBJS \
  -T "$EVT/SRC/Ld/Link.ld" -nostartfiles --specs=nano.specs --specs=nosys.specs \
  -Wl,--gc-sections -Wl,--print-memory-usage \
  -L "$EVT/BLE/LIB" -L "$EVT/SRC/StdPeriphDriver" \
  -Wl,--start-group -lCH572BLE_PERI -lISP572 -lm -lc -lgcc -Wl,--end-group \
  -o "$BUILD/pov.elf"
"${TOOL}size" "$BUILD/pov.elf"
"${TOOL}objcopy" -O binary "$BUILD/pov.elf" "$BUILD/pov-$MARK.bin"
"${TOOL}objcopy" -O ihex "$BUILD/pov.elf" "$BUILD/pov-$MARK.hex"
echo "built $BUILD/pov-$MARK.bin"
