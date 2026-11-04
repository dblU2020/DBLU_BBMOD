# Third-party work

The patch (source and the compiled bytes in `docs/blackbox-mod-*.json`) includes or derives from the following.
All of it is MIT-licensed, and these notices travel with every copy.

| Component | Copyright | License | Where |
|---|---|---|---|
| JOEBOX 1 / blackbox-mod ([j3threejay/blackbox-mod](https://github.com/j3threejay/blackbox-mod)), the base of this mod: everything not listed as DBLU_BBMOD's own in the README | © 2026 Justin Joe | MIT | the whole tree; notice in `LICENSE` |
| Munchi Delay ([charlesvestal/schwung-munchi-delay](https://github.com/charlesvestal/schwung-munchi-delay)) | © 2026 Charles Vestal | MIT | `src/munchi/` (`LICENSE`, `THIRD_PARTY.md` beside it) |
| CHOMPI TEMPO 1.0 firmware (granular delay, compressor, crossfades) | © CHOMPI Club | MIT | `src/munchi/tempo/` |
| `reverb.h`, `fx_engine.h` | © Émilie Gillet (Mutable Instruments) | MIT | `src/munchi/tempo/`, notices in the files |
| DaisySP `dsp.h` | © Electrosmith, Corp. | MIT | `src/munchi/daisysp/` |
| State-variable filter, after stmlib `dsp/filter.h` (`Svf`) | © 2014 Émilie Gillet | MIT | reimplemented in `src/filter.c` |

## Not included

**1010music's Blackbox firmware is not in this repository**, in whole or in part, in source, history, or releases.
The patch file stores only the bytes this project adds or changes; the stock image is identified by SHA-256 and
supplied by you.

## Trademarks

"1010music" and "Blackbox" are trademarks of 1010music LLC. CHOMPI is a trademark of CHOMPI Club. SP-1200, SP-12,
S950, MPC60 and Elektron are trademarks of their owners, named here only to describe what a mode is modelled on.
This project is independent and is not affiliated with, endorsed by, or supported by any of them.

## portkit-blackbox: Renode simulation (`tools/sim/`)

[kyrillleier-jpg/portkit-blackbox](https://github.com/kyrillleier-jpg/portkit-blackbox), MIT licence. `tools/sim/`
holds its `sim/` scripts (`run.py`, `boot.resc`, `blackbox.repl`, `sd_blackbox.resc`, `sdhook.py`, `screenshot.py`,
`screenshot.resc`, `fb2png.py`, `wav.py`, `prof.py`, `PortkitAudioDMA.cs`, `PortkitGT911.cs`); `run.py` is adapted
(paths, Blackbox defaults). `mksd.py`, `sim.sh` and the README are ours.

```
MIT License

Copyright (c) 2026 portkit contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
