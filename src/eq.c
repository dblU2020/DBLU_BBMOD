/*
 * Per-pad EQ. Original 1010music Blackbox, firmware 3.1.9. The filters themselves: eq_dsp.c (bank 2).
 *
 * Where: on the pad's own mix, in the same place as the insert (insert.c) and through its hooks, before or after the
 * insert effect as the pad's "EQ:" setting says (Post by default). So the sends hear the EQ'd pad, and a chord costs
 * the same as one note. Granular pads go another way through the engine and have neither.
 * A pad whose EQ is flat (all three gains 0 dB, Low Cut Off) is not touched and is not given a mix buffer of its
 * own for it: it costs nothing.
 *
 * Settings: nine per pad, in the pad's own store, so they save with the preset (a preset from before has none, and
 * an absent setting reads 0: flat). The eight knobs are 0x1c8 .. 0x1cf, in eq.h's order; the ninth, 0x1f0, is the
 * "EQ:" row on the Conf tab, Post / Pre. None of the nine is registered or special-cased in stock (each was looked
 * for in the image as an immediate: only stack and object offsets carry those numbers). The gains use stock's dB
 * type; the frequencies, Mid Q and Low Cut are lists (DBLU04: the master EQ's Freq / Q types showed nothing on a pad's
 * knob page), with new xml names (eqlofreq, eqmidfreq, eqhifreq, eqmidq) so no older preset's knob units land in them.
 * The engine reads them itself, like insert_tick, one pad per block: insert_tick calls eq_tick with the same pad.
 * State: 16 x 184 bytes behind insert.c's bank, in the part of its 0x22000 that the bank leaves over.
 * Knob changes glide while the pad sounds; a pad that was silent the block before (insert_live sees those: eq_rest)
 * starts its next note right at its settings.
 * UI (master.c): the "EQ:" row on a pad's Conf tab; INFO on that row opens the eight-knob screen for that pad.
 */
#include "eq.h"

#define FN(addr) ((addr) | 1u)
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef int (*setting_fn)(const void *store, unsigned param);
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_setting       ((setting_fn)FN(0x08093e9c))

#define TYPE_DB   7              /* milli-dB, shown as dB */
#define P_EQ      0x1c8          /* + EQ_LO_G .. EQ_Q */
#define P_EQ_POS  0x1f0

static const char *const cut_names[EQ_CUTS] = {"Off", "20Hz", "25Hz", "31Hz", "40Hz", "50Hz", "63Hz", "80Hz", "100Hz",
                                               "125Hz", "160Hz", "200Hz", "250Hz", "315Hz", "400Hz", "500Hz", "630Hz",
                                               "800Hz", "1.0kHz"};
static const char *const pos_names[EQ_POSITIONS] = {"Post", "Pre"};

/*
 * The three frequencies and Mid Q are LISTS (DBLU04). Up to DBLU03 they were knobs of the master EQ's own types
 * (0xa Freq, 0xb Q) so the screen would read Hz and Q; on a pad's knob page stock shows nothing for those types and
 * turning them changed nothing (the first unit, 2026-10-31). A list shows its own names, as Low Cut does. Third-octave
 * steps; the EQ glides between them. eq_tick turns the position into the knob units eq_dsp.c works in
 * (frequency: 100 log2(f / 20 Hz); Q: 1000 / 7.5 log2(Q / 0.1)), so bank 2 is unchanged.
 */
#define LO_FS  14
#define MID_FS 20
#define HI_FS  11
#define QS     15
static const char *const lo_f_names[LO_FS] = {"30Hz", "40Hz", "50Hz", "63Hz", "80Hz", "100Hz", "125Hz", "160Hz", "200Hz",
                                              "250Hz", "315Hz", "400Hz", "500Hz", "600Hz"};
static const char *const mid_f_names[MID_FS] = {"100Hz", "125Hz", "160Hz", "200Hz", "250Hz", "315Hz", "400Hz", "500Hz",
                                                "630Hz", "800Hz", "1.0kHz", "1.25kHz", "1.6kHz", "2.0kHz", "2.5kHz",
                                                "3.15kHz", "4.0kHz", "5.0kHz", "6.3kHz", "8.0kHz"};
static const char *const hi_f_names[HI_FS] = {"1.6kHz", "2.0kHz", "2.5kHz", "3.15kHz", "4.0kHz", "5.0kHz", "6.3kHz",
                                              "8.0kHz", "10kHz", "12.5kHz", "16kHz"};
