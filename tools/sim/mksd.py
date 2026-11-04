"""Virtual SD card for the simulation: a FAT32 image with an MBR, optionally filled from a folder.

  python3 tools/sim/mksd.py out/sim/sd.img [--size 256] [--from <folder>]

macOS: hdiutil (built in). Linux: mtools (mformat, mcopy). The firmware reads the card through tools/sim/sdhook.py.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile


def mac(img, size_mb, tree):
    tmp = tempfile.mkdtemp(dir=os.path.dirname(img))
    try:
        base = os.path.join(tmp, "sd")
        subprocess.run(["hdiutil", "create", "-quiet", "-size", f"{size_mb}m", "-fs", "MS-DOS FAT32", "-volname",
                        "BLACKBOX", "-layout", "MBRSPUD", "-type", "UDIF", base], check=True)
        subprocess.run(["hdiutil", "convert", "-quiet", base + ".dmg", "-format", "UDTO", "-o", base], check=True)
        if tree:
            mnt = os.path.join(tmp, "mnt")
            os.makedirs(mnt)
            subprocess.run(["hdiutil", "attach", "-quiet", "-imagekey", "diskimage-class=CRawDiskImage", "-nobrowse",
                            "-mountpoint", mnt, base + ".cdr"], check=True)
            try:
                subprocess.run(["cp", "-RX", tree + "/.", mnt], check=True)
                subprocess.run(["dot_clean", "-m", mnt], check=False)
                shutil.rmtree(os.path.join(mnt, ".fseventsd"), ignore_errors=True)
            finally:
                subprocess.run(["hdiutil", "detach", "-quiet", mnt], check=True)
        shutil.move(base + ".cdr", img)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def linux(img, size_mb, tree):
    start = 2048                                             # first partition at 1 MiB
    with open(img, "wb") as f:
        f.truncate(size_mb << 20)
        mbr = bytearray(512)
        mbr[446:462] = struct.pack("<B3sB3sII", 0, bytes(3), 0x0C, bytes(3), start, (size_mb << 11) - start)
        mbr[510:512] = b"\x55\xaa"
        f.write(mbr)
    part = f"{img}@@1M"
    subprocess.run(["mformat", "-i", part, "-F", "-v", "BLACKBOX", "::"], check=True)
    if tree:
        names = [os.path.join(tree, n) for n in os.listdir(tree)]
        if names:
            subprocess.run(["mcopy", "-s", "-i", part] + names + ["::"], check=True)


def main(a):
    size, tree = 256, None
    if "--size" in a:
        i = a.index("--size"); size = int(a[i + 1]); del a[i:i + 2]
    if "--from" in a:
        i = a.index("--from"); tree = os.path.abspath(a[i + 1]); del a[i:i + 2]
    img = os.path.abspath(a[0])
    os.makedirs(os.path.dirname(img), exist_ok=True)
    if os.path.exists(img):
        os.remove(img)
    (mac if sys.platform == "darwin" else linux)(img, size, tree)
    print("wrote", img)


if __name__ == "__main__":
    main(sys.argv[1:])
