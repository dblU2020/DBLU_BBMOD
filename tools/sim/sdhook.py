# Virtual SD card for the Renode simulation (IronPython 2.7, loaded by sim/sd.resc).
# The firmware reads its card through STM32Cube's sd_diskio (driver table 0x080bf030) -> BSP_SD_*_DMA -> SDMMC1 with
# its internal DMA, which Renode's STM32HSDMMC model lacks. The five diskio functions are taken over instead: each hook
# serves the call from an image file and returns to the caller (FatFS and everything above stay firmware code).
#   SD_initialize 0x08044fac (lun)        -> 0 (STA ok)       SD_status 0x08045188 (lun) -> 0
#   SD_read  0x0804504c (lun, buf, sector, count) -> RES_OK   SD_write 0x080450bc (same) -> RES_OK
#   SD_ioctl 0x08045130 (lun, cmd, buf): CTRL_SYNC 0, GET_SECTOR_COUNT 1, GET_SECTOR_SIZE 2, GET_BLOCK_SIZE 3
import clr
import System
from Antmicro.Renode.Peripherals.CPU import RegisterValue
from System.IO import FileStream, FileMode, FileAccess, FileShare, SeekOrigin

SECTOR = 512
_f = [None]
stats = {"read": 0, "write": 0}
bufs = {}                                                  # buffer address -> (reads, writes)


def open_image(path):
    _f[0] = FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.Read)


def _reg(cpu, n):
    return int(cpu.GetRegisterUnsafe(n).RawValue)


def _ret(cpu, value):
    cpu.SetRegisterUnsafe(0, RegisterValue.Create(value, 32))
    cpu.PC = RegisterValue.Create(_reg(cpu, 14) & ~1, 32)


def init(cpu):
    _ret(cpu, 0)


def status(cpu):
    _ret(cpu, 0)


def read(cpu):
    buf, sector, count = _reg(cpu, 1), _reg(cpu, 2), _reg(cpu, 3)
    n = count * SECTOR
    data = System.Array.CreateInstance(System.Byte, n)
    _f[0].Seek(sector * SECTOR, SeekOrigin.Begin)
    _f[0].Read(data, 0, n)
    cpu.Bus.WriteBytes(data, buf)
    stats["read"] += count
    r, w = bufs.get(buf, (0, 0))
    bufs[buf] = (r + count, w)
    _ret(cpu, 0)


def write(cpu):
    buf, sector, count = _reg(cpu, 1), _reg(cpu, 2), _reg(cpu, 3)
    n = count * SECTOR
    data = cpu.Bus.ReadBytes(buf, n)
    _f[0].Seek(sector * SECTOR, SeekOrigin.Begin)
    _f[0].Write(data, 0, n)
    _f[0].Flush()
    stats["write"] += count
    r, w = bufs.get(buf, (0, 0))
    bufs[buf] = (r, w + count)
    _ret(cpu, 0)


def ioctl(cpu):
    cmd, buf = _reg(cpu, 1), _reg(cpu, 2)
    if cmd == 1:
        cpu.Bus.WriteDoubleWord(buf, int(_f[0].Length // SECTOR))
    elif cmd == 2:
        cpu.Bus.WriteWord(buf, SECTOR)
    elif cmd == 3:
        cpu.Bus.WriteDoubleWord(buf, 1)
    elif cmd != 0:
        _ret(cpu, 4)                                         # RES_PARERR
        return
    _ret(cpu, 0)


def store_set(bus, store, param, value):
    """set an existing entry of a firmware parameter store (layout: +4 entries, +0xa count u16; entry 8 bytes: id u16,
    value i32 at +4 - as read by 0x080894d0). Returns False when the store has no such entry."""
    ent = int(bus.ReadDoubleWord(store + 4))
    cnt = int(bus.ReadWord(store + 0xA))
    for k in range(cnt):
        if int(bus.ReadWord(ent + 8 * k)) == param:
            bus.WriteDoubleWord(ent + 8 * k + 4, value & 0xFFFFFFFF)
            return True
    return False


def store_get(bus, store, param):
    """value of an entry of a firmware parameter store, None when missing (layout as store_set)."""
    ent = int(bus.ReadDoubleWord(store + 4))
    cnt = int(bus.ReadWord(store + 0xA))
    for k in range(cnt):
        if int(bus.ReadWord(ent + 8 * k)) == param:
            v = int(bus.ReadDoubleWord(ent + 8 * k + 4))
            return v - (1 << 32) if v & 0x80000000 else v
    return None


def find_stores(bus, param, lo=0x24013cb0, hi=0x24013cb0 + 0x8100):
    """addresses in [lo, hi) that look like parameter stores holding param (entries pointer in RAM, small count)"""
    found = []
    for a in range(lo, hi, 4):
        ent = int(bus.ReadDoubleWord(a + 4))
        cnt = int(bus.ReadWord(a + 0xA))
        if not (0x20000000 <= ent < 0x24080000 or 0x30000000 <= ent < 0x30048000 or 0xC0000000 <= ent < 0xC4000000) or not (0 < cnt <= 120):
            continue
        for k in range(cnt):
            if int(bus.ReadWord(ent + 8 * k)) == param:
                v = int(bus.ReadDoubleWord(ent + 8 * k + 4))
                found.append((hex(a), hex(a - 0x24013cb0), v))
                break
    return found
