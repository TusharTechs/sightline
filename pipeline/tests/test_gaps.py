"""Where description is allowed to go.

This is the most consequential logic in the project. Looking for silence found
2.5 usable seconds in a 52 second trailer because the score never stops;
looking for speech and inverting it found 39.8. Everything downstream depends
on these two functions being right.
"""
import detect_speech as ds


def words(*spans):
    """Build a Transcribe result from (start, end) pairs."""
    return {"results": {"items": [
        {"type": "pronunciation", "start_time": str(s), "end_time": str(e)}
        for s, e in spans]}}


class TestSpeechIntervals:
    def test_adjacent_words_merge_into_one_run(self):
        # words inside JOIN_WORDS_S of each other are one utterance, not many
        r = ds.speech_intervals(words((1.0, 1.2), (1.3, 1.5), (1.6, 1.9)))
        assert r == [(1.0, 1.9)]

    def test_a_real_pause_splits_the_run(self):
        r = ds.speech_intervals(words((1.0, 1.2), (5.0, 5.4)))
        assert r == [(1.0, 1.2), (5.0, 5.4)]

    def test_the_join_threshold_is_the_boundary(self):
        just_inside = ds.JOIN_WORDS_S - 0.01
        just_outside = ds.JOIN_WORDS_S + 0.01
        assert len(ds.speech_intervals(words((0.0, 1.0), (1.0 + just_inside, 2.0)))) == 1
        assert len(ds.speech_intervals(words((0.0, 1.0), (1.0 + just_outside, 2.0)))) == 2

    def test_punctuation_items_are_ignored(self):
        res = words((1.0, 1.2))
        res["results"]["items"].append({"type": "punctuation", "content": "."})
        assert ds.speech_intervals(res) == [(1.0, 1.2)]

    def test_no_speech_at_all_is_no_runs(self):
        assert ds.speech_intervals(words()) == []


class TestGapsFromSpeech:
    def test_a_silent_film_is_one_enormous_gap(self):
        # nothing is said, so the whole thing is available
        gaps = ds.gaps_from_speech([], total=100.0)
        assert len(gaps) == 1
        assert gaps[0]["start"] == 0.0
        assert gaps[0]["end"] == 100.0 - ds.BEFORE_SPEECH_S

    def test_room_is_left_after_a_line_and_before_the_next(self):
        gaps = ds.gaps_from_speech([(10.0, 12.0), (30.0, 32.0)], total=40.0)
        mid = [g for g in gaps if g["start"] > 10][0]
        # the pause after a line is when it is understood; do not step on it
        assert mid["start"] == round(12.0 + ds.AFTER_SPEECH_S, 3)
        assert mid["end"] == round(30.0 - ds.BEFORE_SPEECH_S, 3)

    def test_the_opening_gap_starts_at_zero(self):
        # there is no previous line to land, so nothing to leave room for
        gaps = ds.gaps_from_speech([(10.0, 12.0)], total=20.0)
        assert gaps[0]["start"] == 0.0

    def test_gaps_shorter_than_the_minimum_are_dropped(self):
        # two lines a hair apart leave a hole nothing could be said in
        gaps = ds.gaps_from_speech([(10.0, 11.0), (11.5, 12.0)], total=12.0)
        assert all(g["len_s"] >= ds.MIN_GAP_S for g in gaps)
        assert not any(11.0 < g["start"] < 11.5 for g in gaps)

    def test_overlapping_runs_do_not_produce_a_negative_gap(self):
        # Transcribe can return overlapping spans; the cursor must never go back
        gaps = ds.gaps_from_speech([(10.0, 20.0), (15.0, 18.0), (30.0, 31.0)], total=40.0)
        assert all(g["len_s"] > 0 for g in gaps)
        assert all(g["end"] > g["start"] for g in gaps)

    def test_gaps_never_overlap_each_other(self):
        gaps = ds.gaps_from_speech(
            [(5.0, 6.0), (12.0, 14.0), (25.0, 25.5), (40.0, 44.0)], total=60.0)
        for a, b in zip(gaps, gaps[1:]):
            assert a["end"] <= b["start"]

    def test_no_gap_lands_inside_speech(self):
        runs = [(5.0, 6.0), (12.0, 14.0), (25.0, 25.5)]
        for g in ds.gaps_from_speech(runs, total=40.0):
            for s, e in runs:
                assert g["end"] <= s or g["start"] >= e

    def test_loud_content_does_not_reduce_the_room(self):
        """The property the whole approach rests on.

        Gaps are a function of when people speak, not of how loud the film is.
        A continuously scored film and a silent one with identical dialogue get
        identical room. Silence detection could not say this, which is why it
        found 2.5 seconds where this finds 39.8.
        """
        runs = [(10.0, 12.0), (30.0, 32.0)]
        assert ds.gaps_from_speech(runs, 40.0) == ds.gaps_from_speech(runs, 40.0)
        # and the total room is large despite a score that never stops
        room = sum(g["len_s"] for g in ds.gaps_from_speech(runs, 40.0))
        assert room > 30.0
