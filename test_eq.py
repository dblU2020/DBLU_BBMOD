"""Per-pad EQ (src/eq.c, eq_dsp.c, and its parts in insert.c, master.c, lfo.c, patches/filter.py) under Unicorn.

Real firmware runs for: the settings lookup (FUN_08093e9c), the buffer accessors, stock's own Hz and Q curves
(FUN_08060640, FUN_080606c0, which the screen uses for these knobs), our thunks entered the way the patched pad
process enters them, and the EQ's filters from bank 2.
The filters: the firmware build of eq_dsp.c is run block by block against the host build of the same file
(host/render_eq.py), and its coefficients against the RBJ cookbook worked out in double precision.
Stubbed and recorded: registration, the store's add, set-screen, the list clear / add, the selected-row lookup.
NOT run: the pad process functions around the hooks (as for the insert, where the buffer and flag are is from the
disassembly), the screens themselves, the knob's step size on the real unit, CPU cycles on the real chip
(instructions are counted instead).
"""
import struct
import sys

import numpy as np
from scipy import signal
from unicorn.arm_const import (UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_R4, UC_ARM_REG_R12, UC_ARM_REG_S0, UC_ARM_REG_SP)

sys.path.insert(0, "host")
import render_eq as host
import render_insert as host_ins
from emu import RET, STACK, Emu

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
img = open(IMG, "rb").read()
BASE = 0x08040000
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0xC0000000, 0x90000)
BLOCK, BANK = 0xC0000000, 0xC0000000 + 0x56800 + 0xB000
EQB = BANK + 0x21100                              # eq.c's bank, in the last 0xf00 of insert.c's 0x22000
SET_AT, ST_AT, SET_SIZE, ST_SIZE = EQB + 72, EQB + 72 + 16 * 20, 20, host.STATE    # behind magic, now, rest[16]
PMEM, PCHECK, UI = 0x38800F70, 0x38800F74, 0x38800B1C
APP = 0x24020088
APP_PADS = APP + 0x1840
ARR, PAD, BUF, L, R = 0x24072000, 0x24068000, 0x24069000, 0x2406A000, 0x2406B000
N, FS = 128, 48000
P_EQ, P_EQ_POS = 0x1C8, 0x1F0
IDS = {"ins": 0x1B6, "ph": 0x1B7, "fl": 0x1B8, "rate": 0x1B9, "depth": 0x1BA, "manual": 0x1BB, "fb": 0x1BC,
       "spread": 0x1BD, "mix": 0x1BE, "live": 0x1C7, "pos": P_EQ_POS, **{k: P_EQ + i for i, k in enumerate(host.KNOBS)}}
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def memory(on=True):
    e.w32(PMEM, BLOCK if on else 0)
    e.w32(PCHECK, (BLOCK ^ 0x5052534D) if on else 0)
    e.uc.mem_write(BANK, bytes(0x22000))


def store(n, eq=True, **kw):
    """the app's settings store of pad n; with eq, the EQ's nine as eq_defaults leaves them, then kw on top"""
    vals = {0x4: 500, 0xDB: 0}
    if eq:
        vals.update({IDS[k]: v for k, v in host.DEFAULTS.items()})
        vals[P_EQ_POS] = 0
    vals.update({IDS[k]: v for k, v in kw.items()})
    rows = sorted(vals.items())
    at = ARR + n * 0x100
    e.uc.mem_write(at, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
    s = APP_PADS + (n // 4) * 0xF0 + (n % 4) * 0x30
    e.w32(s + 4, at)
    e.uc.mem_write(s + 10, struct.pack("<H", len(rows)))


def scan():
    for _ in range(16):
        e.call("insert_tick")


def fresh(pads=None):
    """memory, every pad flat, then pads = {q: settings}, read in"""
    memory()
    for q in range(16):
        store(q)
    for q, kw in (pads or {}).items():
        store(q, **kw)
    scan()


def pad(q):
    e.uc.mem_write(PAD, bytes(0xC00))
    e.w32(PAD + 0x18, (q % 4) | (q // 4) << 8)
    return PAD


def buffer(left, right=None):
    e.uc.mem_write(L, np.asarray(left, np.float32).tobytes())
    if right is not None:
        e.uc.mem_write(R, np.asarray(right, np.float32).tobytes())
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", len(left), len(left), L, R if right is not None else 0, 0,
                                    1 if right is not None else 0))


def audio(n=N):
    return (np.frombuffer(bytes(e.uc.mem_read(L, 4 * n)), np.float32).copy(),
            np.frombuffer(bytes(e.uc.mem_read(R, 4 * n)), np.float32).copy())


def enter(thunk, r4, sp_words=None, regs=None):
    """Run a thunk as the patched code does: bl from a site, r4 = the pad, the caller's frame on the stack."""
    sp = STACK - 0x100
    for off, v in (sp_words or {}).items():
        e.w32(sp + off, v)
    seed = {UC_ARM_REG_R0: 0x11110000, UC_ARM_REG_R1: 0x22220000, UC_ARM_REG_R2: 0x33330000, UC_ARM_REG_R3: 0x44440000,
            UC_ARM_REG_R12: 0x55550000, UC_ARM_REG_R4: r4}
    seed.update(regs or {})
    for reg, v in seed.items():
        e.uc.reg_write(reg, v)
    e.uc.reg_write(UC_ARM_REG_SP, sp)
    e.uc.reg_write(UC_ARM_REG_LR, RET | 1)
    e.uc.emu_start(e.sym[thunk] | 1, RET, count=20_000_000)
    assert e.uc.reg_read(UC_ARM_REG_PC) == RET
    kept = all(e.uc.reg_read(reg) == seed[reg] for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R12,
                                                           UC_ARM_REG_R4)) and e.uc.reg_read(UC_ARM_REG_SP) == sp
    return e.uc.reg_read(UC_ARM_REG_R3), kept


def render(q, x, mono=False, before_block=None):
    """x through pad q's mix, block by block, as the class A hook runs it on the pad's own buffer"""
    out_l, out_r, p = [], [], pad(q)
    for i, at in enumerate(range(0, len(x) - N + 1, N)):
        if before_block:
            before_block(i)
        buffer(x[at:at + N], None if mono else x[at:at + N])
        enter("insert_run_a", p, {0x18: BUF, 0x1C: 1})
        a, b = audio()
        out_l.append(a)
        out_r.append(b)
    return np.concatenate(out_l), np.concatenate(out_r)


def eq_set(q):
    k = struct.unpack("<8hB", e.uc.mem_read(SET_AT + q * SET_SIZE, 17))
    return dict(zip(host.KNOBS, k[:8]), pos=k[8])


def eq_state(q):
    raw = bytes(e.uc.mem_read(ST_AT + q * ST_SIZE, ST_SIZE))
    coefs = np.array(struct.unpack_from("<20f", raw, 32), np.float64).reshape(4, 5)
    on, primed, busy = raw[176], raw[177], raw[178]
    return coefs, on, primed, busy


def flt(x):
    return struct.unpack("<f", struct.pack("<I", x))[0]


def stock_curve(addr, v):
    """FUN_08060640 / FUN_080606c0 on knob value v, as the screen calls them: v * 0.001 in s0"""
    e.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", v * 0.001))[0])
    e.call(addr)
    return flt(e.uc.reg_read(UC_ARM_REG_S0))


def hz(v):
    return stock_curve(0x08060640, v)


def qv(v):
    return stock_curve(0x080606C0, v)


def level(y, f):
    """the amplitude of the f Hz sine in y (least squares: no whole number of periods needed)"""
    t = np.arange(len(y)) / FS
    m = np.stack([np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t)], 1)
    a, b = np.linalg.lstsq(m, y.astype(np.float64), rcond=None)[0]
    return np.hypot(a, b)


