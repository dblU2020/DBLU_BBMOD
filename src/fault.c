/*
 * WHERE DID IT DIE? The instrument, rebuilt 2026-10-11 because the previous one could not survive the event it was
 * built to measure. Three "facts" about the Relapse hang came out of it and all three were artifacts:
 *
 *   1. "The fault recorder caught nothing, so nothing faulted." The record was 13 words at 0x38800fd0, and backup
 *      SRAM ENDS AT 0x38800fff - so its last word landed at 0x38801000, outside the 4 KB. That write bus-faults
 *      INSIDE the fault handler, which escalates to lockup, and the magic (written last, deliberately) never
 *      lands. A genuine fault therefore left no record. test_fault.py now runs the recorder and fails on the
 *      overrun; the layout below is bounded by a static assert instead of a comment.
 *   2. "All the fault status registers were clear." CFSR / HFSR live in the SCB, which every reset clears, so
 *      after the watchdog reboot they are ALWAYS clear. The reading carried no information.
 *   3. "MODE said Munchi was the last type to complete a block", and the 3.2.p breadcrumb likewise - both are
 *      rewritten by the delay's every audio block, so within a millisecond of the reboot they describe the
 *      REBOOTED unit. Proved on the test unit over USB: a sentinel poked into the crumb was gone before the read back.
 *
 * So: the trail is now LATCHED AT BOOT (instrument_boot, called once per boot from master_alloc) into a saved copy
 * that the running unit never touches, and the reset itself is caught in the act - the window watchdog's early
 * wakeup interrupt fires one tick (~5 ms) before it resets the unit, and its handler records the PC the CPU was
 * spinning on.
 *
 * BACKUP SRAM, 4 KB at 0x38800000, and the free span above master.c's PRISM_CHECK is 0x38800f78..0x38800fff:
 *   0x38800f78  FAULT   13 words  magic "FLT1", PC, LR, xPSR, CFSR, HFSR, MMFAR, BFAR, EXC_RETURN, r0-r3
 *   0x38800fac  WDG      8 words  magic "WDG1", PC, LR, xPSR, stamp A age, stamp B age, misses, CR | SR << 16
 *   0x38800fcc  TRAIL    6 words  the live breadcrumb ring (munchi.cpp's DROP), newest at TRAIL_IDX
 *   0x38800fe4  IDX      1 word   boot count << 8 | ring index
 *   0x38800fe8  SAVED    6 words  the ring as it stood when the unit last booted: the trail INTO the hang
 */
#include <stdint.h>

#define BKP_END    0x38801000u                 /* backup SRAM is 4 KB: nothing may be written at or above this */

#define FAULT_REC  ((volatile uint32_t *)0x38800f78u)   /* was 0x38800fd0, which is where the overrun came from */
#define FAULT_WORDS 16
#define FAULT_MAGIC 0x31544c46u                /* "FLT1" */

#define WDG_REC    ((volatile uint32_t *)0x38800fb8u)
#define WDG_WORDS  8
#define WDG_MAGIC  0x31474457u                 /* "WDG1" */

#define BOOT_REC   ((volatile uint32_t *)0x38800fd8u)
#define BOOT_WORDS 4
#define BOOT_MAGIC 0x31544f42u                 /* "BOT1" */

#define SP_LOW     ((volatile uint32_t *)0x38800fe8u)   /* [0] lowest SP the delay dispatch has ever run at, [1] last */
#define SP_WORDS   2

/*
 * The trails (and, from 0x388003c8, b2.h's three bank 2 words) live in the OTHER free hole - 0x38800384..0x388003ff, the 124 bytes between od.c's bank (0x384 long)
 * and comp.c at 0x38800400 - because the GUI and the audio task each need their own ring. 3.2.q shared one, and
 * six GUI page-builds in a burst flushed every audio crumb out of it, which is exactly the window we needed to see.
 */
