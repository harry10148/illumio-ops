"""R01: Flows currently allowed but a draft deny rule would block them."""
from __future__ import annotations

import pandas as pd

from src.i18n import t
from src.report.rules._base import Finding, _DraftPdRuleMixin


class R01DraftDenyDetected(_DraftPdRuleMixin):
    """R01: Flows currently allowed but a draft deny rule would block them."""

    severity = "HIGH"

    def evaluate(self, flows_df: pd.DataFrame, ctx: dict) -> list[Finding]:
        if not self._has_draft(flows_df):
            return []
        _deny_values = {"blocked_by_boundary", "blocked_by_override_deny"}
        matched = flows_df[
            (flows_df["policy_decision"] == "allowed") &
            flows_df["draft_policy_decision"].isin(_deny_values)
        ]
        if matched.empty:
            return []
        return [Finding(
            rule_id="R01",
            rule_name=t("rule_r01_name"),
            severity=self.severity,
            category="DraftPolicy",
            description=t("rule_r01_desc"),
            recommendation=t("rule_r01_rec"),
            evidence={
                "matching_flows": len(matched),
                "draft_decisions": str(matched["draft_policy_decision"].value_counts().to_dict()),
            },
        )]
