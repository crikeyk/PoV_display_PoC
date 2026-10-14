#include "CH57x_common.h"
#include "board.h"

/* 74HC595, clocks corrected on this board: SCK is SHCP, PA11 is STCP.
 * U4 Q0..Q7 = LEDs 0..7. U5 Q0 = LED 15, U5 Q1..Q7 = LEDs 8..14.
 * Bit 0 of the shift word lands in U4 Q0 when 16 bits are shifted MSB first. */
static const uint8_t led_to_bit[16] = {
    0, 1, 2, 3, 4, 5, 6, 7,
    9, 10, 11, 12, 13, 14, 15,
    8
};

#define PIN_CS_ACC   GPIO_Pin_10
#define PIN_LATCH    GPIO_Pin_11

#define ACC_WHO      0x0F
#define ACC_CTRL1    0x20
#define ACC_CTRL4    0x23
#define ACC_OUT_X_L  0x28

extern void USB_IRQProcessHandler(void);
extern UINT8 SendUSBData(UINT8 *p_send_dat, UINT16 send_len);
extern UINT8 Ep1DataINFlag;
extern UINT8 Ep1DataOUTFlag;
extern UINT8 Ep1DataOUTLen;
extern UINT8 Ep1OUTDataBuf[];

#ifndef FW_MARK
#define FW_MARK 'A'
#endif

static uint8_t chase_i;
static uint8_t tick_n;
static uint8_t acc_ready;

static void spi_mode0(void)
{
    SPI_DataMode(Mode0_HighBitINFront);
}

static void spi_mode3(void)
{
    SPI_DataMode(Mode3_HighBitINFront);
}

static void cs_acc(int selected)
{
    if(selected)
        GPIOA_ResetBits(PIN_CS_ACC);
    else
        GPIOA_SetBits(PIN_CS_ACC);
}

static void acc_write(uint8_t reg, uint8_t val)
{
    spi_mode3();
    cs_acc(1);
    SPI_MasterSendByte(reg & 0x3F);
    SPI_MasterSendByte(val);
    cs_acc(0);
}

static void acc_read(uint8_t reg, uint8_t *buf, uint8_t n)
{
    uint8_t cmd = reg | 0x80;

    if(n > 1)
        cmd |= 0x40;
    spi_mode3();
    cs_acc(1);
    SPI_MasterSendByte(cmd);
    while(n--)
        *buf++ = SPI_MasterRecvByte();
    cs_acc(0);
}

/* Light one LED. Latch stays high except for the update edge, so an
 * accelerometer transfer (which also clocks SCK) does not change the LEDs. */
static void show_led(uint8_t index)
{
    uint16_t word = (uint16_t)1 << led_to_bit[index & 15];
    uint8_t buf[2];

    buf[0] = (uint8_t)(word >> 8);
    buf[1] = (uint8_t)word;
    cs_acc(0);
    spi_mode0();
    GPIOA_ResetBits(PIN_LATCH);
    SPI_MasterTrans(buf, 2);
    GPIOA_SetBits(PIN_LATCH);
}

void board_log(const char *s)
{
    while(*s)
    {
        uint8_t buf[64];
        uint8_t n = 0;
        uint32_t spins = 0;

        while(s[n] && n < sizeof(buf))
        {
            buf[n] = (uint8_t)s[n];
            n++;
        }
        while(!Ep1DataINFlag && spins < 200000)
        {
            USB_IRQProcessHandler();
            spins++;
        }
        if(!Ep1DataINFlag)
            return;
        SendUSBData(buf, n);
        s += n;
    }
}

void board_init(void)
{
    GPIOA_SetBits(PIN_CS_ACC | PIN_LATCH);
    GPIOA_ModeCfg(bSCK | bMOSI | PIN_CS_ACC | PIN_LATCH, GPIO_ModeOut_PP_5mA);
    GPIOA_ModeCfg(bMISO | GPIO_Pin_4 | GPIO_Pin_2, GPIO_ModeIN_PU);

    SPI_MasterDefInit();
    SPI_CLKCfg(100);                 /* 100 MHz / 100 = 1 MHz */

    acc_write(ACC_CTRL1, 0x57);      /* 100 Hz, XYZ on */
    acc_write(ACC_CTRL4, 0x88);      /* BDU, high-res, +/-2 g */
    acc_ready = 1;

    chase_i = 15;
    show_led(0);
}

static int16_t axis_mg(uint8_t lo, uint8_t hi)
{
    int16_t v = (int16_t)((hi << 8) | lo);
    return (int16_t)(v >> 4);        /* 1 mg / count at +/-2 g, high-res */
}

static void append_i16(char *p, int16_t v)
{
    char tmp[8];
    uint8_t n = 0;
    uint16_t u;
    int neg = v < 0;

    if(neg)
        v = (int16_t)(-v);
    u = (uint16_t)v;
    do
    {
        tmp[n++] = (char)('0' + (u % 10));
        u = (uint16_t)(u / 10);
    } while(u);
    if(neg)
        *p++ = '-';
    while(n)
        *p++ = tmp[--n];
    *p = 0;
}