#define AUD        ((volatile uint32_t *)0x38800384u)
#define GUI        ((volatile uint32_t *)0x38800394u)
#define AUD_SAVED  ((volatile uint32_t *)0x388003a4u)
#define GUI_SAVED  ((volatile uint32_t *)0x388003b4u)
#define RING_IDX   (*(volatile uint32_t *)0x388003c4u)  /* audio index in bits 0-7, GUI index in bits 8-15 */
#define RING_LEN   4

_Static_assert((uint32_t)(0x38800f78u + FAULT_WORDS * 4) <= 0x38800fb8u, "the fault record overlaps the watchdog record");
_Static_assert((uint32_t)(0x38800fb8u + WDG_WORDS * 4) <= 0x38800fd8u, "the watchdog record overlaps the boot record");
_Static_assert((uint32_t)(0x38800fd8u + BOOT_WORDS * 4) <= 0x38800fe8u, "the boot record overlaps the SP watermark");
_Static_assert((uint32_t)(0x38800fe8u + SP_WORDS * 4) <= BKP_END, "the SP watermark runs past the end of backup SRAM");
_Static_assert((uint32_t)(0x388003c4u + 4) <= 0x38800400u, "the trails run into comp.c's state at 0x38800400");
_Static_assert((uint32_t)0x38800384u >= 0x38800384u, "the trails must start above od.c's 0x384-byte bank");

#define CFSR   (*(volatile uint32_t *)0xe000ed28u)
#define HFSR   (*(volatile uint32_t *)0xe000ed2cu)
#define MMFAR  (*(volatile uint32_t *)0xe000ed34u)
#define BFAR   (*(volatile uint32_t *)0xe000ed38u)
#define AIRCR  (*(volatile uint32_t *)0xe000ed0cu)

/*
 * The window watchdog, set up by stock's HAL at 0x08046968: prescaler /128, counter 0x7f, window 0x7f (so no
 * early-refresh trap) and EWI OFF. It is fed from a supervisor at 0x08046994 that refreshes only while BOTH of two
 * task stamps are within 3,749 of its own free-running counter - so a reset means one monitored task stopped
 * checking in, and the two ages below say which. The object holding them is at 0x2400a584 (the literal the
 * supervisor's caller loads at 0x0804cb28); the HAL handle follows it at 0x2400a590.
 */
#define WWDG_CR   (*(volatile uint32_t *)0x50003000u)
#define WWDG_CFR  (*(volatile uint32_t *)0x50003004u)
#define WWDG_SR   (*(volatile uint32_t *)0x50003008u)
#define WWDG_EWI  (1u << 9)
#define WDG_SUP   ((volatile uint32_t *)0x2400a584u)   /* +0 stamp A, +4 stamp B, +8 the supervisor's own counter */

#define NVIC_ISER0 (*(volatile uint32_t *)0xe000e100u)
#define NVIC_IPR0  (*(volatile uint8_t *)0xe000e400u)  /* IRQ 0 = WWDG1 */

/* The reset cause, which stock clears for itself at 0x0804695e - readable only this early. Offsets cross-checked
   against the two RCC registers our own code already used: AHB4ENR 0x580244e0 (od.c) and AHB1ENR 0x580244d8
   (usbdev.c), which puts the block at 0x58024400 and RSR at its +0xd0 as the reference manual has it. */
#define RCC_RSR    (*(volatile uint32_t *)0x580244d0u)

void bkp_enable(void);                         /* od.c: clock on, backup-domain writes allowed */

/*
 * THE DATA CACHE ATE EVERY RECORD THIS FILE EVER WROTE. Backup SRAM is covered by no MPU region, so it falls under
 * the privileged default map: normal memory, write-back cached. A record written here and followed microseconds
 * later by SYSRESETREQ is still only in the cache when the core resets, and a reset does not write the cache out.
 * 3.2.o, 3.2.q and 3.2.r all "caught nothing" for this reason, and no suite could show it because the emulator has
 * no cache. Measured on the test unit 2026-10-11: a KNOWN fault (the unaligned trap) left the software-reset signature
 * in RCC_RSR and no record; with backup SRAM made non-cacheable over USB the same fault left the record.
 * So: clean every line of the 4 KB out to the SRAM, then DSB so the writes have actually completed, and only then
 * ask for the reset. The crumb rings get the same treatment for free, so the saved trail is exact, not stale.
 */
