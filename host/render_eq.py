"""Per-pad EQ on the host: src/eq_dsp.c compiled here and driven block by block, the way the firmware drives it.

test_eq.py holds the firmware's build of the same file to this one. Compiled with fused multiply-adds where the
host has them (the firmware's gcc fuses them on the Cortex-M7), and with GCC where there is one, which makes the same
choices of which to fuse: then the two round alike to the bit. With clang they can differ by an ulp in a coefficient,
which a 30 Hz shelf turns into a few 1e-4 of output while it glides.
"""
import ctypes
import os
import platform
import struct
import subprocess

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "out", "libeq.dylib")
F = ctypes.POINTER(ctypes.c_float)
STATE = 184                                       # sizeof(struct eq_state)
KNOBS = ("lo_g", "lo_f", "mid_g", "mid_f", "hi_g", "hi_f", "cut", "q")     # eq.h's order
DEFAULTS = dict(lo_g=0, lo_f=233, mid_g=0, mid_f=565, hi_g=0, hi_f=797, cut=0, q=374)


def gnu_cc():
    """a real GCC if there is one (on a Mac `gcc` is clang): it fuses multiply-adds where the firmware's gcc does"""
    try:
        out = subprocess.run(["gcc", "--version"], capture_output=True, text=True).stdout
    except OSError:
        return None
    return "gcc" if "Free Software Foundation" in out else None


def lib():
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    flags = ["-Os", "-shared", "-fPIC", "-ffp-contract=fast"]           # -Os as the firmware: inlining decides what fuses
    if platform.machine() in ("x86_64", "AMD64") and os.path.exists("/proc/cpuinfo") \
            and " fma " in open("/proc/cpuinfo").read():
        flags.append("-mfma")
    subprocess.run([gnu_cc() or "clang", *flags, "-o", LIB, os.path.join(HERE, "..", "src", "eq_dsp.c")], check=True)
    dll = ctypes.CDLL(LIB)
    dll.eq_render.argtypes = (ctypes.c_void_p, ctypes.c_char_p, F, F, ctypes.c_int)
    return dll


def settings(pos=0, snap=0, **kw):
    """struct eq_set: the eight knobs in store units, the position (0 Post, 1 Pre), and snap (a new note)"""
    k = dict(DEFAULTS, **kw)
    return struct.pack("<8hBB2x", *(k[n] for n in KNOBS), pos, snap)


def new_state():
    return ctypes.create_string_buffer(STATE)


def block(dll, state, s, l, r=None):
    """one block in place; l and r are float32 numpy arrays"""
    dll.eq_render(state, s, l.ctypes.data_as(F), None if r is None else r.ctypes.data_as(F), len(l))


def run(dll, x, sets, n=128, mono=False, state=None):
    """x through the EQ block by block; `sets` is one eq_set for every block, or a function block index -> eq_set"""
    state = state or new_state()
    l, r = x.astype(np.float32).copy(), x.astype(np.float32).copy()
    for i, at in enumerate(range(0, len(x) - n + 1, n)):
        s = sets(i) if callable(sets) else sets
        block(dll, state, s, l[at:at + n], None if mono else r[at:at + n])
    return l, r
