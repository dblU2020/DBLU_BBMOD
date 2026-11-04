/*
 * The pad's ADSR as a modulation source ("ENV" in the Source list). Original 1010music Blackbox, firmware 3.1.9.
 *
 * Stock per-voice sources are velocity (code 0xd), key (0xe) and the LFO (4): the pad keeps them in a list of up to 8
 * entries (pad +0x4ec: float amount, u16 target +4, u16 source +6, u8 slot +8; count +0x54c), and every voice attaches
 * them to its own copies of the parameters (FUN_0805623c: source -> voice +0x84 / +0x8c / +0x520). The preset format
 * already names codes 1..3 "env1".."env3", but the engine drops them.
 *
 * ENV = code 1 = the voice's amp envelope: object at voice +0x28, its level (0..1, written every block by
 * FUN_0806a6c0) at +0x28 of that. A source is read at pointer +4, so the source pointer is voice +0x4c.
 *   env_mod_setup  wraps the pad's slot setup (FUN_08056810, one call @0x0805a138): stock only lists codes 4, 0xd,
 *                  0xe, so ENV goes in as velocity and the entry's source is put back to 1.
 *   env_mod_attach wraps FUN_0805623c (calls @0x08058c34, 0x0805a8da): after stock copied the parameters and attached
 *                  its own sources, attach the ENV entries with the same target -> parameter map stock uses.
 *
 * Clip and Slicer pads (pad class B, 3.1.D) have no list: the pad object holds two playing layers (at pad +0x260 and
 * +0x670, 0x410 apart, the second for the overlap when a clip or slice hands over), each with its own copies of the
 * parameters, and FUN_08067018 attaches a slot's source to both straight away. It only knows velocity, key, the LFO
 * and the MIDI sources, so env_mod_setup_b (the one call @0x080685c4) does the same for ENV and LFO 2 / 3:
 *   ENV      each layer's own amp envelope: object at layer +0x258, so the source pointer is layer +0x27c
 *   LFO2/3   the pad's LFO in lfo.c
 * Targets and amounts as FUN_08067018 has them for the LFO (Pitch counts double there).
 *
 * ENV.V (DBLU06) = code 2 ("env2" in the preset format): the same envelope, its amount scaled by the note's velocity,
 * vel / 127. At the voice start (FUN_08058548) stock attaches the sources BEFORE it writes the velocity into the voice
 * (+0x88 = (vel - 100) / 100), so env_mod_attach takes it from the voice-start thunk instead (duck_thunk.S leaves the
 * fifth argument in the duck state). env_mod_resync (the re-attach of sounding voices when the pad's list changed,
 * @0x0805a8da) reads the voice's own +0x88. Clip / Slicer pads attach per pad, not per note: ENV.V is plain ENV there.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)
typedef void (*setup_fn)(uint8_t *pad, uint8_t *cmd);
typedef void (*sync_fn)(uint8_t *pad, uint8_t *voice);
typedef void (*attach_fn)(float amount, void *param, void *source, int slot);
#define fw_setup  ((setup_fn)FN(0x08056810))
#define fw_sync   ((sync_fn)FN(0x0805623c))
#define fw_attach ((attach_fn)FN(0x0806fcd4))

#define SRC_ENV      1
#define SRC_ENVV     2            /* ENV.V: the envelope x the note's velocity */
#define SRC_LFO2     5            /* lfo.c: LFO 2 and 3, one per pad; the preset format's "lfo2" / "lfo3" */
#define SRC_LFO3     6
void *lfo_source(const uint8_t *pad, int k);
#define SRC_VELOCITY 0xd
#define PAD_LIST     0x4ec
#define PAD_COUNT    0x54c
#define VOICE_ENV_SOURCE 0x4c            /* envelope object voice +0x28, level at its +0x28, read at source +4 */
#define VOICE_VEL        0x88            /* stock's velocity value, (vel - 100) / 100, written after the attach */
#define START_VEL (*(const volatile uint8_t *)(0x2405ff70u + 13))   /* duck_thunk.S: the voice being started */

struct entry {
    float amount;
    uint16_t target, source;
    uint8_t slot, pad[3];
};

/* target code -> the voice's parameter object, as FUN_0805623c maps them */
static const struct {
    uint16_t target, param;
} targets[] = {
    {2, 0x150}, {4, 0x150}, {9, 0x47c}, {10, 0x4b0}, {11, 0x448}, {0x11, 0x334}, {0x3c, 0x388}, {0x3e, 0x3bc},
    {0x40, 0x3f0}, {0x5c, 0x288}, {0x5d, 0x2bc}, {0x62, 0x184}, {0x8f, 0x1b8}, {0x90, 0x1ec}, {0x91, 0x220},
    {0x92, 0x254}, {200, 0x2f8},
};