#define DCCMVAC (*(volatile uint32_t *)0xe000ef68u)    /* data cache: write the line holding this address to memory */

static void bkp_flush(void)
{
    for (uint32_t a = 0x38800000u; a < BKP_END; a += 32u)
        DCCMVAC = a;
    __asm volatile("dsb\n isb");
}

/*
 * Is a stacked frame pointer worth dereferencing? On a STACKING fault the hardware could not push the frame at
 * all, so the pointer it hands us is wherever SP had wandered - and 3.2.q's recorder read frame[6] as its first
 * act, which faults again inside the handler and locks the CPU up: no record, no interrupts, and the watchdog
 * resets it looking exactly like a spin. That is the one fault class this instrument still could not see, and it
 * is the leading candidate for the Relapse hang, so the frame is now checked before it is read.
 */
static int frame_ok(uint32_t sp)
{
    static const uint32_t lo[] = {0x20000000u, 0x24000000u, 0x30000000u, 0x38000000u, 0xC0000000u};
    static const uint32_t hi[] = {0x20020000u, 0x24080000u, 0x30048000u, 0x38010000u, 0xC4000000u};
    if (sp & 7u)                               /* the exception frame is 8-byte aligned, always */
        return 0;
    for (unsigned i = 0; i < sizeof lo / sizeof *lo; i++)
        if (sp >= lo[i] && sp + 0x20u <= hi[i])
            return 1;
    return 0;
}

#ifdef FAULT_SHOW
/*
 * THE DIAGNOSTIC BUILD (FAULT_SHOW=1 ./build.sh, 2026-10-14). Testers' units boot-loop at the logo and the records
 * above are lost to them: the unit resets at once, and USB never comes up between resets. So instead of the reset,
 * the record is drawn on the screen, big, and the unit holds there for a photo. Nothing of stock's is called: the
 * frame buffer is whatever the LCD controller is scanning out (each enabled layer's CFBAR / PFCR / CFBLR / CFBLNR),
 * written directly and cleaned out of the data cache. The window watchdog keeps running under a fault handler, so
 * the hold feeds it; stock never starts the independent watchdog (no IWDG address or key in the image).
 * Rows, top down: a tag (FFFF = fault, DDDD = watchdog) followed by the chip's silicon revision from DBGMCU_IDCODE
 * (2003 = rev V, 1003 = rev Y - the test unit is V, 2026-10-14), then the record's words 1..7, each led by its number.
 */
#define REV_ID (*(const volatile uint32_t *)0x5c001000u >> 16)
#define LTDC_L(n, off) (*(volatile uint32_t *)(0x50001084u + 0x80u * ((n) - 1u) + (off)))
#define DCCMVAC_A      (*(volatile uint32_t *)0xe000ef68u)
#define SCALE 3

static const uint8_t glyph[16][7] = {
    {14, 17, 19, 21, 25, 17, 14}, {4, 12, 4, 4, 4, 4, 14},   {14, 17, 1, 2, 4, 8, 31},   {31, 2, 4, 2, 1, 17, 14},
    {2, 6, 10, 18, 31, 2, 2},     {31, 16, 30, 1, 1, 17, 14}, {6, 8, 16, 30, 17, 17, 14}, {31, 1, 2, 4, 8, 8, 8},
    {14, 17, 17, 14, 17, 17, 14}, {14, 17, 17, 15, 1, 2, 12}, {14, 17, 17, 31, 17, 17, 17}, {30, 17, 17, 30, 17, 17, 30},
    {14, 17, 16, 16, 16, 17, 14}, {28, 18, 17, 17, 17, 18, 28}, {31, 16, 16, 30, 16, 16, 31}, {31, 16, 16, 30, 16, 16, 16},
};

