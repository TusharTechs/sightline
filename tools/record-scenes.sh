#!/usr/bin/env bash
#
# Record the scenes that can be recorded without a human in the loop.
#
#   tools/record-scenes.sh list      what this can and cannot film, and why
#   tools/record-scenes.sh check     preconditions
#   tools/record-scenes.sh 1         the gap  — film playing, description off
#   tools/record-scenes.sh 3         hear it  — the same passage, described
#   tools/record-scenes.sh 4tv       the television half of the co-viewing beat
#   tools/record-scenes.sh 5         quiet plate for the evidence section
#   tools/record-scenes.sh 2         generation — undescribed, Select, stages
#   tools/render-scenes.sh all       1, 3, 4tv, 5, then 2 last
#
# Takes land in ~/Desktop/sightline-takes/ as scene-N-<time>.mov. Nothing is
# ever overwritten, so run a scene as many times as you like and pick the best
# one in the edit.
#
# THESE ARE PICTURE AND DEVICE AUDIO ONLY. No voiceover — you record that
# separately over the top. What the app itself says (the stage names, the
# descriptions, the answer) IS captured, because it has to be in sync.
#
# How it drives the device, and why that way: the Vega CLI has no input
# command, and the companion's /KEY/ endpoint only logs what the app already
# received — it cannot send anything. So presses go to the device window as
# real keystrokes via System Events, which needs Accessibility permission.
# Verified working: a synthetic Right changes the rate the app reports back.
#
# The app has no seek control, so there is no way to jump to the 88s passage.
# Instead this polls the position the app posts to the companion and starts
# the recorder when the playhead is nearly there. That is why scene 1 takes a
# minute and a half to produce twelve seconds.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE="${SIGHTLINE_BUNDLE:-/tmp/sightline-serve}"
TAKES="${SIGHTLINE_TAKES:-$HOME/Desktop/sightline-takes}"
HOST="${SIGHTLINE_HOST:-http://127.0.0.1:8190}"
APP="${SIGHTLINE_APP:-com.sightline.tv.main}"
WIN="${SIGHTLINE_WINDOW:-vega-virtual-device}"
SCREEN_DEV="${SIGHTLINE_SCREEN_DEV:-1}"
PYBIN="$ROOT/pipeline/.venv/bin/python"

# macOS virtual key codes.
K_RETURN=36; K_LEFT=123; K_RIGHT=124; K_DOWN=125; K_UP=126

ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$1"; FAILED=1; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }
say()  { printf "\033[1m%s\033[0m\n" "$1"; }

# ---------------------------------------------------------------- device state

state() { curl -s -m 2 "$HOST/state" 2>/dev/null; }

# field <name> — one value out of /state. 'mode' is the audio target
# ('tv'/'phone'), not the fit/pause mode; that is what the app posts.
field() {
  state | "$PYBIN" -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: print(''); raise SystemExit
v=d.get('$1')
print('' if v is None else v)
" 2>/dev/null
}

# The companion keeps the last position it was told, and nothing clears it
# when the app exits. So 'playing:true' can be a reading from a session that
# ended minutes ago -- the first run of this rolled at 185s while waiting for
# 60s, because it trusted a stale value. /state carries 'age'; anything older
# than a couple of seconds is a ghost.
fresh() {
  local age; age="$(field age)"
  [ -n "$age" ] && (( $(echo "$age < 2.5" | bc -l) ))
}

app_running() { vega device is-app-running -a "$APP" 2>/dev/null | grep -qv "is not running"; }

relaunch() {
  say "  restarting the app so the playhead is back at zero"
  vega device terminate-app -a "$APP" >/dev/null 2>&1
  sleep 2
  vega device launch-app -a "$APP" >/dev/null 2>&1
  local i t
  for i in $(seq 1 60); do
    t="$(field t)"
    # Fresh, playing, and near the start -- all three, or it is the old session.
    if fresh && [ "$(field playing)" = "True" ] && [ -n "$t" ] \
       && (( $(echo "$t < 12" | bc -l) )); then
      ok "playing from the top"
      sleep 1
      return 0
    fi
    sleep 1
  done
  bad "the app never started playing — is the companion serving a timeline?"
  return 1
}

# ---------------------------------------------------------------- key presses

