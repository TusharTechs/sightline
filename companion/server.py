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
import base64, json, os, struct, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "pipeline", "src"))

BUNDLE = os.environ.get("SIGHTLINE_BUNDLE", "/tmp/sightline-serve")
PORT = int(os.environ.get("SIGHTLINE_PORT", "8099"))
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


ANSWER_PROMPT = """A blind viewer is watching a film and has paused to ask you a
question about what is on screen right now. The frame is attached.

Their question: "{question}"

Answer it. Nothing else.

- Answer ONLY what was asked. Do not narrate the scene, do not set it up, do not
  add what you think they might want next. They asked a question because the
  description did not cover it; a second description is not an answer.
- If the frame does not show the answer, say so plainly in a few words. Guessing
  is worse than "I can't see that from here".
- At most {max_words} words. Spoken aloud, present tense, plain.
- Do not describe the filming — angles, framing, focus, lighting. Only what is
  in the picture.

{context}"""


def _frame_at(media, t, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
                    "-i", media, "-frames:v", "1", "-vf", "scale=1280:-2", out],
                   check=True)


def answer_question(question, t, max_words=30):
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
    said = [c["text"] for c in sorted(tl["cues"], key=lambda c: c["t"]) if c["t"] <= t]
    context = ("Already described to them, so do not repeat it:\n"
               + "\n".join(f"- {x}" for x in said[-4:])) if said else \
              "Nothing has been described yet."

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
            media = data.get("media", "content.mp4")
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


if __name__ == "__main__":
    print(f"companion service on :{PORT}, serving {BUNDLE}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