struct fb {
    uint32_t base, pitch, bpp, w, h, white, black;
};

static void put(const struct fb *f, uint32_t x, uint32_t y, int on)
{
    if (x >= f->w || y >= f->h)
        return;
    volatile uint8_t *p = (volatile uint8_t *)(f->base + y * f->pitch + x * f->bpp);
    if (f->bpp == 2) {
        *(volatile uint16_t *)p = (uint16_t)(on ? f->white : f->black);
    } else if (f->bpp == 4) {
        *(volatile uint32_t *)p = on ? f->white : f->black;
    } else {
        p[0] = p[1] = p[2] = on ? 0xffu : 0u;
    }
}

static void hexdigit(const struct fb *f, uint32_t x, uint32_t y, unsigned d)
{
    for (uint32_t r = 0; r < 7u * SCALE; r++)
        for (uint32_t c = 0; c < 5u * SCALE; c++)
            if (glyph[d & 15u][r / SCALE] & (16u >> (c / SCALE)))
                put(f, x + c, y + r, 1);
}

static void row(const struct fb *f, uint32_t y, unsigned label, uint32_t v)
{
    const uint32_t step = 6u * SCALE;
    hexdigit(f, 4, y, label);
    for (unsigned i = 0; i < 8; i++)
        hexdigit(f, 4 + step * (i + 2u), y, (v >> (28 - 4 * i)) & 15u);
}

static void show(uint32_t tag, const volatile uint32_t *rec)
{
    for (unsigned n = 1; n <= 2; n++) {
        if (!(LTDC_L(n, 0) & 1u))                        /* layer not enabled */
            continue;
        /* Pixel formats 0 ARGB8888, 1 RGB888, 2 RGB565, 3 ARGB1555, 4 ARGB4444. The Blackbox runs both layers in
           ARGB1555 (read off the test unit, PFCR = 3): its "black" must carry the alpha bit, or the top layer is
           transparent and the picture underneath shows through. */
        static const uint32_t white[5] = {0xffffffffu, 0xffffffu, 0xffffu, 0xffffu, 0xffffu};
        static const uint32_t black[5] = {0xff000000u, 0u, 0u, 0x8000u, 0xf000u};
        uint32_t pf = LTDC_L(n, 0x10) & 7u;
        if (pf > 4)
            continue;                                    /* not a format this draws */
        struct fb f = {LTDC_L(n, 0x28), (LTDC_L(n, 0x2c) >> 16) & 0x1fffu, pf == 0 ? 4u : pf == 1 ? 3u : 2u, 0,
                       LTDC_L(n, 0x30) & 0x7ffu, white[pf], black[pf]};
        if (f.base < 0x20000000u || !f.pitch || !f.h)
            continue;                                    /* not a buffer */
        f.w = f.pitch / f.bpp;
        for (uint32_t y = 0; y < f.h; y++) {
            *(volatile uint32_t *)0x50003000u = 0xffu;   /* the dog, every line: a fault can land late in its count */
            for (uint32_t x = 0; x < f.w; x++)
                put(&f, x, y, 0);
        }
        row(&f, 4, 0, tag);
        for (unsigned i = 1; i <= 7; i++)
            row(&f, 4 + (8u * SCALE) * i, i, rec[i]);
        for (uint32_t a = f.base & ~31u; a < f.base + f.pitch * f.h; a += 32u)
            DCCMVAC_A = a;
    }
    __asm__ volatile("dsb");
}

/* Hold here, picture on screen, for as long as the power stays on. */
static void hold(void)
{
    for (;;)
        *(volatile uint32_t *)0x50003000u = 0xffu;     /* WWDG_CR: WDGA + counter 0x7f, a refresh (window is 0x7f) */
}
#endif

