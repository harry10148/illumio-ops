"""Data visibility in reports (spec §6.5 資料收集: the data visibility check): the managed hosts whose VEN reports
only blocked traffic, or none. Traffic they were allowed is not in the store, so a report whose conclusions rest on
host traffic names them and says its numbers for them are incomplete. The test is the home focus list's
(services/analysis/focus.BLIND). With no such host there is no section."""
from __future__ import annotations

from illumio_ops.domain.report import Column, Section, TableBlock
from illumio_ops.domain.values import VisibilityLevel
from illumio_ops.services.analysis.focus import BLIND
from illumio_ops.services.reports import reads
from illumio_ops.services.reports.common import tr
from illumio_ops.services.reports.registry import BuildInput
from illumio_ops.store.flowdb import workloads

ROWS = 200  # hosts listed; more are counted
_LEVEL_KEYS = {VisibilityLevel.FLOW_OFF.value: "rpt_vis_level_off", VisibilityLevel.FLOW_DROPS.value: "rpt_vis_level_drops"}


def visibility_sections(inp: BuildInput) -> tuple[Section, ...]:
    """The "hosts that report no allowed traffic" section, or nothing when every managed host reports its flows."""
    with reads.reading(inp.ctx) as conn:
        inventory = workloads.all_workloads(conn)
    blind = sorted((w.hostname or w.name or w.href, str(w.visibility_level))
                   for w in inventory if w.managed and w.visibility_level in BLIND)
    if not blind:
        return ()
    table = TableBlock(
        title=tr(inp.lang, "rpt_vis_tbl"),
        columns=(Column(key="host", label=tr(inp.lang, "rpt_col_host")),
                 Column(key="level", label=tr(inp.lang, "rpt_vis_col_level"))),
        rows=tuple((name, tr(inp.lang, _LEVEL_KEYS[level])) for name, level in blind[:ROWS]), total_rows=len(blind),
        empty_text="", limit_note=tr(inp.lang, "rpt_limit_top_n", n=ROWS) if len(blind) > ROWS else None)
    return (Section(id="visibility", title=tr(inp.lang, "rpt_vis_sec"),
                    intro=tr(inp.lang, "rpt_vis_intro", n=len(blind)), blocks=(table,)),)
