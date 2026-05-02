"""R04: Allow rule overrides a regular deny boundary. Verify this is intentional."""
from __future__ import annotations

import pandas as pd

from src.i18n import t
from src.report.rules._base import Finding, _DraftPdRuleMixin


class R04AllowedAcrossBoundary(_DraftPdRuleMixin):
    """R04: Allow rule overrides a regular deny boundary. Verify this is intentional."""

    severity = "LOW"

    def evaluate(self, flows_df: pd.DataFrame, ctx: dict) -> list[Finding]:
        if not self._has_draft(flows_df):
            return []
        matched = flows_df[
            flows_df["draft_policy_decision"] == "allowed_across_boundary"
        ]
        if matched.empty:
            return []
        return [Finding(
            rule_id="R04",
            rule_name=t("rule_r04_name"),
            severity=self.severity,
            category="DraftPolicy",
            description=t("rule_r04_desc"),
            recommendation=t("rule_r04_rec"),
            evidence={
                "matching_flows": len(matched),
            },
        )]
