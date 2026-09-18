"""
Answer a blind viewer's question about the moment they are on.

This is the one thing a pre-rendered description track structurally cannot do:
the question does not exist when the track is made. It ran only against a
local service, which meant the people it was built for could not reach it --
the public demo is static files, and a static page cannot hold an API key.

Deliberately no dependencies beyond the runtime. The model is called over
plain HTTPS rather than through an SDK, so the deployment is one file with no
packaging step and nothing to go stale. boto3 for Polly is already present.

Everything it reads is published static: the frame for that second, the
timeline of descriptions, and the transcript. It never downloads the video.
"""
import base64
import json
import os
import urllib.error
import urllib.request

SITE = os.environ.get("SIGHTLINE_SITE", "https://tushartechs.github.io/sightline")
MODEL = os.environ.get("SIGHTLINE_MODEL", "claude-opus-5")
VOICE = os.environ.get("SIGHTLINE_VOICE", "Ruth")
MAX_WORDS = 45
MAX_QUESTION = 300
# Only these may be asked about. A public endpoint that will fetch and reason
# about any URL handed to it is a different and much worse thing than this.
VIDEOS = {"": "", "film": "film/", "duck": "duck/"}

PROMPT = """A blind viewer is watching a film and has stopped to ask you a
question. The frame they are on is attached, and below it is everything the
film has given them so far: every line of dialogue spoken, and every
description they have heard.

Their question: "{question}"

Answer it. Nothing else.

- Use ALL of it. The answer may be in the frame, or in something said minutes
  ago, or in a description they half remember. A question like "what's the
  dagger about" is not answerable from a picture and is answerable from the
  dialogue. Look everywhere before giving up.
- Answer ONLY what was asked. They asked because the description did not cover
  it; a second description is not an answer.
- NEVER go past the moment they are at. You can see what they cannot. Anything
  that has not happened yet is a spoiler, and a viewer who learns the ending
  from the help feature has been robbed of the film. If the answer only comes
  later, say it has not been explained yet.
- If nothing you have answers it, say so plainly. "That hasn't been explained
  yet" and "I can't see that from here" are both real answers. Guessing is
  worse than either.
- At most {max_words} words. Spoken aloud, present tense, plain.
- Do not describe the filming -- angles, framing, focus, lighting.

WHAT THEY HAVE HEARD SO FAR
{context}"""


def _get(url, binary=False):
    with urllib.request.urlopen(url, timeout=15) as r:
        raw = r.read()
    return raw if binary else json.loads(raw)


def dialogue_up_to(transcript, t):
    """Lines of dialogue spoken before this moment, grouped on pauses."""
    lines, cur, start, last = [], [], None, None
    for it in transcript.get("results", {}).get("items", []):
        if it.get("type") != "pronunciation":
            if cur:
                cur[-1] += it["alternatives"][0]["content"]
            continue
        s0, e0 = float(it["start_time"]), float(it["end_time"])
        if s0 > t:
            break
        if last is not None and s0 - last > 1.2 and cur:
            lines.append((start, " ".join(cur)))
            cur, start = [], None
        if start is None:
            start = s0
        cur.append(it["alternatives"][0]["content"])
        last = e0
    if cur:
        lines.append((start, " ".join(cur)))
    return lines


def build_context(timeline, transcript, t):
    said = [c for c in sorted(timeline["cues"], key=lambda c: c["t"]) if c["t"] <= t]
    parts = []
    parts.append("Descriptions they have heard, in order:\n"
                 + "\n".join(f"  [{c['t']:.0f}s] {c['text']}" for c in said)
                 if said else "Nothing has been described yet.")
    spoken = dialogue_up_to(transcript, t)
    parts.append("Dialogue spoken so far, in order:\n"
                 + "\n".join(f"  [{ts:.0f}s] {tx}" for ts, tx in spoken)
                 if spoken else "No dialogue has been spoken yet.")
    parts.append(f"They are {t:.0f} seconds in. Nothing after this has "
                 f"happened for them yet.")
    return "\n\n".join(parts)


def ask_model(frame_jpg, question, context):
    body = {
        "model": MODEL,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/jpeg",
                                         "data": base64.b64encode(frame_jpg).decode()}},
            {"type": "text", "text": PROMPT.format(
                question=question, max_words=MAX_WORDS, context=context)},
        ]}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json",
                 "anthropic-version": "2023-06-01",
                 "x-api-key": os.environ["ANTHROPIC_API_KEY"]})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    return "".join(b.get("text", "") for b in out.get("content", [])).strip()


def speak(text):
    """Polly, returned inline. The answer is short, so base64 in the response
    avoids a bucket, a signed URL and a second round trip on a slow phone."""
    import boto3
    polly = boto3.client("polly")
    audio = polly.synthesize_speech(
        Text=text, OutputFormat="mp3", VoiceId=VOICE, Engine="generative"
    )["AudioStream"].read()
    return base64.b64encode(audio).decode()


def _reply(code, payload):
    return {"statusCode": code,
            "headers": {"content-type": "application/json",
                        "access-control-allow-origin": "*"},
            "body": json.dumps(payload)}


def lambda_handler(event, context):
    if (event.get("requestContext", {}).get("http", {}).get("method")
            == "OPTIONS"):
        return {"statusCode": 204,
                "headers": {"access-control-allow-origin": "*",
                            "access-control-allow-headers": "content-type",
                            "access-control-allow-methods": "POST, OPTIONS"}}
    try:
        data = json.loads(event.get("body") or "{}")
    except ValueError:
        return _reply(400, {"error": "bad request"})

    question = (data.get("question") or "").strip()[:MAX_QUESTION]
    if not question:
        return _reply(400, {"error": "no question"})
    video = data.get("video", "")
    if video not in VIDEOS:
        return _reply(400, {"error": "unknown video"})
    try:
        t = max(0.0, float(data.get("t", 0)))
    except (TypeError, ValueError):
        return _reply(400, {"error": "bad timestamp"})

    base = f"{SITE}/{VIDEOS[video]}"
    try:
        timeline = _get(base + "timeline.json")
        transcript = _get(base + "transcript.json")
        frame = _get(f"{base}frames/{int(t) + 1:05d}.jpg", binary=True)
    except urllib.error.HTTPError:
        # Past the last extracted second, or the clip has no frame there.
        return _reply(404, {"error": "no frame for that moment"})

    answer = ask_model(frame, question, build_context(timeline, transcript, t))
    if not answer:
        return _reply(502, {"error": "no answer"})

    payload = {"answer": answer, "asked_at": round(t, 2)}
    try:
        payload["audio_mp3_b64"] = speak(answer)
    except Exception as e:                      # speech is a bonus, not the answer
        payload["speech_error"] = type(e).__name__
    return _reply(200, payload)
