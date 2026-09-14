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
  - clips run well past the onset. The difference between the two classes is
    what the level does one to two seconds AFTER the peak, so a clip that ends
    before then has had the answer cut out of it and every clip sounds alike.
    This is not hypothetical: the first version used a 1.5 s tail, and the
    decay was unmeasurable in all sixteen
  - level is matched with a single static gain per clip. Size has to go, because
    the claim under test is that shape is audible independently of level -- but
    it has to go without touching shape. A dynamic loudness normaliser is a
    compressor, and a compressor exists precisely to reshape attacks, so it
    cannot be used to test whether attacks are audible
  - the code has three answers and so does the page. Clips the code could not
    call are included as unscored probes, and a listener can always say they
    could not tell. Forcing a binary choice manufactures confidence nobody has,
    which is the priming problem one layer up
  - filenames are random. The answer key is written separately and should not
    be opened until the sorting is done

Usage:
    shape_test.py MEDIA --out DIR [--lead 2.5] [--tail 1.5]

Then sort the clips in DIR into two groups by ear, and only then read key.json.
"""
import argparse, json, os, random, subprocess, sys, tempfile, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_events import analyse


# A repeat is only a fair second look if the listener cannot remember the
# first. The reviewer's warning:
#
#   "The second play isn't cold. I might remember the clip, and if I do I'll
#    agree with myself for the wrong reason. My number will come out better
#    than it deserves. Space them as far apart as you can."
#
# So twins are pushed into opposite ends of the running order rather than
# merely kept apart, and the requirement relaxes only if nothing satisfies it.
TWIN_GAP_FRACTION = 0.55


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


TARGET_DBFS = -20.0
HEADROOM_DBFS = -1.0


def _levels(path):
    """Mean and peak level of a file, in dBFS."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect",
         "-f", "null", "-"], capture_output=True, text=True).stderr
    mean = peak = None
    for line in out.splitlines():
        if "mean_volume:" in line:
            mean = float(line.split("mean_volume:")[1].split("dB")[0])
        elif "max_volume:" in line:
            peak = float(line.split("max_volume:")[1].split("dB")[0])
    return mean, peak


def cut(media, t, lead, tail, dest):
    """One clip, level-matched by a single static gain.

    The gain is one number applied to the whole clip, so every ratio inside it
    is preserved exactly: the attack is still the attack and the decay is still
    the decay. It is also held back far enough to avoid clipping, because
    clipping flattens peaks and peaks are the thing being judged.
    """
    with tempfile.TemporaryDirectory() as td:
        raw = os.path.join(td, "raw.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t - lead:.3f}",
             "-t", f"{lead + tail:.3f}", "-i", media, "-vn",
             "-ac", "2", "-ar", "44100", raw], check=True)
        mean, peak = _levels(raw)
        gain = 0.0
        if mean is not None:
            gain = TARGET_DBFS - mean
            if peak is not None:
                gain = min(gain, HEADROOM_DBFS - peak)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
             "-af", f"volume={gain:.2f}dB", "-ac", "2", "-ar", "44100",
             dest], check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("media")
    p.add_argument("--out", required=True)
    p.add_argument("--lead", type=float, default=2.5)
    p.add_argument("--tail", type=float, default=3.5)
    p.add_argument("--min-gap", type=float, default=1.0)
    p.add_argument("--max-per-class", type=int, default=12)
    p.add_argument("--max-probes", type=int, default=3,
                   help="clips the code could not call, included unscored")
    p.add_argument("--repeats", type=int, default=3,
                   help="clips played twice, to measure the listener's own "
                        "consistency -- the only fair yardstick for the "
                        "machine's")
    p.add_argument("--seed", type=int, default=None)
    a = p.parse_args()

    rng = random.Random(a.seed)
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", a.media],
        capture_output=True, text=True, check=True).stdout.strip())

    onsets = scan(a.media, dur)
    picked = uncontaminated(onsets, a.lead, a.tail, a.min_gap)
    by = {"hit": [], "swell": [], "unsure": []}
    for o, k in picked:
        by[k].append(o)

    # Balanced, or the listener can win by guessing the majority class.
    n = min(len(by["hit"]), len(by["swell"]), a.max_per_class)
    if n < 5:
        print(f"  only {n} per class available -- too few to test. "
              f"hits={len(by['hit'])} swells={len(by['swell'])}", file=sys.stderr)
    chosen = ([(o, "hit") for o in rng.sample(by["hit"], min(n, len(by["hit"])))] +
              [(o, "swell") for o in rng.sample(by["swell"], min(n, len(by["swell"])))])
    # Probes are not scored. They are the clips the code itself declined to
    # call, and the point of including them is to see what a listener does with
    # a sound the machine had no answer for.
    probes = rng.sample(by["unsure"], min(a.max_probes, len(by["unsure"])))
    chosen += [(o, "unsure") for o in probes]
    rng.shuffle(chosen)

    # Some clips appear twice. A machine that changes its mind on 1% of calls
    # is only bad if a listener changes theirs less often, and nobody knows
    # that number, so the test measures it rather than assuming it.
    dupes = rng.sample(range(len(chosen)), min(a.repeats, len(chosen)))
    chosen += [(chosen[i][0], chosen[i][1]) for i in dupes]
    # A repeat sitting next to its twin is recognised rather than judged, which
    # measures memory instead of hearing. Keep them apart.
    want = max(2, int(len(chosen) * TWIN_GAP_FRACTION))
    best, best_gap = list(chosen), -1
    while want >= 2:
        for _ in range(400):
            rng.shuffle(chosen)
            pos, worst = {}, 10 ** 6
            for i, (o, _k) in enumerate(chosen):
                if o["t"] in pos:
                    worst = min(worst, i - pos[o["t"]])
                pos[o["t"]] = i
            if worst > best_gap:
                best, best_gap = list(chosen), worst
            if worst >= want:
                break
        if best_gap >= want:
            break
        want -= 1
    chosen = best
    print(f"  repeats are at least {best_gap} clips apart")
    print(f"  {len(probes)} unscored probe(s) included "
          f"(of {len(by['unsure'])} available)")

    os.makedirs(a.out, exist_ok=True)
    key = []
    seen = {}
    for i, (o, k) in enumerate(chosen, 1):
        name = f"clip-{i:02d}-{uuid.uuid4().hex[:6]}.mp3"
        cut(a.media, o["t"], a.lead, a.tail, os.path.join(a.out, name))
        twin = seen.get(o["t"])
        seen.setdefault(o["t"], i)
        key.append({"file": name, "answer": k, "t": o["t"], "twin": twin,
                    "attack_ms": o.get("attack_ms"),
                    "above_floor_1s_db": o.get("above_floor_1s_db"),
                    "above_floor_2s_db": o.get("above_floor_2s_db")})

    with open(os.path.join(a.out, "key.json"), "w") as f:
        json.dump(key, f, indent=2)
    pairs = sum(1 for k in key if k["twin"])
    print(f"  {len(chosen)} clips ({n} per class, {pairs} played twice) -> {a.out}")
    print(f"  sort them into two groups by ear, THEN read {a.out}/key.json")
    print(f"  chance of a perfect sort by guessing: "
          f"1 in {_combinations(len(chosen), n)}")


def _combinations(total, k):
    from math import comb
    return comb(total, k) if total and k else 1


if __name__ == "__main__":
    main()
