from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from illumio_ops.domain.report import Column, Section, TableBlock, period_text
from tests_v6.services.reports.conftest import make_doc


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