static const char *const q_names[QS] = {"0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "1.0", "1.2", "1.5", "2.0", "2.5",
                                        "3.0", "4.0", "5.6", "8.0"};
/* the same lists in knob units; 100 Hz and 1 kHz as the defaults before DBLU04 had them (233, 565) */
static const int16_t lo_f_units[LO_FS] = {59, 100, 132, 166, 200, 233, 264, 300, 332, 364, 398, 432, 464, 491};
static const int16_t mid_f_units[MID_FS] = {233, 264, 300, 332, 364, 398, 432, 464, 498, 532, 565, 597, 632, 664, 697,
                                            730, 764, 797, 830, 864};
static const int16_t hi_f_units[HI_FS] = {632, 664, 697, 730, 764, 797, 830, 864, 897, 929, 964};
static const int16_t q_units[QS] = {212, 267, 310, 345, 374, 400, 443, 478, 521, 576, 619, 654, 710, 774, 843};
enum { LO_F_FIRST = 5, MID_F_FIRST = 10, HI_F_FIRST = 5, Q_FIRST = 4 };     /* 100 Hz, 1.0 kHz, 5.0 kHz, 0.7 */
#define LIST_MAX 32              /* a stored value below this is a list position; from it up, knob units as before
                                    (what the host harness sets, to put a band at any frequency) */

static int16_t units(int v, const int16_t *table, int count)
{
    if (v >= LIST_MAX)
        return (int16_t)(v > 32767 ? 32767 : v);
    return table[v < 0 ? 0 : v >= count ? count - 1 : v];
}

/* master.c calls this from its registration hook, lfo.c the other from the pad-defaults one. */
void eq_register(void *table)
{
    fw_register_list(table, P_EQ_POS, "EQ:", pos_names, EQ_POSITIONS, "eqpos");
    fw_register_num(table, P_EQ + EQ_LO_G, TYPE_DB, "Low:", -EQ_GAIN_MAX, EQ_GAIN_MAX, "eqlog");
    fw_register_list(table, P_EQ + EQ_LO_F, "Low Frq:", lo_f_names, LO_FS, "eqlofreq");
    fw_register_num(table, P_EQ + EQ_MID_G, TYPE_DB, "Mid:", -EQ_GAIN_MAX, EQ_GAIN_MAX, "eqmidg");
    fw_register_list(table, P_EQ + EQ_MID_F, "Mid Frq:", mid_f_names, MID_FS, "eqmidfreq");
    fw_register_num(table, P_EQ + EQ_HI_G, TYPE_DB, "High:", -EQ_GAIN_MAX, EQ_GAIN_MAX, "eqhig");
    fw_register_list(table, P_EQ + EQ_HI_F, "High Frq:", hi_f_names, HI_FS, "eqhifreq");
    fw_register_list(table, P_EQ + EQ_CUT, "Low Cut:", cut_names, EQ_CUTS, "eqcut");
    fw_register_list(table, P_EQ + EQ_Q, "Mid Q:", q_names, QS, "eqmidq");
}

void eq_defaults(void *store)
{
    /* flat; the shelves at 100 Hz and 5 kHz and the peak at 1 kHz, Q 0.7 (the sketch's starting points); Post */
    static const int16_t first[EQ_KNOBS] = {0, LO_F_FIRST, 0, MID_F_FIRST, 0, HI_F_FIRST, 0, Q_FIRST};
    for (int i = 0; i < EQ_KNOBS; i++)
        fw_store_add(store, P_EQ + i, first[i]);
    fw_store_add(store, P_EQ_POS, EQ_POST);
}

/* ---- the engine ---- */

struct eq_bank {
    uint32_t magic, now;                         /* now: blocks counted by eq_tick */
    uint32_t rest[16];                           /* the block each pad was last silent in */
    struct eq_set set[16];
    struct eq_state st[16];
    const void *rest_obj[16];                    /* which pad OBJECT was silent. The 16 slots go by row and col only,
                                                    and more objects than the sounding pad pass through a slot: on the
                                                    first unit (DBLUEQ1) another bank's silent pad marked a sounding pad
                                                    "new note" every block, so its EQ started over 375 times a second
                                                    (heavy distortion as soon as any knob was off flat). DBLU03 told
                                                    them apart by the engine id; the unit still did it (DBLU04, the
                                                    resampled loop jumped at every block boundary): stock runs a pad and
                                                    then the object linked at pad + 8, so a silent one can carry the
                                                    same id. The object itself cannot be mistaken. */
};
#define EQ_MAGIC  0x45513033u    /* "EQ03": bumped with the layout, like insert.c's */
#define EQ_OFFSET (0x56800u + 0xb000u + 0x21100u)        /* behind insert.c's bank, inside its 0x22000 */
_Static_assert(sizeof(struct eq_bank) <= 0xf00, "insert.c's 0x22000 leaves the EQ 0xf00 bytes");

