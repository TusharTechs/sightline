#!/bin/bash
# Builds a narrated version of the walkthrough: Polly narration laid onto a
# silent bed at fixed offsets, muxed over the existing video. The gaps between
# segments are what fit-the-gaps mode has to find and fit into.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
DUR="${DUR:-11.0}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

"$PY" - "$HERE/narration.json" "$TMP" <<'PYEOF'
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])) or ".", ""))
sys.path.insert(0, os.environ["SIGHTLINE_SRC"])
from speech import synthesize
segs = json.load(open(sys.argv[1]))["segments"]
for i, s in enumerate(segs):
    meta = synthesize(s["text"], os.path.join(sys.argv[2], f"n{i:02d}.pcm"))
    print(f"{i} t={s['t']} dur={meta['duration_s']}")
PYEOF

# silent bed, then overlay each segment at its offset
ffmpeg -y -loglevel error -f lavfi -i "anullsrc=r=48000:cl=stereo" -t "$DUR" "$TMP/bed.wav"
FILTER=""; INPUTS=(-i "$TMP/bed.wav"); N=0
while read -r idx t _; do
  ffmpeg -y -loglevel error -f s16le -ar 48000 -ac 2 -i "$TMP/n$(printf %02d "$idx").pcm" "$TMP/n$idx.wav"
  INPUTS+=(-i "$TMP/n$idx.wav")
  N=$((N+1))
  FILTER+="[$N]adelay=$(python3 -c "print(int(float('$t')*1000))")|$(python3 -c "print(int(float('$t')*1000))")[d$N];"
done < <("$PY" -c "
import json,sys
for i,s in enumerate(json.load(open('$HERE/narration.json'))['segments']): print(i, s['t'], '')")
MIX=""; for i in $(seq 1 $N); do MIX+="[d$i]"; done
ffmpeg -y -loglevel error "${INPUTS[@]}" \
  -filter_complex "${FILTER}[0]${MIX}amix=inputs=$((N+1)):duration=first:normalize=0[a]" \
  -map "[a]" -ar 48000 -ac 2 "$HERE/narration.wav"
ffmpeg -y -loglevel error -i "$HERE/walkthrough.mp4" -i "$HERE/narration.wav" \
  -c:v copy -c:a aac -shortest "$HERE/walkthrough-narrated.mp4"
echo "wrote narration.wav and walkthrough-narrated.mp4"
