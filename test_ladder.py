"""Filter Type: the classic ladder (src/ladder.c, bank 2) inside the pad filter (src/filter.c) under Unicorn.

Real firmware runs for: filter_process from the patched image with ladder_render in its bank 2, the stock cutoff
curve, the buffer accessors, the store lookup, the Filter Type registration and default, stock's cell defaults
(FUN_08093f20) for the pad store count.
Stubbed: the modulated-parameter read (test values), the list registrar (recorded), the allocator.
Reference: host/render_ladder.py, the same ladder.c compiled for the host and driven the way filter.c drives it.
NOT checked: how it sounds (the demo WAVs, and the unit), CPU load on hardware.
"""
import math
import struct
import sys

import numpy as np
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_S0, UC_ARM_REG_SP

from emu import Emu

sys.path.insert(0, "host")
import render_ladder as R  # noqa: E402

e = Emu("out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin", "out/cave.elf")
dll = R.lib()
e.uc.mem_map(0x38800000, 0x1000)                         # backup SRAM and RCC: b2_live's pairing check (as test_eq)
e.uc.mem_map(0x58024000, 0x1000)

OBJ, PARAMS, PAD, BUF, LBUF, RBUF = 0x24060000, 0x24061000, 0x24062000, 0x24063000, 0x24064000, 0x24066000
APP_PADS, ARR = 0x24020088 + 0x1840, 0x24073000
PAD_ROW, PAD_COL = 1, 2
P_TYPE = 0x19C
N = 128
values = {}
f2i = lambda v: struct.unpack("<I", struct.pack("<f", v))[0]
i2f = lambda v: struct.unpack("<f", struct.pack("<I", v))[0]
e.stub(0x0806FB30, lambda: e.uc.reg_write(UC_ARM_REG_S0, f2i(values.get(e.arg(0), 0.0))))
e.w32(OBJ + 0x84, PARAMS)
e.w32(PAD + 0x18, PAD_ROW << 8 | PAD_COL)

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def set_type(t):
    """the app's record of the pad: Fidelity Normal, Saturation 0, Filter Type t"""
    store = APP_PADS + PAD_ROW * 0xF0 + PAD_COL * 0x30
    arr = ARR + (PAD_ROW * 4 + PAD_COL) * 0x40
    e.uc.mem_write(arr, struct.pack("<HHI", 0xF1, 0, 0) + struct.pack("<HHI", 0xDB, 0, 0) + struct.pack("<HHI", P_TYPE, 0, t))
    e.w32(store + 4, arr)
    e.uc.mem_write(store + 10, struct.pack("<H", 3))


def reset():
    e.uc.mem_write(OBJ + 4, bytes(0x40))


def cutoff(knob):
    """filter.c's cutoff for a low-pass knob (< 0): the stock curve, clamped as filter.c clamps it"""
    e.uc.reg_write(UC_ARM_REG_S0, f2i(knob + 1.0 if knob < 0 else knob))
    e.call(0x08060640)
    return min(max(i2f(e.uc.reg_read(UC_ARM_REG_S0)), 10.0), 0.45 * 48000)


def fw(left, right=None, knob=-0.4, res=0.5):
    """one block through the firmware's filter_process, in place; returns (left, right) as float32 arrays"""
    values[PARAMS + 8], values[PARAMS + 0x44] = knob, res
    e.uc.mem_write(LBUF, np.asarray(left, np.float32).tobytes())
    if right is not None:
        e.uc.mem_write(RBUF, np.asarray(right, np.float32).tobytes())
    e.uc.mem_write(BUF, struct.pack("<IIIIBB", len(left), len(left), LBUF, RBUF if right is not None else 0, 0,
                                    int(right is not None)))
    e.call("filter_process", OBJ, BUF, PAD, 0, count=20_000_000)
    l = np.frombuffer(bytes(e.uc.mem_read(LBUF, 4 * len(left))), np.float32).copy()
    r = np.frombuffer(bytes(e.uc.mem_read(RBUF, 4 * len(left))), np.float32).copy() if right is not None else None
    return l, r


def fw_run(x, knob, res, right=None):
    """a whole signal, block by block"""
    out_l, out_r = [], []
    for at in range(0, len(x) - N + 1, N):
        l, r = fw(x[at:at + N], None if right is None else right[at:at + N], knob, res)
        out_l.append(l)
        if r is not None:
            out_r.append(r)
    return np.concatenate(out_l), (np.concatenate(out_r) if out_r else None)


def worst(a, b):
    return float(np.max(np.abs(np.asarray(a, np.float64) - np.asarray(b, np.float64))))


