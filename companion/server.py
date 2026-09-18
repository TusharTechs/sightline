#!/usr/bin/env python3
"""
The companion service.

Solves the co-viewing problem: a blind viewer and a sighted viewer watch the
same thing together, and only one of them wants description. The room hears the
film untouched; the description goes to one person's phone.

This inverts the on-device audio design deliberately. In solo mode the Fire TV
plays description on a USAGE_ACCESSIBILITY stream and the film ducks under it.
In co-viewing mode the TV plays nothing extra and does not duck — the phone is
the only thing that speaks.

The TV reports where it is in the media; the phone follows. The TV never has to
listen on a socket, which is just as well since description generation already
needs a service to live in.
"""
import base64, json, os, re, struct, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "pipeline", "src"))

BUNDLE = os.environ.get("SIGHTLINE_BUNDLE", "/tmp/sightline-serve")
PORT = int(os.environ.get("SIGHTLINE_PORT", "8190"))
HERE = os.path.dirname(os.path.abspath(__file__))

# What the TV last told us. A dict rather than a class because there is exactly
# one playhead and pretending otherwise would be architecture for its own sake.
STATE = {"t": 0.0, "rate": 1.0, "mode": "solo", "playing": False, "updated": 0.0}
LOCK = threading.Lock()

# Generation progress, so the app can say what is happening rather than showing
# a spinner to someone who cannot see it.
GEN = {"running": False, "stage": "idle", "message": "", "done": 0, "total": 0,
       "ready": False, "error": None}
GEN_LOCK = threading.Lock()

# Debug channel for remote-input bring-up. The access log is suppressed, so
# beacons from the app had nowhere to land.
KEYLOG = []
PIPELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline")
PY_BIN = os.path.join(PIPELINE, ".venv", "bin", "python")


def _gen(**kw):
    with GEN_LOCK:
        GEN.update(kw)


def _run_stage(args, on_line=None):
    """Run a pipeline step, surfacing its progress lines as they appear."""
    proc = subprocess.Popen(args, cwd=PIPELINE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        line = line.rstrip()
        if on_line and line:
            on_line(line)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"{os.path.basename(args[1])} failed")


ALLOWED_SCHEMES = ("http", "https")
MAX_FETCH_BYTES = 600 * 1024 * 1024