def cur(q):
    """the EQ's knobs where its glide has got to: gains in dB, the rest in knob units"""
    return struct.unpack("<8f", e.uc.mem_read(ST_AT + q * ST_SIZE, 32))


def sine(f, blocks, amp=0.25):
    t = np.arange(N * blocks)
    return (amp * np.sin(2 * np.pi * f * t / FS)).astype(np.float32)


# ---------------------------------------------------------------- the image
pages = {"Sample": 0x080EFD38, "Multisample": 0x080EFBD0, "Slicer": 0x080EF900, "Clip": 0x080EFA68,
         "Sample (0x4c)": 0x080EF4C8, "Slicer (0x4c)": 0x080EF1F8, "Clip (0x4c)": 0x080EF360}
rows = {k: struct.unpack_from("<6H", img, a - BASE) for k, a in pages.items()}
check("every pad type's Conf list reads Saturation, Fidelity, Filter Type, Insert, EQ, Input, and the lists still end in a 0",
      all(v[:6] == (0xDB, 0xF1, 0x19C, 0x1B6, P_EQ_POS, 0x1C7) for v in rows.values())
      and all(0 in struct.unpack_from("<36H", img, a - BASE) for a in pages.values()), rows)
check("eq_render is in flash bank 2, the glue in the cave",
      0x08100000 <= e.sym["eq_render"] < 0x081E0000
      and all(0x080F1E78 <= e.sym[f] < 0x08100000 for f in ("eq_register", "eq_defaults", "eq_tick", "eq_on", "eq_process")))
check(f"the image still fits the installer's limit ({len(img)} of 786432 bytes)", len(img) <= 786432)

# ---------------------------------------------------------------- settings
lists, nums = [], []
SP = lambda k=0: e.r32(e.uc.reg_read(UC_ARM_REG_SP) + k)
e.stub(0x0808C0D8, lambda: lists.append((e.arg(1), e.cstr(e.arg(2)), [e.cstr(e.r32(e.arg(3) + 4 * i)) for i in range(SP())],
                                         e.cstr(SP(4)))))
e.stub(0x0808C12C, lambda: nums.append((e.arg(1), e.arg(2), e.cstr(e.arg(3)), SP(), SP(4), e.cstr(SP(8)))))
e.call("eq_register", 0x24001000)
cuts = ["Off", "20Hz", "25Hz", "31Hz", "40Hz", "50Hz", "63Hz", "80Hz", "100Hz", "125Hz", "160Hz", "200Hz", "250Hz",
        "315Hz", "400Hz", "500Hz", "630Hz", "800Hz", "1.0kHz"]
# DBLU04: the frequencies and Mid Q are lists. As the master EQ's Freq / Q knob types (0xa / 0xb) they showed nothing
# on the unit's pad knob page, and turning them changed nothing (2026-10-31); a list shows its own names, as Low Cut.
lo_fs = ["30Hz", "40Hz", "50Hz", "63Hz", "80Hz", "100Hz", "125Hz", "160Hz", "200Hz", "250Hz", "315Hz", "400Hz", "500Hz",
         "600Hz"]
