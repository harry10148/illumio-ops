"""CLI `siem status` and the WebUI integrations tab must report the same set
of SIEM destinations.

Root cause being guarded against (UX_Review §11.2):
    CLI previously only joined on ``SELECT DISTINCT destination FROM
    SiemDispatch`` — so a configured destination with zero dispatch rows (or
    one whose dispatch rows hadn't been produced yet) was invisible in
    ``siem status``. The WebUI integrations tab merges ``/api/siem/destinations``
    (configured names) with ``/api/siem/status`` (per-name counts), so it
    correctly shows the destination with counts ``0 / 0 / 0``.

After the fix, the CLI must also merge configured destinations into the
status output, so both surfaces agree on the destination set.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


def _make_mock_cm(tmp_path, dest_names):
    """Build a ConfigManager mock with the given configured destination names.

    Mirrors the pattern used by tests/test_siem_cli.py.
    """
    mock_cm = MagicMock()
    mock_cm.models.pce_cache.db_path = str(tmp_path / "data" / "test.sqlite")
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    # Build SiemDestinationSettings-like mocks. The CLI only reads .name and
    # .enabled, so a lightweight MagicMock per destination is sufficient.
    dests = []
    for name in dest_names:
        d = MagicMock()
        d.name = name
        d.enabled = True
        dests.append(d)
    mock_cm.models.siem.destinations = dests
    return mock_cm


def test_cli_siem_status_shows_configured_destination_with_zero_counts(
    runner, tmp_path
):
    """A configured destination with no dispatch rows must appear in the
    CLI status output with zero counts — matching the WebUI behaviour."""
    from src.cli.siem import siem_group

    mock_cm = _make_mock_cm(tmp_path, dest_names=["garylog"])
    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(siem_group, ["status"])

    assert result.exit_code == 0, f"siem status failed:\n{result.output}"
    # The destination NAME from config must appear in the output even though
    # there are no SiemDispatch rows for it yet.
    assert "garylog" in result.output, (
        "CLI `siem status` is not surfacing configured destinations; it now "
        "diverges from the WebUI integrations tab. Output was:\n"
        + result.output
    )


def test_cli_siem_status_json_includes_configured_destination(runner, tmp_path):
    """The --json variant must likewise include configured destinations.

    ``--json`` is a global flag attached to the root ``cli`` group, not the
    ``siem`` subgroup, so we invoke through ``src.cli.root.cli``.
    """
    import json as _json

    from src.cli.root import cli

    mock_cm = _make_mock_cm(tmp_path, dest_names=["garylog"])
    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(cli, ["--json", "siem", "status"])

    assert result.exit_code == 0, f"siem --json status failed:\n{result.output}"
    payload = _json.loads(result.output)
    names = {row["destination"] for row in payload}
    assert "garylog" in names, (
        "JSON output of `siem status` does not list the configured destination; "
        "CLI and WebUI sources are out of sync. Payload: " + repr(payload)
    )
    # Counts for an unused destination must default to 0.
    garylog_row = next(r for r in payload if r["destination"] == "garylog")
    assert garylog_row["pending"] == 0
    assert garylog_row["sent"] == 0
    assert garylog_row["failed"] == 0
    assert garylog_row["dlq"] == 0


def test_siem_status_empty_shows_no_records_hint(runner, tmp_path):
    """When config and DB are both empty, CLI must show cli_siem_no_records hint.

    Regression guard: a previous refactor (follow-up to d217646) dropped the
    empty-state hint in the success branch — users saw an empty Rich table
    instead of the dim "No SIEM dispatch records yet" message. Both the
    success branch and the OperationalError fallback must show the hint when
    there is nothing to render.
    """
    from src.cli.siem import siem_group

    # No configured destinations + fresh empty DB → both code paths should
    # produce an empty `rows` list and surface the hint instead of a bare table.
    mock_cm = _make_mock_cm(tmp_path, dest_names=[])
    with patch("src.config.ConfigManager", return_value=mock_cm):
        result = runner.invoke(siem_group, ["status"])

    assert result.exit_code == 0, f"siem status failed:\n{result.output}"
    # The exact i18n value from src/i18n_en.json: cli_siem_no_records.
    assert "No SIEM dispatch records yet" in result.output, (
        "CLI `siem status` dropped the empty-state hint; user now sees a bare "
        "Rich table border instead. Output was:\n" + result.output
    )
