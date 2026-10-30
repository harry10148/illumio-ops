"""A report as data (spec §6.5.5): cover, key metrics with the previous period, findings, data quality and
sections of tables, bar charts and text. Builders fill it with already-translated text; the HTML, XLSX and
email renderers read only this, so the three outputs of one report cannot disagree.

Length rules (project rule: no silent truncation): a table holds every row it has (the XLSX writes them
all, up to XLSX_ROW_CAP); the HTML shows the first HTML_ROW_CAP and says how many there are and where the
rest is; a cell longer than CELL_SOFT_MAX characters is cut in the HTML only, with its full length stated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SkipValidation,
    model_validator,
)

from illumio_ops.domain.values import Language, ReportType, Severity

HTML_ROW_CAP = 200
XLSX_ROW_CAP = 1_000_000
CELL_SOFT_MAX = 2_000
BAR_POINT_CAP = 90

Cell = str | int | float | None


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Kpi(_Model):
    key: str
    label: str
    value: int | float | None  # None: could not be computed; `note` says why (never shown as 0)
    previous: int | float | None  # None: no previous period to compare with
    unit: Literal["count", "percent"] = "count"
    better: Literal["lower", "higher", "neutral"] = "neutral"
    note: str | None = None


class Finding(_Model):
    severity: Severity
    title: str
    why: str
    action: str


class Column(_Model):
    key: str
    label: str
    kind: Literal["text", "number", "time", "host"] = "text"


class TableBlock(_Model):
    kind: Literal["table"] = "table"
    title: str
    columns: tuple[Column, ...] = Field(min_length=1)
    rows: tuple[tuple[Cell, ...], ...]
    total_rows: int  # rows that exist; more than len(rows) when the builder's read was itself limited
    empty_text: str  # what an empty table says (why there is nothing), never a blank panel
    limit_note: str | None = None  # the builder's own read limit, when it hit it

    @model_validator(mode="after")
    def _shape(self) -> TableBlock:
        width = len(self.columns)
        if any(len(r) != width for r in self.rows):
            raise ValueError("every row has one cell per column")
        if self.total_rows < len(self.rows):
            raise ValueError("total_rows counts at least the rows held")
        return self


class BarBlock(_Model):
    kind: Literal["bars"] = "bars"
    title: str
    points: tuple[tuple[str, int | float | None], ...]  # None: no data for that point (a gap, not 0)
    empty_text: str


class TextBlock(_Model):
    kind: Literal["text"] = "text"
    paragraphs: tuple[str, ...]


Block = TableBlock | BarBlock | TextBlock


class Section(_Model):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    title: str
    intro: str = ""
    blocks: tuple[Block, ...] = ()


class RowsExport(_Model):
    """A report's flat rows for the JSON and CSV formats (policy_resolver: rows for other tools, spec §6.5). The rows
    are not validated one by one: half a million of them would cost seconds for nothing."""
    columns: tuple[str, ...]
    rows: SkipValidation[list[tuple[str | int | float | None, ...]]]
    meta: dict[str, str | int | float | bool | None] = {}


class ReportDocument(_Model):
    report_type: ReportType
    lang: Language
    title: str
    period_start: AwareDatetime
    period_end: AwareDatetime
    generated_at: AwareDatetime
    pce_label: str
    kpis: tuple[Kpi, ...]
    findings: tuple[Finding, ...]
    data_quality: tuple[str, ...]
    sections: tuple[Section, ...]
    gui_link: str | None = None
    export: RowsExport | None = None  # the JSON / CSV content, for types that make those formats

    @model_validator(mode="after")
    def _ids(self) -> ReportDocument:
        ids = [s.id for s in self.sections]
        if len(ids) != len(set(ids)) or "appendix" in ids:
            raise ValueError("section ids are unique and 'appendix' is reserved")
        return self

    def tables(self) -> list[tuple[Section, TableBlock]]:
        return [(s, b) for s in self.sections for b in s.blocks if isinstance(b, TableBlock)]


def period_text(start: datetime, end: datetime, tz: tzinfo | None) -> str:
    """'2026-10-20 – 2026-10-26' in the display zone, for a period whose end is exclusive."""
    first = start.astimezone(tz)
    last = (end - timedelta(microseconds=1)).astimezone(tz)
    return f"{first:%Y-%m-%d} – {last:%Y-%m-%d}"
