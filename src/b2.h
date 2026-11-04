/*
 * Flash bank 2, the bank 1 side: what cpu.c (the pairing check) and b2load.c (the card loader) share.
 * NOT included by b2head.c on purpose - that file is hashed into the bank 2 id (build.sh), so touching it would
 * change the id and unpair the payload on the test unit. Its B2_MAGIC and base address are repeated here.
 */
#ifndef B2_H
#define B2_H
#include <stdint.h>

#define B2_MAGIC   0x21324242u   /* "BB2!", as b2head.c */
#define B2_BASE    0x08100000u
#define B2_LIMIT   0x000C0000u   /* sectors 0-5: where a payload may be, and all the loader ever erases */
#define B2_CLAIM_AT B2_LIMIT     /* sector 6, first flash word: "this bank is the mod's" (b2load.c). Never erased. */
#define B2_END     0x000E0000u   /* the end of sector 6. SECTOR 7 (0x081E0000) IS THE UNIT'S FACTORY CALIBRATION */
#define B2_SECTOR  0x00020000u
#define B2_CLAIM   0x43324242u   /* "BB2C" */

/* cpu_state.b2chk */
#define B2_PAIR        0x03u     /* 0 not checked yet, B2_PAIRED, B2_UNPAIRED (3 = two tasks disagreed: not paired) */
#define B2_PAIRED      0x01u
#define B2_UNPAIRED    0x02u
#define B2_LOOKED      0x04u     /* the card loader has had its one go this boot (or a tool wants it kept out) */
#define B2_SCANNING    0x08u     /* a task is inside the pairing scan right now: ask again, do not take its place */
#define B2_FOREIGN     0x40u     /* bank 2 holds something that is neither blank nor the mod's: the loader left it alone */
#define B2_FILE_SHIFT  4         /* what it found on the card: */
#define B2_FILE_OK     1u        /*   this image's own payload, whole */
#define B2_FILE_NONE   2u        /*   no file */
#define B2_FILE_WRONG  3u        /*   another payload, or a damaged one */

/*
 * THREE WORDS OF BACKUP SRAM, in the hole between fault.c's trails (which end at 0x388003c8) and comp.c at
 * 0x38800400. Backup SRAM keeps its contents through a reset, which is the point: they are how one boot tells the
 * next what happened to it.
 *   B2_MARK     B2_MARK_SCANNING while the pairing scan is reading bank 2. If a boot finds it still set, the last
 *               scan never came back - a flash word up there is uncorrectable and the read faulted - so bank 2 is
 *               left unread and unpaired until the loader has rewritten it.
 *               B2_MARK_NAMING is the same thing for the earlier, shorter read that names the effects in the lists.
 *               It has its own value because that read happens in the screen task while the app is being built,
 *               and the audio task can arrive at the pairing scan in the middle of it: a scan that finds NAMING
 *               says "not yet" and asks again next block, where finding SCANNING means a dead scan.
 *   B2_TRIES_*  how many times the loader has programmed THIS payload without a clean scan afterwards.
 * Every write goes through bkp_put: the data cache holds a write to this RAM back, and a reset does not write the
 * cache out (three fault recorders "caught nothing" that way, see fault.c).
 */
#define B2_MARK          ((volatile uint32_t *)0x388003c8u)
#define B2_TRIES_ID      ((volatile uint32_t *)0x388003ccu)
#define B2_TRIES_N       ((volatile uint32_t *)0x388003d0u)
#define B2_MARK_SCANNING 0x4e435332u         /* "2SCN" */
#define B2_MARK_NAMING   0x4d414e32u         /* "2NAM": b2_present is reading it, to decide what the lists call the effects */
#define B2_MARK_CLAIMING 0x4d4c4332u         /* "2CLM": the loader is reading it, to decide whether it may erase it */
#define B2_MAX_TRIES     2u
_Static_assert(0x388003d0u + 4u <= 0x38800400u, "the bank 2 words run into comp.c's state at 0x38800400");

void bkp_enable(void);           /* od.c: backup SRAM clock on, backup-domain writes allowed */

static inline void bkp_put(volatile uint32_t *at, uint32_t value)
{
    *at = value;
    *(volatile uint32_t *)0xe000ef68u = (uint32_t)at;    /* DCCMVAC: write this cache line out to the SRAM */
    __asm__ volatile("dsb\n isb");
}

extern const volatile uint32_t b2_expect_sum;   /* cpu.c: the sum of the payload this image was linked with */

int b2_ready(void);              /* cpu.c: is b2chk set up yet */
uint8_t b2_state(void);          /* cpu.c: b2chk */
void b2_flag(uint8_t bits);      /* cpu.c: set bits in b2chk, atomically */
int b2_live(void);               /* cpu.c: may bank 2 be executed - checks the pairing if nobody has yet */
int b2_rescan(void);             /* cpu.c: bank 2 was just rewritten - scan it again; nonzero = now paired */
int b2_present(void);            /* cpu.c: is this image's payload in bank 2 - for use BEFORE the meter is up */

#endif
