#!/usr/bin/env python3
"""
Silent communication — hand signs, gestures, sign language, and written signs.

Amazon Transcribe only hears spoken audio. When someone on screen communicates
without speaking — by holding up fingers, nodding or shaking their head, putting
a finger to their lips, pointing, signing in ASL or BSL, or holding up a written
note or placard — speech-to-text records silence.

Worse, a two-frame comparison (BEFORE at the previous cue and AFTER at the start
of the next gap) routinely misses gestures altogether. A hand sign is a movement
with a trajectory: the hand rises, holds for a beat, and drops before the next
line of dialogue ends. Sampling only the endpoints sees two frames with hands at
rest and concludes nothing happened.

So this module samples a chronological strip of frames across the stretch, asks
whether any silent sign or gesture occurred across those frames, and produces
both:
  1. A plain spoken line (synthesised via Amazon Polly) that translates the
     meaning rather than describing hand geometry.
  2. A structured transcript entry (`[Sign: ...]`, `[Gesture: ...]`,
     `[On-screen sign: ...]`) so the silent communication sits alongside spoken
     dialogue in the timeline and question-answering context.
"""
import argparse, base64, copy, json, os, subprocess, sys, tempfile
from typing import Literal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from salience import BEDROCK_MODEL, _anthropic, _b64, _client
from speech import budget_words, synthesize

STRIP_FRAMES = 4
STRIP_WIDTH = 960
SIGN_KINDS = ("none", "gesture", "sign_language", "written_sign")

SIGN_PROMPT = """You are examining a chronological sequence of frames from a
video for a blind viewer.

Amazon Transcribe has already captured the spoken dialogue. Your task is to catch
what the microphone CANNOT hear: deliberate silent communication made with the
hands, body, or written signs in the scene.

Look across the frame sequence in order for any of these three things:

1. `gesture` — a deliberate hand sign or bodily gesture that carries meaning:
   holding up fingers for a number, thumbs-up or thumbs-down, a finger to the
   lips for silence, pointing at something specific, beckoning or waving someone
   back, a raised palm to stop, nodding yes, shaking the head no, a salute, or
   handing over / refusing an object.
   Do NOT report ordinary talking-with-hands movement or walking.

2. `sign_language` — sign language (such as ASL or BSL) words, fingerspelling,
   or signed phrases. Sign language IS the speaker's voice: a blind viewer
   wants to lean back and hear what the person is saying, not be told "She
   signs..." before every sentence. Read the recognizable signs, fingerspelled
   letters, and facial grammar across the frame sequence and write both
   `raw_meaning` and `spoken_description` as the **direct spoken translation**
   of what is being communicated (for example: `"Parents supporting children,
   with interpreter Amy Peterson."`, `"Second: talk openly and listen to one
   another."`, `"Work together and support each other as a family."`, `"Keep
   clear rules and explain each step carefully."`).
   Do NOT prefix `spoken_description` with `"She signs"`, `"He signs"`, or
   `"A woman signs about"` — voice the signed meaning directly, as an
   interpreter speaking for the signer. Never describe mechanical hand geometry
   ("places closed fist on flat palm"), and never output meta-disclaimers such
   as "Unclear" or "exact words cannot be read from these frames".

3. `written_sign` — a written sign, held-up note, placard, label, street or door
   sign, lower-third identification, or text message on a screen that a
   character shows or looks at in the scene, or a title card that gives the
   topic, place, date, or speaker.
   Do NOT report studio logos, opening credits, or decorative end cards.

HARD RULES:
- Never output meta-commentary about frame sampling or legibility (never write
  "Unclear", "cannot be read reliably", or "exact words aren't clear"). Report
  what you can genuinely read from the signs, gestures, and on-screen text.
- Do not repeat information already spoken aloud in the dialogue: "{dialogue}"
- Write `spoken_description` for a listener, in at most {max_words} words,
  present tense, plain spoken English, no camera vocabulary."""


