/*
 * Per-pad EQ: the filters. Original 1010music Blackbox, firmware 3.1.9. The glue (settings, hooks, memory): eq.c.
 * No firmware calls in this file: it lives in flash bank 2, which must not call bank 1, and host/render_eq.py
 * compiles it for the host as well, so what is rendered there is this code.
 *
 * Four second-order sections per pad, stereo, in signal order:
 *   Low Cut   12 dB/oct high-pass (Butterworth, Q 0.707), Off or 20 Hz .. 1 kHz in third-octave steps
 *   Low       shelf, +-18 dB, 30 .. 600 Hz
 *   Mid       peak, +-18 dB, 100 Hz .. 8 kHz, Q 0.3 .. 8
 *   High      shelf, +-18 dB, 1.5 .. 16 kHz
 * The coefficients are the RBJ cookbook's (shelves at slope 1), worked out in single precision. Transposed direct
 * form II.
 *
 * Changes glide: each knob moves a fixed share of the way to its setting every block, in dB for the gains and in
 * knob units for the rest (which are octaves of frequency), and a band's coefficients are worked out again only in
 * a block where its knobs moved. Except on a pad that was silent until this block (a new note: `snap`), where there
 * is nothing sounding to glide from, so the EQ starts right at its settings. A band with nothing to do is skipped:
 * its gain is 0 dB (Low Cut: Off). A gain band gets there with a glide to 0 dB, which is exactly the identity, and
 * keeps running a little longer so its last output dies away inside the filter rather than being cut off.
 * The Low Cut has no setting that is the identity, so it FADES in and out against the dry signal instead (DBLU06):
 * up to DBLU05 it glided down to a 2.5 Hz "park" and was then dropped, and a float biquad that low no longer matches
 * the dry signal, so switching it off clicked on the unit (2026-11-01; 0.29 jump on a 40 Hz bass on the host).
 */
#include "eq.h"

#define FS        48000.0f
#define PI_F      3.14159265f
#define LOG2_10   3.32192809f
#define GLIDE     0.35f                  /* share of the way to the setting, per block (2.67 ms): ~40 ms for 18 dB */
#define SNAP_DB   0.005f                 /* closer than this, a gain is there */
#define SNAP_KNOB 0.3f                   /* closer than this, a frequency or Q is there (0.2 % of frequency) */
#define CUT_PARK  (-300.0f)              /* the Low Cut's "Off": 2.5 Hz, where it is as good as not there */
#define LINGER    32                     /* blocks a band keeps running after it reached flat (85 ms) */
#define CUT_FADE  8                      /* blocks the Low Cut takes to fade in or out (21 ms); linger[BAND_CUT] is
                                            how far in it is, 0 = out (not running) .. CUT_FADE = all filtered */

/* Low Cut list -> knob units (100 * log2(f / 20 Hz)): Off, 20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250,
   315, 400, 500, 630, 800, 1000 Hz */
static const float cut_units[EQ_CUTS] = {
    CUT_PARK, 0.0000f, 32.1928f, 65.5352f, 100.0000f, 132.1928f, 165.5352f, 200.0000f, 232.1928f, 264.3856f,
    300.0000f, 332.1928f, 364.3856f, 397.7280f, 432.1928f, 464.3856f, 497.7280f, 532.1928f, 564.3856f};

/* which band each knob belongs to */
static const uint8_t band_of[EQ_KNOBS] = {
    1u << BAND_LO, 1u << BAND_LO, 1u << BAND_MID, 1u << BAND_MID, 1u << BAND_HI, 1u << BAND_HI, 1u << BAND_CUT,
    1u << BAND_MID};

static inline float clampf(float x, float lo, float hi)
{
    return x < lo ? lo : x > hi ? hi : x;
}

