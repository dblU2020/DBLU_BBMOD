#!/usr/bin/env bash
# Fetch 1010music's stock Blackbox 3.1.9 firmware into firmware/ (gitignored) and verify it.
# Set FW_URL to the download link from https://1010music.com/downloads (blackbox, original, 3.1.9),
# or put the URL in the cloud environment as an environment variable.
set -euo pipefail
cd "$(dirname "$0")/.."
DEST=firmware/BLACKBOX-3.1.9.bin
SHA=281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d

if [ -f "$DEST" ] && echo "$SHA  $DEST" | sha256sum -c --status; then
  echo "firmware already present and verified"; exit 0
fi
FW_URL="${FW_URL:-https://1010music.com/wp-content/uploads/2026/07/blackbox-3.1.9.zip}"   # link used in the EQ session

TMP=$(mktemp -d)
curl -fsSL -o "$TMP/dl" "$FW_URL"
if unzip -tq "$TMP/dl" >/dev/null 2>&1; then
  unzip -q "$TMP/dl" -d "$TMP/x"
  SRC=$(find "$TMP/x" -iname 'BLACKBOX.bin' | head -1)
else
  SRC="$TMP/dl"
fi
[ -n "$SRC" ] || { echo "BLACKBOX.bin not found in the download"; exit 1; }
mkdir -p firmware
cp "$SRC" "$DEST"
echo "$SHA  $DEST" | sha256sum -c
rm -rf "$TMP"
