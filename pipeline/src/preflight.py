#!/usr/bin/env python3
"""
Check a built bundle before a person has to.

Every fault this looks for was found by a blind reviewer, one at a time, over
six rounds of correspondence. That is an expensive way to find a truncated
timeline, and an unfair one: a tester's attention should go on whether the
description helps, not on whether the software works.

So each of those faults is now a check that runs in a second.

    preflight.py BUNDLE_DIR [--gaps gaps.json]

Exit code is non-zero if anything failed, so it can gate a deploy.
"""
import argparse, json, os, re, sys
from collections import Counter

# Longest stretch with no description before it counts as a hole. A listener
# reported description "cutting out" at two minutes; it had been truncated.
MAX_SILENCE_S = 45.0
# Unused speakable seconds inside a silence before it counts as a fault rather
# than as the content simply not leaving room.
MIN_WASTED_ROOM_S = 8.0
# A description must not begin before the previous line of dialogue has landed.
MIN_AFTER_SPEECH_S = 0.5
# Nor run into the next one.
MIN_BEFORE_SPEECH_S = 0.2
# Phrases this long repeating across the run read as the system losing track.
REPEAT_WORDS = 4


def check(bundle, gaps_path=None):
    tl = json.load(open(os.path.join(bundle, "timeline.json")))
    cues = sorted(tl["cues"], key=lambda c: c["t"])
    fails, notes = [], []

    if not cues:
        return ["no cues at all"], []

    dur = tl.get("duration_s")
    if dur is None and gaps_path and os.path.exists(gaps_path):
        dur = json.load(open(gaps_path)).get("duration_s")

    # 1. Coverage, judged against what was actually available to say it in.
    #
    # A long silence is only a fault if there was room to speak in it. An
    # instructional film that narrates continuously for nine minutes leaves
    # almost no gaps, and reporting that as a hole blames the software for the
    # content. Found by running this over a 1951 civil defence film that is 77%
    # narration: it has a 200-second stretch with nothing said and there is
    # nothing wrong with it.
    #
    # So a hole counts only if the gaps inside it could have held something.
    gaps = []
    if gaps_path and os.path.exists(gaps_path):
        gaps = json.load(open(gaps_path)).get("gaps", [])

    def room_between(lo, hi):
        """Seconds of describable gap inside a stretch."""
        return sum(max(0.0, min(hi, g["end"]) - max(lo, g["start"])) for g in gaps)

    last = 0.0
    for c in cues:
        if c["t"] - last > MAX_SILENCE_S:
            room = room_between(last, c["t"])
            if not gaps or room > MIN_WASTED_ROOM_S:
                fails.append(
                    f"{c['t'] - last:.0f}s with no description, from {last:.0f}s "
                    f"to {c['t']:.0f}s, with {room:.0f}s of usable gap in it")
            else:
                notes.append(f"{c['t'] - last:.0f}s with no description from "
                             f"{last:.0f}s, but only {room:.1f}s of it was "
                             f"speakable -- that is the content, not a fault")
        last = c["t"] + c.get("duration", 0)
    if dur and dur - last > MAX_SILENCE_S:
        room = room_between(last, dur)
        if not gaps or room > MIN_WASTED_ROOM_S:
            fails.append(f"{dur - last:.0f}s with no description at the end, "
                         f"from {last:.0f}s to {dur:.0f}s, with {room:.0f}s of "
                         f"usable gap in it")

    # 2. Every referenced audio file exists. A missing one plays as silence,
    #    which is indistinguishable from nothing having happened.
    for c in cues:
        base = c.get("pcm", "").replace(".pcm", "")
        if base and not any(os.path.exists(os.path.join(bundle, base + e))
                            for e in (".mp3", ".wav", ".pcm")):
            fails.append(f"cue at {c['t']}s has no audio file ({base}.*)")

    # 3. Dialogue collisions, in both directions.
    if gaps_path and os.path.exists(gaps_path):
        runs = json.load(open(gaps_path)).get("speech_runs", [])
        for c in cues:
            end = c["t"] + c.get("duration", 0)
            for r in runs:
                if r["start"] < end and r["end"] > c["t"]:
                    fails.append(f"cue at {c['t']}s talks over dialogue "
                                 f"at {r['start']}-{r['end']}s")
            before = [r["end"] for r in runs if r["end"] <= c["t"]]
            after = [r["start"] for r in runs if r["start"] >= end]
            if before and c["t"] - max(before) < MIN_AFTER_SPEECH_S:
                fails.append(f"cue at {c['t']}s begins "
                             f"{c['t'] - max(before):.2f}s after a line ends")
            if after and min(after) - end < MIN_BEFORE_SPEECH_S:
                fails.append(f"cue at {c['t']}s ends "
                             f"{min(after) - end:.2f}s before the next line")

    # 4. Continuity of reference.
    #
    # Only one pattern is reported, because only one is reliable without
    # understanding the film: the SAME kind of person introduced indefinitely
    # twice. "A woman" and later "a woman" again is either two women or one
    # being met twice, and the description should have made clear which.
    #
    # A first attempt flagged any noun phrase appearing after a pronoun, which
    # fired on every new character in the scene -- a dragon, a bald man, a
    # guard -- and would have trained anyone reading it to ignore the whole
    # section. Telling a new character from a repeated one is exactly the
    # understanding this system does not have, so it is not claimed here.
    first_seen = {}
    for c in cues:
        d = c.get("description") or c.get("text", "")
        for art, head in re.findall(
                r"\b(a|an)\s+(?:\w+[- ])*?(woman|man|girl|boy|person)\b", d, re.I):
            head = head.lower()
            if head in first_seen:
                notes.append(f"{c['t']}s introduces \"{art} {head}\" again; "
                             f"first introduced at {first_seen[head]}s")
            else:
                first_seen[head] = c["t"]

    # 5. Camera language.
    #
    # Describing where the camera sits gives a listener nothing they can use.
    # Worse, a vantage point gets mistaken for a person: one description of a
    # high shot looking down through rafters said "someone watches her sleep",
    # inventing a character and a threat the film does not contain. A listener
    # asked what that shot was, trying to reconcile it, which is how it was
    # found.
    #
    # "off screen" and "out of shot" are deliberately NOT flagged. Naming an
    # unseen source of a sound is the correct thing to say and the prompt asks
    # for it.
    camera = re.compile(
        r"\b(from above|from below|the camera|pans?|panning|zooms?|close[- ]up|"
        r"cuts? to|we see|past us|toward us|at us|the shot|in frame|"
        r"camera angle|framing)\b", re.I)
    for c in cues:
        d = c.get("description") or c.get("text", "")
        m = camera.search(d)
        if m:
            fails.append(f'{c["t"]}s uses camera language: "{m.group(0)}" in '
                         f'"{d}"')

    # 6. Repeated phrases across the run.
    grams = Counter()
    for c in cues:
        w = re.findall(r"[a-z']+", (c.get("description") or c.get("text","")).lower())
        for i in range(len(w) - REPEAT_WORDS + 1):
            grams[" ".join(w[i:i + REPEAT_WORDS])] += 1
    for phrase, n in grams.items():
        if n > 1:
            notes.append(f'"{phrase}" said {n} times')

    return fails, notes


def main():
    p = argparse.ArgumentParser()
    p.add_argument("bundle")
    p.add_argument("--gaps")
    a = p.parse_args()

    fails, notes = check(a.bundle, a.gaps)
    tl = json.load(open(os.path.join(a.bundle, "timeline.json")))
    print(f"  {len(tl['cues'])} cues in {a.bundle}")
    for n in notes:
        print(f"  note  {n}")
    for f in fails:
        print(f"  FAIL  {f}")
    if not fails:
        print("  passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
