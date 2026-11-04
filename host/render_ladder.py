"""Ladder filter on the host: src/ladder.c compiled here and driven block by block, the way filter.c will drive it.

As host/render_eq.py: GCC where there is one, -Os, fused multiply-adds where the host has them, so the rounding
matches the firmware's build of the same file.

    python3 host/render_ladder.py OUTDIR     renders the listening demo (WAVs) into OUTDIR; "Clean 24" there is the
                                             firmware's own filter_process from the patched image, run under Unicorn
"""
import ctypes
import math
import os
import platform
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "out", "libladder.dylib")
F = ctypes.POINTER(ctypes.c_float)
FS = 48000
N = 128                                                  # the engine's block
SMOOTH = 0.33333                                         # filter.c's per-block coefficient smoothing
TYPES = ["Clean 24", "Ladder", "Ladder 50", "Vintage"]   # ladder.h's order


def gnu_cc():
    try:
        out = subprocess.run(["gcc", "--version"], capture_output=True, text=True).stdout
    except OSError:
        return None
    return "gcc" if "Free Software Foundation" in out else None


def lib():
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    flags = ["-Os", "-shared", "-fPIC", "-ffp-contract=fast"]
    if platform.machine() in ("x86_64", "AMD64") and os.path.exists("/proc/cpuinfo") \
            and " fma " in open("/proc/cpuinfo").read():
        flags.append("-mfma")
    subprocess.run([gnu_cc() or "clang", *flags, "-DLADDER_LINEAR_DEMO", "-o", LIB,
                    os.path.join(ROOT, "src", "ladder.c")], check=True)
    dll = ctypes.CDLL(LIB)
    dll.ladder_render.argtypes = (F, ctypes.c_int, ctypes.c_float, ctypes.c_float, ctypes.c_uint, F, F)
    dll.ladder_render_linear.argtypes = (F, ctypes.c_int, ctypes.c_float, ctypes.c_float, ctypes.c_uint, F)
    return dll


def tan_approx(x):
    """filter.c's tan(x), Pade (3,2), in float32"""
    x = np.float32(x)
    x2 = x * x
    return np.float32(x * (np.float32(15) - x2) / (np.float32(15) - np.float32(6) * x2))


def g_of(hz):
    hz = min(max(hz, 10.0), 0.45 * FS)
    return tan_approx(np.float32(math.pi) * np.float32(hz) / np.float32(FS))


def run(dll, x, hz, res, ftype):
    """mono x through the ladder; hz / res: a number, or a function block index -> value. Returns float32.
    The cutoff glides per block like filter.c's coefficients (here on the frequency itself)."""
    y = x.astype(np.float32).copy()
    s, last = (ctypes.c_float * 4)(), (ctypes.c_float * 1)()
    f = None
    for i, at in enumerate(range(0, len(y) - N + 1, N)):
        ft = np.float32(hz(i) if callable(hz) else hz)
        f = ft if f is None else np.float32(f + np.float32(SMOOTH) * (ft - f))
        r = res(i) if callable(res) else res
        dll.ladder_render(y[at:at + N].ctypes.data_as(F), N, float(f), float(r), ftype, s, last)
    return y


def run_linear(dll, x, hz, res, ftype):
    """the first prototype, for comparison"""
    y = x.astype(np.float32).copy()
    s = (ctypes.c_float * 4)()
    g = None
    for i, at in enumerate(range(0, len(y) - N + 1, N)):
        gt = g_of(hz(i) if callable(hz) else hz)
        g = gt if g is None else np.float32(g + np.float32(SMOOTH) * (gt - g))
        r = res(i) if callable(res) else res
        dll.ladder_render_linear(y[at:at + N].ctypes.data_as(F), N, float(g), float(r), ftype, s)
    return y


# ---------------------------------------------------------------- the firmware's Clean 24, and its cutoff curve