void board_tick(void)
{
    char line[80];
    char *p;
    uint8_t raw[6];
    uint8_t who;
    int16_t x, y, z;

    show_led(chase_i);
    chase_i = (uint8_t)((chase_i - 1) & 15);

    if(!acc_ready)
        return;
    tick_n++;
    if(tick_n < 12)
        return;
    tick_n = 0;

    acc_read(ACC_WHO, &who, 1);
    acc_read(ACC_OUT_X_L, raw, 6);
    x = axis_mg(raw[0], raw[1]);
    y = axis_mg(raw[2], raw[3]);
    z = axis_mg(raw[4], raw[5]);

    p = line;
    *p = 0;
    /* "POV> who=11 x=0 y=0 z=1000 mg\n" */
    {
        const char *prefix = "POV> fw=";
        while(*prefix)
            *p++ = *prefix++;
        *p++ = FW_MARK;
        *p = 0;
        prefix = " who=";
        while(*prefix)
            *p++ = *prefix++;
        *p++ = "0123456789abcdef"[who >> 4];
        *p++ = "0123456789abcdef"[who & 0x0F];
        *p = 0;
        prefix = " x=";
        while(*prefix)
            *p++ = *prefix++;
        *p = 0;
        append_i16(p, x);
        while(*p)
            p++;
        prefix = " y=";
        while(*prefix)
            *p++ = *prefix++;
        *p = 0;
        append_i16(p, y);
        while(*p)
            p++;
        prefix = " z=";
        while(*prefix)
            *p++ = *prefix++;
        *p = 0;
        append_i16(p, z);
        while(*p)
            p++;
        prefix = " mg\n";
        while(*prefix)
            *p++ = *prefix++;
        *p = 0;
    }
    board_log(line);
}

/* Datasheet: RB_SOFTWARE_RESET starts the ROM bootloader only when
 * RB_WDOG_INT_EN is 1, RB_ROM_CODE_WE is 1, RB_ROM_DATA_WE is 0, and
 * 128 <= R8_WDOG_COUNT < 192. This header packs the two ROM bits into
 * RB_ROM_CODE_WE (0xC0). On the older CH57x map those are separate:
 * bit 7 is code-write and bit 6 is data-write. Writing 0xC0 set both,
 * and that reset came back as the application. 0x80 is the protected
 * encoding (bits 7:6 = 10) and also came back as the application.
 * "Configured as 1" is the field value 1, bits 7:6 = 01, which is 0x40.
 * Safe-access mode lasts about 16 cycles and must not be reopened
 * without writing 0 first, so every protected store is one sb after
 * the signature, with the address registers already loaded. */
__attribute__((section(".highcode"), noinline))
static void enter_bootloader(void)
{
    __risc_v_disable_irq();
    FLASH_ROM_SW_RESET();
    __risc_v_disable_irq();
    R8_WDOG_COUNT = 160;
    __asm volatile (
        "li t0, 0x40001040\n\t"
        "li t1, 0x57\n\t"
        "li t2, 0xA8\n\t"
        "li t3, 0x40001044\n\t"
        "li t4, 0x40\n\t"
        "li t5, 0x40001046\n\t"
        "li t6, 4\n\t"
        "li a0, 5\n\t"
        "sb t1, 0(t0)\n\t"
        "sb t2, 0(t0)\n\t"
        "sb t4, 0(t3)\n\t"
        "sb t6, 0(t5)\n\t"
        "sb a0, 0(t5)\n\t"
        ::: "t0", "t1", "t2", "t3", "t4", "t5", "t6", "a0", "memory");
    while(1)
        ;
}

static int is_boot_line(const uint8_t *buf, uint8_t n)
{
    uint8_t i = 0;
    const char *word = "boot";
    uint8_t k = 0;

    while(i < n && (buf[i] == ' ' || buf[i] == '\t' || buf[i] == '\r' || buf[i] == '\n'))
        i++;
    while(word[k])
    {
        char c;
        if(i >= n)
            return 0;
        c = (char)buf[i];
        if(c >= 'A' && c <= 'Z')
            c = (char)(c - 'A' + 'a');
        if(c != word[k])
            return 0;
        i++;
        k++;
    }
    while(i < n)
    {
        if(buf[i] != ' ' && buf[i] != '\t' && buf[i] != '\r' && buf[i] != '\n' && buf[i] != 0)
            return 0;
        i++;
    }
    return 1;
}

void board_poll(void)
{
    uint8_t n;

    if(!Ep1DataOUTFlag)
        return;
    n = Ep1DataOUTLen;
    if(n > 64)
        n = 64;
    Ep1DataOUTFlag = 0;
    if(!is_boot_line(Ep1OUTDataBuf, n))
        return;
    board_log("POV> boot\n");
    enter_bootloader();
}
