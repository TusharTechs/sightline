#!/usr/bin/env python3
"""
Can a listener actually hear the difference the code claims to make?

The code sorts onsets into hits and swells. That sorting is only worth having
if the distinction is real, and the only way to find out is to play people the
audio without telling them which is which.

A first attempt at this asked the wrong question. Nine swells were played one
at a time to a listener who had been told a sound was in each, and all nine
came back as "something arrived" -- which says nothing about the audio, because
a primed listener hearing an isolated four-second clip will call the loudest
thing in it an arrival every time. Detection cannot be the test.

So this builds a sorting test instead:

  - clips are only cut where no onset of the OPPOSITE class falls inside them,
    so a clip labelled "swell" cannot contain a hit
  - every clip is loudness-normalised, which removes size. The claim under test
    is that shape is audible independently of level, so level has to go
  - filenames are random. The answer key is written separately and should not
    be opened until the sorting is done

Usage:
    shape_test.py MEDIA --out DIR [--lead 2.5] [--tail 1.5]

Then sort the clips in DIR into two groups by ear, and only then read key.json.
"""
import argparse, json, os, random, subprocess, sys, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_events import analyse


def classify(o):
    if o.get("unsure"):
        return "unsure"
    return "hit" if o["transient"] else "swell"


def scan(media, duration, step=6.0):
    """Every onset in the file, with its class."""
    out, t = [], 0.0
    while t < duration:
        for o in analyse(media, t, min(t + step, duration))["onsets"]:
            out.append(o)
        t += step
    return out


def uncontaminated(onsets, lead, tail, min_gap):
    """Onsets that can be cut into a clip containing no onset of another class.

    Also drops clips that would overlap a previously chosen one, so the listener
    never hears the same passage twice and cannot match them up by content.
    """
    picked, last_end = [], -1e9
    for o in sorted(onsets, key=lambda o: o["t"]):
        k = classify(o)
        if k == "unsure":
            continue
        lo, hi = o["t"] - lead, o["t"] + tail
        if lo < 0:
            continue
        if any(p is not o and lo <= p["t"] <= hi and classify(p) != k
               for p in onsets):
            continue
        if lo < last_end + min_gap:
            continue
        picked.append((o, k))
        last_end = hi
    return picked


def cut(media, t, lead, tail, dest):
    """One clip, loudness-normalised so that size cannot give the answer away."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t - lead:.3f}",
         "-t", f"{lead + tail:.3f}", "-i", media, "-vn",
         "-af", "loudnorm=I=-20:TP=-1.5:LRA=11", "-ac", "2", "-ar", "44100",
         dest], check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("media")
    p.add_argument("--out", required=True)
    p.add_argument("--lead", type=float, default=2.5)
    p.add_argument("--tail", type=float, default=1.5)
    p.add_argument("--min-gap", type=float, default=1.0)
    p.add_argument("--max-per-class", type=int, default=12)
    p.add_argument("--seed", type=int, default=None)
    a = p.parse_args()

    rng = random.Random(a.seed)
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", a.media],
        capture_output=True, text=True, check=True).stdout.strip())

    onsets = scan(a.media, dur)
    picked = uncontaminated(onsets, a.lead, a.tail, a.min_gap)
    by = {"hit": [], "swell": []}
    for o, k in picked:
        by[k].append(o)

    # Balanced, or the listener can win by guessing the majority class.
    n = min(len(by["hit"]), len(by["swell"]), a.max_per_class)
    if n < 5:
        print(f"  only {n} per class available -- too few to test. "
              f"hits={len(by['hit'])} swells={len(by['swell'])}", file=sys.stderr)
    chosen = ([(o, "hit") for o in rng.sample(by["hit"], min(n, len(by["hit"])))] +
              [(o, "swell") for o in rng.sample(by["swell"], min(n, len(by["swell"])))])
    rng.shuffle(chosen)

    os.makedirs(a.out, exist_ok=True)
    key = []
    for i, (o, k) in enumerate(chosen, 1):
        name = f"clip-{i:02d}-{uuid.uuid4().hex[:6]}.mp3"
        cut(a.media, o["t"], a.lead, a.tail, os.path.join(a.out, name))
        key.append({"file": name, "answer": k, "t": o["t"],
                    "attack_ms": o.get("attack_ms"),
                    "fell_1s_db": o.get("fell_1s_db"),
                    "fell_2s_db": o.get("fell_2s_db")})

    with open(os.path.join(a.out, "key.json"), "w") as f:
        json.dump(key, f, indent=2)
    print(f"  {len(chosen)} clips ({n} per class) -> {a.out}")
    print(f"  sort them into two groups by ear, THEN read {a.out}/key.json")
    print(f"  chance of a perfect sort by guessing: "
          f"1 in {_combinations(len(chosen), n)}")


def _combinations(total, k):
    from math import comb
    return comb(total, k) if total and k else 1


if __name__ == "__main__":
    main()
