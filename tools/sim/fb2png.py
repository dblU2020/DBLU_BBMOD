"""Simulated Bitbox micro screen -> PNG. Input: the L8 UI buffer (240 x 320, native panel orientation) and its CLUT
(ARGB8888, DMA2D FGCMAR), dumped from Renode; or a 16-bit output buffer (--rgb565 / --argb1555).
The UI is landscape: the panel image is rotated to 320 x 240 (default --rot 270; 90 the other way).

  python3 sim/fb2png.py l8 out/sim/l8.bin out/sim/clut.bin out/sim/screen.png [--rot 270]
  python3 sim/fb2png.py rgb565 out/sim/out_a.bin out/sim/a.png [--rot 270] [--swap]   (--swap: high byte first)
"""
import struct
import sys
import zlib

W, H = 240, 320


def png(path, w, h, rgb):
    raw = b"".join(b"\0" + bytes(rgb[y * w * 3:(y + 1) * w * 3]) for y in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def rotate(px, rot):
    """px: list of (r, g, b) in W x H rows -> (w, h, list) rotated"""
    if rot == 0:
        return W, H, px
    out = [None] * (W * H)
    for y in range(H):
        for x in range(W):
            if rot == 90:            # clockwise: new (x', y') = (H - 1 - y, x), width H
                out[x * H + (H - 1 - y)] = px[y * W + x]
            else:                    # 270
                out[(W - 1 - x) * H + y] = px[y * W + x]
    return H, W, out


def main(a):
    rot = 270
    swap = "--swap" in a
    a = [x for x in a if x != "--swap"]
    if "--rot" in a:
        rot = int(a[a.index("--rot") + 1])
        a = a[:a.index("--rot")]
    mode = a[0]
    if mode == "l8":
        data, clut = open(a[1], "rb").read(), open(a[2], "rb").read()
        pal = [(clut[4 * i + 2], clut[4 * i + 1], clut[4 * i]) for i in range(len(clut) // 4)]   # B, G, R, A
        px = [pal[v] for v in data[:W * H]]
        dst = a[3]
    else:
        data = open(a[1], "rb").read()
        px = []
        for i in range(W * H):
            v = data[2 * i] | data[2 * i + 1] << 8
            if swap:
                v = (v >> 8) | (v & 0xFF) << 8
            if mode == "rgb565":
                px.append(((v >> 11 & 31) * 255 // 31, (v >> 5 & 63) * 255 // 63, (v & 31) * 255 // 31))
            else:                    # argb1555
                px.append(((v >> 10 & 31) * 255 // 31, (v >> 5 & 31) * 255 // 31, (v & 31) * 255 // 31))
        dst = a[2]
    w, h, px = rotate(px, rot)
    png(dst, w, h, [c for p in px for c in p])
    print("wrote", dst, w, "x", h)


if __name__ == "__main__":
    main(sys.argv[1:])
