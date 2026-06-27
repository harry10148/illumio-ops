"""R05: Aggregated list of workload pairs where reported=allowed but draft suggests block."""
from __future__ import annotations

import pandas as pd

from src.i18n import t
from src.report.rules._base import Finding, _DraftPdRuleMixin


class R05DraftReportedMismatch(_DraftPdRuleMixin):
    """R05: Aggregated list of workload pairs where reported=allowed but draft suggests block."""

    severity = "INFO"

    def evaluate(self, flows_df: pd.DataFrame, ctx: dict, lang: str = "en") -> list[Finding]:
        if not self._has_draft(flows_df):
            return []
        # Match the standard PCE draft decisions (blocked / potentially_blocked)
        # as well as the boundary/override-deny subtypes (blocked_*).
        _draft = flows_df["draft_policy_decision"]
        matched = flows_df[
            (flows_df["policy_decision"] == "allowed") &
            (_draft.isin({"blocked", "potentially_blocked"}) |
             _draft.str.startswith("blocked_", na=False))
        ]
        if matched.empty:
            return []
        src_col = "src" if "src" in flows_df.columns else "src_ip" if "src_ip" in flows_df.columns else None
        dst_col = "dst" if "dst" in flows_df.columns else "dst_ip" if "dst_ip" in flows_df.columns else None
        if src_col and dst_col:
            top_pairs = matched[[src_col, dst_col]].head(20).to_dict("records")
        else:
            top_pairs = []
        return [Finding(
            rule_id="R05",
            rule_name=t("rule_r05_name", lang=lang),
            severity=self.severity,
            category="DraftPolicy",
            description=t("rule_r05_desc", lang=lang),
            recommendation=t("rule_r05_rec", lang=lang),
            evidence={
                "mismatch_count": len(matched),
                "top_pairs": str(top_pairs),
            },
        )]
