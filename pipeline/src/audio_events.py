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

KNOWN WEAKNESS, and it is the one worth knowing about. This answers "did
something arrive" one sound at a time. It has nothing to say about a passage
where five things arrive together, and a listener in that passage is not
asking which sound to name -- they are asking what the scene just became.
That is a different question and none of this addresses it.

The suspicion was that the rule might also go quietest exactly where the most
is happening, since a suppressed event costs more in a busy stretch. Measured
across the full film, it does not: the proportion of onsets claimed as events
RISES with density, 61% in windows holding one or two onsets against 73% in
windows holding eight or more, and windows that end up claiming nothing are
sparser than average (2.5 onsets against 3.3 film-wide). The floor moves the
other way too -- dense windows sit lower, not higher.

One case does deserve the worry. A window at 360 s holds four onsets with
attacks of 30, 40, 70 and 110 ms and claims none of them. Fast arrivals going
unclaimed together is the failure this would show up as, and it is recorded
here rather than averaged away.
"""
import argparse, json, os, subprocess, sys, tempfile
import numpy as np

SR = 16000
FRAME_MS = 20
# A candidate onset is this many dB above the trailing median of the last ~400ms.
# This finds loud moments. It does NOT distinguish a hit from a swell, which is
# the whole problem — see attack_ms below.
ONSET_DB = 7.0
# Don't report two onsets closer together than this.
MIN_SEPARATION_S = 0.12

# Attack, measured at fine resolution.
#
# From the ADP list reviewer, and it is the separation the magnitude test could
# never make:
#
#   "A swell and a hit are different shapes, not different sizes. Score comes up
#    over a second or two. It ramps. An impact is at full the instant it starts
#    and then it falls away. So measure how fast the level got there rather than
#    how far it got... That's the whole reason a compressor has an attack
#    control."
#
# So: how long did it take to climb the last 12 dB into its peak? An impact does
# it in a few milliseconds. Music takes hundreds.
FINE_MS = 5
ATTACK_RANGE_DB = 12.0
# There is deliberately no single attack threshold here any more. One number
# had to be defended and could not be: a listener does not hear the rise, so no
# ear can tell you where to put it. See FAST_MS / SLOW_MS and the tail below.
# How far either side of a coarse onset to look for the true peak.
REFINE_WINDOW_S = 0.30

# The tail, which is the half the attack cannot see.
#
# Same reviewer, after declining to give me a better threshold:
#
#   "A listener doesn't hear the rise. Nobody ever sat in a chair and clocked 60
#    milliseconds... A hit arrives and then falls away. That's the half you
#    aren't using yet. Score comes up and then it stays up. So for anything
#    close to your boundary, look at what happens after the peak. Back down
#    inside a second, that's an event. Still sitting there two seconds later,
#    that's the music."
#
# So the attack decides only the clear cases, and the tail decides the rest.
# Below FAST_MS the crack is already past the listener and nothing else needs
# asking; above SLOW_MS it plainly ramped. Between the two, the attack is not
# evidence and the decay is.
FAST_MS = 30.0
SLOW_MS = 120.0
TAIL_WINDOW_S = 0.20      # width of each level probe
TAIL_SHORT_S = 1.0        # "back down inside a second"
TAIL_LONG_S = 2.0         # "still sitting there two seconds later"
# Measured against the level BEFORE the onset, not against the peak.
#
# Same reviewer again, on the loudest onset in the trailer, which fell 3 dB in a
# second and 15 dB in two and so counted as neither:
#
#   "That's not your rule failing. That's two things happening at once. A hit
#    doesn't decay into silence, it decays into whatever is underneath it. Put a
#    big impact on top of sustained score and the first second can't fall,
#    because the music is holding the floor up. After the peak you're measuring
#    the loudest thing present, not the decay of the event."
#
# So the question is not how far it dropped, it is whether it came back to where
# it started. Back down to the old floor is an event, however long it took.
# Settling above the old floor is something that arrived and stayed, which is
# the music changing rather than an event.
BACK_HOME_DB = 3.0        # within this of the pre-onset floor -> it went away
STAYED_UP_DB = 3.0        # still this far above the old floor -> it stayed
# A verdict sitting right on a boundary must not be the one that makes us
# speak. Same reviewer, on which way instability should break:
#
#   "A wrong label is a description that's a bit off. A missed onset is
#    silence, and silence is the one thing I can't tell apart from nothing
#    having happened... If the borderline case turns into an announcement,
#    that's the one that sends me hunting for something that was never there.
#    If it turns into quiet, I'm no worse off than I already was."
#
# So "hit" -- the only verdict that can produce a claim -- has to clear its
# condition by this margin. Inside the margin the answer is not sure, and not
# sure is silence. Swell and unsure both end in silence already and need no
# such protection: the asymmetry is the point.
#
# The width is not chosen. It is the measured noise floor of this pipeline:
# run the same film three ways and see how far the settle values move. Uniform
# gain moves them 0.00 dB, exactly, at every onset -- the rule really is
# differences-only. A lossy re-encode moves them a median of 0.00, a 99th
# percentile of 0.16, and a maximum of 1.60. So the margin is 1.6 dB, which is
# wider than anything the pipeline's own instability can produce and no wider.
# Recompute it with stability.py --margin if the chain ever changes.
EDGE_DB = 1.6
# Extra audio loaded past the window so the tail of a late onset is measurable.
TAIL_PAD_S = TAIL_LONG_S + TAIL_WINDOW_S


def load_mono(media, start, end):
    """Mono float samples at SR.

    Read as 32-bit float, not 16-bit. This film -- and any lossily encoded one
    -- decodes to samples above full scale, and converting those to 16-bit
    clips them. Clipping flattens peaks, a flattened peak measures as a slower
    attack, and a slower attack reads as music. So a 16-bit read was quietly
    turning some impacts into swells before the rule ever saw them.

    Found by perturbation: attenuating the whole film by 3 dB flipped five
    onsets from swell to hit, always in that direction, because the quieter
    copy survived the conversion intact while the original did not. A rule that
    is really measuring shape should not care about gain, and this one does not
    -- the loader did.
    """
    with tempfile.TemporaryDirectory() as td:
        raw_path = os.path.join(td, "a.raw")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
             "-to", f"{end:.3f}", "-i", media, "-vn", "-ac", "1",
             "-ar", str(SR), "-c:a", "pcm_f32le", "-f", "f32le", raw_path],
            check=True)
        with open(raw_path, "rb") as f:
            raw = f.read()
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def attack_ms(x, centre_s, window_s=REFINE_WINDOW_S):
    """How fast did the level get to its peak, in milliseconds, and where the
    peak was (seconds into x).

    Returns (None, None) when it cannot be measured. Callers treat that as "not
    sure", and not sure means stay quiet.
    """
    n = max(1, int(SR * FINE_MS / 1000))
    lo = max(0, int((centre_s - window_s) * SR))
    hi = min(x.size, int((centre_s + window_s) * SR))
    seg = x[lo:hi]
    if seg.size < n * 4:
        return None, None
    frames = seg[: (seg.size // n) * n].reshape(-1, n)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    peak = int(np.argmax(db))
    peak_s = (lo + peak * n) / SR
    if peak == 0:
        return None, peak_s
    floor = db[peak] - ATTACK_RANGE_DB
    i = peak
    while i > 0 and db[i] > floor:
        i -= 1
    if db[i] > floor:            # never got that far below; cannot tell
        return None, peak_s
    return (peak - i) * FINE_MS, peak_s


def _level_db(x, centre_s, width_s=TAIL_WINDOW_S):
    """RMS level in dB over a short window, or None if it runs off the end."""
    lo = int((centre_s - width_s / 2) * SR)
    hi = int((centre_s + width_s / 2) * SR)
    if lo < 0 or hi > x.size or hi - lo < SR // 100:
        return None
    seg = x[lo:hi]
    return float(20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9))


def settle(x, peak_s, floor_db):
    """How far above the PRE-ONSET floor the level still sits, one second after
    the peak and two.

    Near zero means the sound went away and left the scene as it found it.
    A positive number means something arrived and is still there.

    Either may be None when there is not enough audio after the peak to look.
    """
    out = []
    for dt in (TAIL_SHORT_S, TAIL_LONG_S):
        later = _level_db(x, peak_s + dt)
        out.append(None if later is None else round(later - floor_db, 1))
    return out[0], out[1]


def shape_of(x, centre_s, floor_db):
    """Is this a hit or a swell? Returns (attack_ms, above_1s, above_2s, verdict)
    where verdict is True for a hit, False for a swell, and None for not sure.

    The attack settles the clear cases. Everything near the boundary is settled
    by whether the level came back to where it started, and anything ambiguous
    on both is left alone.
    """
    a, peak_s = attack_ms(x, centre_s)
    if a is None:
        return None, None, None, None
    if a < FAST_MS:
        return a, None, None, True
    if a > SLOW_MS:
        return a, None, None, False

    above_1s, above_2s = settle(x, peak_s, floor_db)
    # Came home, at either checkpoint, and came home clearly. It took whatever
    # time it took, but a value sitting on the line does not get to speak.
    home = BACK_HOME_DB - EDGE_DB
    if (above_1s is not None and above_1s <= home) or \
       (above_2s is not None and above_2s <= home):
        return a, above_1s, above_2s, True
    # Two seconds on and still well above where it started: it stayed.
    if above_2s is not None and above_2s > STAYED_UP_DB:
        return a, above_1s, above_2s, False
    return a, above_1s, above_2s, None             # tie goes to silence


def analyse(media, start, end):
    # Load past the end so a late onset still has a tail to measure. Detection
    # and the level summary stay inside the real window.
    x = load_mono(media, start, end + TAIL_PAD_S)
    if x.size == 0:
        return {"window": [start, end], "onsets": [], "level_db": -120.0,
                "character": "silent"}

    n = int(SR * FRAME_MS / 1000)
    frames = x[: (x.size // n) * n].reshape(-1, n)
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms)

    inside = int(round((end - start) * 1000 / FRAME_MS))
    look = max(3, int(400 / FRAME_MS))
    onsets = []
    for i in range(look, min(db.size, inside)):
        local = np.median(db[i - look:i])
        rise = db[i] - local
        if rise >= ONSET_DB:
            t = start + i * FRAME_MS / 1000
            # Carry how sharp the rise was, so the caller can spend a limited
            # budget of frame checks on the sounds most likely to matter.
            # The trailing median is also the floor this sound landed on, and
            # the decay only means anything relative to it.
            cand = {"t": round(t, 2), "rise_db": round(rise, 1),
                    "floor_db": round(float(local), 1)}
            if onsets and t - onsets[-1]["t"] < MIN_SEPARATION_S:
                if rise > onsets[-1]["rise_db"]:
                    onsets[-1] = cand
            else:
                onsets.append(cand)

    # Now measure the shape of each, and keep only the hits.
    for o in onsets:
        a, above_1s, above_2s, verdict = shape_of(x, o["t"] - start, o["floor_db"])
        o["attack_ms"] = a
        if above_1s is not None:
            o["above_floor_1s_db"] = above_1s
        if above_2s is not None:
            o["above_floor_2s_db"] = above_2s
        o["transient"] = bool(verdict)
        if verdict is None:
            o["unsure"] = True

    # Only hits are counted as events. A swell is the music getting louder,
    # which is not something that happened -- describing it would tell the
    # viewer about the score rather than about the film.
    hits = [o for o in onsets if o["transient"]]
    # An onset we could not call is not a swell. Saying "music rising" about it
    # would be inventing evidence in the other direction.
    swells = [o for o in onsets if not o["transient"] and not o.get("unsure")]

    win = db[:inside] if inside > 0 else db
    level = float(np.median(win))
    spread = float(win.max() - np.median(win))
    if level < -50:
        character = "silent"
    elif hits:
        character = f"{len(hits)} distinct sound event(s)"
    elif swells:
        character = "music rising, but nothing arrives"
    elif onsets:
        character = "sound whose shape could not be called either way"
    elif spread < 8:
        character = "continuous (music or ambience, no distinct events)"
    else:
        character = "continuous with some variation"

    return {"window": [round(start, 3), round(end, 3)],
            "onsets": onsets, "level_db": round(level, 1),
            "character": character}


def worth_checking(onsets, n):
    """The n sharpest *hits*, in time order.

    Two filters, in order. First shape: a swell is the music rising, and music
    rising is not an event — only something that arrived fast is worth asking
    the picture about. Second confidence: an onset whose attack could not be
    measured is not promoted on the strength of its size. Tie goes to silence.

    Then size, because checking costs a model call and the budget should go to
    the hits a viewer is most likely to have noticed.
    """
    hits = [o for o in onsets if o.get("transient")]
    top = sorted(hits, key=lambda o: -o["rise_db"])[:n]
    return sorted(top, key=lambda o: o["t"])


def describe_for_prompt(info, dialogue="", checked=None):
    """Plain-language evidence for the model.

    `checked` is a list of {t, visible_cause, what} for onsets that were examined
    against the picture. The distinction matters more than the presence of sound:
    a noise that explains itself is already understood, while a noise with
    nothing on screen to account for it is an open question the viewer cannot
    resolve without being told.
    """
    bits = [f"Soundtrack in this stretch: {info['character']}."]

    unexplained = [c for c in (checked or []) if not c["visible_cause"]]
    explained = [c for c in (checked or []) if c["visible_cause"]]

    if unexplained:
        times = ", ".join(f"{c['t']}s" for c in unexplained)
        bits.append(
            f"IMPORTANT — audible event(s) at {times} with NOTHING VISIBLE to "
            f"account for them. The viewer heard something and cannot tell what. "
            f"That is the highest-value thing you can describe here. Say that "
            f"something happened out of shot; do NOT guess what it was.")
    if explained:
        times = ", ".join(f"{c['t']}s ({c['what']})" for c in explained)
        bits.append(
            f"Audible event(s) at {times} WITH a visible cause — the viewer has "
            f"already worked those out. Not worth spending words on.")
    if not checked and any(o.get("transient") for o in info["onsets"]):
        bits.append("Audible events occurred but were not checked against the "
                    "picture.")
    if not any(o.get("transient") for o in info["onsets"]):
        swelled = any(not o.get("unsure") for o in info["onsets"])
        unsure = any(o.get("unsure") for o in info["onsets"])
        bits.append(
            ("The music rises here but nothing arrives — a swell is not an event. "
             if swelled else
             "Something audible happened but its shape could not be called an "
             "event either way, so treat this stretch as unaccounted for rather "
             "than silent. " if unsure else "No distinct audible events. ") +
            "Anything that changed on screen was silent, and the viewer has no "
            "other way to know it.")

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