/* 2^x for |x| <= 30, within 1e-7: an exact power of two times a Taylor series on [-0.5, 0.5] */
static float exp2_f(float x)
{
    x = clampf(x, -30.0f, 30.0f);
    int i = (int)(x + (x < 0.0f ? -0.5f : 0.5f));
    float f = (x - (float)i) * 0.693147181f;
    float p = 1.0f + f * (1.0f + f * (0.5f + f * (1.0f / 6 + f * (1.0f / 24 + f * (1.0f / 120 + f * (1.0f / 720))))));
    union { float f; uint32_t u; } v;
    v.u = (uint32_t)(i + 127) << 23;
    return v.f * p;
}

/* sin and cos of w in (0, pi): Taylor series on [0, pi / 2], the upper half folded down onto it */
static void sincos_f(float w, float *s, float *c)
{
    int upper = w > 0.5f * PI_F;
    float x = upper ? PI_F - w : w, x2 = x * x;
    *s = x * (1.0f - x2 / 6 * (1.0f - x2 / 20 * (1.0f - x2 / 42 * (1.0f - x2 / 72 * (1.0f - x2 / 110)))));
    float cs = 1.0f - x2 / 2 * (1.0f - x2 / 12 * (1.0f - x2 / 30 * (1.0f - x2 / 56 * (1.0f - x2 / 90 * (1.0f - x2 / 132)))));
    *c = upper ? -cs : cs;
}

/* knob units -> radians per sample */
static float omega(float units)
{
    return clampf(2.0f * PI_F / FS * 20.0f * exp2_f(units * 0.01f), 1e-5f, 0.95f * PI_F);
}

static void set5(float c[5], float b0, float b1, float b2, float a0, float a1, float a2)
{
    float i = 1.0f / a0;
    c[0] = b0 * i;
    c[1] = b1 * i;
    c[2] = b2 * i;
    c[3] = a1 * i;
    c[4] = a2 * i;
}

static void highpass(float c[5], float w)
{
    float s, co;
    sincos_f(w, &s, &co);
    float al = s * 0.707106781f;                         /* sin w / (2 Q), Q = 1 / sqrt 2 */
    set5(c, 0.5f * (1.0f + co), -(1.0f + co), 0.5f * (1.0f + co), 1.0f + al, -2.0f * co, 1.0f - al);
}

static void shelf(float c[5], float w, float db, int high)
{
    float s, co;
    sincos_f(w, &s, &co);
    float a = exp2_f(db * (LOG2_10 / 40.0f)), k = 2.0f * exp2_f(db * (LOG2_10 / 80.0f)) * s * 0.707106781f;
    float ap = a + 1.0f, am = a - 1.0f;
    if (high)
        set5(c, a * (ap + am * co + k), -2.0f * a * (am + ap * co), a * (ap + am * co - k),
             ap - am * co + k, 2.0f * (am - ap * co), ap - am * co - k);
    else
        set5(c, a * (ap - am * co + k), 2.0f * a * (am - ap * co), a * (ap - am * co - k),
             ap + am * co + k, -2.0f * (am + ap * co), ap + am * co - k);
}

static void peak(float c[5], float w, float db, float q)
{
    float s, co;
    sincos_f(w, &s, &co);
    float a = exp2_f(db * (LOG2_10 / 40.0f)), al = s / (2.0f * q);
    set5(c, 1.0f + al * a, -2.0f * co, 1.0f - al * a, 1.0f + al / a, -2.0f * co, 1.0f - al / a);
}

static void design(struct eq_state *s, int b)
{
    const float *k = s->cur;
    if (b == BAND_CUT)
        highpass(s->c[b], omega(k[EQ_CUT]));
    else if (b == BAND_LO)
        shelf(s->c[b], omega(k[EQ_LO_F]), k[EQ_LO_G], 0);
    else if (b == BAND_MID)
        peak(s->c[b], omega(k[EQ_MID_F]), k[EQ_MID_G], 0.1f * exp2_f(k[EQ_Q] * 0.0075f));
    else
        shelf(s->c[b], omega(k[EQ_HI_F]), k[EQ_HI_G], 1);
}

