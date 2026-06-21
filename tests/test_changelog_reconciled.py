from pathlib import Path

CHANGELOG = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text()


def test_scheme_sentence_is_semver():
    assert "<topic-slug>" not in CHANGELOG
    assert "`<major>.<minor>.<patch>`" in CHANGELOG


def test_has_4_1_0_and_4_0_0_entries():
    assert "## [4.1.0]" in CHANGELOG
    assert "## [4.0.0]" in CHANGELOG


def test_new_entries_are_above_3_27_0():
    assert CHANGELOG.index("## [4.1.0]") < CHANGELOG.index("## [4.0.0]")
    assert CHANGELOG.index("## [4.0.0]") < CHANGELOG.index("## [3.27.0-docs-refactor]")
