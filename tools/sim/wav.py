"""Raw TDM capture of the simulated micro (sim/PortkitAudioDMA.cs: 32-bit words, 8 slots per frame, 48 kHz) <-> WAV.

  python3 sim/wav.py from-raw out/sim/out.raw out/sim/out.wav [--slots 0,1]     capture -> 16-bit stereo WAV
  python3 sim/wav.py to-raw in.wav out/sim/in.raw [--slots 0,1]                 WAV (16-bit) -> raw input frames
  python3 sim/wav.py stats out/sim/out.raw                                       peak / RMS per slot
"""
import math
import struct
import sys
import wave

SLOTS = 8
RATE = 48000


def frames(raw):
    n = len(raw) // (4 * SLOTS)
    return [struct.unpack_from(f"<{SLOTS}i", raw, 4 * SLOTS * k) for k in range(n)]


def main(a):
    slots = [0, 1]
    if "--slots" in a:
        slots = [int(x) for x in a[a.index("--slots") + 1].split(",")]
        a = a[:a.index("--slots")]
    cmd = a[0]
    if cmd == "stats":
        fr = frames(open(a[1], "rb").read())
        print(f"{len(fr)} frames = {len(fr) / RATE:.2f} s")
        for s in range(SLOTS):
            v = [f[s] / 2 ** 31 for f in fr]
            peak = max((abs(x) for x in v), default=0)
            rms = math.sqrt(sum(x * x for x in v) / max(len(v), 1))
            print(f"  slot {s}: peak {peak:.4f} ({20 * math.log10(peak + 1e-12):.1f} dBFS), rms {rms:.5f}")
    elif cmd == "from-raw":
        fr = frames(open(a[1], "rb").read())
        with wave.open(a[2], "wb") as w:
            w.setnchannels(len(slots))
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(b"".join(struct.pack(f"<{len(slots)}h", *(max(-32768, min(32767, f[s] >> 16)) for s in slots))
                                   for f in fr))
        print("wrote", a[2], len(fr), "frames")
    elif cmd == "to-raw":
        with wave.open(a[1], "rb") as w:
            ch, sw, n = w.getnchannels(), w.getsampwidth(), w.getnframes()
            assert sw == 2 and w.getframerate() == RATE, "16-bit, 48 kHz expected"
            data = w.readframes(n)
        out = bytearray()
        for k in range(n):
            smp = struct.unpack_from(f"<{ch}h", data, 2 * ch * k)
            fr = [0] * SLOTS
            for j, s in enumerate(slots):
                fr[s] = smp[min(j, ch - 1)] << 16
            out += struct.pack(f"<{SLOTS}i", *fr)
        open(a[2], "wb").write(out)
        print("wrote", a[2], n, "frames")


if __name__ == "__main__":
    main(sys.argv[1:])
