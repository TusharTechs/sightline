#!/usr/bin/env python3
"""
Stage 2+3 — salience judgement and change description.

The rule, adopted verbatim from a blind accessibility professional on the ACB
ADP list, is the whole design:

    A change matters when it changes what you can do next.

Counts: a box got ticked, a button went from greyed out to live, a dialog opened
and nothing else will respond until it's dealt with. Doesn't count: a highlight
moving, a hover, a scroll, a transient tooltip.

The same rule decides whether to pause, so this stage drives both.

Model access is pluggable. `claude` runs through the local CLI and works today;
`bedrock` is the intended path for submission but needs credentials and a CA
bundle that tolerates the local TLS setup.
"""
import argparse, base64, json, os, re, subprocess, sys, tempfile
from PIL import Image

# Bedrock is the intended backend. Local TLS inspection breaks the AWS API and
# the SDK's HTTPS calls unless a bundle containing the intercepting chain is
# used; build one with tools/make-ca-bundle.sh and point SIGHTLINE_CA_BUNDLE at
# it (defaults to ~/.config/sightline-ca.pem). Harmless when absent.
CA_BUNDLE = os.environ.get(
    "SIGHTLINE_CA_BUNDLE", os.path.expanduser("~/.config/sightline-ca.pem"))
if os.path.exists(CA_BUNDLE):
    # Set, not setdefault: a narrower bundle already in the environment is the
    # usual cause of "Connection error" here, and ours is a superset.
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "AWS_CA_BUNDLE"):
        os.environ[var] = CA_BUNDLE

# Read the API key from a file if one is configured, so it never has to be
# pasted into a terminal that is being shared or logged. chmod 600 it.
_KEY_FILE = os.environ.get("SIGHTLINE_API_KEY_FILE",
                           os.path.expanduser("~/.config/sightline-anthropic-key"))
if not os.environ.get("ANTHROPIC_API_KEY") and os.path.exists(_KEY_FILE):
    with open(_KEY_FILE) as _f:
        _k = _f.read().strip()
    if _k:
        os.environ["ANTHROPIC_API_KEY"] = _k

BEDROCK_MODEL = os.environ.get("SIGHTLINE_MODEL", "anthropic.claude-opus-5")
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")
# Keep hackathon credentials separate from anything else on the machine:
#   aws configure --profile sightline      (then SIGHTLINE_AWS_PROFILE=sightline)
AWS_PROFILE = os.environ.get("SIGHTLINE_AWS_PROFILE")
if AWS_PROFILE:
    os.environ["AWS_PROFILE"] = AWS_PROFILE

RULE = """A change matters when it changes what the viewer can do next.

COUNTS as salient (describe it):
- a checkbox or toggle changed state
- a control went from disabled to enabled, or enabled to disabled
- a dialog, menu or overlay opened or closed
- content was added, removed, or finished loading
- an error, confirmation or status message appeared

Does NOT count as salient (stay silent):
- a focus ring or highlight moved
- a hover state, or a tooltip appearing or disappearing
- the page scrolled, revealing content that already existed
- a purely cosmetic animation or transition"""

PROMPT = """You are generating audio description for a software walkthrough, for a
viewer who cannot see the screen.

Two frames are given: BEFORE and AFTER. Describe what CHANGED between them, not
what is on screen. Then judge whether that change is salient.

{rule}

Report what changed, whether it is salient, why, and — only if it is salient —
what to say aloud in at most {max_words} words.

The description is spoken, so: plain words, present tense, no UI jargon like
'widget' or 'element', and never mention frames, pixels or the screen itself."""


def crop_pair(before, after, bbox, pad=40):
    """Crop both frames to the changed region, with a little context."""
    outs = []
    with Image.open(before) as b:
        W, H = b.size
    x0, y0, x1, y1 = bbox
    box = (max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad))
    for src, tag in ((before, "before"), (after, "after")):
        f = tempfile.NamedTemporaryFile(suffix=f"_{tag}.png", delete=False)
        with Image.open(src) as im:
            im.crop(box).save(f.name)
        outs.append(f.name)
    return outs


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in model output: {text[:400]}")
    return json.loads(m.group(0))