def sample_strip_times(start_s, end_s, count=STRIP_FRAMES):
    """Evenly spaced timestamps across [start_s, end_s] for gesture capture.

    Avoids the exact boundary endpoints by sitting at the centres of `count`
    equal sub-intervals, so cuts right on `start_s` or `end_s` do not waste a
    frame on the neighbouring shot.
    """
    s0 = max(0.0, float(start_s))
    s1 = max(s0, float(end_s))
    n = max(1, int(count))
    span = s1 - s0
    if span <= 1e-6 or n == 1:
        return [round(s0 + span * 0.5, 3)]
    step = span / n
    return [round(s0 + (i + 0.5) * step, 3) for i in range(n)]


def extract_strip(media, start_s, end_s, out_dir, tag="s",
                  count=STRIP_FRAMES, width=STRIP_WIDTH):
    """Extract a chronological strip of frames across [start_s, end_s]."""
    times = sample_strip_times(start_s, end_s, count)
    frames = []
    for k, t in enumerate(times):
        out = os.path.join(out_dir, f"{tag}_{k:02d}.png")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
             "-i", media, "-frames:v", "1", "-vf", f"scale={width}:-2", out],
            check=True,
        )
        frames.append({"t": t, "path": out})
    return frames


def format_transcript_entry(kind, raw_meaning, spoken_description=""):
    """Format a recognized sign or gesture as a readable transcript line."""
    meaning = (raw_meaning or "").strip()
    spoken = (spoken_description or "").strip()
    if meaning.lower().startswith("unclear"):
        meaning = ""
    body = meaning or spoken
    if not body or kind not in SIGN_KINDS or kind == "none":
        return ""
    if kind == "sign_language":
        return f'[Sign: "{meaning}"]' if meaning else f"[Sign: {spoken}]"
    if kind == "written_sign":
        return f'[On-screen sign: "{meaning}"]' if meaning else f"[On-screen sign: {spoken}]"
    if kind == "gesture":
        return f"[Gesture: {body}]"
    return ""


def describe_signs_for_prompt(verdict):
    """Format a sign-detection verdict as evidence for `FILM_PROMPT`."""
    if not verdict or not verdict.get("found"):
        return ""
    kind = verdict.get("kind", "none")
    meaning = (verdict.get("raw_meaning") or "").strip()
    spoken = (verdict.get("spoken_description") or "").strip()
    detail = meaning or spoken
    if not detail or kind == "none":
        return ""
    label = {
        "gesture": "Silent hand sign / gesture detected across the multi-frame strip of this stretch",
        "sign_language": "Sign-language communication detected across the multi-frame strip of this stretch",
        "written_sign": "Readable on-screen sign / text detected across the multi-frame strip of this stretch",
    }.get(kind, "Silent visual sign detected")
    return (f"{label}: {detail} "
            f"(suggested spoken line: \"{spoken or detail}\"). "
            f"Because BEFORE and AFTER are only two endpoint frames, include "
            f"this signed meaning or gesture in your spoken description.")


def merge_signs_into_transcript(transcript, sign_cues):
    """Return a copy of `transcript` enriched with recognized silent signs.

    Leaves `results.items` intact for word-timing consumers while adding a
    chronological `results.signs` list so transcript readers and the live
    question-answering context can see every gesture, signed phrase, and
    written sign alongside spoken dialogue.
    """
    out = copy.deepcopy(transcript) if transcript else {"results": {"items": []}}
    results = out.setdefault("results", {})
    results.setdefault("items", [])
    entries = []
    for c in sorted(sign_cues or [], key=lambda x: float(x.get("t", 0.0))):
        sign = c.get("sign") if isinstance(c.get("sign"), dict) else c
        if not sign or not sign.get("found", True):
            continue
        kind = sign.get("kind", "none")
        if kind == "none":
            continue
        t = round(float(c.get("t", sign.get("t", 0.0))), 3)
        raw = (sign.get("raw_meaning") or "").strip()
        spoken = (sign.get("spoken_description") or c.get("description") or "").strip()
        entry = (sign.get("transcript_entry")
                 or format_transcript_entry(kind, raw, spoken))
        if not entry:
            continue
        entries.append({
            "t": t,
            "kind": kind,
            "raw_meaning": raw,
            "spoken_description": spoken,
            "transcript_entry": entry,
        })
    results["signs"] = entries
    return out


