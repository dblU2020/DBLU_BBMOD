/*
 * Piano roll, Event editor: the top-right knob rotates the sequence. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock: the piano roll hands encoder 2 (top right) to the note-length handler whether Event is on or not, so in
 * the Event editor it repeats what the note editor already does. With Event on, it now shifts every note of the
 * shown layer by one step per detent, and a note pushed past the end of the loop comes back in at the start (and
 * the other way round). Lengths, pitches, velocities and PLAY values are untouched, so turning back the same number
 * of clicks restores the sequence exactly. With Event off the knob is stock.
 *
 * One step = the sequence's Step Len; the loop = Step Count steps. In Step Mode the app keeps note times at 960
 * per step whatever Step Len says (the player scales them), so there the unit is 960.
 * A note that starts in the last steps keeps its length and rings past the loop end: the player schedules each
 * note-off as an absolute time when the note starts (0x0805d3d2 onward), it does not need the note to fit.
 * Notes that start at or after the loop end (left over from a longer Step Count) are not touched.
 *
 * How: the app keeps each layer's notes sorted by start (a handle array into a pool, see seqfix.c), and the engine
 * has its own copy, updated one note at a time by id. Rotating a sorted list by d moves the notes that wrap, in
 * order, to the front: the starts are rewritten in place and the handle array is turned by that many places, so no
 * note is ever removed or re-inserted on the app side. Each moved note is then sent to the engine the way the stock
 * edit handler (FUN_08098bc8) sends one, and the views get one refresh (message 0x66), which reloads the piano roll
 * and keeps the selected note selected.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

struct event {                   /* 0x18 bytes */
    uint8_t type, cond;
    uint16_t _r0;
    uint32_t start, length, id;
    uint16_t pitch, velocity;
    uint32_t _r1;
};

struct list {
    uint16_t *handles;           /* sorted by start; the low 14 bits index the pool */
    uint32_t count, index, _r;
    struct event **pool;
};

struct ref {
    uint32_t tag;
    uint16_t id, _r;
};

struct msg {
    uint16_t id, _r0;
    uint32_t tag;
    uint16_t seq, _r1;
    int32_t a, b, c;
};

typedef void (*roll_knob_fn)(uint8_t *roll, int counts);
typedef int (*param_get_fn)(uint8_t *app, const void *ref, unsigned param, uint32_t *out);
typedef uint8_t *(*cell_fn)(uint8_t *app, const void *ref, unsigned layer);
typedef uint32_t (*cell_param_fn)(uint8_t *cell, unsigned param);
typedef void (*engine_event_fn)(uint8_t *engine, uint32_t seq, const struct event *event, uint32_t zero,
                                unsigned layer);
typedef void (*app_post_fn)(uint8_t *queue, const struct msg *m);

#define fw_roll_length  ((roll_knob_fn)FN(0x080bacd8))       /* stock handler for encoder 2 */
#define fw_param_get    ((param_get_fn)FN(0x08099504))
#define fw_cell         ((cell_fn)FN(0x08097ce8))
#define fw_cell_param   ((cell_param_fn)FN(0x08093e9c))
#define fw_engine_event ((engine_event_fn)FN(0x0804c798))    /* add / update one note in the engine, by id */
#define fw_app_post     ((app_post_fn)FN(0x080b5758))        /* queue a message for the views */

#define APP    ((uint8_t *)0x24020088u)
#define ENGINE ((uint8_t *)0x2400a9c0u)
#define STEP_TICKS ((const float *)0x080eca6cu)              /* Step Len index -> quarter notes; 960 ticks each */
#define STEP_LENS  15

#define VIEW_ROLL        0x38        /* the piano roll widget: what the knob handlers are given */
#define VIEW_SEQ         0xb490      /* the shown sequence: struct ref */
#define VIEW_EVENT_MODE  0xb8b2      /* Event is on */
#define APP_QUEUE        0x30
#define APP_DIRTY        0x8cc4
#define CELL_LIST        0x18

