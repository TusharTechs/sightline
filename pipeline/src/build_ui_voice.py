#!/usr/bin/env python3
"""
The app's own voice.

Sightline is for people who cannot see the screen, so it cannot rely on a HUD
to say what mode it is in — and it must not rely on the platform screen reader
either, because VoiceView cannot currently be enabled on the virtual device at
all (FRICTION-LOG FL-011) and may simply be off on a real one.

So the app self-voices. Every control speaks its result, and the app announces
itself on startup. Phrases are synthesised here and shipped as PCM with the
bundle, so the device never needs a text-to-speech engine and a confirmation
never waits on the network.

Same voice as the description, deliberately. A second voice for the interface
would be one more thing to learn.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from speech import synthesize

# Short. These are confirmations, not explanations — the user pressed a button
# and needs to know it took, not to be taught the feature again.
PHRASES = {
    "ready":          "Sightline ready.",
    # Startup must be short. The full controls list runs over twelve seconds,
    # and playing that across the opening of the film is exactly the mistake
    # this app exists to avoid. Point at it instead, and let them ask.
    "hint":           "Press Menu at any time to hear the controls.",
    "playing":        "Playing.",
    "paused":         "Paused.",
    "rate_1":         "Normal speed.",
    "rate_15":        "One and a half times speed.",
    "rate_2":         "Double speed.",
    "mode_fit":       "Fitting descriptions into gaps.",
    "mode_pause":     "Pausing to describe.",
    "target_tv":      "Description on this television.",
    "target_phone":   "Description on your phone only.",
    "ended":          "Finished.",
    # Generation. Spoken as each stage begins — a progress bar is no use to
    # someone who cannot see it, and half a minute of silence reads as a hang.
    "undescribed":    "This video has no audio description. Press Select to create one.",
    "gen_listening":  "Listening for dialogue.",
    "gen_watching":   "Watching what changes.",
    "gen_ranking":    "Ranking what matters most.",
    "gen_voicing":    "Preparing the voice.",
    "gen_ready":      "Description ready. Starting.",
    "gen_failed":     "Could not describe this video.",
    "error":          "Something went wrong. Check the companion service.",
    # Spoken on demand, and once at startup, because a blind user has no way to
    # discover the controls otherwise.
    "help": ("Select plays or pauses. "
             "Right changes speed. "
             "Up switches between fitting descriptions into gaps and pausing to describe. "
             "Down moves description to your phone. "
             "Menu repeats this."),
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="bundle directory")
    p.add_argument("--prefix", default="ui-")
    a = p.parse_args()

    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "ui-voice.json")

    # These phrases never change between runs, and re-rendering all of them —
    # the controls list alone is nearly thirteen seconds — was most of the wait
    # when regenerating a bundle. Only synthesise what is missing or reworded.
    previous = {}
    if os.path.exists(path):
        try:
            previous = json.load(open(path))
        except Exception:
            previous = {}

    manifest, made, kept = {}, 0, 0
    for key, text in PHRASES.items():
        name = f"{a.prefix}{key}.pcm"
        old = previous.get(key)
        if old and old.get("text") == text and os.path.exists(os.path.join(a.out, name)):
            manifest[key] = old
            kept += 1
            continue
        meta = synthesize(text, os.path.join(a.out, name))
        manifest[key] = {"pcm": name, "text": text, "duration": meta["duration_s"]}
        made += 1
        print(f"  {key:<14} {meta['duration_s']:>5}s  {text[:58]}", file=sys.stderr)
    if kept:
        print(f"  reused {kept} unchanged phrase(s)", file=sys.stderr)

    json.dump(manifest, open(path, "w"), indent=2)
    print(f"\n{len(manifest)} phrases ({made} rendered) -> {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
