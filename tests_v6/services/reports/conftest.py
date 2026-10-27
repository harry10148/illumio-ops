from datetime import UTC, datetime

import pytest

from illumio_ops.domain.report import Column, Kpi, ReportDocument, Section, TableBlock
from illumio_ops.domain.values import Language, ReportType

START = datetime(2026, 10, 20, tzinfo=UTC)
END = datetime(2026, 10, 27, tzinfo=UTC)


def make_doc(**over):
    base = dict(report_type=ReportType.LATERAL_POSTURE, lang=Language.EN, title="Lateral movement posture",
                period_start=START, period_end=END, generated_at=END, pce_label="pce.lab.local",
                kpis=(Kpi(key="k1", label="Pivot hosts", value=3, previous=1, better="lower"),),
                findings=(), data_quality=("Traffic covers the whole period.",), sections=())
    base.update(over)
    return ReportDocument(**base)


def table(rows, *, title="Hosts", total=None, cols=2):
    columns = tuple(Column(key=f"c{i}", label=f"Col {i}") for i in range(cols))
    return TableBlock(title=title, columns=columns, rows=tuple(rows),
                      total_rows=len(rows) if total is None else total, empty_text="Nothing here")


@pytest.fixture
def doc():
    return make_doc


@pytest.fixture
def doc_with_rows():
    def build(n, *, cell="host"):
        rows = [(cell if i == 0 else f"h{i}", i) for i in range(n)]
        return make_doc(sections=(Section(id="hosts", title="Hosts", blocks=(table(rows),)),))
    return build
