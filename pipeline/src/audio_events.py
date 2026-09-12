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
        if db[i] - local >= ONSET_DB:
            t = start + i * FRAME_MS / 1000
            if not onsets or t - onsets[-1] >= MIN_SEPARATION_S:
                onsets.append(round(t, 2))

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


def describe_for_prompt(info, dialogue=""):
    """Plain-language evidence for the model."""
    bits = [f"Soundtrack in this stretch: {info['character']}."]
    if info["onsets"]:
        times = ", ".join(f"{t}s" for t in info["onsets"][:8])
        bits.append(
            f"Audible events at {times} — a visual change at one of those moments "
            f"was probably HEARD by the viewer and is worth less than a silent one.")
    else:
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
