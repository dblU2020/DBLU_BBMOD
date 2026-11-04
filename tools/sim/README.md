# Blackbox simulator (Renode)

Boots our firmware on the computer, no Blackbox needed: real screens as screenshots, button presses, touch, MIDI
notes, a virtual SD card, and a capture of Out 1's audio. Built on portkit's simulation (MIT, `THIRD_PARTY.md`).

**What it is not:** not cycle-accurate (the CPU load in TOOLS means nothing here), no clock gating, about 5x slower
than real time. USB and preset saving are untested. Check sound and load on the real unit.

## Setup on a Mac (Apple Silicon)

1. **Renode 1.17**: download `renode-1.17.0.osx-arm64-portable.dmg` from
   <https://github.com/renode/renode/releases/tag/v1.17.0>, open it, drag **Renode.app** to Applications. The first
   time, macOS may block it: right-click Renode.app → Open, or run
   `xattr -dr com.apple.quarantine /Applications/Renode.app`. (That release has no Intel-Mac build.)
2. **Build tools** (once, for building the firmware): `brew install --cask gcc-arm-embedded`, and Python 3
   (comes with the Xcode command line tools: `xcode-select --install`).
3. In the repo: `tools/fetch_firmware.sh` (stock 3.1.9, checked by SHA-256).

## Run

```sh
tools/sim/sim.sh
```

It builds the release image if there is none (`REBUILD=1` to force), makes an empty SD card (`out/sim/sd.img`),
boots, and writes `out/sim/pads.png` and `out/sim/tools.png`. TOOLS should show our release name without a "!".
One run takes about a minute.

Own sequences (actions in `tools/sim/run.py`'s header):

```sh
tools/sim/sim.sh wait 15 tap 32 50 wait 1 shot pad1 press B7 wait 2 shot tools
```

- `wait <s>`, `shot <name>`, `press B0..B12`, `tap <x> <y> [<s>]` (screen pixels, 320 x 240, from the top left),
  `note <nr> <s>` (MIDI note), `capture <name>` / `capture-stop` (Out 1 audio; `tools/sim/wav.py` makes a WAV).
- Keys: B0 Pads, B1 Keys, B2 Seq, B3 Song, B4 Perf FX, B5 Mixer, B6 File, B7 Tools; B8–B12 not mapped yet
  (INFO and BACK are among them).
- `--image stock` boots the stock 3.1.9 for comparison. Renode somewhere else: `RENODE=/path/to/renode tools/sim/sim.sh`.
- SD card with files: `python3 tools/sim/mksd.py out/sim/sd.img --from <folder>`.

## Next

Map INFO / BACK (B8–B12), put a test sample and preset on the card, and script the pad pages (Conf, EQ, Filt Type),
so a new page can be checked here before it goes on the unit.