def judge_claude_cli(before_png, after_png, max_words=14, timeout=180):
    prompt = (PROMPT.format(rule=RULE, max_words=max_words)
              + f"\n\nBEFORE frame: {before_png}\nAFTER frame: {after_png}\n"
                "Read both images, then answer.")
    r = subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "Read"],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude cli failed: {r.stderr[:400]}")
    return _extract_json(r.stdout)


def _b64(path):
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode()


_clients = {}


def _client(flavour="mantle"):
    """Bedrock client.

    `mantle` is the current Messages-API endpoint and the default. `legacy`
    goes through bedrock-runtime InvokeModel, which is worth trying if the
    Mantle endpoint rejects the request signature on a network that rewrites
    HTTP headers in flight.
    """
    if flavour not in _clients:
        if flavour == "legacy":
            from anthropic import AnthropicBedrock
            _clients[flavour] = AnthropicBedrock(aws_region=BEDROCK_REGION)
        else:
            from anthropic import AnthropicBedrockMantle
            _clients[flavour] = AnthropicBedrockMantle(aws_region=BEDROCK_REGION)
    return _clients[flavour]


def _anthropic():
    """The shared Anthropic client, built on first use.

    The import lives inside the `if`, not above it. Importing a vendor SDK to
    then not use it makes every function in this module require that SDK
    installed, including the pure logic around it -- which is how the test
    suite ended up needing `anthropic` to check that a continuity repair
    respects its word budget.
    """
    if "anthropic" not in _clients:
        import anthropic
        _clients["anthropic"] = anthropic.Anthropic()
    return _clients["anthropic"]


