#!/bin/bash
# Renders scene.html to a frame sequence + mp4, deterministically.
# Scene state is a pure function of ?t=, so re-running yields identical frames.
#
# Chrome's --screenshot does not reliably exit on this build, so each frame is
# launched detached and reaped once the PNG has been written.
#
# NOTE: this launches one Chrome per frame, which is slow (~3.5s each) and makes
# a dock icon flicker for the whole run. Driving a single instance over the
# DevTools protocol would be faster and quieter; not worth it while fixtures are
# rendered once and then left alone.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FPS="${FPS:-8}"
DUR="${DUR:-24.0}"
OUT="$HERE/frames"
PROFILE="$(mktemp -d)"
trap 'rm -rf "$PROFILE"' EXIT

rm -rf "$OUT"; mkdir -p "$OUT"
N=$(python3 -c "print(int($DUR*$FPS))")
echo "rendering $N frames at ${FPS}fps"

shoot() { # $1=t  $2=outfile
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --no-first-run \
    --no-default-browser-check --disable-extensions --disable-background-networking \
    --force-device-scale-factor=1 --window-size=1280,720 --virtual-time-budget=800 \
    --user-data-dir="$PROFILE/$(basename "$2" .png)" \
    --screenshot="$2" "file://$HERE/scene.html?t=$1" >/dev/null 2>&1 &
  local pid=$!
  for _ in $(seq 1 60); do            # up to ~6s
    if [ -s "$2" ]; then sleep 0.15; break; fi
    sleep 0.1
  done
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
}

for i in $(seq 0 $((N-1))); do
  T=$(python3 -c "print(f'{$i/$FPS:.4f}')")
  F=$(printf "%04d" "$i")
  shoot "$T" "$OUT/f$F.png"
  printf "\r  %s/%s  t=%ss" "$((i+1))" "$N" "$T"
done
echo
ffmpeg -y -loglevel error -framerate "$FPS" -i "$OUT/f%04d.png" \
  -c:v libx264 -pix_fmt yuv420p -crf 18 "$HERE/dense.mp4"
echo "wrote $(ls "$OUT" | wc -l | tr -d ' ') frames + dense.mp4"
