/* A small reverb shared by Confetti's Space and Prism's Hall: four allpass diffusers into four feedback lines
   (Householder mix), each line damped by a one-pole. Mono in, two decorrelated outs. See rev4.c. */
#include <stdint.h>

#define REV4_FLOATS 12234            /* the lines: 229 + 173 + 613 + 449 + 1933 + 2351 + 2927 + 3559 */

struct rev4 {
    uint32_t at[8];                  /* positions in the eight lines */
    float damp[4];
};

void rev4_step(struct rev4 *r, float *lines, float x, float decay, float damping, float *out);
