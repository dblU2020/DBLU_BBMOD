"""Point the four fault vectors at src/fault.c's recorder, and IRQ 0 at its watchdog early-wakeup handler.

Stock's HardFault / MemManage / BusFault / UsageFault handlers are stubs that spin, so a crash resets the unit and
leaves nothing to look at. The recorder latches the faulting PC, the stacked registers and the fault status
registers into backup SRAM, then asks for the reset itself - so recovery is as quick as before, but the crash can
be read out afterwards over the USB peek at 0x38800fd0. Apply together with `cave`.
"""
import os
import struct

from thumb import ROOT, symbols

sym = symbols(os.path.join(ROOT, "out", "cave.elf"))
H = struct.pack("<I", sym["fault_handler"] | 1)     # thumb
W = struct.pack("<I", sym["wdg_handler"] | 1)

PATCHES = [
    (0x0804000C, struct.pack("<I", 0x08046267), H),   # HardFault
    (0x08040010, struct.pack("<I", 0x08046269), H),   # MemManage
    (0x08040014, struct.pack("<I", 0x0804626B), H),   # BusFault
    (0x08040018, struct.pack("<I", 0x0804626D), H),   # UsageFault
    # IRQ 0 = WWDG1. Stock leaves EWI off and the vector at its default stub (0x080402ab); instrument_boot arms the
    # interrupt, and it only ever fires one watchdog tick before a reset that was going to happen anyway.
    (0x08040040, struct.pack("<I", 0x080402AB), W),
]