#define PARAM_STEP_LEN   0x85
#define PARAM_STEP_COUNT 0x86
#define PARAM_STEP_MODE  0x88
#define PARAM_LAYER      0xc0
#define MSG_REFRESH      0x66
#define MSG_TAG          0x080cfba4u
#define TICKS            960
#define COUNTS_PER_STEP  400         /* encoder counts per detent step, as the stock integer knobs use */

void bkp_enable(void);
#define ACC (*(volatile int16_t *)0x388006f0u)               /* backup SRAM: counts not yet turned into a step */

static void reverse(uint16_t *h, unsigned from, unsigned to)
{
    while (from + 1 < to) {
        uint16_t t = h[from];
        h[from++] = h[--to];
        h[to] = t;
    }
}

void rotate_apply(uint8_t *view, int steps)
{
    const struct ref *shown = (const struct ref *)(view + VIEW_SEQ);
    unsigned id = shown->id;
    if ((id & 0xff) >> 4 > 3 || (id & 0xf) > 4)
        return;                                              /* not a sequence cell: the stock handler's own test */

    uint32_t count = 0, len = 0, mode = 0;
    fw_param_get(APP, shown, PARAM_STEP_COUNT, &count);
    fw_param_get(APP, shown, PARAM_STEP_LEN, &len);
    fw_param_get(APP, shown, PARAM_STEP_MODE, &mode);
    if (count < 1 || count > 0x100 || len >= STEP_LENS)
        return;
    uint32_t unit = mode ? TICKS : (uint32_t)(STEP_TICKS[len] * (float)TICKS + 0.5f);
    if (unit < 1)
        return;
    uint32_t loop = count * unit;
    int turn = steps % (int)count;
    if (turn < 0)
        turn += (int)count;
    uint32_t d = (uint32_t)turn * unit;
    if (!d)
        return;

    struct ref ref = {0, (uint16_t)id, 0};
    unsigned layer = fw_cell_param(fw_cell(APP, &ref, 0), PARAM_LAYER) & 0xff;
    struct list *l = (struct list *)(fw_cell(APP, &ref, layer) + CELL_LIST);
    struct event *pool = *l->pool;
    uint16_t *h = l->handles;

    unsigned inside = 0, wrap = 0;                           /* notes inside the loop; of those, the ones that wrap */
    while (inside < l->count && pool[h[inside] & 0x3fff].start < loop)
        inside++;
    if (!inside)
        return;
    for (unsigned i = 0; i < inside; i++) {
        struct event *e = &pool[h[i] & 0x3fff];
        uint32_t start = e->start + d;
        if (start >= loop) {
            start -= loop;
            wrap++;
        }
        e->start = start;
    }
    reverse(h, 0, inside);                                   /* turn the handles right by `wrap` places */
    reverse(h, 0, wrap);
    reverse(h, wrap, inside);

    uint32_t seq = (id & 0xf) | (id >> 8 & 0x1f) << 16 | (id >> 4 & 0xf) << 8;
    for (unsigned i = 0; i < inside; i++)
        fw_engine_event(ENGINE, seq, &pool[h[i] & 0x3fff], 0, layer);

    struct msg m = {MSG_REFRESH, 0, MSG_TAG, (uint16_t)id, 0, 0, 0, 0};
    fw_app_post(APP + APP_QUEUE, &m);
    APP[APP_DIRTY] = 1;
}

/* Replaces the piano roll's call to the note-length handler for encoder 2 (bl @0x080c179a). */
void rotate_knob(uint8_t *roll, int counts)
{
    uint8_t *view = roll - VIEW_ROLL;
    if (!view[VIEW_EVENT_MODE]) {
        fw_roll_length(roll, counts);
        return;
    }
    bkp_enable();
    int acc = ACC;
    if (acc <= -COUNTS_PER_STEP || acc >= COUNTS_PER_STEP)
        acc = 0;                                             /* never written yet */
    acc += counts;
    int steps = acc / COUNTS_PER_STEP;
    ACC = (int16_t)(acc - steps * COUNTS_PER_STEP);
    if (steps)
        rotate_apply(view, steps);
}
