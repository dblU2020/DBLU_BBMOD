/*
 * The reverb behind Confetti's Space and Prism's Hall. Original 1010music Blackbox, firmware 3.1.9.
 * One copy for both (they were the same loop twice).
 */
#include "rev4.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")

static const uint16_t len[8] = {229, 173, 613, 449, 1933, 2351, 2927, 3559};
static const uint16_t off[8] = {0, 229, 402, 1015, 1464, 3397, 5748, 8675};

/* One frame. lines: REV4_FLOATS floats, zeroed to start. decay: feedback of the four lines (below 1).
   damping: 1 = bright, towards 0 = darker tail. out[0] / out[1]: left / right, not scaled.
   This file is in flash bank 2 with its two callers (build.sh: BANK2_SRCS) since 3.3.c. It used to sit in the code
   cave, where every relink moved it out from under the bank 2 code that called it - the crash behind every build
   from 3.2.m to 3.2.r - and then behind a jump pinned at 0x080f8b40 until bank 2 could be rebuilt. Now bank 2
   calls nothing in bank 1 at all. */
void rev4_step(struct rev4 *r, float *lines, float x, float decay, float damping, float *out)
{
    float o[4], sum = 0.0f;
    for (int k = 0; k < 4; k++) {
        float *line = lines + off[k], d = line[r->at[k]], t = x + 0.6f * d;
        line[r->at[k]] = t;
        x = d - 0.6f * t;
        if (++r->at[k] >= len[k])
            r->at[k] = 0;
    }
    for (int k = 0; k < 4; k++) {
        o[k] = lines[off[4 + k] + r->at[4 + k]];
        r->damp[k] += (o[k] - r->damp[k]) * damping;
        o[k] = r->damp[k];
        sum += o[k];
    }
    for (int k = 0; k < 4; k++) {
        lines[off[4 + k] + r->at[4 + k]] = x + decay * (o[k] - 0.5f * sum);
        if (++r->at[4 + k] >= len[4 + k])
            r->at[4 + k] = 0;
    }
    out[0] = o[0] - o[2];
    out[1] = o[1] - o[3];
}
