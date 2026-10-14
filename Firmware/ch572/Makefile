# CH572 bring-up image. Builds against the openwch/ch570 EVT checked out
# at Firmware/third_party/ch570. Toolchain is the MounRiver RISC-V GCC.

EVT  := ../third_party/ch570/EVT/EXAM
TOOL := /home/harry/opt/Toolchain/RISC-V Embedded GCC12/bin/riscv-wch-elf-

CC      := $(TOOL)gcc
OBJCOPY := $(TOOL)objcopy
SIZE    := $(TOOL)size

BUILD := build

CFLAGS := -march=rv32i2p0_m2p0_c2p0_zba1p0_zbb1p0_zbc1p0_zbs1p0_xw2p2 -mabi=ilp32 -mcmodel=medlow -msmall-data-limit=8 \
          -Os -fmessage-length=0 -fsigned-char -ffunction-sections -fdata-sections \
          -fno-common -std=gnu99 --param=highcode-gen-section-name=1 \
          -Wall -Wno-unused-function -Wno-unused-variable \
          -I src \
          -I $(EVT)/BLE/Peripheral/APP/include \
          -I $(EVT)/BLE/Peripheral/Profile/include \
          -I $(EVT)/BLE/HAL/include \
          -I $(EVT)/BLE/LIB \
          -I $(EVT)/SRC/StdPeriphDriver/inc \
          -I $(EVT)/SRC/RVMSIS \
          -I $(EVT)/SRC/Ld \
          -DFW_MARK='A'

LDFLAGS := -T $(EVT)/SRC/Ld/Link.ld -nostartfiles --specs=nano.specs --specs=nosys.specs \
           -Wl,--gc-sections -Wl,--print-memory-usage \
           -L $(EVT)/BLE/LIB -L $(EVT)/SRC/StdPeriphDriver

LIBS := -Wl,--start-group -lCH572BLE_PERI -lISP572 -lm -lc -lgcc -Wl,--end-group

SRC := \
  src/peripheral_main.c \
  src/peripheral.c \
  src/board.c \
  $(EVT)/BLE/Peripheral/Profile/gattprofile.c \
  $(EVT)/BLE/HAL/MCU.c \
  $(EVT)/BLE/HAL/RTC.c \
  $(EVT)/BLE/HAL/SLEEP.c \
  $(EVT)/SRC/StdPeriphDriver/CH57x_clk.c \
  $(EVT)/SRC/StdPeriphDriver/CH57x_cmp.c \
  $(EVT)/SRC/StdPeriphDriver/CH57x_flash.c \
  $(EVT)/SRC/StdPeriphDriver/CH57x_gpio.c \
  $(EVT)/SRC/StdPeriphDriver/CH57x_pwr.c \
  $(EVT)/SRC/StdPeriphDriver/CH57x_spi.c \
  $(EVT)/SRC/StdPeriphDriver/CH57x_sys.c \
  $(EVT)/SRC/StdPeriphDriver/CH57x_timer.c \
  $(EVT)/SRC/StdPeriphDriver/CH57x_uart.c \
  $(EVT)/SRC/Startup/startup_CH572.S

USB_SRC := $(EVT)/USB/Device/COM/src/Main.c

OBJS := $(patsubst %.c,$(BUILD)/%.o,$(filter %.c,$(SRC))) \
        $(patsubst %.S,$(BUILD)/%.o,$(filter %.S,$(SRC))) \
        $(BUILD)/usb_com.o

.PHONY: all clean
all: $(BUILD)/pov.elf $(BUILD)/pov.bin $(BUILD)/pov.hex

$(BUILD)/pov.elf: $(OBJS)
	$(CC) $(CFLAGS) $(OBJS) $(LDFLAGS) $(LIBS) -o $@
	$(SIZE) $@

$(BUILD)/pov.bin: $(BUILD)/pov.elf
	$(OBJCOPY) -O binary $< $@

$(BUILD)/pov.hex: $(BUILD)/pov.elf
	$(OBJCOPY) -O ihex $< $@

$(BUILD)/usb_com.o: $(USB_SRC)
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -Dmain=usb_demo_unused -c $< -o $@

$(BUILD)/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/%.o: %.S
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -rf $(BUILD)