class Firmware:
    """the patched image's filter_process under Unicorn (as test_filter.py drives it), mono"""

    def __init__(self):
        sys.path.insert(0, ROOT)
        os.chdir(ROOT)
        import struct
        from unicorn.arm_const import UC_ARM_REG_S0
        from emu import Emu
        self.struct, self.S0 = struct, UC_ARM_REG_S0
        img = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
        e = self.e = Emu(img, "out/cave.elf")
        self.OBJ, self.PARAMS, self.PAD, self.BUF, self.LBUF = 0x24060000, 0x24061000, 0x24062000, 0x24063000, 0x24064000
        self.vals = {}
        f2i = lambda v: struct.unpack("<I", struct.pack("<f", v))[0]
        e.stub(0x0806FB30, lambda: e.uc.reg_write(UC_ARM_REG_S0, f2i(self.vals.get(e.arg(0), 0.0))))
        e.w32(self.OBJ + 0x84, self.PARAMS)
        store, arr = 0x24020088 + 0x1840 + 0xF0 + 2 * 0x30, 0x24073000 + 6 * 0x40     # pad row 1, col 2: Fidelity Normal
        e.uc.mem_write(arr, struct.pack("<HHI", 0x8B, 0, 0) + struct.pack("<HHI", 0xF1, 0, 0) + struct.pack("<HHI", 0xDB, 0, 0))
        e.w32(store + 4, arr)
        e.uc.mem_write(store + 10, struct.pack("<H", 3))
        e.w32(self.PAD + 0x18, 1 << 8 | 2)

    def cutoff_hz(self, knob):
        """the stock curve filter.c uses: knob 0..1 -> Hz"""
        st = self.struct
        self.e.uc.reg_write(self.S0, st.unpack("<I", st.pack("<f", knob))[0])
        self.e.call(0x08060640)
        return st.unpack("<f", st.pack("<I", self.e.uc.reg_read(self.S0)))[0]

    def clean(self, x, knob, res):
        """mono x through filter_process; knob < 0 = low-pass side, as the pad's Filter knob"""
        st, e = self.struct, self.e
        y = x.astype(np.float32).copy()
        e.uc.mem_write(self.OBJ + 4, bytes(0x40))
        for i, at in enumerate(range(0, len(y) - N + 1, N)):
            self.vals[self.PARAMS + 8] = knob(i) if callable(knob) else knob
            self.vals[self.PARAMS + 0x44] = res(i) if callable(res) else res
            e.uc.mem_write(self.LBUF, y[at:at + N].tobytes())
            e.uc.mem_write(self.BUF, st.pack("<IIIIBB", N, N, self.LBUF, 0, 0, 0))
            e.call("filter_process", self.OBJ, self.BUF, self.PAD, 0, count=5_000_000)
            y[at:at + N] = np.frombuffer(bytes(e.uc.mem_read(self.LBUF, 4 * N)), dtype=np.float32)
        return y


# ---------------------------------------------------------------- the demo

def saw(freqs, amp=0.45):
    """a band-limited-ish saw (polyBLEP) through a list of (Hz, seconds) notes with a short amp envelope"""
    out = []
    for f, d in freqs:
        n = int(d * FS)
        t = np.arange(n)
        ph = (t * f / FS) % 1.0
        dt = f / FS
        y = 2 * ph - 1
        y -= np.where(ph < dt, (ph / dt) * 2 - (ph / dt) ** 2 - 1, 0)          # polyBLEP at the wrap
        y -= np.where(ph > 1 - dt, ((ph - 1) / dt) ** 2 + 2 * (ph - 1) / dt + 1, 0)
        env = np.minimum(1, t / (0.004 * FS)) * np.exp(-t / (0.6 * FS))
        out.append(amp * y * env)
    return np.concatenate(out).astype(np.float32)


def bassline():
    a = 55.0
    semis = [0, 0, 12, 0, 3, 0, 5, 7, 0, 0, 12, 0, 10, 7, 5, 3]
    return saw([(a * 2 ** (s / 12), 0.125) for s in semis * 2])


def write(path, x):
    """16-bit mono WAV. A file whose loudest part would clip is turned down as a whole (so the parts keep their
    relative levels and no clipping is added that is not the filter's)"""
    peak = float(np.max(np.abs(x)))
    if peak > 0.98:
        x = x * np.float32(0.98 / peak)
        print(f"    {os.path.basename(path)}: turned down {20 * math.log10(peak / 0.98):.1f} dB as a whole (peak {peak:.2f})")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes((x * 32767).astype("<i2").tobytes())


