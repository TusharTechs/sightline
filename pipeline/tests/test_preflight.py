"""The checks that catch what a sighted developer cannot.

Every rule here exists because a blind reviewer found the fault it now
catches. These are the tests that stop those faults coming back.
"""
import json, os, pytest
import preflight


def bundle(tmp_path, cues, duration=None, gaps=None, with_audio=True):
    """Write a minimal bundle on disk and return its path."""
    tl = {"media": "content.mp4", "cues": cues}
    if duration is not None:
        tl["duration_s"] = duration
    (tmp_path / "timeline.json").write_text(json.dumps(tl))
    if with_audio:
        for c in cues:
            base = (c.get("pcm") or "").rsplit(".", 1)[0]
            if base:
                (tmp_path / (base + ".pcm")).write_bytes(b"\0" * 32)
    gaps_path = None
    if gaps is not None:
        gaps_path = tmp_path / "gaps.json"
        gaps_path.write_text(json.dumps(gaps))
    return str(tmp_path), (str(gaps_path) if gaps_path else None)


def cue(t, text, rank=1, pcm=None):
    return {"t": t, "rank": rank, "text": text,
            "pcm": pcm or f"desc-{rank:02d}.pcm", "duration": 2.0}


class TestCameraLanguage:
    """A vantage point must never be described as a place, because it gets
    heard as a person. One high shot through rafters became 'someone watches
    her sleep', inventing a character the film does not contain."""

    @pytest.mark.parametrize("phrase", [
        "The camera pans across the room",
        "From above, she sleeps",
        "A close-up of her hand",
        "We see the dragon",
        "Cuts to the street",
        "The shot widens",
    ])
    def test_camera_language_fails_the_build(self, tmp_path, phrase):
        b, g = bundle(tmp_path, [cue(10.0, phrase)])
        fails, _ = preflight.check(b, g)
        assert any("camera language" in f for f in fails), phrase

    @pytest.mark.parametrize("phrase", [
        "Something off screen makes a sound",
        "A voice out of shot answers her",
    ])
    def test_naming_an_unseen_sound_source_is_allowed(self, tmp_path, phrase):
        """Deliberately not flagged. Naming the unseen source of a sound is the
        correct thing to say, and the prompt asks for it."""
        b, g = bundle(tmp_path, [cue(10.0, phrase)])
        fails, _ = preflight.check(b, g)
        assert not any("camera language" in f for f in fails), phrase


class TestDialogueCollisions:
    def test_a_cue_landing_on_speech_fails(self, tmp_path):
        gaps = {"duration_s": 60.0, "speech_runs": [{"start": 9.0, "end": 12.0}]}
        b, g = bundle(tmp_path, [cue(10.0, "She lands")], gaps=gaps)
        fails, _ = preflight.check(b, g)
        assert any("talks over dialogue" in f for f in fails)

    def test_a_cue_in_a_real_gap_passes(self, tmp_path):
        gaps = {"duration_s": 60.0,
                "speech_runs": [{"start": 0.0, "end": 5.0}, {"start": 30.0, "end": 35.0}]}
        b, g = bundle(tmp_path, [cue(15.0, "She lands")], gaps=gaps)
        fails, _ = preflight.check(b, g)
        assert not any("talks over dialogue" in f for f in fails)

    def test_a_cue_crowding_the_end_of_a_line_fails(self, tmp_path):
        gaps = {"duration_s": 60.0, "speech_runs": [{"start": 5.0, "end": 9.9}]}
        b, g = bundle(tmp_path, [cue(10.0, "She lands")], gaps=gaps)
        fails, _ = preflight.check(b, g)
        assert any("after a line ends" in f for f in fails)


class TestMissingAudio:
    def test_a_cue_with_no_rendered_speech_fails(self, tmp_path):
        b, g = bundle(tmp_path, [cue(10.0, "She lands")], with_audio=False)
        fails, _ = preflight.check(b, g)
        assert any("no audio file" in f for f in fails)


class TestCoverage:
    def test_a_long_hole_with_room_in_it_fails(self, tmp_path):
        """Description stopping partway through is the fault a blind tester
        found: a cap on the NUMBER of descriptions was truncating the FILM."""
        gaps = {"duration_s": 300.0,
                "gaps": [{"start": 20.0, "end": 280.0}], "speech_runs": []}
        b, g = bundle(tmp_path, [cue(5.0, "Inside a tent")], duration=300.0, gaps=gaps)
        fails, _ = preflight.check(b, g)
        assert any("no description" in f for f in fails)

    def test_a_long_hole_with_no_room_in_it_is_not_a_fault(self, tmp_path):
        """A 1951 instructional film narrates for nine minutes. It has a 200
        second stretch with nothing said and there is nothing wrong with it:
        the gaps inside that stretch are too small to have held anything.
        Reporting it blames the software for the content."""
        tiny = [{"start": float(t), "end": float(t) + 0.9} for t in range(20, 280, 40)]
        gaps = {"duration_s": 300.0, "gaps": tiny, "speech_runs": []}
        b, g = bundle(tmp_path,
                      [cue(5.0, "A man at a desk", rank=1),
                       cue(290.0, "The film ends", rank=2)],
                      duration=300.0, gaps=gaps)
        fails, _ = preflight.check(b, g)
        assert not any("no description" in f for f in fails), fails

    def test_the_same_hole_with_plenty_of_room_is_a_fault(self, tmp_path):
        """Same shape, same length of silence. The only difference is that this
        one had somewhere to speak and did not."""
        roomy = [{"start": 20.0, "end": 270.0}]
        gaps = {"duration_s": 300.0, "gaps": roomy, "speech_runs": []}
        b, g = bundle(tmp_path,
                      [cue(5.0, "A man at a desk", rank=1),
                       cue(290.0, "The film ends", rank=2)],
                      duration=300.0, gaps=gaps)
        fails, _ = preflight.check(b, g)
        assert any("no description" in f for f in fails)


class TestRepeatedIntroductions:
    def test_introducing_the_same_kind_of_person_twice_is_noted(self, tmp_path):
        b, g = bundle(tmp_path, [
            cue(10.0, "A woman crosses the square", rank=1),
            cue(40.0, "A woman opens the door", rank=2)])
        _, notes = preflight.check(b, g)
        assert any("again" in n for n in notes)


class TestEmptyBundle:
    def test_no_cues_at_all_fails(self, tmp_path):
        b, g = bundle(tmp_path, [])
        fails, _ = preflight.check(b, g)
        assert fails and "no cues" in fails[0]


class TestCleanBundlePasses:
    def test_a_good_bundle_produces_no_failures(self, tmp_path):
        gaps = {"duration_s": 120.0,
                "gaps": [{"start": 0.0, "end": 55.0}, {"start": 65.0, "end": 120.0}],
                "speech_runs": [{"start": 57.0, "end": 62.0}]}
        cues = [cue(10.0, "Inside a tent, a lamp burns", rank=1),
                cue(40.0, "She lifts a knife", rank=2),
                cue(70.0, "The dragon stays put", rank=3),
                cue(100.0, "She steps into the street", rank=4)]
        b, g = bundle(tmp_path, cues, duration=120.0, gaps=gaps)
        fails, _ = preflight.check(b, g)
        assert fails == [], fails
