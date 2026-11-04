/*
 * Classic transistor ladder low-pass, 24 dB/oct, with optional bass compensation. Original 1010music Blackbox, firmware
 * 3.1.9. No firmware calls in this file: it is meant for flash bank 2 (which must not call bank 1), and
 * host/render_ladder.py compiles it for the host as well, so what is rendered there is this code.
 *
 * The circuit, in the form the literature uses (Stilson & Smith 1996, Huovilainen 2004, D'Angelo & Valimaki 2013):
 * four transistor-pair stages, each a one-pole low-pass whose input and output both pass through a tanh, with the
 * fourth stage's output fed back to the first. Signals in units of twice the thermal voltage:
 *   dy1/dt = w (tanh(x - k (y4 - c x)) - tanh(y1))
 *   dyn/dt = w (tanh(y(n-1))            - tanh(yn))      n = 2..4
 * Here it is solved with the trapezoidal rule (zero delay in the feedback) at twice the sample rate. The tanh of
 * each node is taken as tanh(v) = T(v) v with T worked out from that node's state at the start of the sample, which
 * makes each sample's system linear, so the feedback is solved exactly every sample (no delay, no iteration): the
 * cutoff and resonance stay where they are set up to the top of the range, and the nonlinearity is where the circuit
 * has it - every stage - which is what makes the resonance soften and bloom with level, the drive, and the round
 * self-oscillation.
 * c is a bass compensation (not in the original): the feedback also takes back c x, so with small signals the ladder
 * passes (1 + k c) / (1 + k) at DC.
 *   Vintage    c = 0    the original: at full resonance (k = 4) the bass is 14 dB down
 *   Ladder 50  c = 0.5  half way
 *   Ladder     c = 1    no bass loss
 * k follows the Res knob as k = K_MAX res^2: about 1 at the default (noon), self-oscillation from about 98 %.
 * Oversampling: the input is interpolated to 96 kHz (one new point half way), the two outputs of a sample averaged on
 * the way back. Cheap, and it keeps most of the tanh stages' overtones from folding back.
 */
#include "ladder.h"

#pragma GCC optimize("O2", "no-tree-loop-distribute-patterns")   /* per-sample loop for every voice, as filter.c */

#define FS2     96000.0f         /* the filter's own rate */
#define PI_F    3.14159265f
#define K_MAX   4.2f             /* the feedback at full Res: a little past the onset of self-oscillation (4) */
#define DRIVE   0.4f             /* sample level -> circuit level (units of 2 Vt), output scaled back: a normal sample
                                    stays nearly clean, the stages saturate when it is pushed (hot input, high Res) */

/* tan(x) for 0 <= x < 0.75 (the cutoff tops out at 0.45 x 48 kHz = 0.71 rad at 96 kHz), Pade (3,2) as filter.c's */
static inline float tan_small(float x)
{
    float x2 = x * x;
    return x * (15.0f - x2) / (15.0f - 6.0f * x2);
}

/* T(v) = tanh(v) / v as a fraction num / den. Pade (3,2) of tanh: (27 + v^2) / (27 + 9 v^2), exact at 0 and reaching
   1/3 at |v| = 3, where tanh is as good as 1: beyond it 1 / |v|. Even, positive, at most 1. */
#define TANH_RATIO(v, num, den)                                                                                    \
    do {                                                                                                           \
        float v2_ = (v) * (v);                                                                                     \
        float big_ = v2_ >= 9.0f ? 1.0f : 0.0f;    /* a float flag: compiles to selects, an int one to branches */ \
        float a_ = (v) < 0.0f ? -(v) : (v);                                                                        \
        num = big_ != 0.0f ? 1.0f : 27.0f + v2_;                                                                   \
        den = big_ != 0.0f ? a_ : 27.0f + 9.0f * v2_;                                                              \
    } while (0)

static const float comp_of[FT_TYPES] = {1.0f, 1.0f, 0.5f, 0.0f};

/* One 96 kHz step with the sample's coefficients; s0..s3 the stages' trapezoidal states. Stage n:
   y = A a + b s, the feedback solved for the ladder's input a. */
#define STEP(xin, out)                                                                                             \
    do {                                                                                                           \
        float B0 = b0 * s0, B1 = b1 * s1, B2 = b2 * s2, B3 = b3 * s3;                                              \
        float Q = A3 * (A2 * (A1 * B0 + B1) + B2) + B3;                                                            \
        float a = ((xin) * in_gain - k * Q) * inv;                                                                 \
        float y0 = A0 * a + B0, y1 = A1 * y0 + B1, y2 = A2 * y1 + B2, y3 = A3 * y2 + B3;                           \
        s0 = 2.0f * y0 - s0;                                                                                       \
        s1 = 2.0f * y1 - s1;                                                                                       \
        s2 = 2.0f * y2 - s2;                                                                                       \
        s3 = 2.0f * y3 - s3;                                                                                       \
        out = y3;                                                                                                  \
    } while (0)

