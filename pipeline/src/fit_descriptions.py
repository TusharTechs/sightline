#!/usr/bin/env python3
"""
Stage 3b — rewrite each description to the gap it will actually live in.

Fit-the-gaps mode only. For each salient change: find the silence it has to
land in, work out how many words fit AT THE PLAYBACK RATE, rewrite to that
budget — then SYNTHESISE IT AND MEASURE. The budget is an estimate; the
rendered duration is the truth, and only the truth decides whether it fits.
Shrink and retry while it overflows.

This stage also owns gap assignment and writes it into the output, so the
renderer never re-derives it. When both stages assigned gaps independently they
disagreed the moment one dropped a line, and descriptions silently landed in
the wrong silence.
"""
import argparse, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from salience import describe_at_budget
from speech import budget_words, synthesize

MAX_SHRINKS = 3


def main():
    p = argparse.ArgumentParser()
    p.add_argument("judged_json")
    p.add_argument("gaps_json")
    p.add_argument("--rate", type=float, required=True)
    p.add_argument("--backend", default="anthropic")
    p.add_argument("--min-words", type=int, default=2)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    events = [r for r in json.load(open(a.judged_json))["results"] if r.get("salient")]
    gaps = json.load(open(a.gaps_json))["gaps"]

    out, used, td = [], set(), tempfile.mkdtemp()
    for e in events:
        t = e["t_to"]
        cand = [(j, g) for j, g in enumerate(gaps) if j not in used and g["end"] > t]
        if not cand:
            print(f"  t={t:<6} NO GAP after this moment", file=sys.stderr)
            continue
        gi, gap = cand[0]
        avail = gap["len_s"] / a.rate          # wall-clock seconds available
        budget = budget_words(gap["len_s"], a.rate)
        if budget < a.min_words:
            print(f"  t={t:<6} gap {gap['len_s']}s -> {budget}w at {a.rate}x — "
                  f"too short to say anything", file=sys.stderr)
            continue

        line = fitted = None
        for attempt in range(MAX_SHRINKS + 1):
            want = max(a.min_words, budget - attempt)
            line = describe_at_budget(e["changed"], want, a.backend)
            meta = synthesize(line, os.path.join(td, "probe.pcm"))
            if meta["duration_s"] <= avail:
                fitted = (line, meta, want)
                break
            print(f"  t={t:<6} …{len(line.split())}w ran {meta['duration_s']}s > "
                  f"{round(avail,3)}s, shrinking", file=sys.stderr)

        if not fitted:
            print(f"  t={t:<6} DROPPED — cannot fit {round(avail,3)}s at {a.rate}x",
                  file=sys.stderr)
            continue

        line, meta, want = fitted
        used.add(gi)
        print(f"  t={t:<6} gap#{gi} {gap['len_s']}s -> {budget}w budget -> "
              f"{meta['words']}w / {meta['duration_s']}s of {round(avail,3)}s: {line}",
              file=sys.stderr)
        out.append({"t": t, "description": line, "gap_index": gi,
                    "word_budget": budget, "words": meta["words"],
                    "speech_s": meta["duration_s"], "gap_wall_s": round(avail, 3)})

    json.dump(out, open(a.out, "w"), indent=2)
    print(f"{len(out)}/{len(events)} descriptions fitted -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
