"""Screenshot of the simulated Bitbox micro: composes what the LTDC shows from a dump written by Renode
(sim/screenshot.resc): the LTDC registers and both layer framebuffers. The panel is 240 x 320 (portrait) on the LTDC
(RGB interface; SPI3 only carries the panel's init commands); the UI is landscape, so the image is rotated.

  python3 sim/screenshot.py out/sim/shot out/sim/screen.png [--rot 270]

LTDC (RM0433 34.7): BPCR +0x0c / AWCR +0x10 (active area), BCCR +0x2c (background), layer n at +0x84 + 0x80 (n - 1):
CR +0, WHPCR +4, WVPCR +8, PFCR +0x10, CACR +0x14, BFCR +0x1c, CFBAR +0x28, CFBLR +0x2c, CFBLNR +0x30.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fb2png  # noqa: E402


def decode(pf, raw, i):
    """pixel i of a framebuffer -> (r, g, b, a 0..1)"""
    if pf == 3:                                    # ARGB1555
        v = raw[2 * i] | raw[2 * i + 1] << 8
        return ((v >> 10 & 31) * 255 // 31, (v >> 5 & 31) * 255 // 31, (v & 31) * 255 // 31, v >> 15)
    if pf == 2:                                    # RGB565
        v = raw[2 * i] | raw[2 * i + 1] << 8
        return ((v >> 11 & 31) * 255 // 31, (v >> 5 & 63) * 255 // 63, (v & 31) * 255 // 31, 1)
    if pf == 0:                                    # ARGB8888
        b, g, r, a = raw[4 * i:4 * i + 4]
        return (r, g, b, a / 255)
    if pf == 1:                                    # RGB888
        b, g, r = raw[3 * i:3 * i + 3]
        return (r, g, b, 1)
    raise SystemExit(f"pixel format {pf} not handled")


BPP = {0: 4, 1: 3, 2: 2, 3: 2, 4: 2}


def main(a):
    rot = 270
    if "--rot" in a:
        rot = int(a[a.index("--rot") + 1])
        a = a[:a.index("--rot")]
    src, dst = a
    regs = dict((int(k, 16), int(v, 16)) for k, v in (l.split() for l in open(os.path.join(src, "ltdc.txt"))))
    bpcr, awcr = regs[0x0C], regs[0x10]
    x0, y0 = (bpcr >> 16) + 1, (bpcr & 0x7FF) + 1                    # first active pixel (AHBP + 1, AVBP + 1)
    w, h = (awcr >> 16) - (bpcr >> 16), (awcr & 0x7FF) - (bpcr & 0x7FF)
    bg = regs[0x2C]
    img = [((bg >> 16) & 255, (bg >> 8) & 255, bg & 255)] * (w * h)
    for n in (1, 2):
        base = 0x84 + 0x80 * (n - 1)
        if not regs.get(base, 0) & 1:
            continue
        whp, wvp, pf = regs[base + 4], regs[base + 8], regs[base + 0x10] & 7
        cacr = (regs[base + 0x14] & 255) / 255
        pitch = regs[base + 0x2C] >> 16
        lines = regs[base + 0x30] & 0x7FF
        raw = open(os.path.join(src, f"layer{n}.bin"), "rb").read()
        lx0, lx1 = (whp & 0xFFF) - x0 + 1, (whp >> 16) - x0 + 1          # window, in active-area pixels
        ly0, ly1 = (wvp & 0x7FF) - y0 + 1, (wvp >> 16) - y0 + 1
        bpp = BPP[pf]
        for y in range(max(ly0, 0), min(ly1, h, ly0 + lines)):
            for x in range(max(lx0, 0), min(lx1, w)):
                i = (y - ly0) * (pitch // bpp) + (x - lx0)
                r, g, b, al = decode(pf, raw, i)
                al *= cacr
                if al <= 0:
                    continue
                o = img[y * w + x]
                img[y * w + x] = tuple(int(c * al + oc * (1 - al)) for c, oc in zip((r, g, b), o))
    fb2png.W, fb2png.H = w, h
    ow, oh, px = fb2png.rotate(img, rot)
    fb2png.png(dst, ow, oh, [c for p in px for c in p])
    print("wrote", dst, ow, "x", oh)


if __name__ == "__main__":
    main(sys.argv[1:])
