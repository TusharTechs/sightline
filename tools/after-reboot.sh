#!/usr/bin/env bash
#
# Put back everything a restart wipes, then say what is left to do by hand.
#
# The device bundle, the source clip and the gh-pages worktree all live in
# /tmp, which macOS clears on boot. That has already caught this project
# twice. ~/Documents/sightline-media holds the copies.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAVED="$HOME/Documents/sightline-media"
PYBIN="$ROOT/pipeline/.venv/bin/python"
ok()  { printf "  \033[32m✓\033[0m %s\n" "$1"; }
bad() { printf "  \033[31m✗\033[0m %s\n" "$1"; }

echo "Restoring what the reboot cleared"

if [ -d "$SAVED/device-bundle" ]; then
  rm -rf /tmp/sightline-serve
  cp -R "$SAVED/device-bundle" /tmp/sightline-serve && ok "device bundle back at /tmp/sightline-serve"
else
  bad "no saved bundle at $SAVED/device-bundle"
fi

for f in sintel-seg.mp4 duckandcover.mp4; do
  [ -f "$SAVED/$f" ] && cp "$SAVED/$f" "/tmp/$f" && ok "$f back at /tmp/$f"
done

# The published-site worktree is disposable — rebuild it from the branch.
if [ ! -d /tmp/ghp ]; then
  git -C "$ROOT" worktree prune
  git -C "$ROOT" worktree add /tmp/ghp gh-pages >/dev/null 2>&1 \
    && ok "gh-pages worktree recreated at /tmp/ghp" \
    || bad "could not recreate the gh-pages worktree"
else
  ok "gh-pages worktree already present"
fi

echo
echo "Checking the bundle before you rely on it"
if "$PYBIN" "$ROOT/pipeline/src/preflight.py" /tmp/sightline-serve \
     --gaps "$ROOT/pipeline/out/sintel-seg-gaps.json" 2>/dev/null | tail -2 | grep -q passed; then
  ok "bundle passes preflight"
else
  bad "bundle does not pass — see submission/video-script.md to rebuild"
fi

echo
echo "Still yours to do, in this order:"
cat <<'TXT'
  1. Audio MIDI Setup  ->  +  ->  Multi-Output Device
       tick BlackHole 2ch AND your speakers,
       then set that device as the system output.
       (Without this the recorder still gets only the microphone.)

  2. Start the companion service, and leave it running:
       SIGHTLINE_BUNDLE=/tmp/sightline-serve pipeline/.venv/bin/python companion/server.py

  3. Bring up the device and the app:
       vega virtual-device start
       vega device install-app -p app/build/aarch64-debug/sightline_aarch64.vpkg
       vega device launch-app -a com.sightline.tv.main

  4. Phone on the same wifi:  http://192.168.1.10:8190/   -> "Follow a Fire TV instead"

  5. tools/record-demo.sh check
TXT
