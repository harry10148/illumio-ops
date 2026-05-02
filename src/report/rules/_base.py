"""Shared building blocks for the per-rule modules.

Holds the :class:`Finding` dataclass and the :class:`_DraftPdRuleMixin` base
that the R01–R05 draft-policy-decision rules share.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# ─── Finding model ───────────────────────────────────────────────────────────

SEVERITY_RANK = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}


@dataclass
class Finding:
    rule_id: str
    rule_name: str
    severity: str            # CRITICAL | HIGH | MEDIUM | LOW | INFO
    category: str            # e.g. Ransomware, LateralMovement, Policy
    description: str
    recommendation: str
    evidence: dict = field(default_factory=dict)   # supporting data for the finding

    @property
    def severity_rank(self) -> int:
        return SEVERITY_RANK.get(self.severity, 99)

    def to_dict(self) -> dict:
        return {
            'rule_id': self.rule_id,
            'rule_name': self.rule_name,
            'severity': self.severity,
            'category': self.category,
            'description': self.description,
            'recommendation': self.recommendation,
            **{f'evidence_{k}': v for k, v in self.evidence.items()},
        }


# ─── Draft policy-decision rule mixin ────────────────────────────────────────

class _DraftPdRuleMixin:
    """Mixin that marks a rule as requiring draft_policy_decision data."""

    def needs_draft_pd(self) -> bool:
        return True

    def _has_draft(self, flows_df: pd.DataFrame) -> bool:
        return "draft_policy_decision" in flows_df.columns