press() {
  osascript >/dev/null 2>&1 \
    -e "tell application \"System Events\" to tell process \"$WIN\" to set frontmost to true" \
    -e "delay 0.5" \
    -e "tell application \"System Events\" to key code $1"
  sleep 1.2
}

# The app speaks whenever the target changes, so move it well before rolling.
ensure_target() {
  local want="$1" have
  have="$(field mode)"
  if [ "$have" != "$want" ]; then
    say "  moving description to '$want' (it announces this; doing it early)"
    press $K_DOWN
    sleep 4
    have="$(field mode)"
  fi
  [ "$have" = "$want" ] && ok "description target: $want" \
                        || warn "target is '$have', wanted '$want'"
}

# ---------------------------------------------------------------- the window

# Window geometry is in points; the capture is in pixels. Measure the ratio
# rather than assuming 2 — an external display is not necessarily Retina.
scale_factor() {
  local shot px pt
  shot="$(mktemp -t sl).png"
  screencapture -x -t png "$shot" 2>/dev/null
  px=$(sips -g pixelWidth "$shot" 2>/dev/null | awk '/pixelWidth/{print $2}')
  rm -f "$shot"
  pt=$(osascript -e 'tell application "Finder" to get bounds of window of desktop' 2>/dev/null \
       | awk -F', *' '{print $3}')
  [ -n "$px" ] && [ -n "$pt" ] && [ "$pt" -gt 0 ] \
    && echo $(( px / pt )) || echo 2
}

# The process owns more than one window: window 1 is a small unnamed panel,
# and the screen itself is the big one. Picking by index captures a 61x251
# sliver, so pick the largest window instead — that survives the panel coming
# and going, and any renaming.
win_geom() {
  osascript -e "tell application \"System Events\" to tell process \"$WIN\"
set out to \"\"
repeat with w in windows
  set p to position of w
  set z to size of w
  set out to out & ((item 1 of p) as string) & \" \" & ((item 2 of p) as string) & \" \" & ((item 1 of z) as string) & \" \" & ((item 2 of z) as string) & linefeed
end repeat
return out
end tell" 2>/dev/null | awk 'NF==4 && $3*$4 > best { best=$3*$4; line=$0 } END { print line }'
}

crop_rect() {
  local s; s="$(scale_factor)"
  win_geom | awk -v s="$s" '{
    x=$1*s; y=$2*s; w=$3*s; h=$4*s;
    if (w%2) w--; if (h%2) h--;        # x264 will not take odd dimensions
    print w":"h":"x":"y
  }'
}

audio_device_id() {
  ffmpeg -f avfoundation -list_devices true -i "" 2>&1 \
    | awk '/AVFoundation audio devices/,0' \
    | grep -iE "blackhole|loopback|aggregate|multi-?output" \
    | head -1 | sed -E 's/.*\[([0-9]+)\].*/\1/'
}

# The crop is a fixed rectangle of the screen, so whatever is on top at those
# coordinates is what gets recorded. The first test of this captured a browser
# window sitting over the device. Bring the device forward and let the window
# server settle before measuring or rolling.
focus_window() {
  osascript >/dev/null 2>&1 \
    -e "tell application \"System Events\" to tell process \"$WIN\" to set frontmost to true"
  sleep 1
}

# Which device macOS is actually playing through.
default_output() {
  system_profiler SPAudioDataType 2>/dev/null | awk '
    /^ {8}[A-Za-z].*:$/ { s=$0; gsub(/^ +/,"",s); gsub(/ *:$/,"",s); dev=s }
    /Default Output Device: Yes/ { print dev; exit }'
}