/* the store's values, clamped to the knobs' ranges: gains in dB, the rest in knob units */
static void targets(const struct eq_set *p, float t[EQ_KNOBS])
{
    static const int16_t lo[EQ_KNOBS] = {-EQ_GAIN_MAX, EQ_LO_F_MIN, -EQ_GAIN_MAX, EQ_MID_F_MIN, -EQ_GAIN_MAX, EQ_HI_F_MIN,
                                         0, EQ_Q_MIN};
    static const int16_t hi[EQ_KNOBS] = {EQ_GAIN_MAX, EQ_LO_F_MAX, EQ_GAIN_MAX, EQ_MID_F_MAX, EQ_GAIN_MAX, EQ_HI_F_MAX,
                                         EQ_CUTS - 1, EQ_Q_MAX};
    for (int i = 0; i < EQ_KNOBS; i++) {
        int v = p->k[i] < lo[i] ? lo[i] : p->k[i] > hi[i] ? hi[i] : p->k[i];
        t[i] = (float)v;
    }
    t[EQ_LO_G] *= 0.001f;
    t[EQ_MID_G] *= 0.001f;
    t[EQ_HI_G] *= 0.001f;
    t[EQ_CUT] = cut_units[(int)t[EQ_CUT]];
}

/* does a gain band have anything to do, now or on the way to its setting? (The Low Cut has its own fade.) */
static int wanted(int b, const float *t, const float *cur)
{
    static const uint8_t gain_of[EQ_BANDS] = {EQ_CUT, EQ_LO_G, EQ_MID_G, EQ_HI_G};
    int k = gain_of[b];
    return t[k] != 0.0f || cur[k] != 0.0f;
}

#if defined(__GNUC__) && !defined(__clang__)
#define HOT __attribute__((optimize("O2")))      /* the one loop that runs for every sample: speed, not size */
#else
#define HOT
#endif

/* one section over a block, both channels in the same pass */
HOT static void section(const float c[5], float z[2][2], float *l, float *r, int n)
{
    const float b0 = c[0], b1 = c[1], b2 = c[2], a1 = c[3], a2 = c[4];
    float l1 = z[0][0], l2 = z[0][1];
    if (r) {
        float r1 = z[1][0], r2 = z[1][1];
        for (int i = 0; i < n; i++) {
            float xl = l[i], xr = r[i];
            float yl = l1 + b0 * xl, yr = r1 + b0 * xr;
            l1 = (l2 + b1 * xl) - a1 * yl;               /* written so each step is one multiply-add */
            r1 = (r2 + b1 * xr) - a1 * yr;
            l2 = b2 * xl - a2 * yl;
            r2 = b2 * xr - a2 * yr;
            l[i] = yl;
            r[i] = yr;
        }
        z[1][0] = r1;
        z[1][1] = r2;
    } else {
        for (int i = 0; i < n; i++) {
            float xl = l[i], yl = l1 + b0 * xl;
            l1 = (l2 + b1 * xl) - a1 * yl;
            l2 = b2 * xl - a2 * yl;
            l[i] = yl;
        }
    }
    z[0][0] = l1;
    z[0][1] = l2;
}

/* the same, with the output cross-faded from the dry signal: share g0 of the filtered at the block's start, g1 at
   its end (the Low Cut fading in or out). The filter itself runs on, from its own output, as in section. */
HOT static void section_fade(const float c[5], float z[2][2], float *l, float *r, int n, float g0, float g1)
{
    const float b0 = c[0], b1 = c[1], b2 = c[2], a1 = c[3], a2 = c[4];
    float dg = (g1 - g0) / (float)n;
    for (int k = 0; k < 2; k++) {
        float *x = k ? r : l;
        if (!x)
            continue;
        float z1 = z[k][0], z2 = z[k][1], g = g0;
        for (int i = 0; i < n; i++) {
            float in = x[i], y = z1 + b0 * in;
            z1 = (z2 + b1 * in) - a1 * y;
            z2 = b2 * in - a2 * y;
            g += dg;
            x[i] = in + (y - in) * g;
        }
        z[k][0] = z1;
        z[k][1] = z2;
    }
}

