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
import json, os, struct, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BUNDLE = os.environ.get("SIGHTLINE_BUNDLE", "/tmp/sightline-serve")
PORT = int(os.environ.get("SIGHTLINE_PORT", "8099"))
HERE = os.path.dirname(os.path.abspath(__file__))

# What the TV last told us. A dict rather than a class because there is exactly
# one playhead and pretending otherwise would be architecture for its own sake.
STATE = {"t": 0.0, "rate": 1.0, "mode": "solo", "playing": False, "updated": 0.0}
LOCK = threading.Lock()


def wav_header(nbytes, rate=48000, channels=2, bits=16):
    """Phone browsers will not play raw PCM; wrap it on the way out."""
    byte_rate = rate * channels * bits // 8
    block = channels * bits // 8
    return (b"RIFF" + struct.pack("<I", 36 + nbytes) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, channels, rate, byte_rate, block, bits)
            + b"data" + struct.pack("<I", nbytes))


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
