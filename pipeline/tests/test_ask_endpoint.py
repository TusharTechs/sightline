"""Tests for the hosted question-answering endpoint.

Protects the four rules the endpoint exists to enforce:
  - Nothing after the viewer's playhead may enter the prompt (no spoilers).
  - The health probe does not send an empty image block that the model rejects.
  - Asking at the fractional end of a clip steps back to the final extracted frame.
  - When the model refuses, the caller still receives what was described and said so far.
"""
import io, json, os, sys, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "infra"))
import lambda_function as ask_fn


TIMELINE = {
    "media": "content.mp4",
    "cues": [
        {"t": 5.0, "rank": 1, "text": "A woman climbs a snowy ridge."},
        {"t": 20.0, "rank": 2, "text": "A staff lies in the snow."},
        {"t": 45.0, "rank": 3, "text": "A dragon rises from the cliff."},
    ],
}

TRANSCRIPT = {
    "results": {
        "items": [
            {"type": "pronunciation", "start_time": "10.0", "end_time": "10.4",
             "alternatives": [{"content": "Who"}]},
            {"type": "pronunciation", "start_time": "10.4", "end_time": "10.8",
             "alternatives": [{"content": "goes"}]},
            {"type": "punctuation", "alternatives": [{"content": "?"}]},
            {"type": "pronunciation", "start_time": "35.0", "end_time": "35.6",
             "alternatives": [{"content": "Scale"}]},
        ]
    }
}


class TestNoSpoilers:
    def test_context_excludes_descriptions_and_dialogue_after_playhead(self):
        ctx = ask_fn.build_context(TIMELINE, TRANSCRIPT, t=22.0)
        assert "snowy ridge" in ctx
        assert "staff lies" in ctx
        assert "Who goes?" in ctx
        assert "dragon rises" not in ctx
        assert "Scale" not in ctx


class TestProbeRequestShape:
    def test_probe_with_empty_frame_omits_image_block(self, monkeypatch):
        captured = {}

        class FakeResp:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
            def read(self):
                return json.dumps({"content": [{"text": "pong"}]}).encode()

        def fake_urlopen(req, timeout=60):
            captured["body"] = json.loads(req.data.decode())
            return FakeResp()

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(ask_fn.urllib.request, "urlopen", fake_urlopen)

        out = ask_fn.ask_model(b"", "ping", "")
        assert out == "pong"
        content = captured["body"]["messages"][0]["content"]
        assert all(block["type"] != "image" for block in content)

    def test_question_with_frame_includes_image_block(self, monkeypatch):
        captured = {}

        class FakeResp:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
            def read(self):
                return json.dumps({"content": [{"text": "She stands still."}]}).encode()

        def fake_urlopen(req, timeout=60):
            captured["body"] = json.loads(req.data.decode())
            return FakeResp()

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(ask_fn.urllib.request, "urlopen", fake_urlopen)

        out = ask_fn.ask_model(b"\xff\xd8\xff\xd9", "What is happening?", "ctx")
        assert out == "She stands still."
        content = captured["body"]["messages"][0]["content"]
        assert content[0]["type"] == "image"
        assert content[0]["source"]["data"] != ""


class TestEndOfClipFrameFallback:
    def test_fractional_end_of_clip_falls_back_to_final_frame(self, monkeypatch):
        def fake_get(url, binary=False):
            if url.endswith("timeline.json"):
                return TIMELINE
            if url.endswith("transcript.json"):
                return TRANSCRIPT
            if url.endswith("frames/00053.jpg"):
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
            if url.endswith("frames/00052.jpg"):
                return b"\xff\xd8\xff\xd9"
            raise AssertionError(f"unexpected URL {url}")

        monkeypatch.setattr(ask_fn, "_get", fake_get)
        monkeypatch.setattr(ask_fn, "ask_model", lambda f, q, c: "End of the trailer.")
        monkeypatch.setattr(ask_fn, "speak", lambda text: "YWJj")

        event = {
            "requestContext": {"http": {"method": "POST", "path": "/"}},
            "body": json.dumps({"question": "What happened?", "t": 52.2, "video": ""}),
        }
        res = ask_fn.lambda_handler(event, None)
        assert res["statusCode"] == 200
        body = json.loads(res["body"])
        assert body["answer"] == "End of the trailer."
        assert body["asked_at"] == 52.2


class TestRecapFallback:
    def test_model_refusal_returns_labelled_recap_up_to_playhead(self):
        r = ask_fn.recap(TIMELINE, TRANSCRIPT, t=25.0)
        assert "Described so far:" in r
        assert "Said so far:" in r
        assert "dragon rises" not in r


class TestSignStripAndContext:
    def test_fetch_frame_strip_collects_preceding_frames_in_order(self, monkeypatch):
        fetched = []

        def fake_get(url, binary=False):
            fetched.append(url.split("/")[-1])
            return url.split("/")[-1].encode()

        monkeypatch.setattr(ask_fn, "_get", fake_get)
        strip = ask_fn.fetch_frame_strip("https://example.test/", t=10.0, window=3)
        # At t=10.0, idx is 11, so the 4-frame strip is 00008..00011 in chronological order
        assert strip == [b"00008.jpg", b"00009.jpg", b"00010.jpg", b"00011.jpg"]

    def test_multi_frame_question_labels_earlier_and_current_frames(self, monkeypatch):
        captured = {}

        class FakeResp:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
            def read(self):
                return json.dumps({"content": [{"text": "He holds up two fingers."}]}).encode()

        def fake_urlopen(req, timeout=60):
            captured["body"] = json.loads(req.data.decode())
            return FakeResp()

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(ask_fn.urllib.request, "urlopen", fake_urlopen)

        out = ask_fn.ask_model(
            [b"\xff\xd8\x01", b"\xff\xd8\x02", b"\xff\xd8\x03"],
            "What sign did he just make?",
            "ctx",
        )
        assert out == "He holds up two fingers."
        content = captured["body"]["messages"][0]["content"]
        images = [b for b in content if b["type"] == "image"]
        texts = [b["text"] for b in content if b["type"] == "text"]
        assert len(images) == 3
        assert any("2s before" in tx for tx in texts)
        assert any("Current frame" in tx for tx in texts)

    def test_signs_up_to_excludes_future_signs(self):
        tl = {
            "media": "content.mp4",
            "cues": [
                {"t": 6.0, "rank": 1, "text": "He puts a finger to his lips.",
                 "sign": {"transcript_entry": "[Gesture: finger to lips]"}},
                {"t": 40.0, "rank": 2, "text": "She signs wait.",
                 "sign": {"transcript_entry": '[Sign: "Wait"]'}},
            ],
        }
        ctx = ask_fn.build_context(tl, TRANSCRIPT, t=15.0)
        assert "[Gesture: finger to lips]" in ctx
        assert '[Sign: "Wait"]' not in ctx