static void clear(float z[2][2])
{
    z[0][0] = z[0][1] = z[1][0] = z[1][1] = 0.0f;
}

void eq_render(struct eq_state *s, const struct eq_set *p, float *l, float *r, int n)
{
    float t[EQ_KNOBS];
    targets(p, t);
    unsigned moved = 0;
    if (!s->primed || p->snap) {
        /* A new note: start AT the settings. First sight of the pad while it sounds - its EQ was flat, so it has
           not run until now, and a gain is being turned up - start flat, and the gain glides in like any change. */
        for (int i = 0; i < EQ_KNOBS; i++)
            s->cur[i] = t[i];
        if (!p->snap) {
            s->cur[EQ_LO_G] = s->cur[EQ_MID_G] = s->cur[EQ_HI_G] = 0.0f;
            s->cur[EQ_CUT] = CUT_PARK;
        }
        for (int b = 0; b < EQ_BANDS; b++) {
            clear(s->z[b]);
            s->linger[b] = 0;
        }
        s->on = 0;
        s->primed = 1;
        if (p->snap && t[EQ_CUT] != CUT_PARK)
            s->linger[BAND_CUT] = CUT_FADE;      /* a new note starts with the Low Cut all the way in, no fade */
    }
    /* The Low Cut fades rather than glides between on and off: off, it stays at its last frequency while it fades
       out; coming on from out, it starts right at its frequency (it fades in from the dry signal anyway). */
    int cut_on = t[EQ_CUT] != CUT_PARK;
    if (!cut_on)
        t[EQ_CUT] = s->cur[EQ_CUT];
    else if (!s->linger[BAND_CUT])
        s->cur[EQ_CUT] = t[EQ_CUT];
    for (int i = 0; i < EQ_KNOBS; i++) {
        float d = t[i] - s->cur[i];
        if (d == 0.0f)
            continue;
        float snap = i == EQ_LO_G || i == EQ_MID_G || i == EQ_HI_G ? SNAP_DB : SNAP_KNOB;
        s->cur[i] = d < snap && d > -snap ? t[i] : s->cur[i] + d * GLIDE;
        moved |= band_of[i];
    }
    for (int b = 0; b < EQ_BANDS; b++) {
        unsigned bit = 1u << b;
        if (b == BAND_CUT) {
            unsigned f0 = s->linger[b], f1 = cut_on ? (f0 < CUT_FADE ? f0 + 1 : f0) : (f0 ? f0 - 1 : 0);
            s->linger[b] = (uint8_t)f1;
            if (!f0 && !f1) {
                if (s->on & bit) {
                    s->on &= ~bit;
                    clear(s->z[b]);
                }
                continue;
            }
            if (!(s->on & bit)) {
                clear(s->z[b]);
                s->on |= bit;
                moved |= bit;
            }
            if (moved & bit)
                design(s, b);
            if (f0 == CUT_FADE && f1 == CUT_FADE)
                section(s->c[b], s->z[b], l, r, n);
            else
                section_fade(s->c[b], s->z[b], l, r, n, (float)f0 * (1.0f / CUT_FADE), (float)f1 * (1.0f / CUT_FADE));
            if (!f1) {
                s->on &= ~bit;
                clear(s->z[b]);
            }
            continue;
        }
        if (wanted(b, t, s->cur)) {
            if (!(s->on & bit)) {
                clear(s->z[b]);
                s->on |= bit;
                moved |= bit;
            }
            s->linger[b] = LINGER;
        } else if (s->on & bit) {
            if (s->linger[b])
                s->linger[b]--;
            else {
                s->on &= ~bit;
                clear(s->z[b]);
            }
        }
        if (!(s->on & bit))
            continue;
        if (moved & bit)
            design(s, b);
        section(s->c[b], s->z[b], l, r, n);
    }
    s->busy = s->on != 0;
}
