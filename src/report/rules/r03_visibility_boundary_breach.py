"""R03: VEN in visibility/test mode and a deny boundary draft exists for this flow."""
from __future__ import annotations

import pandas as pd

from src.i18n import t
from src.report.rules._base import Finding, _DraftPdRuleMixin


class R03VisibilityBoundaryBreach(_DraftPdRuleMixin):
    """R03: VEN in visibility/test mode and a deny boundary draft exists for this flow."""

    severity = "MEDIUM"

    def evaluate(self, flows_df: pd.DataFrame, ctx: dict) -> list[Finding]:
        if not self._has_draft(flows_df):
            return []
        matched = flows_df[
            (flows_df["policy_decision"] == "potentially_blocked") &
            (flows_df["draft_policy_decision"] == "potentially_blocked_by_boundary")
        ]
        if matched.empty:
            return []
        return [Finding(
            rule_id="R03",
            rule_name=t("rule_r03_name"),
            severity=self.severity,
            category="DraftPolicy",
            description=t("rule_r03_desc"),
            recommendation=t("rule_r03_rec"),
            evidence={
                "matching_flows": len(matched),
            },
        )]