/* Called from the handler with the exception frame and EXC_RETURN. */
void fault_record(uint32_t *frame, uint32_t exc_return)
{
    uint32_t sp = (uint32_t)frame;
    int ok = frame_ok(sp);
    bkp_enable();
    /* The registers first: these come from the core, not from memory, so they land even if the frame is unreadable.
       CFSR's STKERR / MSTKERR / bit 4 is what names a stacking fault, and HFSR's FORCED bit says it escalated. */
    FAULT_REC[4] = CFSR;
    FAULT_REC[5] = HFSR;
    FAULT_REC[6] = MMFAR;
    FAULT_REC[7] = BFAR;
    FAULT_REC[8] = exc_return;
    FAULT_REC[9] = sp;
    FAULT_REC[10] = (uint32_t)ok;
    FAULT_REC[0] = FAULT_MAGIC;                /* EARLY now: half a record beats the nothing 3.2.q would have left */
    if (ok) {
        FAULT_REC[1] = frame[6];               /* PC: the faulting instruction */
        FAULT_REC[2] = frame[5];               /* LR: who called it */
        FAULT_REC[3] = frame[7];               /* xPSR */
        FAULT_REC[11] = frame[0];
        FAULT_REC[12] = frame[1];
        FAULT_REC[13] = frame[2];
        FAULT_REC[14] = frame[3];
    }
    FAULT_REC[15] = SP_LOW[0];                 /* how close the delay dispatch had come to running out of stack */
    bkp_flush();                               /* out of the cache and into the SRAM, or the reset throws it away */
#ifdef FAULT_SHOW
    *(volatile uint32_t *)0x50003000u = 0xffu; /* WWDG refresh before the draw */
    show(0xffff0000u | REV_ID, FAULT_REC);              /* rows: 1 PC, 2 LR, 3 xPSR, 4 CFSR, 5 HFSR, 6 MMFAR, 7 BFAR */
    hold();
#endif
    AIRCR = (0x5fau << 16) | (1u << 2);        /* SYSRESETREQ: reset as promptly as the stub's watchdog did */
    for (;;)
        ;
}

/*
 * Bit 2 of EXC_RETURN says which stack the frame is on. Naked, because the frame pointer must be the stack
 * pointer as it was at the fault, not after a prologue.
 */
__attribute__((naked)) void fault_handler(void)
{
    __asm volatile(
        "tst   lr, #4            \n"
        "ite   eq                \n"
        "mrseq r0, msp           \n"
        "mrsne r0, psp           \n"
        "mov   r1, lr            \n"
        "b     fault_record      \n");
}

/*
 * The early wakeup interrupt, one watchdog tick before the reset. We do NOT refresh and we do NOT prevent the
 * reset - the unit dies exactly when it did before - we only write down where it was and which task had stopped
 * checking in. Clearing EWIF keeps the handler from re-entering for the remaining tick.
 */
void wdg_record(uint32_t *frame, uint32_t exc_return)
{
    uint32_t now = WDG_SUP[2];
    bkp_enable();
    WDG_REC[1] = frame[6];                     /* PC: what the CPU was running when the dog ran out */
    WDG_REC[2] = frame[5];                     /* LR */
    WDG_REC[3] = frame[7];                     /* xPSR: 0 = it was in thread mode, else the exception number */
    WDG_REC[4] = now - WDG_SUP[0];             /* how stale stamp A is (over 3,749 = this is the task that stopped) */
    WDG_REC[5] = now - WDG_SUP[1];
    WDG_REC[6] = now;
    WDG_REC[7] = (WWDG_CR & 0xffffu) | (WWDG_SR << 16);
    WDG_REC[0] = WDG_MAGIC;
    (void)exc_return;
    bkp_flush();                               /* ~5 ms to the reset is long, but not a promise */
#ifdef FAULT_SHOW
    *(volatile uint32_t *)0x50003000u = 0xffu; /* refresh first: the reset is one tick away */
    show(0xdddd0000u | REV_ID, WDG_REC);                /* rows: 1 PC, 2 LR, 3 xPSR, 4 age A, 5 age B, 6 now, 7 CR | SR << 16 */
    hold();
#endif
    WWDG_SR = 0;                               /* EWIF: written zero, so the tick runs out once, not in a loop */
}

