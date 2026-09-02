#!/bin/sh
# Fetch the Titan GPU lifetime summary (Ostrouchov et al., SC '20) from its
# canonical home and refuse to keep anything whose SHA-256 does not match the
# pin in src/slicepacker/hazard.py. The file is fetched rather than vendored:
# upstream publishes it with a citation request and no license grant, so
# redistribution is not this repository's call to make.
set -eu
cd "$(dirname "$0")"
URL="https://raw.githubusercontent.com/olcf/TitanGPULife/master/data/gc_summary_loc.csv"
SHA="07ece0f04e2bf20eb7c9e7eba05f6cd772ea89da08af5761be403635d3490ada"
OUT="titan_gc_summary_loc.csv"
if [ -f "$OUT" ] && printf '%s  %s\n' "$SHA" "$OUT" | shasum -a 256 -c - > /dev/null 2>&1; then
    echo "data/$OUT already present and verified"
    exit 0
fi
curl -fsSL "$URL" -o "$OUT.tmp"
printf '%s  %s\n' "$SHA" "$OUT.tmp" | shasum -a 256 -c - > /dev/null
mv "$OUT.tmp" "$OUT"
echo "fetched and verified data/$OUT"
