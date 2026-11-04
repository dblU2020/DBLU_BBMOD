#!/usr/bin/env bash
# Boot this fork's firmware in the Renode simulation and take screenshots (out/sim/*.png).
#   tools/sim/sim.sh                      build if needed, boot, screenshot the Pads screen and TOOLS
#   tools/sim/sim.sh <run.py actions...>  your own sequence, e.g.: wait 15 press B7 wait 2 shot tools
#   REBUILD=1 tools/sim/sim.sh            rebuild the release image first
# Needs: Renode (tools/sim/README.md), the stock firmware (tools/fetch_firmware.sh), arm-none-eabi-gcc.
set -euo pipefail
cd "$(dirname "$0")/../.."
REL="out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
if [ "${REBUILD:-0}" = 1 ] || [ ! -f "$REL" ] || [ ! -f out/bank2.bin ]; then
  tools/fetch_firmware.sh
  RELEASE=1 ./build.sh >/dev/null
  python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault cave | tail -1
fi
[ -f out/sim/sd.img ] || python3 tools/sim/mksd.py out/sim/sd.img
if [ $# -eq 0 ]; then set -- wait 15 shot pads press B7 wait 2 shot tools; fi
python3 -I tools/sim/run.py "$@"
echo "screenshots: $(pwd)/out/sim/*.png"