uint8_t *master_block(void);     /* master.c: the boot-time SDRAM block, or 0 */
int b2_live(void);               /* cpu.c: is flash bank 2, where eq_render lives, the matching payload */

static struct eq_bank *bank(void)
{
    uint8_t *mem = master_block();
    if (!mem)
        return 0;
    struct eq_bank *b = (struct eq_bank *)(mem + EQ_OFFSET);
    if (b->magic != EQ_MAGIC) {
        /* all flat, nothing primed: the SDRAM keeps whatever a reset or an older build left there */
        for (unsigned i = 0; i < sizeof *b / 4; i++)
            ((volatile uint32_t *)b)[i] = 0;
        b->magic = EQ_MAGIC;
    }
    return b;
}

/* insert_tick, for the pad it is reading this block */
void eq_tick(unsigned q, const void *store)
{
    struct eq_bank *b = bank();
    if (!b)
        return;
    b->now++;                                    /* insert_tick runs once a block */
    struct eq_set *p = &b->set[q & 15];
    for (int i = 0; i < EQ_KNOBS; i++) {
        int v = fw_setting(store, P_EQ + (unsigned)i);
        p->k[i] = (int16_t)(v < -32768 ? -32768 : v > 32767 ? 32767 : v);
    }
    p->k[EQ_LO_F] = units(p->k[EQ_LO_F], lo_f_units, LO_FS);
    p->k[EQ_MID_F] = units(p->k[EQ_MID_F], mid_f_units, MID_FS);
    p->k[EQ_HI_F] = units(p->k[EQ_HI_F], hi_f_units, HI_FS);
    p->k[EQ_Q] = units(p->k[EQ_Q], q_units, QS);
    p->pos = fw_setting(store, P_EQ_POS) == EQ_PRE ? EQ_PRE : EQ_POST;
}

/* insert_live: the pad object `pad` (slot q) has no voice sounding this block. Integers only, like eq_on. */
void eq_rest(unsigned q, const void *pad)
{
    struct eq_bank *b = bank();
    if (b) {
        b->rest[q & 15] = b->now;
        b->rest_obj[q & 15] = pad;
    }
}

/* Does pad q's EQ have anything to do: a gain off 0 dB, the Low Cut on, or a band still finishing? Integers only:
   insert_on asks this for the buffer decision, which runs with the caller's float registers live. */
static int on(const struct eq_bank *b, unsigned q)
{
    const struct eq_set *p = &b->set[q & 15];
    return p->k[EQ_LO_G] || p->k[EQ_MID_G] || p->k[EQ_HI_G] || p->k[EQ_CUT] > 0 || b->st[q & 15].busy;
}

int eq_on(unsigned q)
{
    struct eq_bank *b = bank();
    return b && on(b, q);
}

/* insert_process, once a block: which side of the insert pad q's EQ runs on (EQ_PRE, EQ_POST), or -1, not at all.
   One lookup, so a pad with an insert and a flat EQ pays next to nothing for it. */
int eq_at(unsigned q)
{
    struct eq_bank *b = bank();
    return b && on(b, q) ? b->set[q & 15].pos : -1;
}

/* ...and then, on that side of the insert */
void eq_process(unsigned q, const void *pad, float *l, float *r, int n)
{
    struct eq_bank *b = bank();
    if (!b)
        return;
    struct eq_set *p = &b->set[q & 15];
    /* this pad object silent in this block or the two before: a new note. Any other object in the same slot being
       silent says nothing about this one. */
    p->snap = b->rest_obj[q & 15] == pad && b->now - b->rest[q & 15] <= 2;
    if (b2_live())               /* eq_render is in bank 2: bypass rather than fault on a bad one */
        eq_render(&b->st[q & 15], p, l, r, n);
}
