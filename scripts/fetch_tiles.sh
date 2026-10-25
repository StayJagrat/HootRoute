#!/usr/bin/env bash
# Prepares the self-hosted SF basemap for Abhishek's PWA.
# Copies the existing local extract when available; otherwise needs pmtiles CLI
# and network once. The archive is ignored by Git and must exist on the demo host.
set -euo pipefail
cd "$(dirname "$0")/.."
TARGET="web/public/tiles/sf.pmtiles"
mkdir -p "$(dirname "$TARGET")"
if [[ -s "$TARGET" ]]; then
  echo "Basemap already present: $TARGET"
elif [[ -s legacy/web/public/tiles/sf.pmtiles ]]; then
  cp legacy/web/public/tiles/sf.pmtiles "$TARGET"
  echo "Copied the local SF basemap to $TARGET"
else
  command -v pmtiles >/dev/null || { echo "Install the pmtiles CLI first (brew install pmtiles)." >&2; exit 1; }
  BUILD="${1:-$(curl --fail --silent --show-error https://build-metadata.protomaps.dev/builds.json | python3 -c 'import sys,json; print(sorted(json.load(sys.stdin), key=lambda x: x["key"])[-1]["key"])')}"
  echo "Extracting San Francisco from Protomaps build $BUILD"
  pmtiles extract "https://build.protomaps.com/$BUILD" "$TARGET" --bbox=-122.54,37.69,-122.34,37.84 --maxzoom=15
fi
if [[ ! -s "$TARGET" ]]; then echo "Basemap preparation failed." >&2; exit 1; fi
ls -lh "$TARGET"
