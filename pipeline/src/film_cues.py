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
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from salience import describe_film_change, onset_has_visible_cause, make_continuous
from speech import budget_words, synthesize
from audio_events import analyse, describe_for_prompt, worth_checking

FRAME_WIDTH = 1280     # 800px was slower AND lost detail; measured, not assumed
# A long gap gets described more than once. Sixteen seconds of silence in a film
# where things are visibly happening is not restraint, it is a hole — real
# description speaks periodically rather than once per pause.
MAX_SEGMENT_S = 6.0
MIN_SEGMENT_S = 1.2
# Segments are described concurrently. Sequentially this took over 90 seconds
# for a 52-second trailer, which is too slow to ever show anyone.
WORKERS = 16
# Checking whether a sound has a visible cause costs a model call, so only the
# sharpest few per segment are examined.
ONSET_CHECKS = 2
# Ask for fewer words than the budget strictly allows. The budget is computed
# from a measured average speaking rate, but any individual line can come out
# slower — and every overshoot costs a rewrite AND a re-synthesis, which is
# where the time actually went. Undershooting slightly is far cheaper than
# correcting afterwards, and it stops lines being dropped for want of a retry.
FIRST_ASK = 0.85
SHRINK_ATTEMPTS = 4


def _near_black(png, threshold=14):
    """Is there effectively nothing on screen? Title cards, fades, cuts to black."""
    try:
        import numpy as np
        from PIL import Image
        return float(np.asarray(Image.open(png).convert("L"), dtype=float).mean()) < threshold
    except Exception:
        return False


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
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
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
    segments = gaps[: a.max_cues]

    def build(i, g, anchor):
        """Describe one segment. Returns a cue, or None if nothing to say."""
        budget = budget_words(g["len_s"], a.rate)
        if budget < a.min_words:
            return None, f"gap {g['start']}-{g['end']} -> {budget}w, too short"

        before = os.path.join(td, f"b{i}.png")
        after = os.path.join(td, f"a{i}.png")
        grab(a.media, anchor, before)
        grab(a.media, g["start"], after)
        spoken = dialogue_between(None, items, anchor, g["start"]) if items else ""
        audio = analyse(a.media, anchor, g["start"])

        # Which of those sounds explained themselves? A noise with nothing on
        # screen to account for it is the single most useful thing to describe;
        # a noise with a visible cause is the least.
        checked = []
        for o in worth_checking(audio["onsets"], ONSET_CHECKS):
            ob = os.path.join(td, f"o{i}_{o['t']}_b.png")
            oa = os.path.join(td, f"o{i}_{o['t']}_a.png")
            try:
                grab(a.media, max(0.0, o["t"] - 0.18), ob)
                grab(a.media, o["t"] + 0.18, oa)
                # A near-black frame makes "nothing visible accounts for it"
                # trivially true and useless — over a title card or a fade it is
                # the score, not an event anyone is wondering about. The rule is
                # for a bang with nothing attached, not for music.
                if _near_black(ob) and _near_black(oa):
                    continue
                v = onset_has_visible_cause(ob, oa, a.backend)
                checked.append({"t": o["t"], **v})
            except Exception:
                pass
        note = describe_for_prompt(audio, spoken, checked)

        ask = max(a.min_words, int(budget * FIRST_ASK))
        v = describe_film_change(before, after, ask, spoken, a.backend, note, a.effort)
        if not (v["worth_saying"] and v["description"].strip()):
            return None, f"[skip] gap {g['start']:>6}-{g['end']:<6} {v['changed'][:52]}"

        # Budget is an estimate; the rendered duration decides.
        avail = g["len_s"] / a.rate
        text, meta = v["description"], None
        for shrink in range(SHRINK_ATTEMPTS):
            meta = synthesize(text, os.path.join(td, f"p{i}-{shrink}.pcm"))
            if meta["duration_s"] <= avail:
                break
            # Scale by how far over we actually are rather than stepping down a
            # fixed amount, so a badly overrunning line converges immediately.
            over = meta["duration_s"] / avail
            want = max(a.min_words, int(len(text.split()) / over) - 1)
            text = describe_film_change(before, after, want, spoken,
                                        a.backend, note, a.effort)["description"]
        if meta and meta["duration_s"] > avail:
            return None, f"[drop] gap {g['start']} will not fit {avail:.2f}s"

        return {
            "t": g["start"], "gap": g, "word_budget": budget,
            "changed": v["changed"], "description": text,
            "speech_s": meta["duration_s"] if meta else None,
            "audio": {"character": audio["character"], "onsets": audio["onsets"],
                      "checked": checked,
                      "unexplained": [c["t"] for c in checked
                                      if not c["visible_cause"]]},
        }, f"[say ] gap {g['start']:>6}-{g['end']:<6} {text[:52]}"

    # Pass 1, concurrent. Each segment is described against the START OF THE
    # PREVIOUS SEGMENT rather than the previous thing actually said, which makes
    # them independent and therefore parallelisable.
    guesses = [0.0] + [g["start"] for g in segments[:-1]]
    results = [None] * len(segments)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(build, i, g, guesses[i]): i
                   for i, g in enumerate(segments)}
        # Report as each finishes rather than in a batch at the end. Callers
        # show this to someone waiting, and a silent minute reads as a hang.
        for n, fut in enumerate(as_completed(futures), 1):
            results[futures[fut]] = fut.result()
            print(f"  progress {n}/{len(segments)}", file=sys.stderr, flush=True)

    # Pass 2, sequential and usually tiny. Where a segment was skipped, the next
    # one's real anchor is further back than we guessed, and it may have missed
    # what changed during the skipped stretch. Only those get redone.
    cues, log, last_said = [], [], 0.0
    for i, (cue, msg) in enumerate(results):
        expected = guesses[i]
        if cue is not None and abs(expected - last_said) > 0.01:
            cue, msg = build(i, segments[i], last_said)
            msg = (msg or "") + "   (redone: anchor moved back)"
        log.append(msg)
        if cue is not None:
            cues.append(cue)
            last_said = cue["t"]

    for m in log:
        if m:
            print(f"  {m}", file=sys.stderr)

    # Pass 3. Every description above was written looking only at its own
    # moment, in parallel, knowing nothing of what any other line said. Over a
    # stretch of film that shows: a woman established as "she" is met again six
    # lines later as "a tattooed woman", the same bloodied wing is reported
    # twice, and a character's gender can flip between shots. A blind reviewer
    # put it as the descriptions not drawing a line through the film, and this
    # is one concrete part of that.
    #
    # One call, repairing only how things are referred to. It may not add,
    # embellish or re-describe, and any line it lengthens past the budget its
    # audio has to fit is discarded in favour of the original.
    if len(cues) > 1:
        budgets = [c["word_budget"] for c in cues]
        before = [c["description"] for c in cues]
        after = make_continuous(before, budgets, a.backend, a.effort)
        changed = 0
        for c, old, new in zip(cues, before, after):
            if new != old:
                changed += 1
                print(f"  [cont] {old}\n     ->  {new}", file=sys.stderr)
                c["description"] = new
        print(f"  continuity pass: {changed} of {len(cues)} lines adjusted",
              file=sys.stderr)

    json.dump({"media": a.media, "rate": a.rate, "count": len(cues), "cues": cues},
              open(a.out, "w"), indent=2)
    print(f"\n{len(cues)} cues from {len(gaps)} gaps -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
