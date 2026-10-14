#ifndef BOARD_H
#define BOARD_H

/* Shift-register chase, SC7A20 reads, and USB log lines. */
void board_init(void);
void board_tick(void);
void board_poll(void);
void board_log(const char *s);

#endif
