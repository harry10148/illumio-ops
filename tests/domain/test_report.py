from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from illumio_ops.domain.report import Column, Finding, Section, TableBlock, period_text
from illumio_ops.domain.values import Severity
from tests.services.reports.conftest import make_doc


def test_row_width_must_match_columns():
    with pytest.raises(ValidationError):
        TableBlock(title="t", columns=(Column(key="a", label="A"),), rows=(("x", "y"),), total_rows=1,
                   empty_text="")


def test_total_rows_counts_held_rows():
    with pytest.raises(ValidationError):
        TableBlock(title="t", columns=(Column(key="a", label="A"),), rows=(("x",),), total_rows=0, empty_text="")


def test_section_ids_unique_and_appendix_reserved():
    with pytest.raises(ValidationError):
        make_doc(sections=(Section(id="a", title="A"), Section(id="a", title="B")))
    with pytest.raises(ValidationError):
        make_doc(sections=(Section(id="appendix", title="A"),))


def test_period_text_end_exclusive_in_display_zone():
    tz = timezone(timedelta(hours=8))
    start, end = datetime(2026, 10, 19, 16, tzinfo=UTC), datetime(2026, 10, 26, 16, tzinfo=UTC)
    assert period_text(start, end, tz) == "2026-10-20 – 2026-10-26"


# stage 3a: what a finding asks for as a code, what to know before the numbers, the hosts a table's cells name
def _finding(**over):
    return Finding(**{"severity": Severity.HIGH, "title": "T", "why": "W", "action": "A", **over})


def _hosts_table(**over):
    return TableBlock(**{"title": "t", "columns": (Column(key="host", label="Host"), Column(key="n", label="N")),
                         "rows": (("a", 1), ("b", 2)), "total_rows": 2, "empty_text": "", **over})


def test_a_report_built_without_the_new_fields_is_as_before():
    f = _finding()
    assert (f.what, f.action_code, f.action_short, f.action_focus) == ("", None, "", "")
    t = _hosts_table()
    assert t.host_keys == {} and t.host_section is None
    d = make_doc()
    assert d.caveats == () and d.gui_base is None


def test_caveats_hold_two_sentences_at_most():
    assert make_doc(caveats=("a", "b")).caveats == ("a", "b")
    with pytest.raises(ValidationError):
        make_doc(caveats=("a", "b", "c"))


def test_an_action_code_needs_its_sentence():
    assert _finding(action_code="enforce", action_short="Move them to enforcement.").action_code == "enforce"
    assert _finding(action_short="A sentence with no code is allowed.").action_code is None
    with pytest.raises(ValidationError):
        _finding(action_code="enforce")
    with pytest.raises(ValidationError):
        _finding(action_code="enforce", action_short="  ")


@pytest.mark.parametrize("code", ["Enforce", "1st", "narrow-rules", "", "a b"])
def test_an_action_code_is_a_lower_case_identifier(code):
    with pytest.raises(ValidationError):
        _finding(action_code=code, action_short="Do it.")


def test_host_keys_name_a_column_and_are_no_longer_than_the_rows():
    t = _hosts_table(host_keys={"host": ("/orgs/1/workloads/a", None)}, host_section="connections")
    assert t.host_keys["host"] == ("/orgs/1/workloads/a", None)
    assert _hosts_table(host_keys={"host": ("/orgs/1/workloads/a",)}).host_keys["host"] == ("/orgs/1/workloads/a",)
    with pytest.raises(ValidationError):
        _hosts_table(host_keys={"nope": ("x", "y")})
    with pytest.raises(ValidationError):
        _hosts_table(host_keys={"host": ("x", "y", "z")})


def test_host_section_is_one_the_host_page_has():
    for section in ("status", "alerts", "different", "usual", "connections", "would-block", "ransomware", "tamper",
                    "quarantine"):
        assert _hosts_table(host_section=section).host_section == section
    with pytest.raises(ValidationError):
        _hosts_table(host_section="nowhere")


def test_host_sections_are_the_front_end_ones():
    """The report links into the host page: the allowed sections are the HostSection type of the web app."""
    import re
    from pathlib import Path
    from typing import get_args

    from illumio_ops.domain.report import HostSection
    src = (Path(__file__).resolve().parents[2] / "web/src/components/HostLink.tsx").read_text(encoding="utf-8")
    declared = re.search(r"export type HostSection =(.*?);", src, re.DOTALL)
    assert declared and set(re.findall(r'"([a-z-]+)"', declared.group(1))) == set(get_args(HostSection))
