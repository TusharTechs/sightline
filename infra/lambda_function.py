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


def recap(timeline, transcript, t, limit=3):
    """What has been described and said around this moment, without a model.

    The model is not always there. It was refused for a fortnight because a
    workspace spend limit had been reached, and Bedrock is blocked on this
    account entirely. A blind viewer who asks a question and gets an error has
    been handed nothing, which is the state this whole project exists to
    remove.

    So when the model will not answer, say what is actually known: the last few
    descriptions and the last few lines of dialogue before this second. It is
    not an answer and it is never presented as one. It is the difference
    between "I cannot help" and "here is what you have been told so far".
    """
    said = [c for c in sorted(timeline["cues"], key=lambda c: c["t"]) if c["t"] <= t]
    spoken = dialogue_up_to(transcript, t)
    bits = []
    if said:
        recent = said[-limit:]
        bits.append("Described so far: " + " ".join(c["text"] for c in recent))
    if spoken:
        recent = spoken[-limit:]
        bits.append("Said so far: " + " ".join(tx for _, tx in recent))
    if not bits:
        return "Nothing has been described or said yet at this point."
    return " ".join(bits)


class ModelRefused(Exception):
    """The model service answered, and said no.

    Distinct from the function falling over, and the difference is the whole
    point of reporting it: a judge hitting a 500 cannot tell a broken
    deployment from a model that declined the request.
    """


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
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        # Read the body. Without this a 400 from the model surfaces as
        # "Internal Server Error" and nobody can say why, which is how this
        # endpoint sat failing. The key is not in the body and is never logged.
        try:
            detail = json.loads(e.read()).get("error", {})
            msg = f"{detail.get('type', e.code)}: {detail.get('message', '')}"
        except Exception:
            msg = f"HTTP {e.code}"
        print(f"[ask] model refused: {msg}")
        raise ModelRefused(msg) from None
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


def _health(probe=False):
    """What this deployment can and cannot currently do.

    A judge should not have to POST a question to find out whether the
    endpoint is up. But a cheap check can only see configuration, and
    configuration being right is not the same as the thing working: this
    reported "ok" for a week while every question was being refused, because
    the workspace had hit a spend limit the check could not see.

    So the cheap answer says exactly what it checked, and `?probe=1` spends one
    very small model call to answer the question it cannot otherwise answer.
    """
    ok_key = bool(os.environ.get("ANTHROPIC_API_KEY")
                  or os.environ.get("SIGHTLINE_KEY_SECRET_ARN"))
    model_state = "not checked, pass ?probe=1 to actually try it"
    if probe and ok_key:
        try:
            ask_model(b"", "ping", "")
            model_state = "answering"
        except ModelRefused as e:
            print(f"model refused on probe: {e}")   # detail to the log, not the caller
            model_state = "refusing"
        except Exception as e:
            model_state = f"unreachable: {type(e).__name__}"
    reachable = {}
    for name, path in VIDEOS.items():
        try:
            _get(f"{SITE}/{path}timeline.json")
            reachable[name] = "ok"
        except Exception as e:
            reachable[name] = f"unreachable: {type(e).__name__}"
    configured = ok_key and all(v == "ok" for v in reachable.values())
    healthy = configured and (not probe or model_state == "answering")
    return _reply(200 if healthy else 503, {
        "checked": "configuration and content reachability"
                   + (", and the model itself" if probe else ""),
        "status": "ok" if healthy else "degraded",
        "model_key": "configured" if ok_key else "missing",
        "model": model_state,
        "voice": VOICE,
        "site": SITE,
        "timelines": reachable,
    })


def lambda_handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    if http.get("method") == "OPTIONS":
        return {"statusCode": 204,
                "headers": {"access-control-allow-origin": "*",
                            "access-control-allow-headers": "content-type",
                            "access-control-allow-methods": "GET, POST, OPTIONS"}}
    if http.get("method") == "GET" or (http.get("path") or "").endswith("/health"):
        q = event.get("queryStringParameters") or {}
        return _health(probe=str(q.get("probe", "")).lower() in ("1", "true", "yes"))
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

    degraded = None
    try:
        answer = ask_model(frame, question, build_context(timeline, transcript, t))
    except ModelRefused as e:
        # Answer with what is known rather than with an error. Labelled, so
        # nobody mistakes a recap for the answer they asked for.
        answer = recap(timeline, transcript, t)
        # The upstream body can name the account, the workspace or the billing
        # state, and this endpoint is public. Log the detail, publish the fact.
        print(f"model refused: {e}")
        degraded = True
    if not answer:
        return _reply(502, {"error": "no answer"})

    payload = {"answer": answer, "asked_at": round(t, 2)}
    if degraded:
        payload["answered_from"] = ("the descriptions and dialogue so far, not "
                                    "the frame: the model was unavailable")
        payload["model_unavailable"] = "the model did not answer"
    try:
        payload["audio_mp3_b64"] = speak(answer)
    except Exception as e:                      # speech is a bonus, not the answer
        payload["speech_error"] = type(e).__name__
    return _reply(200, payload)
