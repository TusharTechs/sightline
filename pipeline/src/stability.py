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

Three numbers come out. Label flips say how stable the rule is. Evidence
changes say how much of that instability reaches the description, which is the
only place it can do harm. And direction says which way it breaks, which
matters more than the count:

    "A wrong label is a description that's a bit off. A missed onset is
     silence, and silence is the one thing I can't tell apart from nothing
     having happened... If the borderline case turns into an announcement,
     that's the one that sends me hunting for something that was never there.
     If it turns into quiet, I'm no worse off than I already was. I'd take that
     trade every time."

So a change that makes the system say less is counted as safe, and one that
makes it announce something it was not going to announce is counted as costly.
They are not the same failure and they should never be added together.

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


def says_event(info):
    """Would this window produce a claim that something audible happened?"""
    return any(o["transient"] for o in info["onsets"])


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

        # Which way does it break? Measured over the whole film on the scan
        # grid, so the sample is every window rather than a handful of gaps.
        print("\n  direction, over every window in the film")
        print(f"  {'perturbation':<26} {'->quiet':>9} {'->announce':>12}")
        for name, path in variants:
            to_quiet = to_announce = 0
            t = 0.0
            while t < dur:
                w = (t, min(t + a.step, dur))
                was = says_event(analyse(base, *w))
                now = says_event(analyse(path, *w))
                if was and not now:
                    to_quiet += 1
                elif now and not was:
                    to_announce += 1
                t += a.step
            print(f"  {name:<26} {to_quiet:>9} {to_announce:>12}")

        if a.gaps:
            print("\n  and in the real gaps")
            gaps = json.load(open(a.gaps))
            gaps = gaps.get("gaps", gaps) if isinstance(gaps, dict) else gaps
            for g in gaps:
                s, e = g["start"], g["end"]
                ref = analyse(base, s, e)
                want = describe_for_prompt(ref)
                for name, path in variants:
                    got = analyse(path, s, e)
                    if describe_for_prompt(got) != want:
                        was, now = says_event(ref), says_event(got)
                        way = ("-> ANNOUNCE (costly)" if now and not was
                               else "-> quiet (safe)" if was and not now
                               else "wording only, same conclusion")
                        print(f"      gap {s}-{e}s under {name}: {way}")


if __name__ == "__main__":
    main()
