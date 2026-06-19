from unittest.mock import patch

from click.testing import CliRunner

from src.cli.root import cli


def _run(args):
    """Invoke a report command, capturing the (use_cache, clip_to_cache) it would
    pass to the generator. Stops before real work via SystemExit."""
    captured = {}

    def fake_generate_from_api(self, *a, **k):
        captured["use_cache"] = k.get("use_cache")
        captured["clip_to_cache"] = k.get("clip_to_cache")
        raise SystemExit(0)

    with patch("src.report.report_generator.ReportGenerator.generate_from_api",
               fake_generate_from_api), \
         patch("src.report.cache_support.cache_available", return_value=True):
        CliRunner().invoke(cli, args, catch_exceptions=True)
    return captured


def test_cli_data_source_live():
    assert _run(["report", "traffic", "--data-source", "live"])["use_cache"] is False


def test_cli_data_source_hybrid():
    c = _run(["report", "traffic", "--data-source", "hybrid"])
    assert (c["use_cache"], c["clip_to_cache"]) == (True, False)


def test_cli_data_source_cache_only():
    c = _run(["report", "traffic", "--data-source", "cache-only"])
    assert (c["use_cache"], c["clip_to_cache"]) == (True, True)


def test_cli_no_cache_alias_still_works():
    assert _run(["report", "traffic", "--no-cache"])["use_cache"] is False


def test_cli_default_is_hybrid():
    c = _run(["report", "traffic"])
    assert (c["use_cache"], c["clip_to_cache"]) == (True, False)