# Prove sound actually ARRIVES, rather than that a device exists.
#
# The old check passed as long as something BlackHole-shaped showed up in the
# input list. It does not follow that anything is routed to it: installing
# BlackHole creates the device but changes no routing, so system audio keeps
# going to the speakers and the capture is digital silence. That green tick
# cost a six-minute take that came back at -91 dB. This plays a sound and
# listens for it.
audio_reaches_recorder() {
  local aid probe mean ff
  aid="$(audio_device_id)"
  if [ -z "$aid" ]; then
    bad "no system-audio capture device — install BlackHole (brew install blackhole-2ch)"
    return 1
  fi
  # Generate the test sound rather than using a system one. Ping.aiff is a
  # third of a second long and macOS routes alert sounds by their own output
  # setting, so it could miss the capture window or never reach the device at
  # all -- which reported a correctly-routed Multi-Output as silent. A tone of
  # known length and level cannot be missed.
  local tone
  tone="$(mktemp -t sltone).wav"
  probe="$(mktemp -t slaud).wav"
  ffmpeg -hide_banner -v error -f lavfi -i "sine=frequency=440:duration=2" \
    -ar 48000 -ac 2 -y "$tone" 2>/dev/null
  ffmpeg -hide_banner -v error -f avfoundation -i ":$aid" -t 3 -y "$probe" </dev/null 2>/dev/null &
  ff=$!
  sleep 0.5
  afplay "$tone" 2>/dev/null
  wait "$ff" 2>/dev/null
  rm -f "$tone"
  mean="$(ffmpeg -hide_banner -i "$probe" -af volumedetect -f null - 2>&1 \
          | awk -F': ' '/mean_volume/{print $2}' | tr -d ' dB')"
  rm -f "$probe"
  if [ -z "$mean" ] || (( $(echo "${mean:--91} < -80" | bc -l) )); then
    bad "capture device is SILENT — your audio is not routed to it"
    echo "      playing through: $(default_output)"
    echo "      Fix, either way:"
    echo "        • Audio MIDI Setup -> + -> Multi-Output Device -> tick BlackHole 2ch"
    echo "          AND your speakers -> set that device as the system output."
    echo "          (you hear the app and it records)"
    echo "        • or set the system output straight to BlackHole 2ch"
    echo "          (it records, you hear nothing while filming)"
    return 1
  fi
  ok "sound reaches the recorder (${mean} dB, via $(default_output))"
}

# capture <name> <seconds> [keycode] [press-after-seconds]
#
# The press is sequenced against the recorder actually writing, not against a
# timer started alongside it. A background ( sleep 4; press ) raced ffmpeg's
# startup and the button never made it into the take -- the app's reported
# target was unchanged afterwards, which is how it was caught.
capture() {
  local name="$1" dur="$2" key="${3:-}" after="${4:-0}" rect aid out ff i
  focus_window
  rect="$(crop_rect)"
  [ -z "$rect" ] && { bad "cannot find the '$WIN' window"; return 1; }
  aid="$(audio_device_id)"
  [ -z "$aid" ] && warn "no system-audio device — this take will have microphone audio"
  mkdir -p "$TAKES"
  out="$TAKES/scene-${name}-$(date +%H%M%S).mov"

  printf "  \033[36m● recording %ss\033[0m -> %s\n" "$dur" "${out##*/}"
  printf "    do not click anything — a window moved on top lands in the take\n"
  ffmpeg -hide_banner -loglevel error \
    -f avfoundation -capture_cursor 0 -pixel_format uyvy422 \
    -i "${SCREEN_DEV}:${aid:-0}" \
    -t "$dur" \
    -vf "crop=${rect},scale=1920:-2,fps=30" \
    -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p \
    -c:a aac -b:a 192k -ar 48000 \
    "$out" </dev/null 2>/dev/null &
  ff=$!

  # Only start counting once there are bytes on disk.
  if [ -n "$key" ] || [ -n "${ON_START:-}" ]; then
    for i in $(seq 1 60); do [ -s "$out" ] && break; sleep 0.25; done
  fi

  # Anything that has to happen ON CAMERA from its first frame goes here, not
  # before the call. Fronting the window and measuring the crop takes about
  # four and a half seconds, so an app launched beforehand is already talking
  # by the time ffmpeg opens the file -- the spoken offer came out clipped to
  # its last 1.6 seconds that way.
  if [ -n "${ON_START:-}" ]; then
    eval "$ON_START"
  fi

  if [ -n "$key" ]; then
    sleep "$after"
    press "$key"
    ok "pressed (key $key)"
  fi
  wait "$ff"

  # The crop is a fixed screen rectangle, so anything brought forward over the
  # device lands in the take and nothing complains. Two takes here were quietly
  # a browser window. Check who ended up on top.
  local front
  front="$(osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true' 2>/dev/null)"
  if [ -n "$front" ] && [ "$front" != "$WIN" ]; then
    bad "'$front' was in front when this ended — the take is probably of that, not the device"
    echo "      Re-run it and leave the machine alone while the ● is showing."
  fi

  if [ -s "$out" ]; then
    ok "saved ${out##*/} ($(ffprobe -v error -show_entries format=duration \
        -of default=nw=1:nk=1 "$out" 2>/dev/null | cut -d. -f1)s)"
  else
    bad "nothing was written — check Screen Recording permission"
  fi
}

