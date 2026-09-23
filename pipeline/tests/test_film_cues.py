"""Splitting long silences into speakable segments, and reading back the
dialogue around them.

A 30 second silence is not one description. Subdividing it is what lets a long
wordless stretch carry several lines instead of one overlong one, and the
segments it produces must never leave the gap they came from.
"""
import film_cues as fc


def gap(a, b):
    return {"start": float(a), "end": float(b), "len_s": float(b - a)}


class TestSubdivide:
    def test_a_short_gap_is_left_alone(self):
        out = fc.subdivide([gap(0, 4)])
        assert len(out) == 1
        assert out[0]["start"] == 0.0 and out[0]["end"] == 4.0

    def test_a_long_gap_is_split(self):
        out = fc.subdivide([gap(0, 30)])
        assert len(out) > 1

    def test_a_remainder_too_small_to_stand_alone_is_absorbed(self):
        """13 seconds becomes two segments of 6.5, not 6 + 6 + 1.

        A one second orphan is below the minimum and could not hold a line, so
        the remainder is spread across its siblings instead. That is why a
        segment can exceed MAX_SEGMENT_S: the bound is max + min, and the
        segment is still inside the gap, which is the constraint that matters.
        """
        out = fc.subdivide([gap(200, 213)])
        assert len(out) == 2
        assert all(g["end"] - g["start"] > fc.MAX_SEGMENT_S for g in out)

    def test_no_segment_exceeds_the_real_bound(self):
        limit = fc.MAX_SEGMENT_S + fc.MIN_SEGMENT_S
        for g in fc.subdivide([gap(0, 30), gap(40, 97), gap(200, 213),
                               gap(300, 306.9), gap(400, 431.4)]):
            assert g["end"] - g["start"] <= limit + 1e-6

    def test_no_segment_is_shorter_than_the_minimum(self):
        for g in fc.subdivide([gap(0, 30), gap(40, 47.3)]):
            assert g["end"] - g["start"] >= fc.MIN_SEGMENT_S - 1e-6

    def test_segments_stay_inside_the_gap_they_came_from(self):
        """A segment that runs past the end of its gap is a line spoken over
        the dialogue that closed it."""
        for g in fc.subdivide([gap(10, 41)]):
            assert g["start"] >= 10.0 - 1e-6
            assert g["end"] <= 41.0 + 1e-6

    def test_segments_do_not_overlap_each_other(self):
        out = fc.subdivide([gap(0, 30)])
        for a, b in zip(out, out[1:]):
            assert a["end"] <= b["start"] + 1e-6

    def test_an_empty_list_stays_empty(self):
        assert fc.subdivide([]) == []

    def test_every_segment_reports_its_own_length(self):
        for g in fc.subdivide([gap(0, 25)]):
            assert g["len_s"] == round(g["end"] - g["start"], 3)


class TestDialogueBetween:
    def items(self, *pairs):
        return [{"type": "pronunciation", "start_time": str(t),
                 "end_time": str(t + 0.3),
                 "alternatives": [{"content": w}]} for t, w in pairs]

    def test_it_returns_only_the_words_in_the_window(self):
        it = self.items((1.0, "hello"), (5.0, "there"), (9.0, "later"))
        assert fc.dialogue_between([], it, 4.0, 6.0) == "there"

    def test_the_window_is_half_open(self):
        it = self.items((4.0, "start"), (6.0, "end"))
        got = fc.dialogue_between([], it, 4.0, 6.0)
        assert "start" in got and "end" not in got

    def test_punctuation_is_skipped(self):
        it = self.items((1.0, "hello"))
        it.append({"type": "punctuation", "alternatives": [{"content": "!"}]})
        assert fc.dialogue_between([], it, 0.0, 2.0) == "hello"

    def test_a_silent_window_returns_nothing(self):
        it = self.items((1.0, "hello"))
        assert fc.dialogue_between([], it, 50.0, 60.0) == ""
