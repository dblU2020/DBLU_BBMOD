/* Per-pad EQ: what eq.c (firmware glue, bank 1) and eq_dsp.c (the filters, bank 2; also built for the host) share. */
#ifndef EQ_H
#define EQ_H
#include <stdint.h>

/*
 * The eight knobs, in the order the knob page shows them. Slots come in vertical pairs on that screen, so this is
 * column by column: Low over Low Frq, Mid over Mid Frq, High over High Frq, Low Cut over Mid Q (the sketch's layout:
 * gains and the cut on top, the frequencies and Q under them).
 * Units are the store's: gains in milli-dB; the three frequencies and Q in stock's own knob units (the master EQ's
 * "Freq:" and "Q:" types, so the screen shows Hz and Q exactly as the DSP uses them); Low Cut an index into a list.
 */
enum { EQ_LO_G, EQ_LO_F, EQ_MID_G, EQ_MID_F, EQ_HI_G, EQ_HI_F, EQ_CUT, EQ_Q, EQ_KNOBS };
enum { EQ_POST, EQ_PRE, EQ_POSITIONS };          /* after the pad's insert (the default), or before it */
enum { BAND_CUT, BAND_LO, BAND_MID, BAND_HI, EQ_BANDS };        /* signal order: low cut first, as in the sketch */

#define EQ_CUTS 19                               /* Off, then 20 Hz .. 1 kHz in third-octave steps */

/* The knobs' ranges, in store units. Freq knob v is 20 Hz * 2^(v / 100); Q knob v is 0.1 * 2^(7.5 v / 1000)
   (FUN_08060640 and FUN_080606c0, the curves stock's display uses for types 0xa and 0xb). */
#define EQ_GAIN_MAX 18000                        /* +-18 dB */
#define EQ_LO_F_MIN 59                           /* 30 Hz */
#define EQ_LO_F_MAX 491                          /* 601 Hz */
#define EQ_MID_F_MIN 233                         /* 101 Hz */
#define EQ_MID_F_MAX 865                         /* 8.03 kHz */
#define EQ_HI_F_MIN 623                          /* 1.50 kHz */
#define EQ_HI_F_MAX 965                          /* 16.07 kHz */
#define EQ_Q_MIN 212                             /* 0.30 */
#define EQ_Q_MAX 843                             /* 8.00 */

/* The pad's knobs as its store has them. Bank 1 writes (eq_tick, one pad per block), bank 2 reads. */
struct eq_set {
    int16_t k[EQ_KNOBS];
    uint8_t pos;
    uint8_t snap;                                /* the pad was silent just now: start at the settings, no glide */
    uint8_t _r[2];
};

/*
 * Bank 2's working state for one pad. `cur` follows the knobs a step per block (gains in dB, the rest in knob
 * units, so a frequency glides in octaves), and a band's coefficients are worked out again only in a block where its
 * `cur` moved. `busy` is the one thing bank 1 reads: whether any band still has sound to finish, as a byte, because
 * the buffer decision runs with the caller's float registers live.
 */
struct eq_state {
    float cur[EQ_KNOBS];
    float c[EQ_BANDS][5];                        /* b0 b1 b2 a1 a2, a0 divided out */
    float z[EQ_BANDS][2][2];                     /* per band, per channel: transposed direct form II */
    uint8_t on;                                  /* bit per band: running */
    uint8_t primed;                              /* cur has been set up */
    uint8_t busy;
    uint8_t _r;
    uint8_t linger[EQ_BANDS];                    /* blocks a band keeps running after it reached flat */
};

/* One block, in place. r may be 0 (a mono mix). */
void eq_render(struct eq_state *s, const struct eq_set *p, float *l, float *r, int n);

/* eq.c, bank 1: what insert.c calls */
void eq_tick(unsigned q, const void *store);
void eq_rest(unsigned q, const void *pad);
int eq_on(unsigned q);
int eq_at(unsigned q);
void eq_process(unsigned q, const void *pad, float *l, float *r, int n);

#endif