DEMO = ["Clean 24 (today)", "Linear ladder (1st try)", "Vintage", "Ladder 50", "Ladder"]


def five(dll, fw, x, knob, hz, res):
    """the same part through the five filters of the demo, in DEMO's order"""
    return [fw.clean(x, knob, res), run_linear(dll, x, hz, res, 1),
            run(dll, x, hz, res, 3), run(dll, x, hz, res, 2), run(dll, x, hz, res, 1)]


def db(y):
    return 20 * math.log10(np.sqrt(np.mean(y ** 2)) + 1e-12)


def demo(outdir):
    os.makedirs(outdir, exist_ok=True)
    dll, fw = lib(), Firmware()
    gap = np.zeros(int(0.35 * FS), np.float32)
    order = "clean-linear-vintage-ladder50-ladder"
    bass = bassline()
    knob = -0.45                                             # Filter knob left of centre: low-pass, fairly closed
    hz = fw.cutoff_hz(knob + 1)
    print(f"bass line: Filter knob {knob} -> {hz:.0f} Hz")
    for res in (0.0, 0.5, 0.9, 1.0):
        ys = five(dll, fw, bass, knob, hz, res)
        for name, y in zip(DEMO, ys):
            print(f"  Res {res:4.0%} {name:24s}: RMS {db(y):6.1f} dB, peak {np.max(np.abs(y)):.2f}, nan {np.isnan(y).any()}")
        write(os.path.join(outdir, f"bass_res{int(res * 100):03d}_{order}.wav"),
              np.concatenate([p for y in ys for p in (y, gap)]))
    # a held chord with the cutoff swept closed -> open -> closed over 4 s, Res 85 %
    chord = sum(saw([(f, 4.0)], amp=0.18) for f in (110.0, 164.8, 220.0, 277.2))
    chord *= np.float32(1 / np.max(np.abs(chord)) * 0.5)
    blocks = len(chord) // N
    sweep = lambda i: -0.9 + 0.75 * math.sin(math.pi * i / blocks)            # knob -0.9 .. -0.15 .. -0.9
    sweep_hz = [fw.cutoff_hz(sweep(i) + 1) for i in range(blocks)]
    ys = five(dll, fw, chord, sweep, lambda i: sweep_hz[i], 0.85)
    for name, y in zip(DEMO, ys):
        print(f"  sweep Res 85% {name:24s}: peak {np.max(np.abs(y)):.2f}")
    write(os.path.join(outdir, f"sweep_res085_{order}.wav"), np.concatenate([p for y in ys for p in (y, gap)]))
    # drive: the same bass line at its normal level, +6 dB and +12 dB into Vintage at Res 70 %, levelled back
    # afterwards so only the change of sound is left: normal, hot, very hot
    parts = []
    for amp in (1.0, 2.0, 4.0):
        y = run(dll, bass * np.float32(amp), hz, 0.7, 3) / np.float32(amp)
        parts += [y, gap]
        print(f"  drive {amp:4.2f}x into Vintage, Res 70%: levelled RMS {db(y):6.1f} dB")
    write(os.path.join(outdir, "drive_vintage_res070_normal-hot-veryhot.wav"), np.concatenate(parts))
    # self-oscillation: Res 100 %, a tiny click to start it, the cutoff swept 100 Hz -> 4 kHz -> 100 Hz over 6 s
    x = np.zeros(6 * FS, np.float32)
    x[0] = 0.5
    blocks = len(x) // N
    osc_hz = lambda i: 100 * 40 ** math.sin(math.pi * i / blocks)
    tone = run(dll, x, osc_hz, 1.0, 1)
    print(f"  self-oscillation sweep (Ladder, Res 100%): peak {np.max(np.abs(tone)):.2f}, nan {np.isnan(tone).any()}")
    write(os.path.join(outdir, "selfosc_ladder_res100_sweep.wav"), tone)


if __name__ == "__main__":
    demo(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "out", "ladder-demo"))
