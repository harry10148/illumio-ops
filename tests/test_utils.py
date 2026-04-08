import io

from src import utils


class _StdoutStub(io.StringIO):
    encoding = "cp950"

    def isatty(self):
        return True


def test_safe_input_uses_ascii_prompt_on_cp950(monkeypatch):
    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return "1"

    monkeypatch.setattr(utils.sys, "stdout", _StdoutStub())
    monkeypatch.setattr("builtins.input", fake_input)

    value = utils.safe_input("Pick one", value_type=int, valid_range={1, 2}, allow_cancel=False)

    assert value == 1
    assert prompts
    assert "❯" not in prompts[0]
    assert ">" in prompts[0]


def test_safe_input_does_not_crash_when_input_raises_value_error(monkeypatch):
    calls = {"count": 0}

    def fake_input(prompt):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("prompt failure")
        return "2"

    monkeypatch.setattr("builtins.input", fake_input)

    value = utils.safe_input("Pick one", value_type=int, valid_range={1, 2}, allow_cancel=False)

    assert value == 2
