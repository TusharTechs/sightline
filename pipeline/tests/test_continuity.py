"""The continuity pass, and the guard that stops it breaking the timing.

Descriptions are written independently, so the second one does not know the
first introduced a character. A repair pass fixes the references. It must
never fix them into a line that no longer fits the gap, because a line that
overruns is spoken over dialogue, which is the one thing that must not happen.
"""
import salience


class FakeParsed:
    def __init__(self, lines):
        self.parsed_output = type("O", (), {"lines": lines})()


class FakeLine:
    def __init__(self, index, text):
        self.index, self.text = index, text


class FakeMessages:
    def __init__(self, lines=None, raises=None):
        self._lines, self._raises = lines or [], raises

    def parse(self, **kwargs):
        if self._raises:
            raise self._raises
        return FakeParsed(self._lines)


class FakeClient:
    def __init__(self, lines=None, raises=None):
        self.messages = FakeMessages(lines, raises)


def use(client, monkeypatch):
    monkeypatch.setitem(salience._clients, "anthropic", client)


class TestMakeContinuous:
    def test_a_repair_within_budget_is_accepted(self, monkeypatch):
        use(FakeClient([FakeLine(0, "She lifts it")]), monkeypatch)
        out = salience.make_continuous(["A hand lifts it"], budgets=[5])
        assert out == ["She lifts it"]

    def test_a_repair_that_overruns_its_budget_is_refused(self, monkeypatch):
        """The guard. A three word budget cannot take an eight word line, however
        much better the prose is."""
        long = "She lifts the small bleeding creature very carefully indeed"
        use(FakeClient([FakeLine(0, long)]), monkeypatch)
        out = salience.make_continuous(["A hand lifts it"], budgets=[3])
        assert out == ["A hand lifts it"]

    def test_the_budget_boundary_is_inclusive(self, monkeypatch):
        use(FakeClient([FakeLine(0, "one two three")]), monkeypatch)
        assert salience.make_continuous(["original"], budgets=[3]) == ["one two three"]
        use(FakeClient([FakeLine(0, "one two three four")]), monkeypatch)
        assert salience.make_continuous(["original"], budgets=[3]) == ["original"]

    def test_an_index_that_does_not_exist_is_ignored(self, monkeypatch):
        use(FakeClient([FakeLine(7, "from nowhere"), FakeLine(-1, "also nowhere")]),
            monkeypatch)
        out = salience.make_continuous(["a", "b"], budgets=[9, 9])
        assert out == ["a", "b"]

    def test_a_failing_model_call_keeps_every_original(self, monkeypatch):
        use(FakeClient(raises=RuntimeError("upstream is down")), monkeypatch)
        out = salience.make_continuous(["a", "b", "c"], budgets=[9, 9, 9])
        assert out == ["a", "b", "c"]

    def test_the_output_is_always_the_same_length_as_the_input(self, monkeypatch):
        use(FakeClient([FakeLine(0, "only this one")]), monkeypatch)
        out = salience.make_continuous(["a", "b", "c"], budgets=[9, 9, 9])
        assert len(out) == 3

    def test_only_the_lines_the_model_returned_are_changed(self, monkeypatch):
        use(FakeClient([FakeLine(1, "repaired")]), monkeypatch)
        out = salience.make_continuous(["a", "b", "c"], budgets=[9, 9, 9])
        assert out == ["a", "repaired", "c"]

    def test_repaired_text_is_stripped(self, monkeypatch):
        use(FakeClient([FakeLine(0, "  padded  ")]), monkeypatch)
        assert salience.make_continuous(["x"], budgets=[9]) == ["padded"]