def _judgement_request(before_png, after_png, max_words, scroll_dy=0):
    """The request both backends send.

    Structured output is used rather than prompting for JSON, so a malformed
    reply is impossible and the salience field is always a real boolean —
    'the model returned prose we could not parse' must never be scored as a
    salience decision.
    """
    from pydantic import BaseModel, Field

    class Judgement(BaseModel):
        changed: str = Field(description="what visibly changed, one short clause")
        salient: bool = Field(description="does it change what the viewer can do next")
        reason: str = Field(description="why it does or does not")
        description: str = Field(
            description=f"what to say aloud, at most {max_words} words; "
                        f"empty string when not salient")

    content = [
        {"type": "text", "text": "BEFORE:"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": _b64(before_png)}},
        {"type": "text", "text": "AFTER:"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": _b64(after_png)}},
        {"type": "text", "text": PROMPT.format(rule=RULE, max_words=max_words)},
    ]
    if scroll_dy:
        # A measured fact, not a verdict. The rule still decides.
        content.insert(4, {"type": "text", "text": (
            f"Measured: the content in this region moved vertically by "
            f"{abs(scroll_dy)} pixels between the two frames. Anything that left "
            f"or entered the view did so because the view moved, not because it "
            f"was added or removed.")})
    return dict(
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": content}],
        output_format=Judgement,
    )


def judge_bedrock(before_png, after_png, max_words=14, effort=None, scroll_dy=0,
                  flavour="mantle"):
    kwargs = _judgement_request(before_png, after_png, max_words, scroll_dy)
    kwargs["model"] = BEDROCK_MODEL
    if effort:
        kwargs["output_config"] = {"effort": effort}
    return _client(flavour).messages.parse(**kwargs).parsed_output.model_dump()


def judge_bedrock_legacy(before_png, after_png, max_words=14, effort=None, scroll_dy=0):
    return judge_bedrock(before_png, after_png, max_words, effort, scroll_dy,
                         flavour="legacy")


def judge_anthropic(before_png, after_png, max_words=14, effort=None, scroll_dy=0):
    """First-party Claude API. Same request shape as Bedrock, different client.

    Used while this AWS account cannot reach Bedrock. Needs ANTHROPIC_API_KEY.
    """
    _anthropic()
    kwargs = _judgement_request(before_png, after_png, max_words, scroll_dy)
    kwargs["model"] = os.environ.get("SIGHTLINE_API_MODEL", "claude-opus-5")
    if effort:
        kwargs["output_config"] = {"effort": effort}
    return _clients["anthropic"].messages.parse(**kwargs).parsed_output.model_dump()


BACKENDS = {
    "bedrock": judge_bedrock,
    "bedrock-legacy": judge_bedrock_legacy,
    "anthropic": judge_anthropic,
    "claude": judge_claude_cli,
}


def run(frames_dir, changes_json, fps, backend="bedrock", max_words=14, limit=None,
        effort=None):
    data = json.load(open(changes_json))
    events = data["events"][:limit] if limit else data["events"]
    judge = BACKENDS[backend]
    results = []
    for e in events:
        bi, ai = int(round(e["t_from"] * fps)), int(round(e["t_to"] * fps))
        bp = os.path.join(frames_dir, f"f{bi:04d}.png")
        ap = os.path.join(frames_dir, f"f{ai:04d}.png")
        cb, ca = crop_pair(bp, ap, e["bbox"])
        try:
            verdict = (judge(cb, ca, max_words, effort, e.get("scroll_dy", 0))
                       if backend.startswith(("bedrock", "anthropic"))
                       else judge(cb, ca, max_words))
        except Exception as ex:
            verdict = {"changed": "", "salient": None, "reason": f"ERROR: {ex}",
                       "description": ""}
        finally:
            for f in (cb, ca):
                try: os.unlink(f)
                except OSError: pass
        results.append({**{k: e[k] for k in ("id", "t_from", "t_to", "bbox", "changed_px")},
                        **verdict})
        print(f"  [{e['id']}] t={e['t_from']:>5}s  salient={verdict.get('salient')}  "
              f"{verdict.get('changed','')[:60]}", file=sys.stderr)
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("frames_dir")
    p.add_argument("changes_json")
    p.add_argument("--fps", type=float, required=True)
    p.add_argument("--backend", default="bedrock", choices=list(BACKENDS))
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--max-words", type=int, default=14)
    p.add_argument("--limit", type=int)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    res = run(a.frames_dir, a.changes_json, a.fps, a.backend, a.max_words, a.limit,
              a.effort)
    model = (BEDROCK_MODEL if a.backend.startswith("bedrock")
             else os.environ.get("SIGHTLINE_API_MODEL", "claude-opus-5")
             if a.backend == "anthropic" else "claude-cli")
    json.dump({"backend": a.backend, "model": model, "effort": a.effort, "results": res},
              open(a.out, "w"), indent=2)
    print(f"{len(res)} judged -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Budget-aware rewriting.
#
# A description written without knowing its gap cannot be made to fit by
# speaking faster — that is the failure the ADP list reviewer described, where a line that
# sits neatly in a gap at 1x lands on the narrator at 2x. The gap has to
# constrain the writing, so the word budget feeds back into generation here.
# Text-only: the change has already been identified, so this needs no images.
# ---------------------------------------------------------------------------

SHORTEN_PROMPT = """A blind viewer is watching a video. Something changed on screen:

{changed}

There is a gap in the narration exactly long enough for {max_words} words.
Write what to say aloud, in AT MOST {max_words} words.

Keep what changed and what it means for what the viewer can do now. Drop
everything else — colour, position, styling, names of controls that do not
matter. If {max_words} words cannot carry the meaning, say the single most
important thing. Plain spoken words, no UI jargon."""


def describe_at_budget(changed, max_words, backend="anthropic"):
    from pydantic import BaseModel, Field

    class Line(BaseModel):
        description: str = Field(description=f"at most {max_words} words")

    kwargs = dict(
        max_tokens=2000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content":
                   SHORTEN_PROMPT.format(changed=changed, max_words=max_words)}],
        output_format=Line,
    )
    if backend.startswith("bedrock"):
        kwargs["model"] = BEDROCK_MODEL
        client = _client("legacy" if backend.endswith("legacy") else "mantle")
    else:
        client = _anthropic()
        kwargs["model"] = os.environ.get("SIGHTLINE_API_MODEL", "claude-opus-5")
    return client.messages.parse(**kwargs).parsed_output.description


# ---------------------------------------------------------------------------
# Ranking.
#
# "Rank the changes first, then let the gaps decide how far down the list you
#  get. Same order every time. More of it at 1x, less of it at 2x. I can live
#  with less. What I can't live with is a different story at a different speed."
#
# The tie-break is his too: a change the viewer CAUSED outranks one that merely
# happened — "I clicked something and I'm waiting to hear it took. That's the
# one I need."
# ---------------------------------------------------------------------------

RANK_PROMPT = """These changes all happened during a video, in this order. A blind
viewer cannot see any of them, and there will not be time to describe them all.

Rank them by how much each one changes what the viewer can do next. Rank 1 is
the one they most need to hear.

Tie-break, and it matters: a change the viewer CAUSED outranks a change that
merely happened. Someone who has just acted is waiting to hear that it took
effect.

Be honest about the list. If something does not really change what they can do
next, rank it last — do not pad the order to be polite.

Changes:
{items}"""


def rank_changes(changes, backend="anthropic"):
    """Return [{index, rank, caused_by_viewer, why}] covering every input."""
    from pydantic import BaseModel, Field

    class Ranked(BaseModel):
        index: int = Field(description="0-based index of the change in the input list")
        rank: int = Field(description="1 is most important")
        caused_by_viewer: bool = Field(
            description="did the viewer's own action cause this")
        why: str = Field(description="one short clause")

    class Ranking(BaseModel):
        ranked: list[Ranked]

    items = "\n".join(f"[{i}] at {c['t']}s — {c['changed']}"
                       for i, c in enumerate(changes))
    kwargs = dict(
        max_tokens=8000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": RANK_PROMPT.format(items=items)}],
        output_format=Ranking,
    )
    if backend.startswith("bedrock"):
        kwargs["model"] = BEDROCK_MODEL
        client = _client("legacy" if backend.endswith("legacy") else "mantle")
    else:
        client = _anthropic()
        kwargs["model"] = os.environ.get("SIGHTLINE_API_MODEL", "claude-opus-5")
    return [r.model_dump()
            for r in client.messages.parse(**kwargs).parsed_output.ranked]


# ---------------------------------------------------------------------------
# Film mode.
#
# The salience rule as given — "a change matters when it changes what you can do
# next" — is about software, where the viewer is the one acting. In drama the
# viewer acts on nothing, so the sibling question is what they need in order to
# FOLLOW what is happening. Same shape, different subject; kept explicitly
# separate rather than stretched to cover both.
#
# The other half is restraint: the soundtrack is already telling the viewer a
# great deal. Description that repeats the dialogue, or narrates what is
# obvious from a sound effect, spends the one resource there is least of.
# ---------------------------------------------------------------------------

FILM_PROMPT = """You are writing audio description for a film, for a viewer who
cannot see the screen. Two frames are given: the last moment that was described,
and the moment you are about to speak.

Describe what CHANGED between them.

THE TEST, and it is the only one that matters:
Will the viewer be lost thirty seconds from now without this? If not, say
nothing. They are not acting on anything — this is not about what they can do,
it is about whether they can still follow the story.

WHAT TO SPEND THE GAP ON — what is SILENT.
The soundtrack is already doing half the work. A door, footsteps, a slap, a car
pulling away, someone crying: the viewer has all of that already and does not
need it said back to them. Spend the words on what makes no sound:
- who else is present and has not spoken
- what someone is carrying, wearing, or holding
- where someone went while the music was up
- a look or gesture that changes what the next line means
- something visible that contradicts what is being said

NEVER NAME WHAT YOU CANNOT SEE.
If a sound had no visible source, say that something happened out of shot and
stop there. "Something crashes off screen" is right. Naming what fell is a
guess, and one wrong guess costs the viewer their trust in everything else you
say.

WHAT NOT TO SAY:
- anything the soundtrack already explained on its own — a door, footsteps,
  someone crying. Those sounds account for themselves and the viewer has them.
- anything the dialogue already said
{camera_rule}
- anything that describes the FILMING rather than the film. The test is not
  whether it is camera vocabulary, it is whether the viewer can use it. "She is
  crying" is usable. "Close on her face" is not — there is nothing they can do
  with where the camera is sitting. Cuts, angles, framing, focus, lighting
  setups: all unusable. "From above", "past us", "toward us" and "we see" are
  the same mistake wearing plainer clothes.
- A PERSON YOU INFERRED FROM THE VANTAGE POINT ALONE. A shot looking down
  through rafters, or past a doorway, or through leaves, MIGHT be somebody
  looking. Films do use a hidden vantage to show you a watcher — slatted
  doors, keyholes, foliage — and when they do, who is watching is often the
  most important thing in the scene and must be said.

  But the framing on its own is not evidence of it. The question is whether
  you can point to the watcher:

    SAY a watcher when a person is visible in the frame, or when the film has
    already shown you who is looking and this is plainly their view.

    DO NOT say a watcher when the only reason you think there is one is that
    the shot is high, or partly blocked, or taken through something. Describe
    what is actually in the frame instead.

  Getting this wrong in the inventing direction is the worse of the two. A
  listener cannot check an unseen watcher against the picture, so a made-up
  one becomes a fact they carry for the rest of the film, along with a threat
  that is not in it. A missed watcher costs them one detail. An invented one
  costs them the plot. When you cannot tell, describe the room.
- mood or atmosphere asserted rather than shown

AUDIO EVIDENCE FOR THIS STRETCH:
{audio_note}

You have room for AT MOST {max_words} words. Hard limit, short on purpose —
this has to fit between lines of dialogue. Present tense. Plain."""


# Whether to describe the filmmaking is a preference, not a fact, and two
# blind reviewers gave opposite answers within a week of each other.
#
# One was unambiguous that camera vocabulary is useless: "there is nothing they
# can do with where the camera is sitting". The other, asked about a high shot,
# wanted to know why the scene was shot that way -- "I even though blind
# understand and enjoy directors having their own styles of film making."
#
# Both are right about themselves, and the research says so too: studies
# comparing a standard style against a "cinematic" one that names camera work
# found most blind and partially sighted participants responded positively to
# the cinematic style, and that it increased their sense of presence.
#
# So this is a setting. The default stays plain, because a listener who does
# not want it gets nothing usable from it and it costs words that could have
# carried the story. Anyone who does want it can ask.
PLAIN_CAMERA = """- anything about where the camera is or what it is doing.
  "Close on her face" is unusable; "she is crying" is what she needs. Cuts,
  angles, framing, focus and lighting setups are all in this category."""

CINEMATIC_CAMERA = """- DO mention how a shot is made, but only when the
  making of it is doing something the story needs and you can say so in a few
  words. A held distance, a sudden closeness, a vantage the scene has not used
  before: these are choices, and a listener who enjoys how films are put
  together can use them. Two rules. Never spend words on the camera in place of
  saying what is happening -- the event comes first and the shot second, and if
  there is only room for one it is the event. And never describe an ordinary
  shot; if the framing is unremarkable, say nothing about it at all."""


def describe_film_change(before_png, after_png, max_words, dialogue="",
                         backend="anthropic", audio_note="", effort=None,
                         cinematic=False):
    from pydantic import BaseModel, Field

    class FilmCue(BaseModel):
        changed: str = Field(description="what changed between the two frames")
        worth_saying: bool = Field(
            description="does the viewer need this to follow the story")
        description: str = Field(
            description=f"what to say aloud, at most {max_words} words; "
                        f"empty if not worth saying")

    if not audio_note:
        audio_note = ("No audio analysis available — assume nothing was audible "
                      "and prefer changes that are plainly visual.")
        if dialogue.strip():
            audio_note += f' Dialogue spoken: "{dialogue}" — do not repeat it.'

    content = [
        {"type": "text", "text": "LAST DESCRIBED MOMENT:"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": _b64(before_png)}},
        {"type": "text", "text": "NOW:"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": _b64(after_png)}},
        {"type": "text", "text": FILM_PROMPT.format(
            audio_note=audio_note, max_words=max_words,
            camera_rule=CINEMATIC_CAMERA if cinematic else PLAIN_CAMERA)},
    ]
    kwargs = dict(
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": content}],
        output_format=FilmCue,
    )
    if effort:
        kwargs["output_config"] = {"effort": effort}
    if backend.startswith("bedrock"):
        kwargs["model"] = BEDROCK_MODEL
        client = _client("legacy" if backend.endswith("legacy") else "mantle")
    else:
        client = _anthropic()
        kwargs["model"] = os.environ.get("SIGHTLINE_API_MODEL", "claude-opus-5")
    return client.messages.parse(**kwargs).parsed_output.model_dump()


FILM_RANK_PROMPT = """These are the moments described in a film, in order. A blind
viewer cannot see any of it, and at higher playback speeds there will not be
time for all of them.

Rank them by how much the viewer needs each one to follow what is happening.
Rank 1 is the one they most need.

Most needed, in this order:
1. A sound with nothing visible to account for it. The viewer heard something
   and cannot work out what — it will nag at them through the next minute of
   the film. Only description can resolve it.
2. A change that made no sound at all. Invisible to them by every other route.
3. A change that made a sound with a visible cause. They have already worked
   that out; it is the first thing to cut.

Then: who someone is, where the story has moved to, what someone did that
changes the situation, something revealed or lost.

Least needed: titles, logos, credits and end cards. A viewer who misses those
misses nothing about the story — they are the first thing to cut, not the last.
Rank them at the bottom regardless of how much text they contain.

ONE EXCEPTION, and it is not a title at all: a card that gives a PLACE, a DATE,
or an elapsed time such as "three years later" is story, not decoration. Drop it
and the viewer is lost for the next five minutes without knowing why. Rank those
with the story, near the top.

Moments:
{items}"""


def rank_film_cues(cues, backend="anthropic"):
    """Rank for film. The walkthrough criterion — what can you do next — does
    not apply when the viewer is acting on nothing, and using it ranked a
    trailer's end card above the protagonist's first appearance."""
    from pydantic import BaseModel, Field

    class Ranked(BaseModel):
        index: int = Field(description="0-based index in the input list")
        rank: int = Field(description="1 is most needed")
        why: str = Field(description="one short clause")

    class Ranking(BaseModel):
        ranked: list[Ranked]

    items = "\n".join(f"[{i}] at {c['t']}s — {c['changed']}" for i, c in enumerate(cues))
    kwargs = dict(
        max_tokens=8000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": FILM_RANK_PROMPT.format(items=items)}],
        output_format=Ranking,
    )
    if backend.startswith("bedrock"):
        kwargs["model"] = BEDROCK_MODEL
        client = _client("legacy" if backend.endswith("legacy") else "mantle")
    else:
        client = _anthropic()
        kwargs["model"] = os.environ.get("SIGHTLINE_API_MODEL", "claude-opus-5")
    out = [r.model_dump() for r in client.messages.parse(**kwargs).parsed_output.ranked]
    for r in out:
        r["caused_by_viewer"] = False      # never applicable in film
    return out


# ---------------------------------------------------------------------------
# Does a sound explain itself?
#
# The rule, sharpened by the ADP list reviewer after a first pass got it wrong:
#
#   "It isn't sound present, skip it. It's sound that EXPLAINS ITSELF, skip it.
#    Sound that doesn't explain itself goes near the top... A bang with nothing
#    attached to it isn't information, it's a question, and I'll sit on that
#    question for the next minute of the film instead of following the story."
#
# So the ranking is three-tier, not two:
#
#   1. a noise with no visible cause   — highest; only description can resolve it
#   2. a silent change                 — invisible, but nothing is nagging at them
#   3. a noise with a visible cause    — lowest; they have worked it out already
#
# And a hard constraint on the writing: NEVER name what made an unseen sound.
#   "Get that wrong once and I stop trusting the whole track. 'Something crashes
#    off screen' tells me what I need without naming what fell."
# ---------------------------------------------------------------------------

ONSET_PROMPT = """Two frames from a film, a fraction of a second apart. Something
audible happened between them — a sharp rise in the soundtrack.

Does anything visible in these frames account for that sound?

Answer yes only if you can see the thing that made it, or see it happening: an
impact, a door, someone striking something, a vehicle, a fall. Movement alone is
not an explanation, and neither is a plausible guess about what is off screen.

If nothing visible accounts for it, say so. Do NOT speculate about what made it."""


def onset_has_visible_cause(before_png, after_png, backend="anthropic"):
    """Was there anything on screen to account for a sound?"""
    from pydantic import BaseModel, Field

    class Verdict(BaseModel):
        visible_cause: bool = Field(
            description="is the source of the sound visible in these frames")
        what: str = Field(
            description="the visible cause in a few words, or empty if none")

    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": _b64(before_png)}},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": _b64(after_png)}},
        {"type": "text", "text": ONSET_PROMPT},
    ]
    kwargs = dict(
        max_tokens=4000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": content}],
        output_format=Verdict,
    )
    if backend.startswith("bedrock"):
        kwargs["model"] = BEDROCK_MODEL
        client = _client("legacy" if backend.endswith("legacy") else "mantle")
    else:
        client = _anthropic()
        kwargs["model"] = os.environ.get("SIGHTLINE_API_MODEL", "claude-opus-5")
    return client.messages.parse(**kwargs).parsed_output.model_dump()


