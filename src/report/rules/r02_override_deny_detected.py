"""R02: Override deny rule present in draft — cannot be overridden by any allow rule."""
from __future__ import annotations

import pandas as pd

from src.i18n import t
from src.report.rules._base import Finding, _DraftPdRuleMixin


class R02OverrideDenyDetected(_DraftPdRuleMixin):
    """R02: Override deny rule present in draft — cannot be overridden by any allow rule."""

    severity = "HIGH"

    def evaluate(self, flows_df: pd.DataFrame, ctx: dict) -> list[Finding]:
        if not self._has_draft(flows_df):
            return []
        matched = flows_df[
            flows_df["draft_policy_decision"].str.endswith("_override_deny", na=False)
        ]
        if matched.empty:
            return []
        return [Finding(
            rule_id="R02",
            rule_name=t("rule_r02_name"),
            severity=self.severity,
            category="DraftPolicy",
            description=t("rule_r02_desc"),
            recommendation=t("rule_r02_rec"),
            evidence={
                "matching_flows": len(matched),
                "draft_decisions": str(matched["draft_policy_decision"].value_counts().to_dict()),
            },
        )]