def fetch_media(url, dest_dir):
    """Download a video the viewer asked for, into the bundle.

    The point of the whole project is content nobody has described, and until
    now the only content it could describe was the file that shipped with it.
    Someone who likes what it does to one clip immediately wants it pointed at
    the thing they actually could not watch, and there was no way to do that.

    Deliberately a direct media URL and nothing cleverer. No scraping, no
    extracting from a site that did not offer the file: what the viewer may
    fetch is their business and their right, and guessing at it on their
    behalf is how a tool ends up doing something they would not have chosen.
    """
    import urllib.parse, urllib.request

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError("only http and https URLs")

    name = os.path.basename(parsed.path) or "added.mp4"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
    if not os.path.splitext(name)[1]:
        name += ".mp4"
    dest = os.path.join(dest_dir, name)

    req = urllib.request.Request(url, headers={"User-Agent": "Sightline/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            got += len(chunk)
            if got > MAX_FETCH_BYTES:
                f.close()
                os.remove(dest)
                raise ValueError("file is larger than 600 MB")
            f.write(chunk)

    # Confirm it is really video before spending a pipeline run on it.
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", dest],
        capture_output=True, text=True)
    if "video" not in probe.stdout:
        os.remove(dest)
        raise ValueError("that URL is not a video file")
    return name


def generate(media_name):
    """Describe a video that has none, start to finish.

    Runs as a background thread and reports progress, because the whole point
    of showing this is that the work is otherwise invisible — the app plays a
    file and nothing reveals that the file was written minutes ago by looking
    at the picture.
    """
    try:
        media = os.path.join(BUNDLE, media_name)
        out = os.path.join(BUNDLE, "out")
        os.makedirs(out, exist_ok=True)
        gaps = os.path.join(out, "gaps.json")
        cues = os.path.join(out, "cues.json")
        tcache = os.path.join(out, "transcript.json")

        _gen(running=True, ready=False, error=None, done=0, total=0,
             stage="listening", message="Listening for dialogue")
        _run_stage([PY_BIN, "src/detect_speech.py", media,
                    "--cache", tcache, "--out", gaps])

        with open(gaps) as f:
            n_gaps = json.load(f)["count"]
        _gen(stage="watching", total=0,
             message=f"Found {n_gaps} places to speak. Watching what changes")

        def progress(line):
            line = line.strip()
            # Long gaps get subdivided, so the unit of work is segments, not
            # gaps — taking the total from the gap count reported done past
            # total.
            if line.startswith("progress "):
                done, total = line.split()[1].split("/")
                with GEN_LOCK:
                    GEN["done"], GEN["total"] = int(done), int(total)
                    GEN["message"] = f"Watched {done} of {total} moments"
            elif "speakable segments" in line:
                with GEN_LOCK:
                    GEN["total"] = int(line.split("->")[1].split()[0])

        _run_stage([PY_BIN, "src/film_cues.py", media, gaps,
                    "--transcript", tcache, "--rate", "1.0", "--out", cues],
                   progress)

        _gen(stage="ranking", message="Ranking what matters most")
        _run_stage([PY_BIN, "src/export_device_bundle.py", cues, media,
                    "--gaps", gaps, "--mode", "fit", "--rate", "1.0",
                    "--out", BUNDLE])

        _gen(stage="voicing", message="Preparing the voice")
        _run_stage([PY_BIN, "src/build_ui_voice.py", "--out", BUNDLE])

        _gen(running=False, ready=True, stage="ready", message="Description ready")
    except Exception as e:
        _gen(running=False, ready=False, stage="failed", error=str(e)[:200],
             message="Could not describe this")


def wav_header(nbytes, rate=48000, channels=2, bits=16):
    """Phone browsers will not play raw PCM; wrap it on the way out."""
    byte_rate = rate * channels * bits // 8
    block = channels * bits // 8
    return (b"RIFF" + struct.pack("<I", 36 + nbytes) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, channels, rate, byte_rate, block, bits)
            + b"data" + struct.pack("<I", nbytes))


ANSWER_PROMPT = """A blind viewer is watching a film and has stopped to ask you
a question. The frame they are on is attached, and below it is everything the
film has given them so far: every line of dialogue that has been spoken, and
every description they have heard.

Their question: "{question}"

Answer it. Nothing else.

- Use ALL of it. The answer may be in the frame, or in something said twenty
  minutes ago, or in a description they heard earlier and have half forgotten.
  A question like "what's the dagger about" is not answerable from a picture
  and is answerable from the dialogue. Look everywhere before giving up.
- Answer ONLY what was asked. Do not narrate the scene or set it up. They
  asked because the description did not cover it; a second description is not
  an answer.
- NEVER go past the moment they are at. You can see the whole film; they
  cannot. Anything that has not happened yet is a spoiler, and a viewer who
  learns the ending from the help feature has been robbed of the film. If the
  answer only exists later, say that it has not been explained yet.
- If nothing you have answers it, say so plainly in a few words. "That hasn't
  been explained yet" and "I can't see that from here" are both real answers.
  Guessing is worse than either.
- At most {max_words} words. Spoken aloud, present tense, plain.
- Do not describe the filming — angles, framing, focus, lighting.

WHAT THEY HAVE HEARD SO FAR
{context}"""


def _frame_at(media, t, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
                    "-i", media, "-frames:v", "1", "-vf", "scale=1280:-2", out],
                   check=True)


def dialogue_up_to(t):
    """Every line of dialogue spoken before this moment, with its timing.

    Read from the Transcribe result the pipeline already caches. Words are
    grouped into lines on pauses, which is close enough to sentences to be
    readable and does not need punctuation the transcript may not carry.
    """
    for path in (os.path.join(BUNDLE, "out", "transcript.json"),
                 os.path.join(BUNDLE, "transcript.json")):
        if os.path.exists(path):
            break
    else:
        return []
    try:
        items = json.load(open(path))["results"]["items"]
    except Exception:
        return []

    lines, cur, start, last = [], [], None, None
    for it in items:
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


