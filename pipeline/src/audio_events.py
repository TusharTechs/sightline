#!/usr/bin/env python3
"""
What did the viewer already HEAR?

From the ADP list, and it is the tie-break for film:

    "The change I can't hear beats the change I can. The soundtrack is already
     doing half your job... Spend the gap on what's silent."

Until this existed the film path looked only at the picture, so it could not
tell a silent change from one the audience already had. This does not identify
sounds — it is not a semantic soundtrack model — it detects that something
audible happened, and when. That is weaker than knowing a door slammed, but it
is enough to answer "was this change accompanied by a noise, or was it silent?"

Method: short-time RMS, then onsets where energy jumps sharply above the recent
local level. Music that swells gradually does not produce onsets; impacts,
footfalls and slams do.
"""
import argparse, json, os, subprocess, sys, tempfile
import numpy as np

SR = 16000
FRAME_MS = 20
# An onset is this many dB above the trailing median of the last ~400ms.
ONSET_DB = 7.0
# Don't report two onsets closer together than this.
MIN_SEPARATION_S = 0.12


def load_mono(media, start, end):
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
             "-to", f"{end:.3f}", "-i", media, "-vn", "-ac", "1", "-ar", str(SR),
             "-f", "wav", wav], check=True)
        import wave
        with wave.open(wav) as w:
            raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0


def analyse(media, start, end):
    x = load_mono(media, start, end)
    if x.size == 0:
        return {"window": [start, end], "onsets": [], "level_db": -120.0,
                "character": "silent"}

    n = int(SR * FRAME_MS / 1000)
    frames = x[: (x.size // n) * n].reshape(-1, n)
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms)

    look = max(3, int(400 / FRAME_MS))
    onsets = []
    for i in range(look, db.size):
        local = np.median(db[i - look:i])
        rise = db[i] - local
        if rise >= ONSET_DB:
            t = start + i * FRAME_MS / 1000
            # Carry how sharp the rise was, so the caller can spend a limited
            # budget of frame checks on the sounds most likely to matter.
            if onsets and t - onsets[-1]["t"] < MIN_SEPARATION_S:
                if rise > onsets[-1]["rise_db"]:
                    onsets[-1] = {"t": round(t, 2), "rise_db": round(rise, 1)}
            else:
                onsets.append({"t": round(t, 2), "rise_db": round(rise, 1)})

    level = float(np.median(db))
    spread = float(db.max() - np.median(db))
    if level < -50:
        character = "silent"
    elif not onsets and spread < 8:
        character = "continuous (music or ambience, no distinct events)"
    elif onsets:
        character = f"{len(onsets)} distinct sound event(s)"
    else:
        character = "continuous with some variation"

    return {"window": [round(start, 3), round(end, 3)],
            "onsets": onsets, "level_db": round(level, 1),
            "character": character}


def loudest(onsets, n):
    """The n sharpest onsets, in time order. Checking whether a sound has a
    visible cause costs a model call, so the budget goes to the sounds a viewer
    is most likely to have noticed."""
    top = sorted(onsets, key=lambda o: -o["rise_db"])[:n]
    return sorted(top, key=lambda o: o["t"])


def describe_for_prompt(info, dialogue="", checked=None):
    """Plain-language evidence for the model.

    `checked` is a list of {t, visible_cause, what} for onsets that were examined
    against the picture. The distinction matters more than the presence of sound:
    a noise that explains itself is already understood, while a noise with
    nothing on screen to account for it is an open question the viewer cannot
    resolve without being told.
    """
    bits = [f"Soundtrack in this stretch: {info['character']}."]

    unexplained = [c for c in (checked or []) if not c["visible_cause"]]
    explained = [c for c in (checked or []) if c["visible_cause"]]

    if unexplained:
        times = ", ".join(f"{c['t']}s" for c in unexplained)
        bits.append(
            f"IMPORTANT — audible event(s) at {times} with NOTHING VISIBLE to "
            f"account for them. The viewer heard something and cannot tell what. "
            f"That is the highest-value thing you can describe here. Say that "
            f"something happened out of shot; do NOT guess what it was.")
    if explained:
        times = ", ".join(f"{c['t']}s ({c['what']})" for c in explained)
        bits.append(
            f"Audible event(s) at {times} WITH a visible cause — the viewer has "
            f"already worked those out. Not worth spending words on.")
    if not checked and info["onsets"]:
        bits.append("Audible events occurred but were not checked against the "
                    "picture.")
    if not info["onsets"]:
        bits.append("No distinct audible events — anything that changed on screen "
                    "here was silent, and the viewer has no other way to know it.")

    if dialogue.strip():
        bits.append(f'Dialogue spoken: "{dialogue}" — do not repeat it.')
    else:
        bits.append("No dialogue spoken in this stretch.")
    return " ".join(bits)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("media")
    p.add_argument("--start", type=float, required=True)
    p.add_argument("--end", type=float, required=True)
    a = p.parse_args()
    info = analyse(a.media, a.start, a.end)
    print(json.dumps(info, indent=2))
    print("\n" + describe_for_prompt(info), file=sys.stderr)


if __name__ == "__main__":
    main()
