#!/usr/bin/env python3
"""
Does the same film get the same answers twice?

From the ADP list reviewer, on a count of unresolved onsets that had just
dropped from 59 to 3:

    "Run the same fourteen minutes again with something changed that shouldn't
     matter. A different encode, the whole thing three decibels quieter,
     whatever you've got handy. Then line the labels up against the first run.
     Anything that flips was never being decided by the sound. It was being
     decided by where your threshold happened to land that day. A rule that's
     really measuring shape won't care."

Every perturbation here is one the classifier is supposed to be blind to. A
uniform gain change should be exactly invariant, because every quantity in the
rule is a difference between two levels: the rise over the trailing median, the
12 dB climb into the peak, the settle relative to the pre-onset floor. Shifting
all of them by the same amount should cancel. A lossy re-encode is not exactly
invariant -- it genuinely alters the waveform -- but it is inaudible, so
anything it flips was not being decided by what the sound is.

Two numbers come out. Label flips say how stable the rule is. Evidence changes
say how much of that instability reaches the description, which is the only
place it can do any harm.

Usage:
    stability.py MEDIA --gaps gaps.json
"""
import argparse, json, os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_events import analyse, describe_for_prompt

MATCH_S = 0.06          # two onsets this close are the same onset


def classify(o):
    if o.get("unsure"):
        return "unsure"
    return "hit" if o["transient"] else "swell"


def make_variants(media, workdir, duration):
    """The same audio, changed in ways that should not matter.

    Everything is 32-bit float. A first version of this used 16-bit and boosted
    by 6 dB, on material that already peaked at full scale, so the "louder"
    variant was clipped -- which flattens exactly the peaks the rule measures.
    That is a distorted signal, not an invariance test, and it produced flips
    that were real responses to real damage. Float leaves the headroom.
    """
    base = os.path.join(workdir, "base.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", media, "-vn",
                    "-ac", "1", "-ar", "48000", "-c:a", "pcm_f32le", base],
                   check=True)
    quiet = os.path.join(workdir, "quiet.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", base,
                    "-af", "volume=-3dB", "-c:a", "pcm_f32le", quiet], check=True)
    softer = os.path.join(workdir, "softer.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", base,
                    "-af", "volume=-9dB", "-c:a", "pcm_f32le", softer], check=True)
    recode = os.path.join(workdir, "recode.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", base,
                    "-b:a", "128k", recode], check=True)
    # Only attenuation. Boosting is not a usable invariance test here: this
    # film is mastered to full scale, and the reader quantises to 16-bit, so
    # any boost clips somewhere in the chain. A clipped signal is a different
    # sound -- flattened peaks are exactly what the rule measures -- so a flip
    # under boost says nothing about the rule.
    return [("3 dB quieter", quiet), ("9 dB quieter", softer),
            ("re-encoded to 128k mp3", recode)], base


def scan(media, duration, step=6.0):
    out, t = [], 0.0
    while t < duration:
        out += analyse(media, t, min(t + step, duration))["onsets"]
        t += step
    return out


def compare(a, b):
    """Match onsets by time, then count what moved."""
    flips, gone, extra, matched = [], 0, 0, 0
    used = set()
    for o in a:
        best, bd = None, MATCH_S
        for j, p in enumerate(b):
            if j in used:
                continue
            d = abs(p["t"] - o["t"])
            if d <= bd:
                best, bd = j, d
        if best is None:
            gone += 1
            continue
        used.add(best)
        matched += 1
        if classify(o) != classify(b[best]):
            flips.append((o["t"], classify(o), classify(b[best])))
    extra = len(b) - len(used)
    return flips, gone, extra, matched


def main():
    p = argparse.ArgumentParser()
    p.add_argument("media")
    p.add_argument("--gaps", help="gaps json, to check whether flips reach the prompt")
    p.add_argument("--step", type=float, default=6.0)
    a = p.parse_args()

    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", a.media],
        capture_output=True, text=True, check=True).stdout.strip())

    with tempfile.TemporaryDirectory() as td:
        variants, base = make_variants(a.media, td, dur)
        ref = scan(base, dur, a.step)
        print(f"  baseline: {len(ref)} onsets over {dur:.0f}s\n")
        print(f"  {'perturbation':<26} {'matched':>8} {'flipped':>8} "
              f"{'lost':>6} {'new':>5}")
        worst = 0
        for name, path in variants:
            got = scan(path, dur, a.step)
            flips, gone, extra, matched = compare(ref, got)
            worst = max(worst, len(flips))
            print(f"  {name:<26} {matched:>8} {len(flips):>8} {gone:>6} {extra:>5}")
            for t, was, now in flips[:6]:
                print(f"      {t}s  {was} -> {now}")
            if len(flips) > 6:
                print(f"      ... and {len(flips)-6} more")

        if a.gaps:
            print("\n  does any of it reach the description?")
            gaps = json.load(open(a.gaps))
            gaps = gaps.get("gaps", gaps) if isinstance(gaps, dict) else gaps
            changed = 0
            for g in gaps:
                s, e = g["start"], g["end"]
                want = describe_for_prompt(analyse(base, s, e))
                for name, path in variants:
                    if describe_for_prompt(analyse(path, s, e)) != want:
                        changed += 1
                        print(f"      gap {s}-{e}s differs under {name}")
                        break
            print(f"      {changed} of {len(gaps)} gaps change their evidence line")


if __name__ == "__main__":
    main()