mid_fs = ["100Hz", "125Hz", "160Hz", "200Hz", "250Hz", "315Hz", "400Hz", "500Hz", "630Hz", "800Hz", "1.0kHz", "1.25kHz",
          "1.6kHz", "2.0kHz", "2.5kHz", "3.15kHz", "4.0kHz", "5.0kHz", "6.3kHz", "8.0kHz"]
hi_fs = ["1.6kHz", "2.0kHz", "2.5kHz", "3.15kHz", "4.0kHz", "5.0kHz", "6.3kHz", "8.0kHz", "10kHz", "12.5kHz", "16kHz"]
qs = ["0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "1.0", "1.2", "1.5", "2.0", "2.5", "3.0", "4.0", "5.6", "8.0"]
check("registered: EQ (Post, Pre); Low Frq, Mid Frq, High Frq, Low Cut and Mid Q as lists in third octaves",
      lists == [(P_EQ_POS, "EQ:", ["Post", "Pre"], "eqpos"), (0x1C9, "Low Frq:", lo_fs, "eqlofreq"),
                (0x1CB, "Mid Frq:", mid_fs, "eqmidfreq"), (0x1CD, "High Frq:", hi_fs, "eqhifreq"),
                (0x1CE, "Low Cut:", cuts, "eqcut"), (0x1CF, "Mid Q:", qs, "eqmidq")], lists)
check("...the gains in stock's dB type (7), +-18 dB, and nothing in the master EQ's types any more",
      nums == [(0x1C8, 7, "Low:", -18000, 18000, "eqlog"), (0x1CA, 7, "Mid:", -18000, 18000, "eqmidg"),
               (0x1CC, 7, "High:", -18000, 18000, "eqhig")], nums)
names = {l[3] for l in lists} | {n[5] for n in nums}
check("nine xml names (the four lists renamed, so no older build's knob units land in a list), labels short enough",
      names == {"eqlog", "eqmidg", "eqhig", "eqcut", "eqlofreq", "eqmidfreq", "eqhifreq", "eqmidq", "eqpos"}
      and all(len(x[1]) <= 9 for x in lists) and all(len(x[2]) <= 9 for x in nums), sorted(names))
added = []
e.stub(0x08093EF6, lambda: added.append((e.arg(1), e.arg(2))))
e.call("eq_defaults", 0x24073000)
check("a new pad: flat, 100 Hz / 1.0 kHz / 5.0 kHz, Low Cut Off, Q 0.7, Post (list positions)",
      added == [(0x1C8, 0), (0x1C9, lo_fs.index("100Hz")), (0x1CA, 0), (0x1CB, mid_fs.index("1.0kHz")), (0x1CC, 0),
                (0x1CD, hi_fs.index("5.0kHz")), (0x1CE, 0), (0x1CF, qs.index("0.7")), (P_EQ_POS, 0)], added)
added.clear()
e.call("lfo_defaults", 0x24073000, 0xDC, 0)
check(f"the pad store still has room: stock's 58 + the hooked add + ours = {58 + len(added)} of 96, the EQ's nine "
      "next to last (the Filter Type, test_ladder.py, after them)",
      58 + len(added) <= 96 and [a[0] for a in added[-10:-1]] == list(range(0x1C8, 0x1D0)) + [P_EQ_POS]
      and added[-1] == (0x19C, 0), len(added))
del e.stubs[0x08093EF6]

# ---------------------------------------------------------------- the engine's copy of the settings
fresh({5: dict(lo_g=6000, lo_f=300, mid_g=-12500, mid_f=700, hi_g=3000, hi_f=900, cut=7, q=500, pos=1)})
check("sixteen blocks read all sixteen pads: pad 6's nine as the store has them",
      eq_set(5) == dict(lo_g=6000, lo_f=300, mid_g=-12500, mid_f=700, hi_g=3000, hi_f=900, cut=7, q=500, pos=1), eq_set(5))
check("...the others as eq_defaults leaves them, Post", all(eq_set(q) == dict(host.DEFAULTS, pos=0) for q in range(16) if q != 5))
store(5, pos=9)
store(6, eq=False)                                            # a preset from before the EQ: none of the nine
scan()
check("a position past the list reads as Post; a pad with no EQ settings at all reads as flat (the lists at their first)",
      eq_set(5)["pos"] == 0 and eq_set(6) == dict(lo_g=0, lo_f=59, mid_g=0, mid_f=233, hi_g=0, hi_f=632, cut=0, q=212, pos=0),
      eq_set(6))
store(5, lo_g=6000, lo_f=lo_fs.index("100Hz"), mid_f=len(mid_fs) - 1, hi_f=hi_fs.index("10kHz"), q=0)
store(7, lo_f=25, mid_f=-3)                                   # past the end of the list / below it (still a position)
scan()
k5, k7 = eq_set(5), eq_set(7)
check(f"list positions reach the EQ as knob units: 100 Hz -> {hz(k5['lo_f']):.0f} Hz, the last Mid -> "
      f"{hz(k5['mid_f']):.0f} Hz, 10 kHz -> {hz(k5['hi_f']):.0f} Hz, Q 0.3 -> {qv(k5['q']):.2f}",
      (k5["lo_f"], k5["mid_f"], k5["hi_f"], k5["q"]) == (233, 864, 897, 212)
      and 99 < hz(k5["lo_f"]) < 102 and 7900 < hz(k5["mid_f"]) < 8100 and 9900 < hz(k5["hi_f"]) < 10100, k5)
check("a position past a list's end is its last entry, one below 0 its first", k7["lo_f"] == 491 and k7["mid_f"] == 233, k7)

# ---------------------------------------------------------------- "take a separate mix buffer?" and the flat bypass
for what, kw, want in (("flat (the defaults)", {}, 0), ("a pad from before the EQ", None, 0), ("Low +6 dB", dict(lo_g=6000), 1),
                       ("Mid -0.5 dB", dict(mid_g=-500), 1), ("High +18 dB", dict(hi_g=18000), 1), ("Low Cut 80 Hz", dict(cut=7), 1),
                       ("frequencies and Q moved, gains at 0", dict(lo_f=400, mid_f=300, hi_f=700, q=800), 0)):
    memory()
    for q in range(16):
        store(q)
    if kw is None:
        store(2, eq=False)
    else:
        store(2, **kw)
    scan()
    got = [enter(t, pad(2))[0] for t in ("insert_buf_a", "insert_buf_b")]
    check(f"EQ {what}: both pad classes {'take' if want else 'do not take'} a buffer of their own for it", got == [want, want], got)
rng = np.random.default_rng(7)
noise = (0.5 * rng.uniform(-1, 1, N * 4)).astype(np.float32)
fresh({2: dict(lo_f=400, mid_f=300, q=800, pos=1)})
count = {"n": 0}
hook = e.uc.hook_add(0x4, lambda uc, a, s, u: count.__setitem__("n", count["n"] + 1))     # UC_HOOK_CODE
gl, gr = render(2, noise[:N])
flat_cost = count["n"]
e.uc.hook_del(hook)
check(f"a flat EQ (frequencies and Q moved, gains at 0): not one sample changed, {flat_cost} instructions for the block",
      np.array_equal(gl, noise[:N]) and np.array_equal(gr, noise[:N]) and flat_cost < 400, flat_cost)
check("...and its state was never touched (nothing primed)", eq_state(2)[2] == 0)

# ---------------------------------------------------------------- the firmware's filters = the host build's
dll = host.lib()
t = np.arange(N * 40)
src = (0.3 * np.sin(2 * np.pi * 70 * t / FS) + 0.2 * np.sin(2 * np.pi * 1300 * t / FS)
       + 0.15 * rng.uniform(-1, 1, len(t))).astype(np.float32)
cases = {
    "Low +12 dB at 100 Hz": dict(lo_g=12000, lo_f=233),
    "Low -18 dB at 30 Hz": dict(lo_g=-18000, lo_f=59),
    "Mid +18 dB, Q 8, 8 kHz": dict(mid_g=18000, mid_f=865, q=843),
    "Mid -18 dB, Q 0.3, 100 Hz": dict(mid_g=-18000, mid_f=233, q=212),
    "High +9 dB at 16 kHz": dict(hi_g=9000, hi_f=965),
    "High -12 dB at 1.5 kHz": dict(hi_g=-12000, hi_f=623),
    "Low Cut 20 Hz": dict(cut=1),
    "Low Cut 1 kHz": dict(cut=18),
    "all four": dict(lo_g=5000, lo_f=300, mid_g=-7000, mid_f=600, q=500, hi_g=4000, hi_f=800, cut=9),
}
worst = 0.0
for name, kw in cases.items():
    fresh({3: kw})
    got_l, got_r = render(3, src)
    want_l, want_r = host.run(dll, src, host.settings(**kw))
    err = max(np.abs(got_l - want_l).max(), np.abs(got_r - want_r).max()) / np.abs(want_l).max()
    worst = max(worst, err)
    check(f"{name}: 40 blocks match the host build (worst {err:.1e} of full scale), both channels",
          err < 1e-4 and np.allclose(got_l, got_r, atol=1e-6), err)
fresh({3: cases["all four"]})
gl, _ = render(3, src[:N * 8], mono=True)
want, _ = host.run(dll, src[:N * 8], host.settings(**cases["all four"]), mono=True)
check("a mono mix buffer: left processed, no right channel read or written", np.abs(gl - want).max() < 1e-4 * np.abs(want).max())

# ---------------------------------------------------------------- what it does to sound
def rbj(kind, f, db=0.0, q=0.7071067811865476):
    """the RBJ cookbook in double precision, a0 divided out (shelves at slope 1)"""
    w = 2 * np.pi * f / FS
    s, c = np.sin(w), np.cos(w)
    a = 10 ** (db / 40)
    if kind == "hp":
        al = s / (2 * q)
        b, aa = [(1 + c) / 2, -(1 + c), (1 + c) / 2], [1 + al, -2 * c, 1 - al]
    elif kind == "peak":
        al = s / (2 * q)
        b, aa = [1 + al * a, -2 * c, 1 - al * a], [1 + al / a, -2 * c, 1 - al / a]
    else:
        k = 2 * np.sqrt(a) * s / np.sqrt(2)
        ap, am = a + 1, a - 1
        if kind == "low":
            b = [a * (ap - am * c + k), 2 * a * (am - ap * c), a * (ap - am * c - k)]
            aa = [ap + am * c + k, -2 * (am + ap * c), ap + am * c - k]
        else:
            b = [a * (ap + am * c + k), -2 * a * (am + ap * c), a * (ap + am * c - k)]
            aa = [ap - am * c + k, 2 * (am - ap * c), ap - am * c - k]
    return np.array(b + aa) / aa[0]


CUT_HZ = [0, 20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000]
grid = np.geomspace(20, 20000, 400)


def response(sos):
    return 20 * np.log10(np.abs(signal.sosfreqz(sos, worN=grid, fs=FS)[1]))


def reference(kw):
    """[(band, double-precision RBJ section)] for the bands these settings switch on, at the screen's frequencies"""
    k = dict(host.DEFAULTS, **kw)
    want = []
    if k["cut"]:
        want.append((0, rbj("hp", CUT_HZ[k["cut"]])))
    if k["lo_g"]:
        want.append((1, rbj("low", hz(k["lo_f"]), k["lo_g"] / 1000)))
    if k["mid_g"]:
        want.append((2, rbj("peak", hz(k["mid_f"]), k["mid_g"] / 1000, qv(k["q"]))))
    if k["hi_g"]:
        want.append((3, rbj("high", hz(k["hi_f"]), k["hi_g"] / 1000)))
    return want


def sos(sections):
    return np.array([[*c[:3], 1.0, *c[3:]] for c in sections])


for name, kw in cases.items():
    fresh({3: kw})
    render(3, src)                                                # 40 blocks: the glide in from flat is over
    coefs, on, _, _ = eq_state(3)
    want = reference(kw)
    diff = np.abs(response(sos([coefs[b] for b, _ in want])) - response(sos([c[[0, 1, 2, 4, 5]] for _, c in want]))).max()
    check(f"{name}: the bands that run are the ones set ({on:04b}), and the response is the cookbook's at the "
          f"frequency the screen shows, within {diff:.3f} dB from 20 Hz to 20 kHz",
          on == sum(1 << b for b, _ in want) and diff < 0.02, (on, diff))


# the filters' own rounding: single precision against the same coefficients in double (the host build is the
# firmware's to the bit, above, so this is the firmware's noise). Low, steep settings are where it is worst.
long = (0.3 * np.sin(2 * np.pi * 70 * np.arange(N * 400) / FS) + 0.15 * rng.uniform(-1, 1, N * 400)).astype(np.float32)
floor = {}
for name, kw in (("Low +18 dB at 30 Hz", dict(lo_g=18000, lo_f=59)), ("Low Cut 20 Hz", dict(cut=1)),
                 ("Mid +18 dB, Q 8, 100 Hz", dict(mid_g=18000, mid_f=233, q=843)), ("all four", cases["all four"])):
    st = host.new_state()
    y, _ = host.run(dll, long, lambda i: host.settings(snap=int(i == 0), **kw), state=st)
    c = np.array(struct.unpack_from("<20f", st.raw, 32), np.float64).reshape(4, 5)
    ref = signal.sosfilt(sos([c[b] for b in range(4) if st.raw[176] >> b & 1]), long.astype(np.float64))
    floor[name] = 20 * np.log10(np.sqrt(np.mean((y - ref) ** 2)))
check("rounding noise of the single-precision filters, worst case: " + ", ".join(f"{k} {v:.0f}" for k, v in floor.items())
      + " dBFS RMS", max(floor.values()) < -75, floor)


def through(kw, f, blocks=48):
    """a steady f Hz tone through pad 4: the measured gain, and the cookbook's at f"""
    fresh({4: kw})
    x = sine(f, blocks)
    y, _ = render(4, x)
    got = 20 * np.log10(level(y[N * 24:], f) / level(x[N * 24:], f))      # once the glide in is over
    h = signal.sosfreqz(sos([c[[0, 1, 2, 4, 5]] for _, c in reference(kw)]), worN=[f], fs=FS)[1][0]
    return got, 20 * np.log10(abs(h))


heard = {"Low +12 dB at 100 Hz, a 30 Hz tone": (dict(lo_g=12000, lo_f=233), 30, 9, 12),
         "...a 5 kHz tone": (dict(lo_g=12000, lo_f=233), 5000, -0.1, 0.1),
         "Mid -18 dB at 1 kHz, Q 8, a tone right on it": (dict(mid_g=-18000, mid_f=565, q=843), hz(565), -18.05, -17.95),
         "...a tone an octave up": (dict(mid_g=-18000, mid_f=565, q=843), 2 * hz(565), -1.5, 0.0),
         "Low Cut 100 Hz, a 100 Hz tone": (dict(cut=8), 100, -3.1, -2.9),
         "...a 25 Hz tone, two octaves down (12 dB per octave)": (dict(cut=8), 25, -24.5, -23.5),
         "...a 1 kHz tone": (dict(cut=8), 1000, -0.1, 0.1)}
for name, (kw, f, lo, hi) in heard.items():
    got, want = through(kw, f)
    check(f"{name}: {got:+.2f} dB (the cookbook: {want:+.2f})", lo <= got <= hi and abs(got - want) < 0.05, (got, want))

# ---------------------------------------------------------------- knobs that move
fresh({4: dict(lo_f=233)})
x = sine(60, 60)
change_at, path = 10, []


def turn_up(i):
    if i == change_at:
        store(4, lo_f=233, lo_g=18000)
        scan()
    if i:
        path.append(cur(4)[0])


y, _ = render(4, x, before_block=turn_up)
after = path[change_at:]                           # where the gain had got to after each block from the change on
check(f"Low 0 -> +18 dB mid-note: the gain glides up ({after[0]:+.1f}, {after[1]:+.1f}, {after[3]:+.1f} dB ...) "
      f"instead of jumping, and is there within 25 blocks ({after[24]:+.3f} dB)",
      after[0] < 9 and all(b >= a for a, b in zip(after, after[1:])) and after[24] == 18.0
      and all(g == 0 for g in path[:change_at]), [round(g, 2) for g in path])
steps = np.abs(np.diff(y.astype(np.float64)))
check("...no click: no sample-to-sample step bigger than the loud tone's own",
      steps[change_at * N - 4:].max() <= steps[-N * 10:].max() * 1.02, (steps[change_at * N - 4:].max(), steps[-N * 10:].max()))
check(f"...and the gain is really there: {20 * np.log10(level(y[-N * 16:], 60) / level(x[-N * 16:], 60)):+.2f} dB at 60 Hz",
      abs(20 * np.log10(level(y[-N * 16:], 60) / level(x[-N * 16:], 60)) - through(dict(lo_g=18000, lo_f=233), 60)[1]) < 0.05)
want_l, _ = host.run(dll, x, lambda i: host.settings(lo_f=233, lo_g=18000 if i >= change_at else 0))
check("...and the glide is the host build's, block for block", np.abs(y - want_l).max() < 1e-4 * np.abs(want_l).max())

fresh({4: dict(lo_g=18000, cut=12)})
for _ in range(3):                                                # the pad silent for a few blocks
    enter("insert_live_a", pad(4))
    e.call("insert_tick")
render(4, sine(60, 1))
check("a new note on a pad whose EQ is set (silent the block before): it starts right at the settings, no glide in",
      cur(4)[0] == 18.0 and abs(cur(4)[6] - 364.3856) < 1e-3, cur(4))
for _ in range(3):
    e.call("insert_tick")
store(4, lo_g=0, cut=12)
scan()
render(4, sine(60, 1))
check("...while a change on a pad that keeps sounding still glides", 0 < cur(4)[0] < 18.0, cur(4)[0])
for live in (0, 3):
    fresh({4: dict(lo_g=18000, live=live)})
    render(4, sine(60, 1))                                        # sounding, gliding in from flat
    enter("insert_live_a", pad(4))
    check(f"Input {'On' if live else 'Off'}: insert_live {'leaves the pad sounding, so the EQ is not reset' if live else 'marks the pad silent'}",
          (e.r32(EQB + 8 + 4 * 4) == e.r32(EQB + 4)) != bool(live), (e.r32(EQB + 8 + 16), e.r32(EQB + 4)))

fresh({4: dict(lo_g=18000)})
blocks_to_quiet, p4 = None, pad(4)
x = sine(60, 1)
for i in range(120):
    if i == 2:
        store(4, lo_g=0)
        scan()
    buffer(x, x)
    enter("insert_run_a", p4, {0x18: BUF, 0x1C: 1})
    if i > 2 and blocks_to_quiet is None and enter("insert_buf_a", pad(4))[0] == 0:
        blocks_to_quiet = i - 2
    p4 = pad(4)
check(f"Low back to 0 dB: the EQ glides down, lets its last output die away, and the pad gives up its buffer after "
      f"{blocks_to_quiet} blocks ({blocks_to_quiet and blocks_to_quiet * 2.67:.0f} ms)",
      blocks_to_quiet is not None and 30 <= blocks_to_quiet <= 70 and eq_state(4)[1] == 0, blocks_to_quiet)
buffer(noise[:N], noise[:N])
enter("insert_run_a", pad(4), {0x18: BUF, 0x1C: 1})
check("...after which the pad is untouched again", np.array_equal(audio()[0], noise[:N]))

fresh({4: dict(cut=0)})
x = sine(30, 40)
path = []


def cut_on(i):
    if i == 4:
        store(4, cut=18)
        scan()
    path.append(cur(4)[6])


y, _ = render(4, x, before_block=cut_on)
path = path[1:] + [cur(4)[6]]                      # each block's value once it has run
# DBLU06: the Low Cut fades in and out against the dry signal (8 blocks) instead of gliding up from a 2.5 Hz park and
# being dropped there, which clicked on the unit (2026-11-01)
fade = e.r8(ST_AT + 4 * ST_SIZE + 180)                         # eq_state.linger[BAND_CUT]: how far the fade is in
step, own = float(np.max(np.abs(np.diff(y[N * 3:])))), float(np.max(np.abs(np.diff(x))))
check(f"Low Cut Off -> 1 kHz on a sounding pad: it comes in right at 1 kHz and fades in (fade {fade} of 8), "
      f"no jump (largest step {step:.4f}, the signal's own {own:.4f})",
      eq_state(4)[2] and all(v == 0 for v in path[:4]) and all(abs(v - 564.3856) < 1e-3 for v in path[4:])
      and fade == 8 and step <= 2 * own, [round(v, 1) for v in path])

g = 20 * np.log10(level(y[-N * 16:], 30) / level(x[-N * 16:], 30))
check(f"...where a 30 Hz tone ends up {g:+.1f} dB down", g < -55, g)


def cut_off(i):
    if i == 10:
        store(4, cut=0)
        scan()


fresh({4: dict(cut=18)})
x = (0.3 * np.sin(2 * np.pi * 40 * np.arange(N * 60) / FS)).astype(np.float32)
y, _ = render(4, x, before_block=cut_off)
step, own = float(np.max(np.abs(np.diff(y[N * 3:])))), float(np.max(np.abs(np.diff(x))))
check(f"Low Cut 1 kHz -> Off on a 40 Hz bass: fades out without a jump (largest step {step:.4f}, the signal's own "
      f"{own:.4f}); then the band stops and the pad is the dry signal again",
      step <= 2 * own and eq_state(4)[1] == 0 and np.array_equal(y[-N:], x[-N:]), (step, own, eq_state(4)[1]))

# ---------------------------------------------------------------- another bank's pad at the same place
# Every bank's pad at a place runs through the engine, and the EQ's 16 slots go by row and col only. On the first unit
# (DBLUEQ1, 2026-10-31) the silent pad of another bank marked the sounding one "new note" every block, so its EQ
# started over 375 times a second: heavy distortion as soon as any knob was off flat. Here a bank 1 pad at pad 5's
# place is silent in every block while pad 5 plays.
SIB = PAD + 0x0C00


def sibling(q, bank=1):
    e.uc.mem_write(SIB, bytes(0xC00))
    e.w32(SIB + 0x18, (bank << 16) | (q // 4) << 8 | (q % 4))
    return SIB


def play_with(silent_sibling, bank=1):
    fresh({5: dict(lo_g=6000)})
    x = sine(220, 40)
    out = []
    for at in range(0, len(x) - N + 1, N):
        e.call("insert_tick")
        if silent_sibling:
            enter("insert_live_a", sibling(5, bank))
        buffer(x[at:at + N], x[at:at + N])
        enter("insert_run_a", pad(5), {0x18: BUF, 0x1C: 1})
        out.append(audio()[0])
    return np.concatenate(out)[N * 20:]


alone, beside = play_with(False), play_with(True)
check(f"a silent pad of another bank at the same place leaves the sounding pad's EQ alone "
      f"(max difference {np.max(np.abs(alone - beside)):.1e}, largest step {np.max(np.abs(np.diff(beside))):.4f})",
      np.array_equal(alone, beside))
# DBLU04 on the unit (2026-10-31): the resampled loop still jumped at every block boundary. Stock runs a pad's process
# and then the object linked at pad + 8, so a silent object can carry the SAME id as the sounding pad: the silence
# has to be told apart by the object, not by its id.
same = play_with(True, bank=0)
check(f"a silent object with the same id (another object, same bank, row and col) leaves it alone too "
      f"(max difference {np.max(np.abs(alone - same)):.1e}, largest step {np.max(np.abs(np.diff(same))):.4f})",
      np.array_equal(alone, same))

# ---------------------------------------------------------------- Pre / Post around the insert
ins_dll = host_ins.lib()
PH = dict(ins=1, ph=0, rate=600, depth=900, manual=400, fb=700, spread=300, mix=500)
EQK = dict(cut=11, hi_g=-12000, hi_f=700)
ins_set = struct.pack("<BBBB6f5f", 1, 0, 0, 0, *(PH[k] / 1000 for k in ("rate", "depth", "manual", "fb", "spread", "mix")),
                      0, 0, 0, 0, 0)
import ctypes

for pos, name in ((0, "Post"), (1, "Pre")):
    fresh({6: dict(**PH, **EQK, pos=pos)})
    got, _ = render(6, src[:N * 30])
    l, r = src[:N * 30].copy(), src[:N * 30].copy()
    st_i, st_e, s = ctypes.create_string_buffer(16384), host.new_state(), host.settings(pos=pos, **EQK)
    for at in range(0, len(l), N):
        bl, br = l[at:at + N], r[at:at + N]
        if pos == 1:
            host.block(dll, st_e, s, bl, br)
        ins_dll.ins_render(st_i, ins_set, bl.ctypes.data_as(host_ins.F), br.ctypes.data_as(host_ins.F), N)
        if pos == 0:
            host.block(dll, st_e, s, bl, br)
    err = np.abs(got - l).max()
    check(f"EQ {name} with a Phaser on the pad: {'phaser, then EQ' if pos == 0 else 'EQ, then phaser'} "
          f"(the host builds in that order; worst {err:.1e})", err < 3e-3, err)
    if pos == 0:
        post = got
check("...and Pre really is a different sound from Post", np.abs(got - post).max() > 0.01)

# ---------------------------------------------------------------- cost
fresh({2: dict(lo_g=5000, mid_g=-4000, hi_g=3000, cut=5)})
for _ in range(10):
    render(2, src[:N])                                            # the first block designs every band; the Low Cut
                                                                  # takes 8 to fade in
count["n"] = 0
hook = e.uc.hook_add(0x4, lambda uc, a, s, u: count.__setitem__("n", count["n"] + 1))
render(2, src[N:2 * N])
steady = count["n"]
store(2, lo_g=-5000, mid_g=4000, hi_g=-3000, cut=12, lo_f=400, mid_f=300, hi_f=900, q=700)
scan()
count["n"] = 0
render(2, src[2 * N:3 * N])
moving = count["n"]
e.uc.hook_del(hook)
check(f"all four bands, stereo: {steady / N:.0f} instructions per frame ({steady} a block, ~{steady / 1.28e4:.1f} % of a "
      f"2.67 ms block at 480 MHz if one a cycle); a block with every knob moving: {moving}",
      steady / N < 110 and moving < steady + 3000, (steady, moving))

# ---------------------------------------------------------------- no memory, no bank 2
memory(False)
for q in range(16):
    store(q, lo_g=6000)
check("no memory block: no buffer is asked for, nothing runs, nothing faults",
      enter("insert_buf_a", pad(2))[0] == 0 and np.array_equal(render(2, noise[:N])[0], noise[:N]))
fresh({2: dict(lo_g=6000, cut=4)})
saved = bytes(e.uc.mem_read(0x08100000, 0x8000))
e.uc.mem_write(0x08100000, b"\xff" * 0x8000)                      # bank 2 as an erase leaves it
e.uc.mem_write(0x2405FFD0 + 35, b"\x00")                          # not yet checked, as at a fresh boot
ok = True
try:
    gl, _ = render(2, noise[:N])
except Exception as exc:
    ok = False
    print(f"     FAULTED: {type(exc).__name__} {exc}")
check("bank 2 erased: the EQ bypasses itself instead of calling into 0xff", ok and np.array_equal(gl, noise[:N]))
e.uc.mem_write(0x08100000, saved)
e.uc.mem_write(0x2405FFD0 + 35, b"\x00")

# ---------------------------------------------------------------- the knob page
calls = []
e.stub(0x0809EAEC, lambda: calls.append(("screen", e.arg(1), e.r16(APP + 0x28))))
e.stub(0x080A4FC2, lambda: calls.append(("clear",)))
e.stub(0x080A5038, lambda: calls.append(("add", e.arg(1), e.arg(2))))
e.stub(0x08098D40, lambda: calls.append(("stock page",)), value=1)
selected = {"id": P_EQ_POS}
e.stubs[0x080B9D20] = lambda: e.ret(selected["id"])
e.uc.mem_map(0x24100000, 0x100000)
GUIOBJ = 0x24100000
e.w32(0x24002E6C, GUIOBJ)
VIEW = GUIOBJ + 0x732D8
e.uc.mem_write(APP + 0x14, struct.pack("<H", 0x0112))             # pad row 1, col 2 = pad 7
e.uc.mem_write(APP + 0x28, struct.pack("<H", 0x0034))             # the FX screen's own cell
e.uc.mem_write(APP + 0x8CC6, b"\x01")
e.uc.mem_write(UI, bytes(4))


def info():
    calls.clear()
    e.uc.reg_write(UC_ARM_REG_R0, APP)
    e.uc.reg_write(UC_ARM_REG_SP, STACK - 0x100)
    e.uc.reg_write(UC_ARM_REG_LR, RET | 1)
    e.uc.emu_start(e.sym["insert_info_thunk"] | 1, RET, count=1_000_000)
    return e.uc.reg_read(UC_ARM_REG_R3)


e.w32(VIEW + 0xF6CC, 4)
r3 = info()
check("INFO on the EQ row of the Conf list: the knob screen opens on that pad's cell, and stock is told 'nothing to do'",
      calls == [("screen", 0x23, 0x0112)] and r3 == 0 and e.r16(APP + 0x28) == 0x0034
      and bytes(e.uc.mem_read(UI, 4)) == bytes([4, 1, 0x12, 0x01]), (calls, r3, bytes(e.uc.mem_read(UI, 4)).hex()))
selected["id"] = 0x1B6
info()
check("...the Insert row still opens the insert's page", bytes(e.uc.mem_read(UI, 4))[:2] == bytes([3, 1]))
selected["id"] = 0xF1
e.uc.mem_write(UI, bytes(4))
r3 = info()
check("INFO on another row: stock's 'can be modulated' byte, nothing opened", r3 == 1 and not calls and e.r8(UI + 1) == 0)
selected["id"] = P_EQ_POS
info()
store(6, lo_g=-3500, lo_f=100, mid_g=7000, mid_f=400, hi_g=1500, hi_f=700, cut=6, q=600)
CELL = 0x24074000
e.uc.mem_write(CELL, struct.pack("<IH", 0, 0x0112))
calls.clear()
e.call("master_list", APP, CELL, 0x24075000, 0)
check("the EQ page: Low over Low Frq, Mid over Mid Frq, High over High Frq, Low Cut over Mid Q, with the pad's values",
      calls == [("clear",), ("add", 0x1C8, -3500 & 0xFFFFFFFF), ("add", 0x1C9, 100), ("add", 0x1CA, 7000),
                ("add", 0x1CB, 400), ("add", 0x1CC, 1500), ("add", 0x1CD, 700), ("add", 0x1CE, 6), ("add", 0x1CF, 600)],
      calls)
e.call("master_title")
check("the header is left to the pad's own name, as on the insert page", e.arg(0) == 0)
e.uc.mem_write(APP + 0x8CA4, bytes([0x23]))
calls.clear()
e.call("master_info_knob", APP)
check("INFO on the EQ page: back to the pad's Conf list", calls == [("screen", 0x1C, 0x0034)] and e.r8(UI + 1) == 0, calls)
info()
calls.clear()
e.call("master_back", APP, 0x30, 0, 0)
check("BACK on the EQ page: back to the pad's Conf list", calls == [("screen", 0x1C, 0x0034)] and e.r8(UI + 1) == 0, calls)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
