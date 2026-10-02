#!/bin/bash
# The runs viewer's posters: the first frame of each published recording, at the recording's own size, so the player is
# never a black box and Play starts on the same picture (build_runs_site.poster_attr reads them).
#   tools/site/make_posters.sh <site>/runs/v <site>/runs/p
# Run it on the build VM (ffmpeg), after the recordings are encoded; it overwrites <out>/<trial>.jpg for every <trial>.mp4.
set -euo pipefail
V=$1; OUT=$2; mkdir -p "$OUT"
ls "$V" | grep '\.mp4$' | xargs -P 8 -I{} sh -c 'f={}; t=${f%.mp4}; ffmpeg -v error -y -i "'"$V"'/$f" -frames:v 1 -q:v 3 "'"$OUT"'/$t.jpg" || echo "FAIL $t"'
echo "done $(ls "$OUT" | wc -l)"