t = np.arange(N * 24)
saw = (0.45 * (2 * ((t * 110 / 48000) % 1.0) - 1)).astype(np.float32)
noise = np.random.default_rng(7).uniform(-0.5, 0.5, len(t)).astype(np.float32)

# ---------------------------------------------------------------- placement
check("ladder_render is in bank 2, the glue in the cave",
      0x08100000 <= e.sym["ladder_render"] < 0x081E0000
      and all(0x080F1E78 <= e.sym[f] < 0x08100000 for f in ("filter_register", "filter_defaults", "filter_process")))

# ---------------------------------------------------------------- the firmware against the host build
knob, hz = -0.4, None
hz = cutoff(knob)
for ftype, name in ((1, "Ladder"), (2, "Ladder 50"), (3, "Vintage")):
    for res in (0.0, 0.5, 0.95):
        reset()
        set_type(ftype)
        got, _ = fw_run(saw, knob, res)
        want = R.run(dll, saw, hz, res, ftype)
        err = worst(got, want)
        check(f"{name}, Res {res:.0%}: firmware = host build of ladder.c (max diff {err:.1e})", err < 1e-5, err)

reset()
set_type(1)
gl, gr = fw_run(saw, knob, 0.7, right=noise)
check("stereo: each channel is its own ladder (left = the mono run, right = the host on its own input)",
      worst(gl, R.run(dll, saw, hz, 0.7, 1)) < 1e-5 and worst(gr, R.run(dll, noise, hz, 0.7, 1)) < 1e-5)

# ---------------------------------------------------------------- what it does
dc = np.full(N * 160, 0.1, np.float32)
k = 4.2 * 0.9 ** 2
for ftype, c, name in ((1, 1.0, "Ladder"), (2, 0.5, "Ladder 50"), (3, 0.0, "Vintage")):
    reset()
    set_type(ftype)
    y, _ = fw_run(dc, -0.3, 0.9)
    want = (1 + k * c) / (1 + k)
    check(f"{name}: bass at Res 90 % passes {y[-1] / 0.1:.3f} (expected {want:.3f})", abs(y[-1] / 0.1 - want) < 0.01)

reset()
set_type(1)
kick = np.zeros(N * 375, np.float32)                     # 1 s
kick[0] = 0.5
y, _ = fw_run(kick, -0.45, 1.0)
tail = y[-24000:]
zc = np.sum(np.diff(np.signbit(tail).astype(int)) != 0)
fc = cutoff(-0.45)
check(f"Res 100 %: self-oscillates at the cutoff ({zc} Hz for {fc:.0f} Hz) and holds a level (peak {np.max(np.abs(tail)):.2f})",
      abs(zc / fc - 1) < 0.03 and 0.05 < np.max(np.abs(tail)) < 1.0)

reset()
hot = (4.0 * np.random.default_rng(1).uniform(-1, 1, N * 40)).astype(np.float32)
y, _ = fw_run(hot, -0.2, 1.0)
check(f"full-scale x4 noise at Res 100 %: bounded, no NaN (peak {np.max(np.abs(y)):.2f})",
      np.isfinite(y).all() and np.max(np.abs(y)) < 8)

# ---------------------------------------------------------------- the switches
def svf_only(x, knob, res):
    """the same blocks through Clean 24 from a fresh object"""
    reset()
    set_type(0)
    return fw_run(x, knob, res)[0]


reset()
set_type(1)
hp, _ = fw_run(saw, 0.4, 0.5)
check("high-pass side (knob right of centre): Clean 24's SVF whatever the type", worst(hp, svf_only(saw, 0.4, 0.5)) == 0.0)

reset()
set_type(1)
fw_run(saw[:N * 4], -0.4, 0.8)
set_type(0)
after, _ = fw(saw[N * 4:N * 5], None, -0.4, 0.8)
fresh = svf_only(saw[N * 4:N * 5], -0.4, 0.8)
check("Ladder -> Clean 24 on a sounding voice: the SVF starts clean, as on a fresh voice", worst(after, fresh) == 0.0)

reset()
set_type(0)
fw_run(saw[:N * 4], -0.4, 0.8)
set_type(3)
after, _ = fw(saw[N * 4:N * 5], None, -0.4, 0.8)
ref = R.run(dll, saw[N * 4:N * 5], hz, 0.8, 3)
check("Clean 24 -> Vintage: the ladder starts clean (no SVF state read as ladder state)", worst(after, ref) < 1e-5)

reset()
set_type(2)
y0, _ = fw(saw[:N], None, 0.0, 0.5)
check("Filter knob at centre with a ladder type: untouched, as before", worst(y0, saw[:N]) == 0.0)

