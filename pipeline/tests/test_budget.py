"""How many words fit in a gap.

Every line is measured against its gap before it is kept, so this function
decides whether a description is spoken or dropped. It is also where a day
went: we asked Polly for 170 wpm, budgeted at 170, and every line overflowed,
because the delivered rate is 203 once the padding is trimmed.
"""
import pytest
import speech


class TestBudgetWords:
    def test_the_budget_uses_the_measured_rate_not_the_requested_one(self):
        """Locks the bug. DEFAULT_WPM is what we ask Polly for; MEASURED_WPM is
        what comes back. Budgeting with the first one overflows every gap."""
        assert speech.MEASURED_WPM != speech.DEFAULT_WPM
        assert speech.budget_words(60.0, 1.0) == pytest.approx(speech.MEASURED_WPM, abs=1)

    def test_a_longer_gap_holds_more_words(self):
        assert speech.budget_words(6.0, 1.0) > speech.budget_words(3.0, 1.0)

    def test_speed_shrinks_the_budget_rather_than_the_delivery(self):
        """A 3s gap at 2x is 1.5s of wall clock. We say fewer words at a normal
        rate; we do not say the same words twice as fast."""
        assert speech.budget_words(3.0, 2.0) == speech.budget_words(1.5, 1.0)
        assert speech.budget_words(3.0, 2.0) < speech.budget_words(3.0, 1.0)

    def test_budget_scales_linearly_with_the_gap(self):
        assert speech.budget_words(10.0, 1.0) == pytest.approx(
            2 * speech.budget_words(5.0, 1.0), abs=1)

    def test_a_gap_too_short_to_say_anything_budgets_nothing(self):
        assert speech.budget_words(0.05, 1.0) == 0

    def test_the_budget_is_never_negative(self):
        for gap in (-5.0, -0.1, 0.0):
            assert speech.budget_words(gap, 1.0) >= 0

    def test_an_absurd_rate_cannot_divide_by_zero(self):
        assert speech.budget_words(3.0, 0.0) >= 0
        assert speech.budget_words(3.0, -1.0) >= 0

    def test_an_explicit_rate_overrides_the_measured_one(self):
        assert speech.budget_words(60.0, 1.0, wpm=120) == pytest.approx(120, abs=1)