# 30 was the limit while answers came from a single frame, where there is not
# much to say. With the dialogue and the description history in scope, a good
# answer often needs to cite what was said and by whom -- "she calls the dragon
# a kindred spirit, the stranger is the one calling her a hunter" does not fit
# in 30 and is worth more than a shorter one. Measured answers to real
# questions ran to about 35, so the stated limit is now one the model can
# actually keep.
def answer_question(question, t, max_words=45):
    """Look at the frame the viewer is on, and answer what they asked.

    This is the thing a pre-recorded description track structurally cannot do.
    Every batch tool decides in advance what is worth saying; only something
    running at playback time can answer a question about the frame in front of
    you, and only because the viewer is the one who chose the moment.
    """
    import salience
    from speech import synthesize

    with LOCK:
        tl = STATE.get("timeline_cache")
    tlp = os.path.join(BUNDLE, "timeline.json")
    tl = json.load(open(tlp)) if os.path.exists(tlp) else None
    if not tl:
        return {"error": "no timeline loaded"}

    media = os.path.join(BUNDLE, tl["media"])

    # Everything the viewer has been given, not just the last few lines.
    #
    # This used to pass the four most recent descriptions and one frame, which
    # answers "what is on screen" and nothing else. A blind reviewer asked what
    # the dagger was about and why a character was bound -- neither is in any
    # frame, both are in dialogue from minutes earlier. The transcript and the
    # full description history are already sitting on disk; not passing them
    # was the only reason those questions could not be answered.
    said = [c for c in sorted(tl["cues"], key=lambda c: c["t"]) if c["t"] <= t]
    parts = []
    if said:
        parts.append("Descriptions they have heard, in order:\n"
                     + "\n".join(f"  [{c['t']:.0f}s] {c['text']}" for c in said))
    else:
        parts.append("Nothing has been described yet.")

    spoken = dialogue_up_to(t)
    if spoken:
        parts.append("Dialogue spoken so far, in order:\n"
                     + "\n".join(f"  [{ts:.0f}s] {txt}" for ts, txt in spoken))
    else:
        parts.append("No dialogue has been spoken yet.")

    parts.append(f"They are {t:.0f} seconds in. Nothing after this has "
                 f"happened for them yet.")
    context = "\n\n".join(parts)

    with tempfile.TemporaryDirectory() as td:
        png = os.path.join(td, "f.png")
        _frame_at(media, t, png)

        from pydantic import BaseModel, Field

        class Answer(BaseModel):
            answer: str = Field(description=f"at most {max_words} words")
            can_see: bool = Field(description="was the answer visible in the frame")

        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.standard_b64encode(
                                             open(png, "rb").read()).decode()}},
            {"type": "text", "text": ANSWER_PROMPT.format(
                question=question, max_words=max_words, context=context)},
        ]
        import anthropic
        client = anthropic.Anthropic()
        parsed = client.messages.parse(
            model=os.environ.get("SIGHTLINE_API_MODEL", "claude-opus-5"),
            max_tokens=8000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": content}],
            output_format=Answer,
        ).parsed_output

        name = f"answer-{int(time.time()*1000)}.pcm"
        meta = synthesize(parsed.answer, os.path.join(BUNDLE, name))

    return {"answer": parsed.answer, "can_see": parsed.can_see,
            "audio": name.replace(".pcm", ".wav"), "duration": meta["duration_s"],
            "asked_at": round(t, 2)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # the access log was only ever noise here

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, b"", extra={"Access-Control-Allow-Headers": "Content-Type",
                                    "Access-Control-Allow-Methods": "GET,POST,OPTIONS"})

    def do_POST(self):
        if self.path == "/generate":
            n = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                data = {}
            with GEN_LOCK:
                if GEN["running"]:
                    return self._send(409, json.dumps({"error": "already running"}))
            url = (data.get("url") or "").strip()
            media = data.get("media", "content.mp4")
            if url:
                # Fetch before claiming the run, so a bad URL fails fast and
                # does not leave the UI waiting on a job that never starts.
                try:
                    media = fetch_media(url, BUNDLE)
                except Exception as e:
                    return self._send(400, json.dumps(
                        {"error": f"could not fetch that: {str(e)[:120]}"}))
            # Reset synchronously, before the worker starts. The caller polls
            # immediately, and a stale "ready" from the previous run would send
            # it straight to playback of a description that no longer exists.
            _gen(running=True, ready=False, error=None, done=0, total=0,
                 stage="starting", message="Starting")
            threading.Thread(target=generate, args=(media,), daemon=True).start()
            return self._send(202, json.dumps({"started": True, "media": media}))

        if self.path == "/ask":
            n = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                data = {}
            q = (data.get("question") or "").strip()
            if not q:
                return self._send(400, json.dumps({"error": "no question"}))
            # The viewer chose this moment; use where the TV actually is.
            with LOCK:
                t = float(data.get("t", STATE.get("t", 0.0)))
            try:
                return self._send(200, json.dumps(answer_question(q, t)))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)[:200]}))

        if self.path != "/position":
            return self._send(404, b"{}")
        n = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            data = {}
        with LOCK:
            STATE.update({k: data[k] for k in ("t", "rate", "mode", "playing")
                          if k in data})
            STATE["updated"] = time.time()
        self._send(200, b'{"ok":true}')

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/phone", "/phone.html"):
            with open(os.path.join(HERE, "phone.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")

        if path.startswith("/KEY/"):
            import urllib.parse
            KEYLOG.append({"at": round(time.time(), 2),
                           "raw": urllib.parse.unquote(path[5:])})
            del KEYLOG[:-60]
            return self._send(200, b'{"ok":true}')

        if path == "/keys":
            return self._send(200, json.dumps(KEYLOG[-30:], indent=2))

        if path == "/generate/status":
            with GEN_LOCK:
                return self._send(200, json.dumps(dict(GEN)))

        if path == "/state":
            with LOCK:
                s = dict(STATE)
            # How stale is this? The phone needs to know the TV is still talking.
            s["age"] = round(time.time() - s["updated"], 2) if s["updated"] else None
            tl = os.path.join(BUNDLE, "timeline.json")
            s["timeline"] = json.load(open(tl)) if os.path.exists(tl) else None
            return self._send(200, json.dumps(s))

        # Description audio, PCM on disk, WAV on the wire.
        if path.endswith(".wav"):
            pcm = os.path.join(BUNDLE, os.path.basename(path)[:-4] + ".pcm")
            if os.path.exists(pcm):
                raw = open(pcm, "rb").read()
                return self._send(200, wav_header(len(raw)) + raw, "audio/wav")

        local = os.path.join(BUNDLE, os.path.basename(path))
        if os.path.isfile(local):
            ctype = ("video/mp4" if local.endswith(".mp4")
                     else "application/json" if local.endswith(".json")
                     else "application/octet-stream")
            with open(local, "rb") as f:
                return self._send(200, f.read(), ctype)

        self._send(404, b'{"error":"not found"}')


def _port_already_answering(port):
    """Is something else already serving here?

    Binding 0.0.0.0 succeeds even when another process holds 127.0.0.1 on the
    same port, and the more specific bind wins for localhost. The result is two
    servers, no error, and requests silently reaching the wrong one — which is
    exactly what happened, and looked like our own service hanging.
    """
    import urllib.error, urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/state", timeout=1.5).read()
        return True
    except urllib.error.HTTPError:
        return True          # something answered, just not with 200
    except Exception:
        return False


if __name__ == "__main__":
    if _port_already_answering(PORT):
        raise SystemExit(
            f"refusing to start: something is already answering on port {PORT}.\n"
            f"  check with:  lsof -nP -iTCP:{PORT} -sTCP:LISTEN\n"
            f"  or choose another:  SIGHTLINE_PORT=8191 ...")
    print(f"companion service on :{PORT}, serving {BUNDLE}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