__attribute__((naked)) void wdg_handler(void)
{
    __asm volatile(
        "tst   lr, #4            \n"
        "ite   eq                \n"
        "mrseq r0, msp           \n"
        "mrsne r0, psp           \n"
        "mov   r1, lr            \n"
        "b     wdg_record        \n");
}

/*
 * One breadcrumb, into the audio ring (which == 0) or the GUI ring (1). Consecutive repeats are dropped, so four
 * slots hold the last four DISTINCT steps of that task rather than four copies of what it does every block. The
 * two rings are separate because in 3.2.q they were not: a burst of GUI page-builds flushed the audio task's whole
 * trail out of the shared ring, and the audio task is the one that dies.
 */
void crumb_drop(uint32_t v, uint32_t which)
{
    volatile uint32_t *ring = which ? GUI : AUD;
    unsigned shift = which ? 8u : 0u;
    uint32_t i = (RING_IDX >> shift) & 0xffu;
    if (i >= RING_LEN)
        i = 0;
    if (ring[i] == v)
        return;
    i = i + 1 >= RING_LEN ? 0 : i + 1;
    ring[i] = v;
    RING_IDX = (RING_IDX & ~(0xffu << shift)) | (i << shift);
}

/*
 * The stack watermark, from the audio task's own dispatch: the lowest SP the delay has ever been called at. If the
 * hang is a stacking fault this is where it shows up, without having to survive the fault to find out. Also
 * re-arms the watchdog's early wakeup, because stock's HAL_WWDG_Init runs AFTER master_alloc and clears the bit
 * (measured on the test unit: instrument_boot's NVIC writes stuck, CFR came back 0x387f = HAL's own value).
 */
void audio_watch(uint32_t sp)
{
    SP_LOW[1] = sp;
    if (!SP_LOW[0] || sp < SP_LOW[0])
        SP_LOW[0] = sp;
    if (!(WWDG_CFR & WWDG_EWI))
        WWDG_CFR |= WWDG_EWI;
}

/*
 * Once per boot, from master_alloc (master.c), at the point the delay's lines are allocated - before any audio
 * block has run, so the rings still hold the trail from BEFORE the reset. Copy them where the running unit will
 * not touch them, write down WHY the unit reset, then arm the watchdog's early wakeup.
 *
 * RCC_RSR is the whole point of doing this here: stock clears it itself (RCC_RSR |= RMVF at 0x0804695e) in the
 * same init that sets up the WWDG - and we now know that init runs AFTER master_alloc, so at this moment the
 * reset-cause flags are still intact. By the time USB is up they read 0, which is why three sessions could never
 * tell a watchdog reset from a fault from a brown-out.
 */
void cpu_boot(void);                          /* cpu.c: the meter's state, and the bank 2 verdict in it, start again */

void instrument_boot(void)
{
    uint32_t rsr = RCC_RSR;
    bkp_enable();
    cpu_boot();
    for (uint32_t i = 0; i < RING_LEN; i++) {
        AUD_SAVED[i] = AUD[i];
        GUI_SAVED[i] = GUI[i];
        AUD[i] = 0;
        GUI[i] = 0;
    }
    BOOT_REC[1] = rsr;
    BOOT_REC[2] = BOOT_REC[2] + 1;                      /* boots since the records were cleared */
    BOOT_REC[3] = (RING_IDX << 16) | (WWDG_CFR & 0xffffu);   /* the ring indexes as they stood, and the dog's setup */
    BOOT_REC[0] = BOOT_MAGIC;
    RING_IDX = 0;
    SP_LOW[0] = 0;
    NVIC_IPR0 = 0;                                      /* highest priority: it must preempt whatever is spinning */
    NVIC_ISER0 |= 1u;                                   /* IRQ 0 = WWDG1 */
    WWDG_CFR |= WWDG_EWI;                               /* armed again from audio_watch, since HAL clears this one */
}