# Wait for the playhead to approach <t>, leaving <lead> seconds for ffmpeg to
# come up. Restarts the app if the passage has already gone by.
cue_to() {
  local target="$1" lead="${2:-3}" t
  t="$(field t)"
  [ -z "$t" ] && { bad "no position from the app — is it running?"; return 1; }
  # Stale, or already past the passage: start it over.
  if ! fresh || (( $(echo "$t > $target - $lead" | bc -l) )); then
    relaunch || return 1
  fi
  say "  waiting for the playhead to reach ${target}s"
  while :; do
    t="$(field t)"
    [ -z "$t" ] && { bad "lost contact with the app"; return 1; }
    fresh || { printf "\r    position went stale — did the app quit?\n"; return 1; }
    (( $(echo "$t >= $target - $lead" | bc -l) )) && break
    printf "\r    at %.0fs" "$t"
    sleep 1
  done
  printf "\r    at %.0fs — rolling\n" "$t"
}

# Scenes 1 and 5 need the film with NO description on screen. Moving the audio
# to the phone is not enough: the caption is set inside the scheduler's speak()
# and appears on the television whatever the audio target is. The first scene-1
# take proved it -- the frame at 91s carried "She stares down at the collapsed
# creature", which hands a sighted judge the very thing the cold open is meant
# to withhold.
#
# The undescribed phase does not play video at all (boot returns before
# player.play() when there is no timeline), so it cannot be filmed either.
# What works is the real app playing the real film against an empty cue list,
# which is exactly what undescribed content is.
bare_timeline_on() {
  [ -f "$BUNDLE/timeline.json.real" ] && return 0     # already swapped
  cp "$BUNDLE/timeline.json" "$BUNDLE/timeline.json.real" || return 1
  "$PYBIN" - "$BUNDLE" <<'PYEOF'
import json, os, sys
b = sys.argv[1]
d = json.load(open(os.path.join(b, "timeline.json.real")))
d["cues"] = []
json.dump(d, open(os.path.join(b, "timeline.json"), "w"))
PYEOF
  ok "no cues: the film plays, nothing is described or captioned"
  warn "if a phone is following right now, reload it when this scene finishes."
  echo "      The phone calls loadTimeline once and returns early ever after"
  echo "      ('if (timeline) return'), so a phone that connects during this"
  echo "      scene caches an empty cue list. It keeps tracking the playhead"
  echo "      perfectly and never says anything, which does not look like a"
  echo "      caching problem at all."
}

bare_timeline_off() {
  if [ -f "$BUNDLE/timeline.json.real" ]; then
    mv "$BUNDLE/timeline.json.real" "$BUNDLE/timeline.json"
    ok "cues restored"
  fi
}

# prepare <audio-target> <cue-seconds>
#
# Always from the top, in this order. Setting the target first and letting
# cue_to restart the app afterwards silently undoes it -- the app boots with
# description on the television -- which would have sent scenes 1 and 5 out
# with description audible over a passage that is supposed to be bare.
prepare() {
  relaunch || return 1
  ensure_target "$1"
  cue_to "$2" 3
}

# ---------------------------------------------------------------- the scenes

scene_1() {
  say "Scene 1 · the gap — film playing, description off, 88–95s"
  echo "  Cold open. The judge hears something happen and cannot tell what."
  trap bare_timeline_off RETURN
  bare_timeline_on || return 1
  prepare phone 88 || return 1
  capture "1-gap" 14
}

scene_3() {
  say "Scene 3 · hear it — the identical passage, described"
  echo "  Must be the same stretch as scene 1 or the comparison does not land."
  prepare tv 85 || return 1        # description back on the television
  capture "3-described" 24
}

scene_4tv() {
  say "Scene 4 · the television half — description moves to the phone"
  echo "  The phone half is yours to film; this is the HUD flip and the TV audio."
  prepare tv 60 || return 1
  capture "4tv-handoff" 18 "$K_DOWN" 4     # pressed on camera, not before
}