void ladder_render(float *x, int n, float hz, float res, unsigned type, float *s, float *last)
{
    float c = comp_of[type < FT_TYPES ? type : FT_LADDER];
    float r = res < 0.0f ? 0.0f : res > 1.0f ? 1.0f : res;
    float k = K_MAX * r * r, in_gain = 1.0f + k * c;
    float f = hz < 10.0f ? 10.0f : hz > 21600.0f ? 21600.0f : hz;
    float g = tan_small(PI_F * f / FS2);
    float s0 = s[0], s1 = s[1], s2 = s[2], s3 = s[3], prev = *last;
    for (int i = 0; i < n; i++) {
        float in = x[i] * DRIVE;
        float mid = 0.5f * (prev + in);
        prev = in;
        /* The coefficients of this 48 kHz sample: each node's tanh slope t = num / den from where the node is now,
           kept for both 96 kHz steps (the slopes move slowly against 96 kHz). Stage n needs g t(n-1) and
           b = 1 / (1 + g tn) = den / (den + g num): with e = den (den + g num) both come from 1 / e. The five
           reciprocals (four stages and the ladder's input, estimated from the last output) share one division. */
        float n0, d0, n1, d1, n2, d2, n3, d3, ni, di;
        TANH_RATIO(s0, n0, d0);
        TANH_RATIO(s1, n1, d1);
        TANH_RATIO(s2, n2, d2);
        TANH_RATIO(s3, n3, d3);
        float est = mid - k * (s3 - c * mid);
        TANH_RATIO(est, ni, di);
        float h0 = d0 + g * n0, h1 = d1 + g * n1, h2 = d2 + g * n2, h3 = d3 + g * n3;
        float e0 = d0 * h0, e1 = d1 * h1, e2 = d2 * h2, e3 = d3 * h3;
        float p1 = e0 * e1, p2 = p1 * e2, p3 = p2 * e3;
        float q = 1.0f / (p3 * di);
        float ri = q * p3;
        q *= di;
        float r3 = q * p2;
        q *= e3;
        float r2 = q * p1;
        q *= e2;
        float r1 = q * e0, r0 = q * e1;
        float b0 = d0 * d0 * r0, b1 = d1 * d1 * r1, b2 = d2 * d2 * r2, b3 = d3 * d3 * r3;
        float A0 = b0 * g * ni * ri;
        float A1 = b1 * g * n0 * h0 * r0;
        float A2 = b2 * g * n1 * h1 * r1;
        float A3 = b3 * g * n2 * h2 * r2;
        float inv = 1.0f / (1.0f + k * A0 * A1 * A2 * A3);
        float ya, yb;
        STEP(mid, ya);
        STEP(in, yb);
        x[i] = (ya + yb) * (0.5f / DRIVE);
    }
    s[0] = s0;
    s[1] = s1;
    s[2] = s2;
    s[3] = s3;
    *last = prev;
}

#ifdef LADDER_LINEAR_DEMO
/* The first prototype: linear trapezoidal stages, one soft clip on the ladder's input, at 48 kHz. Host only. */
static inline float soft(float x)
{
    float v = x > 1.5f ? 1.5f : x < -1.5f ? -1.5f : x;
    return v * (1.0f - 0.148148f * v * v);
}

void ladder_render_linear(float *x, int n, float g, float res, unsigned type, float *s)
{
    float c = comp_of[type < FT_TYPES ? type : FT_LADDER];
    float r = res < 0.0f ? 0.0f : res > 1.0f ? 1.0f : res;
    float k = K_MAX * r * r;
    float G = g / (1.0f + g), H = 1.0f - G;
    float G2 = G * G, G3 = G2 * G, G4 = G2 * G2;
    float in_gain = 1.0f + k * c, norm = 1.0f / (1.0f + k * G4);
    for (int i = 0; i < n; i++) {
        float S = G3 * H * s[0] + G2 * H * s[1] + G * H * s[2] + H * s[3];
        float u = soft((x[i] * in_gain - k * S) * norm);
        float y0 = G * u + H * s[0], y1 = G * y0 + H * s[1], y2 = G * y1 + H * s[2], y3 = G * y2 + H * s[3];
        s[0] = 2.0f * y0 - s[0];
        s[1] = 2.0f * y1 - s[1];
        s[2] = 2.0f * y2 - s[2];
        s[3] = 2.0f * y3 - s[3];
        x[i] = y3;
    }
}
#endif
