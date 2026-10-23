"""Tests for silent communication — hand signs, gestures, sign language, and
written signs (`signs.py`).

Amazon Transcribe hears only spoken words. A hand sign, a signed phrase, or a
held-up written note happens across a sequence of frames and makes no sound, so
these tests verify:
  - Frame-strip timestamps sit strictly inside the window and stay ordered.
  - Transcript entries format gestures, sign language, and written signs
    distinctly, and stay empty when nothing was found.
  - Prompt evidence is emitted only when a sign is genuinely present.
  - Merging signs into a Transcribe-shaped transcript preserves word-level
    pronunciation items and orders silent signs chronologically.
"""
import signs


class TestSampleStripTimes:
    def test_timestamps_sit_inside_the_window(self):
        pts = signs.sample_strip_times(10.0, 14.0, count=4)
        assert len(pts) == 4
        assert all(10.0 < t < 14.0 for t in pts)

    def test_timestamps_are_strictly_increasing(self):
        pts = signs.sample_strip_times(2.0, 8.0, count=4)
        assert pts == sorted(pts)
        assert len(set(pts)) == 4

    def test_zero_length_window_returns_single_point(self):
        pts = signs.sample_strip_times(5.0, 5.0, count=4)
        assert pts == [5.0]


class TestFormatTranscriptEntry:
    def test_sign_language_quotes_the_translated_meaning(self):
        entry = signs.format_transcript_entry(
            "sign_language", "Wait here", "She signs wait here."
        )
        assert entry == '[Sign: "Wait here"]'

    def test_gesture_uses_gesture_tag(self):
        entry = signs.format_transcript_entry(
            "gesture", "holds a finger to his lips", "He puts a finger to his lips."
        )
        assert entry == "[Gesture: holds a finger to his lips]"

    def test_written_sign_quotes_the_text(self):
        entry = signs.format_transcript_entry(
            "written_sign", "Keep Out", "A wooden sign reads Keep Out."
        )
        assert entry == '[On-screen sign: "Keep Out"]'

    def test_none_kind_or_empty_meaning_returns_empty_string(self):
        assert signs.format_transcript_entry("none", "Wait", "She waits.") == ""
        assert signs.format_transcript_entry("gesture", "", "") == ""


class TestDescribeSignsForPrompt:
    def test_unfound_verdict_adds_nothing_to_prompt(self):
        note = signs.describe_signs_for_prompt({
            "found": False, "kind": "none", "raw_meaning": "",
            "spoken_description": "",
        })
        assert note == ""

    def test_found_sign_mentions_kind_and_suggested_phrasing(self):
        note = signs.describe_signs_for_prompt({
            "found": True,
            "kind": "sign_language",
            "raw_meaning": "Thank you",
            "spoken_description": "She signs thank you.",
        })
        assert "Sign-language communication" in note
        assert "Thank you" in note
        assert "She signs thank you." in note


class TestMergeSignsIntoTranscript:
    def test_preserves_spoken_items_and_adds_sorted_signs(self):
        base = {
            "results": {
                "items": [
                    {"type": "pronunciation", "start_time": "1.0", "end_time": "1.4",
                     "alternatives": [{"content": "Quiet"}]},
                ]
            }
        }
        cues = [
            {
                "t": 12.0,
                "description": "A wooden sign reads Bridge Out.",
                "sign": {
                    "found": True,
                    "kind": "written_sign",
                    "raw_meaning": "Bridge Out",
                    "spoken_description": "A wooden sign reads Bridge Out.",
                    "transcript_entry": '[On-screen sign: "Bridge Out"]',
                },
            },
            {
                "t": 4.5,
                "description": "He holds a finger to his lips.",
                "sign": {
                    "found": True,
                    "kind": "gesture",
                    "raw_meaning": "holds a finger to his lips",
                    "spoken_description": "He holds a finger to his lips.",
                    "transcript_entry": "[Gesture: holds a finger to his lips]",
                },
            },
        ]
        merged = signs.merge_signs_into_transcript(base, cues)
        # Original input is not mutated
        assert "signs" not in base["results"]
        # Word items stay intact
        assert len(merged["results"]["items"]) == 1
        # Signs are sorted chronologically
        recorded = merged["results"]["signs"]
        assert [s["t"] for s in recorded] == [4.5, 12.0]
        assert recorded[0]["transcript_entry"] == "[Gesture: holds a finger to his lips]"
        assert recorded[1]["transcript_entry"] == '[On-screen sign: "Bridge Out"]'
