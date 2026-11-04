# DBLU_BBMOD

An unofficial feature mod for the **original 1010music Blackbox** (not the Blackbox 2), stock firmware 3.1.9.
It is Justin Joe's [JOEBOX 1](https://github.com/j3threejay/blackbox-mod) with three additions: a **per-pad EQ**, a
**classic ladder filter** and the **ENV·V** modulation source. Everything JOEBOX 1 has stays.

Release: **DBLU_BBMOD_01** (TOOLS shows `DBLUBB01`).

> **Not affiliated with, endorsed by, or supported by 1010music, and not an official JOEBOX build.** This repository
> does not contain 1010music's firmware: you supply your own copy and patch it yourself. Use at your own risk. **So
> far it has run on one unit.** Running modified firmware may affect your warranty. Don't ask 1010music (or Justin)
> for support on a unit running this; flash stock first.

## What it adds

- **Per-pad EQ** on Sample, Multisample, Slicer and Clip pads: low shelf, mid peak, high shelf and a Low Cut.
  - Conf tab, row **EQ:** with **Post** (after the pad's insert effect, default) or **Pre** (before it). Press
    **INFO** on that row for the eight knobs: Low / Mid / High gain, Low Cut, Low / Mid / High frequency, Mid Q.
  - Low 30–600 Hz, Mid 100 Hz–8 kHz with Q 0.3–8, High 1.5–16 kHz, Low Cut Off or 20 Hz–1 kHz.
  - It works on the pad's own mix, so the reverb and delay sends hear the EQ'd pad, and a chord costs no more than
    one note. A flat EQ is bypassed and costs nothing; fully on, about 1 % CPU per playing pad.
  - Gains glide and the Low Cut fades in and out, so turning knobs doesn't click.
- **Classic ladder filter**: Conf tab, **Filt Type:**
  - **Clean 24**: JOEBOX's 24 dB filter, unchanged (default).
  - **Ladder**: a classic transistor ladder with full bass compensation, so the low end stays at high resonance.
  - **Ladder 50**: half the compensation. **Vintage**: none, like the original circuit (the bass thins as Res goes up).
  - Nonlinear in every stage, 2x oversampled, self-oscillates near full Res. Only the low-pass side changes; the
    high-pass side stays Clean 24. About 2 % of a block per voice (4 % stereo).
- **ENV·V** modulation source, right after ENV in the Source list: the pad's envelope scaled by the note's velocity,
  so soft notes open the filter less than hard ones. Sample and Multisample pads per note; on Clip and Slicer pads it
  acts as plain ENV.

**Presets** save these settings per pad, by name. Presets made without them load with the EQ flat, Clean 24 and no
ENV·V routing. Stock firmware and JOEBOX ignore the extra settings.

For everything else (Master FX, inserts, delay and reverb types, LFO 2/3, ENV and KEY sources, Fidelity, chords, note
conditions, solo, USB audio and MIDI, ...) see the [JOEBOX 1 README](https://github.com/j3threejay/blackbox-mod/tree/19d29f1).

## Install

1. Download **blackbox 3.1.9** from <https://1010music.com/downloads> and unzip it. You need the `BLACKBOX.bin` inside.
2. Patch it, either way:
   - **In your browser:** <https://dblu2020.github.io/DBLU_BBMOD/>. Your file never leaves your computer.
   - **With Python 3:** `python3 apply.py path/to/BLACKBOX.bin` → `out/blackbox-mod-dblu-bbmod-01/`
3. Keep the stock `BLACKBOX.bin` somewhere safe. That file is your way back.
4. Copy **both** files, `BLACKBOX.bin` and `BBEXTRA.BIN`, to the **root** of the microSD card.
5. Hold BACK + INFO while powering on, and let go as soon as the install screen shows.
6. On the first boot the Blackbox **restarts itself once** while it installs the second file. Leave the card in and
   the power on until it is back up.
7. TOOLS shows `DBLUBB01`. A `!` in front of the load figures means `BBEXTRA.BIN` is missing or from another build:
   copy both files again.

**To go back to stock:** put the stock `BLACKBOX.bin` on the card and install it the same way.

The patcher only accepts the unmodified 3.1.9 file and checks the result:

| File | SHA-256 |
|---|---|
| Stock `BLACKBOX.bin` (3.1.9, what you patch) | `281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d` |
| Patched `BLACKBOX.bin` (DBLU_BBMOD_01) | `13150b80eacfbd319f81ffdf2afd922c6cde9f304552be73aee629aafe3efabd` |
| `BBEXTRA.BIN` (DBLU_BBMOD_01) | `7e6526dc84afec285a2b20b13a6bb3b350da731ad05c6d7f82989b8ce622c8a4` |

## Known issues

- Tested on one unit so far. Reports are welcome as GitHub issues.
- Everything in JOEBOX 1's known issues applies too (CPU headroom on heavy projects, USB on some units).
- The EQ has no tab of its own yet: it lives behind INFO on the Conf tab's EQ row.

## Build from source

Needs `arm-none-eabi-gcc` and Python 3. Put your stock image at `firmware/BLACKBOX-3.1.9.bin`
(`tools/fetch_firmware.sh` downloads and checks it).

```
RELEASE=1 ./build.sh
python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault cave
```

That writes `out/<patchsets>/BLACKBOX.bin` and `out/BBEXTRA.BIN`, byte-identical to the release.
`python3 make_patch.py <image> "DBLU_BBMOD_01" --extra out/BBEXTRA.BIN` turns the pair into the patch in `docs/`.
`./check.sh` builds, patches and runs every suite (`test_*.py`) under Unicorn (`pip install unicorn capstone numpy scipy`).

**Simulator:** `tools/sim/` boots the firmware in [Renode](https://renode.io) on a computer: real screens as
screenshots, buttons, touch, MIDI notes and an Out 1 capture. See [tools/sim/README.md](tools/sim/README.md).

### What is DBLU_BBMOD's own

`src/eq.c`, `src/eq.h`, `src/eq_dsp.c`, `src/ladder.c`, `src/ladder.h`, their hooks in `src/insert.c`,
`src/master.c`, `src/lfo.c`, `src/filter.c`, `src/duck.c`, `src/duck_thunk.S`, `src/envmod.c`, `patches/filter.py`,
`patches/duck.py`, the tests `test_eq.py`, `test_ladder.py`, `test_render_eq.py`, `host/render_eq.py`,
`host/render_ladder.py`, and `tools/sim/` (on portkit's simulation). Everything else is JOEBOX 1.

## What is and isn't in this repository

In it: source code, patch definitions (addresses and replacement bytes), tools, and MIT-licensed third-party work with
its notices ([THIRD_PARTY.md](THIRD_PARTY.md)).

Not in it, and please don't add it in issues, pull requests or forks: 1010music's firmware, patched firmware images,
decompiled or disassembled listings of the firmware, and 1010music's manuals or artwork.

## License

MIT ([LICENSE](LICENSE)): Justin Joe's JOEBOX and the additions here. "1010music" and "Blackbox" are trademarks of
1010music LLC, used only to say what this mod is for. If you are from 1010music and have a concern about anything
here, please open an issue and it will be dealt with promptly.
