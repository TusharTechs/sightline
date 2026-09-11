#!/usr/bin/env python3
"""
Film mode — the pipeline runs the other way round.

For a walkthrough, changes drive the schedule: detect what happened, then find
somewhere to say it. That does not work for film. The picture is in constant
motion, so a pixel-diff gate fires on every frame pair and tells you nothing,
and there is no moment when "nothing is happening".

So for film the GAPS set the cadence. For each gap where nobody is speaking,
ask what has changed since the last thing we said, and whether the viewer needs
it. The word budget comes from the gap, at the playback rate, exactly as before.
"""
import argparse, json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from salience import describe_film_change
from speech import budget_words, synthesize

FRAME_WIDTH = 1280      # 1080p costs tokens for no benefit here
# A long gap gets described more than once. Sixteen seconds of silence in a film
# where things are visibly happening is not restraint, it is a hole — real
# description speaks periodically rather than once per pause.
MAX_SEGMENT_S = 6.0
MIN_SEGMENT_S = 1.2


def subdivide(gaps, max_len=MAX_SEGMENT_S, min_len=MIN_SEGMENT_S):
    """Split long gaps into speakable segments."""
    out = []
    for g in gaps:
        span = g["end"] - g["start"]
        if span <= max_len:
            out.append(dict(g))
            continue
        n = int(span // max_len) + (1 if span % max_len >= min_len else 0)
        n = max(1, n)
        step = span / n
        for k in range(n):
            s0 = g["start"] + k * step
            s1 = min(g["end"], s0 + step)
            if s1 - s0 >= min_len:
                out.append({"start": round(s0, 3), "end": round(s1, 3),
                            "len_s": round(s1 - s0, 3)})
    return out


def grab(media, t, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
                    "-i", media, "-frames:v", "1",
                    "-vf", f"scale={FRAME_WIDTH}:-2", out], check=True)


def dialogue_between(runs, transcript_items, a, b):
    """The words actually spoken between two times."""
    out = []
    for it in transcript_items:
        if it.get("type") != "pronunciation":
            continue
        s = float(it["start_time"])
        if a <= s < b:
            out.append(it["alternatives"][0]["content"])
    return " ".join(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("media")
    p.add_argument("gaps_json", help="detect_speech.py output")
    p.add_argument("--transcript", help="cached Transcribe result, for context")
    p.add_argument("--rate", type=float, default=1.0)
    p.add_argument("--backend", default="anthropic")
    p.add_argument("--min-words", type=int, default=3)
    p.add_argument("--max-cues", type=int, default=12)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    data = json.load(open(a.gaps_json))
    gaps = subdivide(data["gaps"])
    print(f"  {len(data['gaps'])} gaps -> {len(gaps)} speakable segments",
          file=sys.stderr)
    items = []
    if a.transcript and os.path.exists(a.transcript):
        items = json.load(open(a.transcript))["results"]["items"]

    td = tempfile.mkdtemp()
    cues, anchor = [], 0.0
    for i, g in enumerate(gaps[: a.max_cues]):
        budget = budget_words(g["len_s"], a.rate)
        if budget < a.min_words:
            print(f"  gap {g['start']}-{g['end']} -> {budget}w, too short", file=sys.stderr)
            continue

        before = os.path.join(td, f"b{i}.png")
        after = os.path.join(td, f"a{i}.png")
        grab(a.media, anchor, before)
        grab(a.media, g["start"], after)
        spoken = dialogue_between(None, items, anchor, g["start"]) if items else ""

        v = describe_film_change(before, after, budget, spoken, a.backend)
        mark = "say " if v["worth_saying"] else "skip"
        print(f"  [{mark}] gap {g['start']:>6}-{g['end']:<6} {budget:>2}w  "
              f"{v['changed'][:58]}", file=sys.stderr)
        if not (v["worth_saying"] and v["description"].strip()):
            continue

        # The budget is an estimate; the rendered duration decides. Shrink until
        # it genuinely fits rather than trusting the word count.
        avail = g["len_s"] / a.rate
        text, meta = v["description"], None
        for shrink in range(3):
            meta = synthesize(text, os.path.join(td, f"p{i}.pcm"))
            if meta["duration_s"] <= avail:
                break
            want = max(a.min_words, budget - (shrink + 1) * 2)
            print(f"          {meta['duration_s']}s > {avail:.2f}s, "
                  f"rewriting to {want}w", file=sys.stderr)
            text = describe_film_change(before, after, want, spoken,
                                        a.backend)["description"]
        if meta and meta["duration_s"] > avail:
            print(f"          dropped — will not fit {avail:.2f}s", file=sys.stderr)
            continue

        cues.append({
            "t": g["start"], "gap": g, "word_budget": budget,
            "changed": v["changed"], "description": text,
            "speech_s": meta["duration_s"] if meta else None,
        })
        anchor = g["start"]

    json.dump({"media": a.media, "rate": a.rate, "count": len(cues), "cues": cues},
              open(a.out, "w"), indent=2)
    print(f"\n{len(cues)} cues from {len(gaps)} gaps -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