scene_5() {
  say "Scene 5 · quiet plate — film running, nothing spoken over it"
  echo "  75 seconds for the evidence voiceover to sit on top of."
  trap bare_timeline_off RETURN
  bare_timeline_on || return 1
  prepare phone 105 || return 1
  capture "5-plate" 75
}

# Scene 2 is last and separate: it is the only one that changes the bundle.
scene_2() {
  say "Scene 2 · generation — the undescribed state, Select, and the stages"
  echo
  warn "This one really runs generation. It costs a little (Transcribe + Polly"
  echo "      + model) and takes 2–4 minutes, and it OVERWRITES timeline.json"
  echo "      and the desc-*.pcm files in the bundle."
  echo "      A snapshot is taken first and restored afterwards, so the cue"
  echo "      lines quoted in the shooting script survive."
  echo
  read -r -p "  Go ahead? [y/N] " a
  [ "$a" = "y" ] || { echo "  skipped."; return 0; }

  local snap="$TAKES/bundle-snapshot-$(date +%H%M%S)"
  mkdir -p "$snap"
  cp "$BUNDLE/timeline.json" "$snap/" 2>/dev/null
  cp "$BUNDLE"/desc-*.pcm "$snap/" 2>/dev/null
  ok "snapshot in ${snap##*/}"

  # No timeline means the app offers to make one, which is the state we film.
  mv "$BUNDLE/timeline.json" "$BUNDLE/timeline.json.held" 2>/dev/null
  say "  booting it with nothing to play"
  vega device terminate-app -a "$APP" >/dev/null 2>&1
  sleep 2

  # Launch from inside the take, so the offer is spoken on camera.
  # Select at 9s after launch: after the offer finishes, with a beat.
  ON_START="vega device launch-app -a $APP >/dev/null 2>&1" \
    capture "2-generation" 62 "$K_RETURN" 9

  say "  letting generation finish before putting the bundle back"
  local i st
  for i in $(seq 1 160); do
    st="$(curl -s -m 2 "$HOST/generate/status" 2>/dev/null \
          | "$PYBIN" -c "import json,sys;print(json.load(sys.stdin).get('stage',''))" 2>/dev/null)"
    printf "\r    %-28s" "${st:-…}"
    case "$st" in ready|failed) break;; esac
    sleep 3
  done
  echo

  rm -f "$BUNDLE/timeline.json.held"
  cp "$snap"/timeline.json "$BUNDLE/" 2>/dev/null
  cp "$snap"/desc-*.pcm "$BUNDLE/" 2>/dev/null
  ok "bundle restored from the snapshot"

  if "$PYBIN" "$ROOT/pipeline/src/preflight.py" "$BUNDLE" >/dev/null 2>&1; then
    ok "restored bundle passes preflight"
  else
    bad "restored bundle FAILS preflight — do not film anything else until you look"
  fi
}

# ---------------------------------------------------------------- check / list

check() {
  FAILED=0
  say "Tools"
  command -v ffmpeg >/dev/null && ok "ffmpeg" || bad "ffmpeg missing — brew install ffmpeg"
  command -v vega   >/dev/null && ok "vega CLI" || bad "vega CLI not on PATH"
  command -v bc     >/dev/null && ok "bc" || bad "bc missing"

  say "Permissions"
  if [ -n "$(win_geom)" ]; then
    ok "Accessibility — this terminal can press keys on the device"
  else
    bad "no Accessibility permission, or the device window is not open."
    echo "      System Settings -> Privacy & Security -> Accessibility, add your"
    echo "      terminal, then quit and reopen it. Without this, nothing can be"
    echo "      pressed and every scene here fails."
  fi

  say "Device"
  if vega virtual-device status 2>/dev/null | grep -q '"running":true'; then
    ok "virtual device running"
  else
    bad "virtual device is not running — vega virtual-device start"
  fi
  local rect; rect="$(crop_rect)"
  [ -n "$rect" ] && ok "window found, cropping to $rect" || bad "cannot measure the device window"

  say "What the app needs"
  if [ -f "$BUNDLE/timeline.json" ]; then
    local n; n=$("$PYBIN" -c "import json;print(len(json.load(open('$BUNDLE/timeline.json'))['cues']))" 2>/dev/null)
    ok "bundle present, $n cues"
    "$PYBIN" "$ROOT/pipeline/src/preflight.py" "$BUNDLE" >/dev/null 2>&1 \
      && ok "passes preflight" || bad "FAILS preflight — do not film it"
  else
    bad "no bundle at $BUNDLE — tools/after-reboot.sh"
  fi
  [ -n "$(state)" ] && ok "companion answering" \
    || bad "companion not running — $PYBIN companion/server.py"

  say "Audio"
  audio_reaches_recorder

  echo
  [ "${FAILED:-0}" -eq 0 ] && say "Ready." || say "Fix the ✗ items first."
  return "${FAILED:-0}"
}

