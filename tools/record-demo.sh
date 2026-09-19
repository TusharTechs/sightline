#!/usr/bin/env bash
#
# Record the demo. Checks everything that has silently broken before, then
# captures the screen with real system audio.
#
#   tools/record-demo.sh check      what is ready and what is not
#   tools/record-demo.sh record     start recording (ctrl-C to stop)
#
# The audio matters more here than in most demos. Sightline's whole output is
# a voice, and macOS will not give a recorder its own system audio without a
# virtual device. Without one you are recording your speakers through the
# laptop microphone, on a video about audio quality, for judges wearing
# headphones. Install BlackHole; it is free and takes two minutes.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE="${SIGHTLINE_BUNDLE:-/tmp/sightline-serve}"
OUT="${SIGHTLINE_RECORDING:-$HOME/Desktop/sightline-demo-$(date +%H%M).mov}"
PYBIN="$ROOT/pipeline/.venv/bin/python"

ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$1"; FAILED=1; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }

audio_device_id() {
  ffmpeg -f avfoundation -list_devices true -i "" 2>&1 \
    | awk '/AVFoundation audio devices/,0' \
    | grep -iE "blackhole|loopback|aggregate|multi-?output" \
    | head -1 | sed -E 's/.*\[([0-9]+)\].*/\1/'
}

check() {
  FAILED=0
  echo "Recording setup"

  command -v ffmpeg >/dev/null && ok "ffmpeg present" || bad "ffmpeg missing — brew install ffmpeg"

  local aid; aid="$(audio_device_id)"
  if [ -n "$aid" ]; then
    ok "system audio device found (index $aid)"
  else
    bad "no system-audio device. You will record your speakers through the mic."
    echo "      brew install blackhole-2ch"
    echo "      then Audio MIDI Setup -> + -> Multi-Output Device -> tick BlackHole 2ch"
    echo "      and your speakers, and set that as the system output."
  fi

  echo
  echo "What the app needs"
  if [ -f "$BUNDLE/timeline.json" ]; then
    local n; n=$("$PYBIN" -c "import json;print(len(json.load(open('$BUNDLE/timeline.json'))['cues']))" 2>/dev/null)
    ok "device bundle present, $n cues"
    if "$PYBIN" "$ROOT/pipeline/src/preflight.py" "$BUNDLE" >/dev/null 2>&1; then
      ok "bundle passes preflight"
    else
      bad "bundle FAILS preflight — do not film it. Run:"
      echo "      $PYBIN $ROOT/pipeline/src/preflight.py $BUNDLE"
    fi
  else
    bad "no bundle at $BUNDLE (/tmp gets cleaned). Rebuild — see submission/video-script.md"
  fi

  curl -s -m 2 -o /dev/null http://127.0.0.1:8190/state \
    && ok "companion service answering on 8190" \
    || bad "companion service not running — python3 companion/server.py"

  echo
  echo "Housekeeping"
  local free; free=$(df -g / | awk 'NR==2{print $4}')
  [ "$free" -gt 5 ] && ok "${free} GB free" || warn "only ${free} GB free"
  local pct; pct=$(pmset -g batt | grep -o '[0-9]*%' | head -1)
  echo "  • battery $pct — plug in, a throttled machine drops frames"
  echo "  • silence notifications: Focus on, and quit Mail, Slack, Messages"
  echo "  • the mark, the film and the HUD all need to be legible at 1080p"

  echo
  [ "${FAILED:-0}" -eq 0 ] && echo "Ready to record." || echo "Fix the ✗ items first."
  return "${FAILED:-0}"
}

record() {
  check || { echo; read -r -p "Record anyway? [y/N] " a; [ "$a" = "y" ] || exit 1; }
  local aid; aid="$(audio_device_id)"
  local audio_in="${aid:-0}"
  [ -z "$aid" ] && warn "recording microphone audio, not system audio"

  echo
  echo "Recording to $OUT"
  echo "Press ctrl-C to stop. Give it two seconds of silence before you start talking."
  echo
  # 30fps is plenty for a UI demo and keeps the file manageable. Audio is
  # captured at 48k to match what Polly and the device produce.
  ffmpeg -hide_banner -loglevel warning \
    -f avfoundation -capture_cursor 1 -framerate 30 -i "1:${audio_in}" \
    -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p \
    -c:a aac -b:a 192k -ar 48000 \
    "$OUT"
  echo
  echo "Saved $OUT"
  ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$OUT" 2>/dev/null | sed 's/^/  /'
}

case "${1:-check}" in
  check)  check ;;
  record) record ;;
  *) echo "usage: $0 [check|record]"; exit 1 ;;
esac
