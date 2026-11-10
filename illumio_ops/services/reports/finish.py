"""What every built report gets before it is rendered (6.6.0), whatever its type:
- a section that was computed and holds nothing (every block an empty table or an empty chart) no longer takes a
  panel of its own: it becomes one line — its title and what its empty table said — in a closing section "Nothing
  to show this period", so a reader still sees it was looked at;
- a table column that is blank on every row is not printed;
- one data note when none of the key numbers has a previous period to compare with (it replaces the "No previous
  period" line that sat under every number);
- a data note said twice is said once.
A part that is missing for another reason (an unset setting, an analysis not run, an unsupported PCE) is not this
module's: its builder leaves it out and says why in the data notes (hints.py).
Called by generate (and by the tests that build a report directly)."""
from __future__ import annotations

from illumio_ops.domain.report import (
    BarBlock,
    Block,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.services.reports.common import tr

NOTHING = "nothing"  # the closing section's id


def _empty(block: Block) -> bool:
    if isinstance(block, TableBlock):
        return not block.rows
    if isinstance(block, BarBlock):
        return all(v is None or v == 0 for _, v in block.points)
    return False  # words are content


def holds_nothing(section: Section) -> bool:
    """Every block is a table without rows or a chart without a value (a section with words is not judged)."""
    return bool(section.blocks) and all(_empty(b) for b in section.blocks)


def _line(section: Section) -> str:
    said = next((b.empty_text for b in section.blocks if isinstance(b, (TableBlock, BarBlock)) and b.empty_text), "")
    return f"{section.title}: {said}" if said else section.title


def _without_empty_columns(block: Block) -> Block:
    """A table's columns that hold a value in at least one row (a column blank on every row is not printed); a
    table with no rows, or whose every column is blank, is left as it is."""
    if not isinstance(block, TableBlock) or not block.rows:
        return block
    keep = [i for i in range(len(block.columns)) if any(r[i] not in (None, "") for r in block.rows)]
    if not keep or len(keep) == len(block.columns):
        return block
    return block.model_copy(update={"columns": tuple(block.columns[i] for i in keep),
                                    "rows": tuple(tuple(r[i] for i in keep) for r in block.rows)})


def finish(doc: ReportDocument) -> ReportDocument:
    doc = doc.model_copy(update={"sections": tuple(
        s.model_copy(update={"blocks": tuple(_without_empty_columns(b) for b in s.blocks)}) for s in doc.sections)})
    notes = list(dict.fromkeys(doc.data_quality))
    valued = [k for k in doc.kpis if k.value is not None]
    if valued and all(k.previous is None for k in valued):
        notes.append(tr(doc.lang, "rpt_quality_no_previous"))
    kept = [s for s in doc.sections if not holds_nothing(s)]
    folded = [s for s in doc.sections if holds_nothing(s)]
    if folded and kept:  # a report with nothing at all keeps its sections: each says why it is empty
        kept.append(Section(id=NOTHING, title=tr(doc.lang, "rpt_sec_nothing"), intro=tr(doc.lang, "rpt_nothing_intro"),
                            blocks=(TextBlock(paragraphs=tuple(_line(s) for s in folded)),)))
    else:
        kept = list(doc.sections)
    return doc.model_copy(update={"data_quality": tuple(notes), "sections": tuple(kept)})