# Is the phone actually following the television?
#
# There is no registration step to look up: the phone just polls /state. So
# ask the three questions separately -- can the phone reach the companion at
# all, is the television posting a live position, and is anything other than
# this Mac connected. 'playing:true' on its own means nothing, because that
# reading survives the app exiting.
pair() {
  local ip url age playing t found peers i

  say "Companion"
  ip="$(ipconfig getifaddr en0 2>/dev/null)"
  if [ -z "$ip" ]; then
    bad "this Mac has no address on en0 — is wifi on?"
  else
    url="http://$ip:8190/"
    if curl -s -m 3 -o /dev/null "$url"; then
      ok "reachable at $url"
      echo "      open exactly that on the phone, then press 'Follow a Fire TV instead'"
    else
      bad "not answering on $url — is companion/server.py running?"
    fi
  fi

  say "Television"
  age="$(field age)"; playing="$(field playing)"; t="$(field t)"
  if [ -z "$age" ]; then
    bad "the companion has never heard from the app"
  elif ! fresh; then
    bad "last position was ${age}s ago — the app is not running"
    echo "      a stale reading still says playing:${playing}; ignore it"
    echo "      vega device launch-app -a $APP"
  elif [ "$playing" = "True" ]; then
    ok "playing, ${t}s in (${age}s ago)"
  else
    warn "app is up but paused at ${t}s — press Select on the device"
  fi

  say "Phone"
  for i in $(seq 1 8); do
    peers="$(lsof -nP -iTCP:8190 2>/dev/null | grep ESTABLISHED | grep -v 127.0.0.1 | awk '{print $9}')"
    [ -n "$peers" ] && { found="$peers"; break; }
    sleep 1
  done
  if [ -n "$found" ]; then
    ok "something other than this Mac is connected:"
    echo "$found" | sed 's/->.*//' | sort -u | sed 's/^/        /'
    echo "      on the phone the button should read 'Following the television'"
  else
    bad "no phone connected in 8 seconds"
    echo "      same wifi? opened the address above, not the GitHub Pages site?"
    echo "      the hosted pages are standalone and never follow a television."
  fi
}

list() {
  cat <<'TXT'

CAN be filmed by this script
  1     the gap          film playing, description off, across 88–95s
  3     hear it          the same passage with description on
  4tv   the handoff      the HUD flipping description over to the phone
  5     quiet plate      75s of film running, nothing spoken, for voiceover
  2     generation       undescribed state, Select, the stages speaking
                         (runs real generation; snapshots and restores)

CANNOT — these need you
  the phone screen       a physical phone; film it yourself, then cut between
  the spoken question    your voice into the phone's microphone
  all voiceover          every "Say" line in the shooting script
  the mark / end card    made in the edit, not on the device
  captioned evidence     the three-row table; that is a graphic

WHY those five and not more
  The app exposes five remote keys and no seek, so anything needing a
  particular moment is reached by waiting for the playhead, not jumping to it.
  Anything involving a second physical device, or a human voice, is outside
  what a script can press.

TXT
}

case "${1:-list}" in
  list)  list ;;
  check) check ;;
  pair)  pair ;;
  1)     check >/dev/null; scene_1 ;;
  2)     scene_2 ;;
  3)     scene_3 ;;
  4tv)   scene_4tv ;;
  5)     scene_5 ;;
  all)   check || exit 1; echo; scene_1; echo; scene_3; echo; scene_4tv; echo; scene_5; echo; scene_2 ;;
  *) echo "usage: $0 [list|check|pair|1|2|3|4tv|5|all]"; exit 1 ;;
esac
