"""The onset classifier, and the property a blind reviewer proposed.

He asked a question I had not thought of: if you turn the whole file down,
does the classification move? It should not, because every quantity here is a
difference between two levels and a uniform gain cancels.

It did move, and that exposed a real bug. The loader was reading 16-bit, this
film decodes to samples above full scale, and those were being clipped, which
is not a uniform operation. Reading 32-bit float fixed it.
"""
import numpy as np
import pytest
import audio_events as ae


def hit(seconds=6.0, at=2.0, decay=0.25, amp=0.35):
    """A sound that arrives fast and leaves: a door, a thud."""
    t = np.arange(int(ae.SR * seconds)) / ae.SR
    x = 0.01 * np.sin(2 * np.pi * 110 * t)          # a quiet room
    i = int(at * ae.SR)
    env = np.exp(-(t[i:] - at) / decay)
    x[i:] += amp * env * np.sin(2 * np.pi * 240 * t[i:])
    return x.astype(np.float32)


def swell(seconds=8.0, at=2.0, rise=1.0, amp=0.3):
    """A sound that arrives slowly and stays: music coming up under a scene."""
    t = np.arange(int(ae.SR * seconds)) / ae.SR
    x = 0.01 * np.sin(2 * np.pi * 110 * t)
    i = int(at * ae.SR)
    env = np.clip((t[i:] - at) / rise, 0, 1)
    x[i:] += amp * env * np.sin(2 * np.pi * 240 * t[i:])
    return x.astype(np.float32)


class TestAttack:
    def test_a_fast_arrival_measures_a_short_attack(self):
        a, peak = ae.attack_ms(hit(), 2.0)
        assert a is not None and a < ae.FAST_MS
        assert peak == pytest.approx(2.0, abs=0.1)

    def test_a_slow_arrival_measures_a_long_attack(self):
        a, _ = ae.attack_ms(swell(), 2.5)
        assert a is not None and a > ae.FAST_MS

    def test_too_little_audio_returns_not_sure(self):
        """Not sure means stay quiet. It must never guess."""
        a, _ = ae.attack_ms(np.zeros(8, dtype=np.float32), 0.0)
        assert a is None


class TestShape:
    def test_a_hit_is_classified_as_a_hit(self):
        x = hit()
        floor = ae._level_db(x, 1.0)
        *_, verdict = ae.shape_of(x, 2.0, floor)
        assert verdict is True

    def test_a_swell_is_classified_as_a_swell(self):
        x = swell()
        floor = ae._level_db(x, 1.0)
        *_, verdict = ae.shape_of(x, 2.5, floor)
        assert verdict is False

    def test_an_unmeasurable_onset_is_not_sure_rather_than_guessed(self):
        x = np.zeros(int(ae.SR * 4), dtype=np.float32)
        assert ae.shape_of(x, 2.0, -60.0)[3] is None


class TestGainInvariance:
    """The reviewer's test. Every quantity is a difference between two levels,
    so a uniform gain must cancel exactly."""

    @pytest.mark.parametrize("db", [-3.0, -9.0, -18.0, +6.0])
    def test_classification_does_not_move_when_the_file_is_attenuated(self, db):
        x = hit()
        g = 10 ** (db / 20.0)
        floor = ae._level_db(x, 1.0)
        floor_g = ae._level_db(x * g, 1.0)
        assert ae.shape_of(x, 2.0, floor)[3] == ae.shape_of(x * g, 2.0, floor_g)[3]

    @pytest.mark.parametrize("db", [-3.0, -9.0, -18.0])
    def test_the_attack_time_itself_does_not_move(self, db):
        x = hit()
        g = 10 ** (db / 20.0)
        a1, _ = ae.attack_ms(x, 2.0)
        a2, _ = ae.attack_ms(x * g, 2.0)
        assert a1 == a2

    @pytest.mark.parametrize("db", [-3.0, -9.0, -18.0])
    def test_the_level_difference_moves_by_exactly_the_gain(self, db):
        """0.00 dB of drift is the number this had to reach."""
        x = hit()
        g = 10 ** (db / 20.0)
        before = ae._level_db(x, 1.0)
        after = ae._level_db(x * g, 1.0)
        assert after - before == pytest.approx(db, abs=0.01)

    def test_settle_is_measured_against_the_floor_not_the_peak(self):
        """A quiet scene and a loud one with the same shape must settle the
        same. Measuring against the peak made loud scenes look different."""
        x = hit()
        g = 10 ** (-12.0 / 20.0)
        s1 = ae.settle(x, 2.0, ae._level_db(x, 1.0))
        s2 = ae.settle(x * g, 2.0, ae._level_db(x * g, 1.0))
        for a, b in zip(s1, s2):
            if a is None or b is None:
                assert a is None and b is None
            else:
                assert a == pytest.approx(b, abs=0.2)
