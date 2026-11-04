"""Render level: the per-pad EQ inside stock's own pad process (FUN_080596b0, class A) under Unicorn.

The handoff's "priority 2" test. test_eq.py enters the hooks with a buffer it made itself; here stock's pad process
runs for real around them: its command queue, its choice of a separate mix buffer (insert_buf_a), its voice loop,
the hook after it (insert_run_a -> the EQ), its level / send / output stage. The engine context is built in RAM the
way the pad process reads it: buses at + 0x150e4 + i * 0x14, the pad's mix buffers at + 0x151fc + k * 0x14, each
the 20-byte buffer object {cap, len, l, r, silent, stereo}.
Stubbed: the voice render (FUN_08056fd0) adds a test signal into the mix buffer it is given, as a voice would; the
voice tidy-up after the loop (FUN_08055740).
Reference: host/render_eq.py, the host build of eq_dsp.c, on the same signal.
"""
import struct
import sys

import numpy as np
from unicorn.arm_const import UC_ARM_REG_SP

sys.path.insert(0, "host")
import render_eq as host  # noqa: E402
from emu import Emu  # noqa: E402

IMG = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
e = Emu(IMG, "out/cave.elf")
e.uc.mem_map(0x38800000, 0x1000)
e.uc.mem_map(0x58024000, 0x1000)
e.uc.mem_map(0xC0000000, 0x90000)
dll = host.lib()

BLOCK, BANK = 0xC0000000, 0xC0000000 + 0x56800 + 0xB000
PMEM, PCHECK = 0x38800F70, 0x38800F74
APP_PADS = 0x24020088 + 0x1840
ARR = 0x24072000
CTX = 0x24030000                                 # the engine context the pad process is handed (r1)
PADO, VOICE, VTBL = 0x24068000, 0x24069800, 0x24069C00
CHAN = 0x24058000                                # channel memory for the buffers
N = 128
P_EQ, P_EQ_POS = 0x1C8, 0x1F0
IDS = {"pos": P_EQ_POS, **{k: P_EQ + i for i, k in enumerate(host.KNOBS)}}
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


# ---------------------------------------------------------------- memory, settings
def memory():
    e.w32(PMEM, BLOCK)
    e.w32(PCHECK, BLOCK ^ 0x5052534D)
    e.uc.mem_write(BANK, bytes(0x22000))


