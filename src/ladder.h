/*
 * Classic ladder low-pass for the pad filter's "Filter Type:" (see ladder.c). Shared by filter.c and the host.
 */
#ifndef LADDER_H
#define LADDER_H
#include <stdint.h>

enum { FT_CLEAN, FT_LADDER, FT_LADDER50, FT_VINTAGE, FT_TYPES };   /* list order: Clean 24, Ladder, Ladder 50, Vintage */

/* One channel, one block, in place. hz = cutoff, res = the Res knob 0..1, s = this channel's four stage states,
   last = its last input sample (the 2x interpolation). Apart, so filter.c can keep them where its state has room. */
void ladder_render(float *x, int n, float hz, float res, unsigned type, float *s, float *last);

#ifdef LADDER_LINEAR_DEMO
/* the first prototype (linear stages, one soft clip), kept on the host for comparison only; g = tan(pi fc / 48 kHz) */
void ladder_render_linear(float *x, int n, float g, float res, unsigned type, float *s);
#endif

#endif