void env_mod_setup(uint8_t *pad, uint8_t *cmd)
{
    uint16_t *source = (uint16_t *)(cmd + 0x14), ours = *source;
    if (ours != SRC_ENV && ours != SRC_ENVV && ours != SRC_LFO2 && ours != SRC_LFO3) {
        fw_setup(pad, cmd);
        return;
    }
    *source = SRC_VELOCITY;
    fw_setup(pad, cmd);
    *source = ours;
    uint16_t target = (uint16_t)*(uint32_t *)(cmd + 0xc);
    uint8_t slot = (uint8_t)*(uint32_t *)(cmd + 0x10);
    struct entry *e = (struct entry *)(pad + PAD_LIST);
    uint32_t n = *(uint32_t *)(pad + PAD_COUNT);
    for (uint32_t i = 0; i < n && i < 8; i++)
        if (e[i].target == target && e[i].slot == slot && e[i].source == SRC_VELOCITY)
            e[i].source = ours;
}

/* velocity 1..128 -> ENV.V's share of the amount */
static float vel_scale(int vel)
{
    return vel <= 0 ? 0.0f : vel >= 127 ? 1.0f : (float)vel * (1.0f / 127.0f);
}

static void attach_ours(uint8_t *pad, uint8_t *voice, float vel)
{
    fw_sync(pad, voice);
    const struct entry *e = (const struct entry *)(pad + PAD_LIST);
    uint32_t n = *(uint32_t *)(pad + PAD_COUNT);
    for (uint32_t i = 0; i < n && i < 8; i++) {
        void *from;
        float scale = 1.0f;
        if (e[i].source == SRC_ENV)
            from = voice + VOICE_ENV_SOURCE;
        else if (e[i].source == SRC_ENVV) {
            from = voice + VOICE_ENV_SOURCE;
            scale = vel;
        }
        else if (e[i].source == SRC_LFO2 || e[i].source == SRC_LFO3)
            from = lfo_source(pad, e[i].source - SRC_LFO2);
        else
            continue;
        if (!from)
            continue;
        for (unsigned k = 0; k < sizeof targets / sizeof *targets; k++)
            if (targets[k].target == e[i].target) {
                float amount = e[i].amount * scale;
                fw_attach(e[i].target == 10 ? amount * 14.0f : amount, voice + targets[k].param, from, e[i].slot);
                break;
            }
    }
}

/* Replaces the attach at the voice start (@0x08058c34): the velocity is the one the voice-start thunk left. */
void env_mod_attach(uint8_t *pad, uint8_t *voice)
{
    attach_ours(pad, voice, vel_scale(START_VEL));
}

/* Replaces the re-attach of sounding voices (@0x0805a8da): their velocity is in the voice by now. */
void env_mod_resync(uint8_t *pad, uint8_t *voice)
{
    float v = *(const float *)(voice + VOICE_VEL);
    attach_ours(pad, voice, vel_scale((int)(100.0f + 100.0f * v + 0.5f)));
}

/* ---- Clip and Slicer pads ---- */

#define fw_setup_b ((setup_fn)FN(0x08067018))
#define LAYER_STEP 0x410
#define LAYER_ENV_SOURCE (0x260 + 0x258 + 0x24)  /* first layer's envelope object, read at +4 = its level at +0x28 */
#define PAD_B_NOTHING 0xb70                      /* the source stock attaches for "none" */

static const struct {
    uint16_t target, param;                      /* the first layer's parameter object */
} targets_b[] = {
    {2, 0x2b8}, {4, 0x2b8}, {0x11, 0x484}, {0x3c, 0x514}, {0x3e, 0x548}, {0x40, 0x57c}, {0x5c, 0x2f4}, {0x62, 0x26c},
    {200, 0x448},
};

void env_mod_setup_b(uint8_t *pad, uint8_t *cmd)
{
    uint16_t source = *(uint16_t *)(cmd + 0x14), target = (uint16_t)*(uint32_t *)(cmd + 0xc);
    if (source == SRC_ENVV)
        source = SRC_ENV;                        /* per pad, not per note, here: plain ENV */
    if (source != SRC_ENV && source != SRC_LFO2 && source != SRC_LFO3) {
        fw_setup_b(pad, cmd);
        return;
    }
    int slot = (int)(*(uint32_t *)(cmd + 0x10) & 0xffff);
    float amount = (float)*(int16_t *)(cmd + 0x16) * 0.001f;
    for (unsigned k = 0; k < sizeof targets_b / sizeof *targets_b; k++) {
        if (targets_b[k].target != target)
            continue;
        if (target == 0x62)
            amount += amount;
        for (unsigned layer = 0; layer < 2; layer++) {
            uint8_t *from = source == SRC_ENV ? pad + LAYER_ENV_SOURCE + layer * LAYER_STEP
                                              : (uint8_t *)lfo_source(pad, source - SRC_LFO2);
            fw_attach(from ? amount : 0.0f, pad + targets_b[k].param + layer * LAYER_STEP, from ? from : pad + PAD_B_NOTHING, slot);
        }
        return;
    }
}
