"""(From portkit-blackbox, MIT; adapted for this fork: paths, Blackbox defaults. See THIRD_PARTY.md.)
Run the simulated Bitbox micro / Blackbox through a sequence of actions and take screenshots.

  python3 sim/run.py [--image stock|pk|<path>] [--sd out/sim/sd.img] <actions...>
  actions: wait <s> | press <HOME|TOOLS|LEFT|RIGHT> | shot <name> | hook <addr> <label> | ticks | py <code>
           capture <name> | capture-stop | input <raw> | set <param id> <value> | midi <hex> | note <nr> <s>
           tap <x> <y> [<s>] | touch <x> <y> | release (screen coordinates) | dump <addr> <len> <name>
           prof <phase> | prof report | store <addr> <id> <value>
           mark <text> | watch <addr> <label> (reads) | watchw <addr> <label> <Byte|Word|DoubleWord> (writes) (engine instructions per audio block, sim/prof.py)
  e.g.     python3 sim/run.py --image pk wait 12 shot pads press TOOLS wait 1 shot tools press LEFT wait 1 shot comp

Screenshots go to out/sim/<name>.png (LTDC composition, sim/screenshot.py). Renode: ~/tools/renode (see README).
Buttons (table 0x24009da4, polled by 0x08041a50 from the engine block 0x08093e48, i.e. only while audio runs; active
low, 25 ms debounce; index = table position, as flag +0xc14 is set at run time - else 3 - position, checked in the
simulation): HOME = PG3, TOOLS = PD4, LEFT = PC13, RIGHT = PB13. All four are held high (released) from the start.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root (tools/sim/..)
SIM = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out", "sim")
# Renode: $RENODE, else the usual install places (macOS app, a portable Linux build in ~/tools)
RENODE = os.environ.get("RENODE") or next(
    (p for p in (os.path.expanduser("~/Applications/Renode.app/Contents/MacOS/renode"),
                 "/Applications/Renode.app/Contents/MacOS/renode",
                 os.path.expanduser("~/tools/renode/Renode.app/Contents/MacOS/renode"),
                 os.path.expanduser("~/tools/renode/renode"))
     if os.path.exists(p)), "renode")
RELEASE_DIR = os.path.join(ROOT, "out",
                           "solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave")
# this fork: "ours" = the release build (RELEASE=1 ./build.sh + patch.py, README Build) with its bank 2 payload
IMAGES = {"ours": os.path.join(RELEASE_DIR, "BLACKBOX.bin"),
          "stock": os.path.join(ROOT, "firmware", "BLACKBOX-3.1.9.bin")}
BANK2 = os.path.join(ROOT, "out", "bank2.bin")
BUTTONS = {"HOME": ("gpioPortG", 3), "TOOLS": ("gpioPortD", 4), "LEFT": ("gpioPortC", 13), "RIGHT": ("gpioPortB", 13)}
# Blackbox 3.1.9: 13 keys, active low, polled at 0x080438DE (table index = order below; names = index until known)
BB_BUTTONS = {f"B{k}": pp for k, pp in enumerate([
    ("gpioPortI", 8), ("gpioPortD", 4), ("gpioPortD", 7), ("gpioPortI", 12), ("gpioPortI", 14), ("gpioPortG", 3),
    ("gpioPortH", 7), ("gpioPortC", 13), ("gpioPortB", 13), ("gpioPortJ", 1), ("gpioPortH", 4), ("gpioPortC", 2),
    ("gpioPortC", 3)])}
PRESS_S = 0.1
TOUCH_FLIP_Y = os.environ.get("SIM_TOUCH_FLIP_Y", "1") == "1"   # the UI's y counts from the bottom (checked: see README)
MIDI_INS = ("uart4", "usart6")                               # their TX carries MIDI clock (0xf8): the two MIDI ports
UARTS = ("usart1", "usart2", "usart3", "uart4", "uart5", "usart6", "uart7", "uart8", "lpuart1")


def body(path):
    return [l for l in open(path).read().splitlines() if l.strip() and not l.startswith("#")]


def build(image, sd, actions, repl="micro.repl", bank2=None):
    flip = TOUCH_FLIP_Y and repl == "micro.repl"         # Blackbox: touch y counts from the top (checked: VEL slider)
    lines = [f"include @{os.path.join(SIM, 'PortkitAudioDMA.cs')}", f"include @{os.path.join(SIM, 'PortkitGT911.cs')}",
             f"$bin=@{image}", f"$repl=@{os.path.join(SIM, repl)}", f"include @{os.path.join(SIM, 'boot.resc')}"]
    if bank2:                                            # flash bank 2 as the card loader would leave it (JOEBOX)
        lines.append(f"sysbus LoadBinary @{os.path.abspath(bank2)} 0x08100000")
    keys = BUTTONS if repl == "micro.repl" else BB_BUTTONS
    for port, pin in keys.values():
        lines.append(f"sysbus.{port} OnGPIO {pin} true")
    sdr = "sd.resc" if repl == "micro.repl" else "sd_blackbox.resc"   # diskio hooks at each firmware's addresses
    lines += [l.replace("$simdir", SIM).replace("$sdimg", sd) for l in body(os.path.join(SIM, sdr))]
    for u in (x for x in UARTS if not (repl != "micro.repl" and x == "lpuart1")):   # serial output -> out/sim/uart_<name>.txt
        lines.append(f"sysbus.{u} CreateFileBackend @{os.path.join(OUT, 'uart_' + u + '.txt')} true")
    shots = []
    i = 0
    while i < len(actions):
        act = actions[i]
        if act == "wait":
            lines.append(f'emulation RunFor "{float(actions[i + 1])}"')
            i += 2
        elif act == "press":
            port, pin = keys[actions[i + 1].upper()]
            lines += [f"sysbus.{port} OnGPIO {pin} false", f'emulation RunFor "{PRESS_S}"',
                      f"sysbus.{port} OnGPIO {pin} true", f'emulation RunFor "{PRESS_S}"']
            i += 2
        elif act == "peek":                                  # peek <addr> <label> <reg> <off>: log byte at reg+off, if nonzero
            lines.append(f'cpu AddHook {actions[i + 1]} "v=self.GetMachine().SystemBus.ReadByte(self.GetRegisterUnsafe({actions[i + 3]}).RawValue + {actions[i + 4]}); '
                         f'(v and self.Log(LogLevel.Warning, \'HOOK {actions[i + 2]} %d\' % v))"')
            i += 5
        elif act in ("keydown", "keyup"):                     # keydown / keyup <key>: hold a key (combinations)
            port, pin = keys[actions[i + 1].upper()]
            lines.append(f"sysbus.{port} OnGPIO {pin} {'false' if act == 'keydown' else 'true'}")
            i += 2
        elif act == "hook":                                  # hook <addr> <label>: log each time it runs
            lines.append(f'cpu AddHook {actions[i + 1]} "self.Log(LogLevel.Warning, \'HOOK {actions[i + 2]} r0=0x%x r1=0x%x\' % '
                         f'(self.GetRegisterUnsafe(0).RawValue, self.GetRegisterUnsafe(1).RawValue))"')
            i += 3
        elif act == "ticks":                                 # audio clock ticks so far (log)
            lines.append('python "print(\'AUDIO TICKS\', self.Machine[\'sysbus.audioDma\'].Ticks)"')
            i += 1
        elif act == "capture":                               # capture <name>: output (DMA2 stream 1) -> out/sim/<name>.raw
            lines.append(f'python "self.Machine[\'sysbus.audioDma\'].CaptureTo(1, \'{os.path.join(OUT, actions[i + 1] + ".raw")}\')"')
            i += 2
        elif act == "capture-stop":
            lines.append('python "self.Machine[\'sysbus.audioDma\'].CaptureStop()"')
            i += 1
        elif act == "input":                                 # input <raw file>: into DMA2 stream 5 (SAI1 B), looped
            lines.append(f'python "self.Machine[\'sysbus.audioDma\'].InputFrom(5, \'{os.path.abspath(actions[i + 1])}\')"')
            i += 2
        elif act == "set":                                   # set <id> <value>: settings store (app +0x7fd0) entry
            lines.append(f'python "import sdhook; sdhook.store_set(self.Machine.SystemBus, 0x24013cb0 + 0x7fd0, {actions[i + 1]}, {actions[i + 2]})"')
            i += 3
        elif act == "midi":                                  # midi <hex bytes, e.g. 903c64>: into both MIDI ins
            data = bytes.fromhex(actions[i + 1])
            for u in MIDI_INS:
                lines += [f"sysbus.{u} WriteChar {b:#04x}" for b in data]
            i += 2
        elif act == "note":                                  # note <nr> <seconds>: note on (ch 1, vel 100) .. off
            nr, dur = int(actions[i + 1]), float(actions[i + 2])
            for u in MIDI_INS:
                lines += [f"sysbus.{u} WriteChar {b:#04x}" for b in (0x90, nr, 100)]
            lines.append(f'emulation RunFor "{dur}"')
            for u in MIDI_INS:
                lines += [f"sysbus.{u} WriteChar {b:#04x}" for b in (0x80, nr, 0)]
            i += 3
        elif act == "tap":                                   # tap <x> <y> [<s>]: screen coordinates (screenshot, top left)
            x, y = int(actions[i + 1]), int(actions[i + 2])
            dur = 0.15
            i += 3
            if i < len(actions) and actions[i].replace(".", "").isdigit():
                dur = float(actions[i])
                i += 1
            ux, uy = x, (239 - y) if flip else y
            lines += [f'python "self.Machine[\'sysbus.i2c1.touch\'].Touch({ux}, {uy})"', f'emulation RunFor "{dur}"',
                      'python "self.Machine[\'sysbus.i2c1.touch\'].Release()"', 'emulation RunFor "0.15"']
        elif act == "touch":                                 # touch <x> <y>: finger down (screen coordinates), stays
            x, y = int(actions[i + 1]), int(actions[i + 2])
            uy = (239 - y) if flip else y
            lines.append(f'python "self.Machine[\'sysbus.i2c1.touch\'].Touch({x}, {uy})"')
            i += 3
        elif act == "release":
            lines.append('python "self.Machine[\'sysbus.i2c1.touch\'].Release()"')
            i += 1
        elif act == "dump":                                  # dump <addr> <len> <name>: append memory to out/sim/<name>.bin
            path = os.path.join(OUT, actions[i + 3] + ".bin")
            lines.append(f'python "b=self.Machine.SystemBus; f=open(\'{path}\', \'ab\'); '
                         f'f.write(bytes(bytearray(b.ReadBytes({actions[i + 1]}, {actions[i + 2]})))); f.close()"')
            i += 4
        elif act == "prof":                                  # prof <phase>|report: engine instructions per block
            if not any("prof.start" in l for l in lines):
                for a in (0x08042458, 0x08042474):
                    lines.append(f'cpu AddHook {a:#x} "import prof; prof.start(self)"')
                for a in (0x08042468, 0x08042484):
                    lines.append(f'cpu AddHook {a:#x} "import prof; prof.end(self)"')
            arg = actions[i + 1]
            lines.append('python "import prof; prof.report()"' if arg == "report" else f'python "import prof; prof.phase(\'{arg}\')"')
            i += 2
        elif act == "store":                                 # store <store addr> <id> <value>: any parameter store
            lines.append(f'python "import sdhook; sdhook.store_set(self.Machine.SystemBus, {actions[i + 1]}, {actions[i + 2]}, {actions[i + 3]})"')
            i += 4
        elif act == "mips":                                  # mips <n>: simulated CPU speed (Renode default 100)
            lines.append(f"cpu PerformanceInMips {actions[i + 1]}")
            i += 2
        elif act == "mark":                                  # mark <text>: a line in the log
            lines.append(f'python "print(\'MARK {actions[i + 1]}\')"')
            i += 2
        elif act == "watch":                                 # watch <addr> <label>: log PC / LR of every read there
            lines.append(f'sysbus AddWatchpointHook {actions[i + 1]} DoubleWord Read "self.Log(LogLevel.Warning, '
                         f'\'HOOK {actions[i + 2]} pc=0x%x lr=0x%x\' % (self.GetMachine()[\'sysbus.cpu\'].PC.RawValue, '
                         f'self.GetMachine()[\'sysbus.cpu\'].LR.RawValue))"')
            i += 3
        elif act == "watchw":                                # watchw <addr> <label> <width>: PC / LR of every write
            lines.append(f'sysbus AddWatchpointHook {actions[i + 1]} {actions[i + 3]} Write "self.Log(LogLevel.Warning, '
                         f'\'HOOK {actions[i + 2]} pc=0x%x lr=0x%x\' % (self.GetMachine()[\'sysbus.cpu\'].PC.RawValue, '
                         f'self.GetMachine()[\'sysbus.cpu\'].LR.RawValue))"')
            i += 4
        elif act == "fill":                                  # fill <addr> <len> <byte>: memory pattern (e.g. before boot)
            n, v = int(actions[i + 2], 0), int(actions[i + 3], 0)
            path = os.path.join(OUT, f"fill_{v:02x}_{n:x}.bin")
            if not os.path.exists(path):
                with open(path, "wb") as f:
                    f.write(bytes([v]) * n)
            lines.append(f"sysbus LoadBinary @{path} {actions[i + 1]}")
            i += 4
        elif act == "regs":                                  # regs <addr> <label>: log r0-r3 each time it runs
            lines.append(f'cpu AddHook {actions[i + 1]} "self.Log(LogLevel.Warning, \'HOOK {actions[i + 2]} '
                         f'r0=0x%x r1=0x%x r2=0x%x r3=0x%x lr=0x%x\' % tuple(self.GetRegisterUnsafe(k).RawValue '
                         f'for k in (0, 1, 2, 3, 14)))"')
            i += 3
        elif act == "regsx":                                 # regsx <addr> <label>: log r4-r8, [r4+0x18], sp
            lines.append(f'cpu AddHook {actions[i + 1]} "c=self; b=self.GetMachine().SystemBus; '
                         f'self.Log(LogLevel.Warning, \'HOOK {actions[i + 2]} r4=0x%x r5=0x%x r6=0x%x r7=0x%x r8=0x%x id=0x%x sp=0x%x\' % '
                         f'(c.GetRegisterUnsafe(4).RawValue, c.GetRegisterUnsafe(5).RawValue, c.GetRegisterUnsafe(6).RawValue, '
                         f'c.GetRegisterUnsafe(7).RawValue, c.GetRegisterUnsafe(8).RawValue, b.ReadDoubleWord(c.GetRegisterUnsafe(4).RawValue + 0x18), '
                         f'c.SP.RawValue))"')
            i += 3
        elif act == "py":                                    # py <monitor python>: raw monitor python line
            lines.append('python "' + actions[i + 1] + '"')
            i += 2
        elif act == "shot":
            d = os.path.join(OUT, "shot_" + actions[i + 1])
            os.makedirs(d, exist_ok=True)
            lines += [l.replace("$shot", d) for l in body(os.path.join(SIM, "screenshot.resc"))]
            shots.append((actions[i + 1], d))
            i += 2
        else:
            raise SystemExit(f"unknown action {act}")
    lines.append('python "self.Machine[\'sysbus.audioDma\'].CaptureStop()"')
    lines.append("quit")
    return lines, shots


def main(a):
    # this fork: the Blackbox by default (portkit's original defaulted to the Bitbox micro)
    image, sd, repl, bank2 = IMAGES["ours"], os.path.join(OUT, "sd.img"), "blackbox.repl", BANK2
    while a and a[0].startswith("--"):
        if a[0] == "--image":
            image = IMAGES.get(a[1], a[1])
            if a[1] != "ours":
                bank2 = None                                 # bank 2 only with our own build (or --bank2 after)
        elif a[0] == "--repl":                               # platform description in sim/ (blackbox.repl)
            repl = a[1]
        elif a[0] == "--sd":
            sd = os.path.abspath(a[1])
        elif a[0] == "--bank2":                              # flash bank 2 contents (JOEBOX: out/bb/jb/bank2.bin)
            bank2 = None if a[1] == "none" else a[1]
        a = a[2:]
    os.makedirs(OUT, exist_ok=True)
    lines, shots = build(image, sd, a, repl, bank2)
    resc = os.path.join(OUT, "run.resc")
    open(resc, "w").write("\n".join(lines) + "\n")
    with open(os.path.join(OUT, "run.log"), "w") as log:
        # no stdin: on a script error Renode's console gets EOF and exits instead of waiting for input
        r = subprocess.run([RENODE, "--console", "--disable-gui", "--plain", resc], stdin=subprocess.DEVNULL, stdout=log,
                           stderr=subprocess.STDOUT, timeout=1800)
    print("renode exit", r.returncode)
    for name, d in shots:
        rot = "270" if repl == "micro.repl" else "0"     # Micro panel is portrait, the Blackbox LTDC landscape
        subprocess.run([sys.executable, "-I", os.path.join(SIM, "screenshot.py"), d, os.path.join(OUT, name + ".png"),
                        "--rot", rot])


if __name__ == "__main__":
    main(sys.argv[1:])