def detect_signs(frames, max_words=14, dialogue="", backend="anthropic",
                 effort=None):
    """Inspect a chronological sequence of frames for signs or gestures.

    `frames` may be a list of file paths or a list of `{"t": float, "path": str}`
    dicts. Returns `{found, kind, raw_meaning, transcript_entry, spoken_description}`.
    """
    from pydantic import BaseModel, Field

    class SignVerdict(BaseModel):
        found: bool = Field(
            description="was a meaningful gesture, sign-language sign, or story-relevant written sign present")
        kind: Literal["none", "gesture", "sign_language", "written_sign"] = Field(
            description="category of silent sign, or 'none'")
        raw_meaning: str = Field(
            description="the translated word/phrase for sign language, the literal text for a written sign, or the meaning of the gesture; empty if none")
        spoken_description: str = Field(
            description=f"what to say aloud to a blind viewer in at most {max_words} words; empty if not found")

    if not frames:
        return {"found": False, "kind": "none", "raw_meaning": "",
                "transcript_entry": "", "spoken_description": ""}

    content = []
    for idx, item in enumerate(frames, 1):
        if isinstance(item, dict):
            path = item["path"]
            label = f"FRAME {idx} (at {item.get('t', 0.0):.2f}s):"
        else:
            path = str(item)
            label = f"FRAME {idx}:"
        media_type = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
        content.append({"type": "text", "text": label})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": media_type, "data": _b64(path),
        }})

    content.append({"type": "text", "text": SIGN_PROMPT.format(
        dialogue=dialogue or "(none)", max_words=max_words,
    )})

    kwargs = dict(
        max_tokens=8000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": content}],
        output_format=SignVerdict,
    )
    if effort:
        kwargs["output_config"] = {"effort": effort}
    if backend.startswith("bedrock"):
        kwargs["model"] = BEDROCK_MODEL
        client = _client("legacy" if backend.endswith("legacy") else "mantle")
    else:
        client = _anthropic()
        kwargs["model"] = os.environ.get("SIGHTLINE_API_MODEL", "claude-opus-5")

    parsed = client.messages.parse(**kwargs).parsed_output.model_dump()
    if not parsed.get("found") or parsed.get("kind") == "none":
        return {"found": False, "kind": "none", "raw_meaning": "",
                "transcript_entry": "", "spoken_description": ""}

    entry = format_transcript_entry(
        parsed["kind"], parsed["raw_meaning"], parsed["spoken_description"]
    )
    return {
        "found": True,
        "kind": parsed["kind"],
        "raw_meaning": parsed["raw_meaning"].strip(),
        "transcript_entry": entry,
        "spoken_description": parsed["spoken_description"].strip(),
    }


def main():
    p = argparse.ArgumentParser(
        description="Detect hand signs, gestures, sign language, and written signs in video.")
    p.add_argument("media", help="path to video file")
    p.add_argument("--start", type=float, default=0.0, help="window start in seconds")
    p.add_argument("--end", type=float, default=4.0, help="window end in seconds")
    p.add_argument("--frames", type=int, default=STRIP_FRAMES,
                   help="number of frames to sample across the window")
    p.add_argument("--max-words", type=int, default=14)
    p.add_argument("--backend", default="anthropic")
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--pcm-out", help="optional path to synthesise spoken audio (.pcm)")
    p.add_argument("--out", required=True, help="output JSON path")
    a = p.parse_args()

    with tempfile.TemporaryDirectory() as td:
        strip = extract_strip(a.media, a.start, a.end, td, count=a.frames)
        verdict = detect_signs(strip, max_words=a.max_words,
                               backend=a.backend, effort=a.effort)
        if verdict["found"] and a.pcm_out and verdict["spoken_description"]:
            meta = synthesize(verdict["spoken_description"], a.pcm_out)
            verdict["speech_s"] = meta["duration_s"]
            verdict["pcm"] = a.pcm_out

    payload = {
        "media": a.media,
        "start": a.start,
        "end": a.end,
        "frames_sampled": a.frames,
        "sign": verdict,
    }
    with open(a.out, "w") as f:
        json.dump(payload, f, indent=2)
    status = verdict["transcript_entry"] if verdict["found"] else "none"
    print(f"signs [{a.start:.1f}s..{a.end:.1f}s] -> {status}", file=sys.stderr)


if __name__ == "__main__":
    main()