CONTINUITY_PROMPT = """These lines of audio description are spoken over one
continuous stretch of film, in this order. Each was written on its own, looking
only at its own moment, so nothing knows what any other line already said.

That produces three faults, and they are the only faults you may repair:

1. RE-INTRODUCING someone already established. Once a person has been
   described, later lines refer back to them rather than meeting them again.
   "A tattooed woman" after six lines of "she" tells the listener a second
   person has walked in.
2. WRONG OR INCONSISTENT reference. A person called "she" early and "he" later
   is one of them being wrong. Use what the lines together make most likely.
3. REPEATING a detail already given. A bloodied wing described twice, a tattoo
   noted three times. Say it once, the first time, and use those words on
   something else or say less.

You may NOT do anything else. Do not add information no line contains. Do not
describe anything not already described. Do not improve the writing, change
the tone, or make anything more vivid. If a line has none of the three faults,
return it EXACTLY as it is, character for character.

Each line has a hard word limit, given in brackets. A repaired line must be no
longer than its limit. Shorter is fine.

THE LINES:
{lines}"""


def make_continuous(descriptions, budgets, backend="anthropic", effort=None):
    """Repair references across a run of independently written descriptions.

    Returns a list the same length. Any line the model lengthens past its
    budget, or returns for an index that does not exist, falls back to the
    original: a continuity repair is worth having but never worth overrunning
    the gap it has to fit inside.
    """
    from pydantic import BaseModel, Field

    class Line(BaseModel):
        index: int = Field(description="0-based index of the line")
        text: str = Field(description="the line, repaired or unchanged")

    class Continuity(BaseModel):
        lines: list[Line]

    listing = "\n".join(
        f"[{i}] (limit {budgets[i]} words) {d}" for i, d in enumerate(descriptions))
    kwargs = dict(
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user",
                   "content": CONTINUITY_PROMPT.format(lines=listing)}],
        output_format=Continuity,
    )
    if effort:
        kwargs["output_config"] = {"effort": effort}
    if backend.startswith("bedrock"):
        kwargs["model"] = BEDROCK_MODEL
        client = _client("legacy" if backend.endswith("legacy") else "mantle")
    else:
        client = _anthropic()
        kwargs["model"] = os.environ.get("SIGHTLINE_API_MODEL", "claude-opus-5")

    fixed = list(descriptions)
    try:
        out = client.messages.parse(**kwargs).parsed_output
    except Exception as e:
        print(f"  continuity pass failed, keeping originals: {e}", file=sys.stderr)
        return fixed
    for line in out.lines:
        i = line.index
        if not (0 <= i < len(fixed)):
            continue
        if len(line.text.split()) <= budgets[i]:
            fixed[i] = line.text.strip()
    return fixed
