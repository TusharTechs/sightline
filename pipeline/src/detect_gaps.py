#!/usr/bin/env python3
"""
Stage 1b — find the silences a description could live in.

Only needed for fit-the-gaps mode (film, drama), where pausing is not allowed
and the description has to land between the lines.

Everything here is in MEDIA time. Converting to playback time is the caller's
job and is the whole point of the speed work: a 3s gap is 1.5s of wall clock at
2x, and the answer to that is fewer words, not faster speech.
"""
import argparse, json, re, subprocess, sys

# A quiet passage has to be this quiet, for this long, to be usable.
NOISE_DB = -35
MIN_GAP_S = 0.45
# Don't start speaking the instant the narrator stops, or finish flush against
# their next word.
EDGE_GUARD_S = 0.12


def media_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    return float(out)


def find_gaps(path, noise_db=NOISE_DB, min_gap=MIN_GAP_S):
    r = subprocess.run(
        ["ffmpeg", "-i", path, "-af",
         f"silencedetect=n={noise_db}dB:d={min_gap}", "-f", "null", "-"],
        capture_output=True, text=True)
    log = r.stderr
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", log)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*(-?[\d.]+)", log)]
    dur = media_duration(path)

    gaps = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else dur      # trailing silence to EOF
        s, e = max(0.0, s) + EDGE_GUARD_S, min(dur, e) - EDGE_GUARD_S
        if e - s >= min_gap:
            gaps.append({"start": round(s, 3), "end": round(e, 3),
                         "len_s": round(e - s, 3)})
    return gaps, dur


def main():
    p = argparse.ArgumentParser()
    p.add_argument("media")
    p.add_argument("--noise-db", type=float, default=NOISE_DB)
    p.add_argument("--min-gap", type=float, default=MIN_GAP_S)
    p.add_argument("--out", default="-")
    a = p.parse_args()
    gaps, dur = find_gaps(a.media, a.noise_db, a.min_gap)
    blob = json.dumps({"media": a.media, "duration_s": round(dur, 3),
                       "noise_db": a.noise_db, "min_gap_s": a.min_gap,
                       "count": len(gaps), "gaps": gaps}, indent=2)
    if a.out == "-":
        print(blob)
    else:
        open(a.out, "w").write(blob)
        print(f"{len(gaps)} gaps -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
