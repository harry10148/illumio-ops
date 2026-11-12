"""A report as data (spec §6.5.5): cover, key metrics with the previous period, findings, data quality and
sections of tables, bar charts and text. Builders fill it with already-translated text; the HTML, XLSX and
email renderers read only this, so the three outputs of one report cannot disagree.

Length rules (project rule: no silent truncation): a table holds every row it has (the XLSX writes them
all, up to XLSX_ROW_CAP); the HTML shows the first HTML_ROW_CAP and says how many there are and where the
rest is; a cell longer than CELL_SOFT_MAX characters is cut in the HTML only, with its full length stated.
A report has at most 2 caveats ("know this before reading the numbers"): a third is refused when the document is
built, never dropped. One thing to do (domain/actions.py) lists the titles of its first 4 findings and says how many
more there are; the first page lists the first 3 things to do and says how many more there are.
The email is the first page: 3 numbers (the others are in the report), the first 3 things to do and how many more;
it lists no finding and no data note, and only its subject is ever cut (render_email.SUBJECT_MAX, with an ellipsis).
The XLSX summary writes every caveat, number and finding whole.
On paper a table lists its first PRINT_ROW_CAP rows (the first as the reader sorted them) and a sentence under it
says how many there are and where: the XLSX sheet, or the report on screen. The tables of "how to read this report"
are printed whole. Every finding is a card (no cap: the rules are 19 at most, a builder adds a handful).
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
CAVEATS_MAX = 2
PRINT_ROW_CAP = 10
# Section ids a builder may not use: 'notes' is the data notes chapter the HTML renderer writes at the end.
RESERVED_SECTION_IDS = frozenset({"appendix", "notes"})

# The part of the host page a table's host links open at: the web app's HostSection (components/HostLink.tsx).
HostSection = Literal["status", "alerts", "different", "usual", "connections", "would-block", "ransomware", "tamper",
                      "quarantine"]

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
    techniques: tuple[tuple[str, str], ...] = ()  # MITRE ATT&CK (id, official English name), never translated
    what: str = ""  # what happened (the fact); empty: the card's first part is the title alone
    # What to do, as a code: findings with the same code are one thing to do (domain/actions.py). action_short is
    # the one imperative sentence of that thing; action_focus one sentence naming where most of it is (may be empty).
    action_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    action_short: str = ""
    action_focus: str = ""

    @model_validator(mode="after")
    def _action(self) -> Finding:
        if self.action_code is not None and not self.action_short.strip():
            raise ValueError("a finding with an action code says what to do (action_short)")
        return self


def techniques_text(techniques: tuple[tuple[str, str], ...]) -> str:
    """'T1486 Data Encrypted for Impact, T1021.002 SMB/Windows Admin Shares' (a table cell, an XLSX cell)."""
    return ", ".join(f"{tid} {name}" for tid, name in techniques)


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
    # Rows the HTML prints (the first N, 0: none); the XLSX always holds them all. None: the renderer's own cap.
    # html_note says, in the builder's words, what the rows left out of the HTML are.
    html_rows: int | None = Field(default=None, ge=0)
    html_note: str | None = None
    # Column key -> the host key of each row's cell in that column, in the order of `rows` (None: that cell names
    # no host the console has a page for). Only the first HTML_ROW_CAP rows need one: the HTML prints no more and
    # the XLSX carries no links. Matched to columns by key, never by position (columns are dropped before printing).
    host_keys: dict[str, tuple[str | None, ...]] = {}
    host_section: HostSection | None = None  # the part of the host page the links open at

    @model_validator(mode="after")
    def _shape(self) -> TableBlock:
        width = len(self.columns)
        if any(len(r) != width for r in self.rows):
            raise ValueError("every row has one cell per column")
        if self.total_rows < len(self.rows):
            raise ValueError("total_rows counts at least the rows held")
        keys = {c.key for c in self.columns}
        if any(k not in keys for k in self.host_keys):
            raise ValueError("host_keys are given per column key")
        if any(len(v) > len(self.rows) for v in self.host_keys.values()):
            raise ValueError("host_keys hold at most one key per row")
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
    workbench_link: str | None = None  # the section's analysis segment opened in the workbench (custom reports)


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
    conclusion: str = ""  # the one opening sentence (domain/conclusion.py), filled by the generator
    # "Know this before reading the numbers", right under the opening sentence: two sentences at most.
    caveats: tuple[str, ...] = Field(default=(), max_length=CAVEATS_MAX)
    # The console's external address (settings.reports.gui_external_url, no trailing '/'), filled by the generator
    # where it fills gui_link. None: no address is set, so the report links nowhere.
    gui_base: str | None = None

    @model_validator(mode="after")
    def _ids(self) -> ReportDocument:
        ids = [s.id for s in self.sections]
        if len(ids) != len(set(ids)) or RESERVED_SECTION_IDS & set(ids):
            raise ValueError("section ids are unique; 'appendix' and 'notes' are reserved")
        return self

    def tables(self) -> list[tuple[Section, TableBlock]]:
        return [(s, b) for s in self.sections for b in s.blocks if isinstance(b, TableBlock)]


def period_text(start: datetime, end: datetime, tz: tzinfo | None) -> str:
    """'2026-10-20 – 2026-10-26' in the display zone, for a period whose end is exclusive."""
    first = start.astimezone(tz)
    last = (end - timedelta(microseconds=1)).astimezone(tz)
    return f"{first:%Y-%m-%d} – {last:%Y-%m-%d}"