def store(n, **kw):
    vals = {0x4: 500, 0xDB: 0, **{IDS[k]: v for k, v in host.DEFAULTS.items()}, P_EQ_POS: 0}
    vals.update({IDS[k]: v for k, v in kw.items()})
    rows = sorted(vals.items())
    at = ARR + n * 0x100
    e.uc.mem_write(at, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
    s = APP_PADS + (n // 4) * 0xF0 + (n % 4) * 0x30
    e.w32(s + 4, at)
    e.uc.mem_write(s + 10, struct.pack("<H", len(rows)))


def settings(slot, **kw):
    memory()
    for p in range(16):
        store(p)
    store(slot, **kw)
    for _ in range(16):
        e.call("insert_tick")


# ---------------------------------------------------------------- the engine context and the pad
nbuf = [0]


def buffer_object(at, stereo=False):
    """a buffer object at `at`, empty, with channel memory of its own"""
    l, r = CHAN + nbuf[0] * 0x400, CHAN + nbuf[0] * 0x400 + 0x200
    nbuf[0] += 1
    e.uc.mem_write(l, bytes(0x400))
    e.uc.mem_write(at, struct.pack("<IIIIBB2x", N, 0, l, r, 1, 1 if stereo else 0))


def context():
    nbuf[0] = 0
    e.uc.mem_write(CTX, bytes(0x15400))
    for i in range(0xC):                         # the buses: 0 = this pad's output, 0xa / 0xb the FX sends
        buffer_object(CTX + 0x150E4 + i * 0x14, stereo=True)
    for k in range(3):                           # the pad's mix / scratch buffers
        buffer_object(CTX + 0x151FC + k * 0x14)


def pad(q):
    e.uc.mem_write(PADO, bytes(0x800))
    e.w32(VTBL + 0x54, 0x08046A15)                # the default "which output" method: pad + 0x1e is the bus
    e.w32(PADO, VTBL)
    e.w32(PADO + 0x18, (q // 4) << 8 | (q % 4))
    e.uc.mem_write(PADO + 0x1E, struct.pack("<H", 0))
    e.w32(PADO + 0x20, 0x24069F00)                # non-zero: the pad has something loaded
    e.uc.mem_write(PADO + 0x28, b"\x01")           # a voice is sounding
    e.w32(PADO + 0x2C, VOICE)
    e.w32(PADO + 0x6C, 1)
    e.uc.mem_write(VOICE, b"\x01" + bytes(0x3FF))
    e.uc.mem_write(PADO + 0x56C, struct.pack("<f", 1.0))   # level 1.0, stage off, sends 0


# the voice: adds this block of the test signal into the mix buffer it is handed (second stack argument)
sig = {"l": None, "r": None, "at": 0}
seen = []


def voice_render():
    sp = e.uc.reg_read(UC_ARM_REG_SP)
    buf = e.r32(sp + 4)
    cap, ln, l, r, silent, stereo = struct.unpack("<IIIIBB", bytes(e.uc.mem_read(buf, 18)))
    seen.append((buf, cap, ln, silent, stereo))
    at = sig["at"]
    x = sig["l"][at:at + N]
    y = (sig["r"] if sig["r"] is not None else sig["l"])[at:at + N]
    old_l = np.zeros(N, np.float32) if silent else np.frombuffer(bytes(e.uc.mem_read(l, 4 * N)), np.float32)
    e.uc.mem_write(l, (old_l + x).astype(np.float32).tobytes())
    if sig["r"] is not None:
        old_r = np.zeros(N, np.float32) if silent else np.frombuffer(bytes(e.uc.mem_read(r, 4 * N)), np.float32)
        e.uc.mem_write(r, (old_r + y).astype(np.float32).tobytes())
    e.uc.mem_write(buf + 4, struct.pack("<I", N))
    e.uc.mem_write(buf + 16, bytes([0, 1 if sig["r"] is not None else 0]))


e.stub(0x08056FD0, voice_render)
e.stub(0x08055740)


def play(x, right=None, q=5, blocks=None):
    """x through the pad process block by block; returns the output bus's left (and right) channel"""
    sig.update(l=x, r=right, at=0)
    pad(q)
    out_l, out_r = [], []
    for at in range(0, len(x) - N + 1, N):
        context()
        e.call("insert_tick")
        sig["at"] = at
        e.call(0x080596B0, PADO, CTX, count=20_000_000)
        cap, ln, l, r, silent, stereo = struct.unpack("<IIIIBB", bytes(e.uc.mem_read(CTX + 0x150E4, 18)))
        out_l.append(np.frombuffer(bytes(e.uc.mem_read(l, 4 * N)), np.float32).copy() if not silent else np.zeros(N, np.float32))
        out_r.append(np.frombuffer(bytes(e.uc.mem_read(r, 4 * N)), np.float32).copy() if not silent and stereo else out_l[-1])
    return np.concatenate(out_l), np.concatenate(out_r)


t = np.arange(N * 60)
sine = (0.25 * np.sin(2 * np.pi * 220 * t / 48000)).astype(np.float32)
noise = np.random.default_rng(3).uniform(-0.3, 0.3, len(t)).astype(np.float32)

# ---------------------------------------------------------------- flat: stock's own path, untouched
settings(5)
yl, _ = play(sine)
check(f"EQ flat: the pad's voice reaches its output bus unchanged (max diff {np.max(np.abs(yl - sine)):.1e})",
      np.max(np.abs(yl - sine)) < 1e-6, seen[:2])

# ---------------------------------------------------------------- EQ on: what the unit plays
for name, kw in (("Low +6 dB", dict(lo_g=6000)), ("Low Cut 200 Hz", dict(cut=11)), ("High -9 dB", dict(hi_g=-9000)),
                 ("Mid +12 dB, Q 2", dict(mid_g=12000, q=619))):
    for stereo in (False, True):
        settings(5, **kw)
        seen.clear()
        yl, yr = play(sine if not stereo else noise, right=None if not stereo else sine)
        x = sine if not stereo else noise
        wl, wr = host.run(dll, x, host.settings(**kw), mono=not stereo)
        err = np.max(np.abs(yl - wl))
        if stereo:
            err = max(err, np.max(np.abs(yr - host.run(dll, sine, host.settings(**kw))[0])))
        steps = np.max(np.abs(np.diff(yl[N * 4:])))
        check(f"{name}, {'stereo' if stereo else 'mono'}: the output bus = the host EQ on the voice's signal "
              f"(max diff {err:.1e}, largest step {steps:.3f}); buffers seen {sorted(set((s[1], s[4]) for s in seen))}",
              err < 1e-4, seen[:3])

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