reset()
set_type(7)
odd, _ = fw_run(saw[:N * 4], -0.4, 0.6)
check("a Filter Type value from the future: Clean 24", worst(odd, svf_only(saw[:N * 4], -0.4, 0.6)) == 0.0)

# ---------------------------------------------------------------- no bank 2
saved = bytes(e.uc.mem_read(0x08100000, 0x8000))
e.uc.mem_write(0x08100000, b"\xff" * 0x8000)             # bank 2 as an erase leaves it
e.uc.mem_write(0x2405FFD0 + 35, b"\x00")                 # not yet checked, as at a fresh boot
ok = True
try:
    reset()
    set_type(1)
    nob2, _ = fw_run(saw[:N * 4], -0.4, 0.6)
except Exception as exc:
    ok = False
    print(f"     FAULTED: {type(exc).__name__} {exc}")
e.uc.mem_write(0x08100000, saved)
e.uc.mem_write(0x2405FFD0 + 35, b"\x00")
check("bank 2 erased: Ladder plays as Clean 24 instead of calling into 0xff", ok and worst(nob2, svf_only(saw[:N * 4], -0.4, 0.6)) == 0.0)

# ---------------------------------------------------------------- settings
reg = []
e.stub(0x0808C0D8, lambda: reg.append((e.arg(1), e.arg(2), e.arg(3), e.r32(e.uc.reg_read(UC_ARM_REG_SP)),
                                       e.r32(e.uc.reg_read(UC_ARM_REG_SP) + 4))))


def cstr(a):
    b = bytes(e.uc.mem_read(a, 32))
    return b[:b.index(0)].decode()


e.call("filter_register", 0x24070000)
param, label, names, count, xml = reg[0]
shown = [cstr(e.r32(names + 4 * i)) for i in range(count)]
check(f"registered: {param:#x} \"{cstr(label)}\" {shown} xml \"{cstr(xml)}\"",
      param == P_TYPE and count == 4 and cstr(xml) == "filtertype" and shown[0] == "Clean 24" and shown[1:] in (
          ["Ladder", "Ladder 50", "Vintage"], ["---", "---", "---"]), reg)
del e.stubs[0x0808C0D8]

STORE, CELL, HEAP = 0x2406F000, 0x2406F100, 0x24070000
e.stub(0x0804436C, value=HEAP)
adds = []
e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, d: adds.append((uc.reg_read(UC_ARM_REG_R1), uc.reg_read(UC_ARM_REG_R2))),
              begin=0x08093EF6, end=0x08093EF7)
for celltype, name in ((3, "pad cell"), (0x4C, "pad cell, second table")):
    e.uc.mem_write(STORE, bytes(0x20))
    e.uc.mem_write(HEAP, bytes(0x800))
    e.uc.mem_write(CELL, bytes([celltype]) + bytes(0x3F))
    adds.clear()
    e.call(0x08093F20, STORE, CELL, count=500000)
    n, cap = e.r16(STORE + 10), e.r16(STORE + 12)
    stored = {e.r16(HEAP + 8 * i): e.r32(HEAP + 8 * i + 4) for i in range(n)}
    check(f"{name}: {len(adds)} defaults of {cap} places, Filter Type stored and Clean 24",
          len(adds) <= cap and stored.get(P_TYPE, None) == 0, (len(adds), cap, stored.get(P_TYPE)))

# ---------------------------------------------------------------- cost
count = {"ins": 0, "div": 0}


def tally(uc, a, size, d):
    count["ins"] += 1
    if size == 4:
        h1, h2 = struct.unpack("<HH", uc.mem_read(a, 4))
        count["div"] += (h1 & 0xFFB0) == 0xEE80 and (h2 & 0x0F50) == 0x0A00


h = e.uc.hook_add(UC_HOOK_CODE, tally)
for stereo in (False, True):
    reset()
    set_type(1)
    fw(saw[:N], noise[:N] if stereo else None, -0.4, 0.8)
    count["ins"] = count["div"] = 0
    fw(saw[N:2 * N], noise[N:2 * N] if stereo else None, -0.4, 0.8)
    cyc = count["ins"] + 13 * count["div"]                # vdiv.f32: 14 cycles on the M7
    print(f"     {'stereo' if stereo else 'mono'} voice, Ladder: {count['ins']} instructions + {count['div']} divisions per "
          f"128-frame block, ~{cyc} cycles = {cyc / 1.28e6 * 100:.1f} % of a block at 480 MHz")
    check(f"{'stereo' if stereo else 'mono'}: under {6 if stereo else 3} % of a block per voice",
          cyc / 1.28e6 * 100 < (6 if stereo else 3), cyc)
e.uc.hook_del(h)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
