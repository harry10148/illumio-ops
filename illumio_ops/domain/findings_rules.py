"""The findings rules carried over from 5.x (src/report/rules_engine.py B001–B009, L001–L010, 5.x 3758c4b8): their
ids, categories, copy keys and the port sets they read. The evaluation is in services.reports.findings; what changed
from 5.x is said there, rule by rule."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from illumio_ops.domain.values import Severity

TCP, UDP = 6, 17

# (port, protocol) sets, protocol-aware like the built-in management ports (2026-10-27).
CRITICAL_PORTS = frozenset({(135, TCP), (445, TCP), (3389, TCP), (3389, UDP), (5985, TCP), (5986, TCP)})
HIGH_PORTS = frozenset({(5938, TCP), (5938, UDP), (5900, TCP), (137, UDP), (138, UDP), (139, TCP)})
MEDIUM_PORTS = frozenset({(22, TCP), (2049, TCP), (2049, UDP), (20, TCP), (21, TCP), (5353, UDP), (5355, UDP),
                          (80, TCP), (3702, UDP), (1900, UDP), (23, TCP)})
DB_PORTS = frozenset({(p, TCP) for p in (1433, 3306, 5432, 1521, 27017, 6379, 9200, 5984, 50000)})
IDENTITY_PORTS = frozenset({(88, TCP), (88, UDP), (389, TCP), (389, UDP), (636, TCP), (3268, TCP), (3269, TCP),
                            (464, TCP), (464, UDP)})
CLEARTEXT_PORTS = frozenset({(20, TCP), (21, TCP), (23, TCP)})
DISCOVERY_PORTS = frozenset({(137, UDP), (138, UDP), (5353, UDP), (5355, UDP), (1900, UDP), (3702, UDP)})
WINDOWS_MGMT_PORTS = frozenset({(135, TCP), (445, TCP), (5985, TCP), (5986, TCP), (47001, TCP)})


@dataclass(frozen=True)
class RuleInfo:
    rule_id: str
    category: str  # ransomware | exposure | coverage | lateral | data | hygiene
    name_key: str
    how_key: str


# Copy keys are spelled out: the i18n gate counts a key as used only where it appears as a literal.
RULES: tuple[RuleInfo, ...] = (
    RuleInfo("B001", "ransomware", "rpt_rule_b001_name", "rpt_rule_b001_how"),
    RuleInfo("B002", "ransomware", "rpt_rule_b002_name", "rpt_rule_b002_how"),
    RuleInfo("B003", "exposure", "rpt_rule_b003_name", "rpt_rule_b003_how"),
    RuleInfo("B004", "exposure", "rpt_rule_b004_name", "rpt_rule_b004_how"),
    RuleInfo("B005", "coverage", "rpt_rule_b005_name", "rpt_rule_b005_how"),
    RuleInfo("B006", "lateral", "rpt_rule_b006_name", "rpt_rule_b006_how"),
    RuleInfo("B007", "lateral", "rpt_rule_b007_name", "rpt_rule_b007_how"),
    RuleInfo("B008", "data", "rpt_rule_b008_name", "rpt_rule_b008_how"),
    RuleInfo("B009", "hygiene", "rpt_rule_b009_name", "rpt_rule_b009_how"),
    RuleInfo("L001", "exposure", "rpt_rule_l001_name", "rpt_rule_l001_how"),
    RuleInfo("L002", "exposure", "rpt_rule_l002_name", "rpt_rule_l002_how"),
    RuleInfo("L003", "lateral", "rpt_rule_l003_name", "rpt_rule_l003_how"),
    RuleInfo("L004", "lateral", "rpt_rule_l004_name", "rpt_rule_l004_how"),
    RuleInfo("L005", "lateral", "rpt_rule_l005_name", "rpt_rule_l005_how"),
    RuleInfo("L006", "lateral", "rpt_rule_l006_name", "rpt_rule_l006_how"),
    RuleInfo("L007", "lateral", "rpt_rule_l007_name", "rpt_rule_l007_how"),
    RuleInfo("L008", "lateral", "rpt_rule_l008_name", "rpt_rule_l008_how"),
    RuleInfo("L009", "data", "rpt_rule_l009_name", "rpt_rule_l009_how"),
    RuleInfo("L010", "lateral", "rpt_rule_l010_name", "rpt_rule_l010_how"),
)
BY_ID = {r.rule_id: r for r in RULES}
CATEGORY_KEYS = {"ransomware": "rpt_rule_cat_ransomware", "exposure": "rpt_rule_cat_exposure",
                 "coverage": "rpt_rule_cat_coverage", "lateral": "rpt_rule_cat_lateral", "data": "rpt_rule_cat_data",
                 "hygiene": "rpt_rule_cat_hygiene"}
SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


@dataclass(frozen=True)
class RuleOutcome:
    """A rule that fired (severity set) or could not be evaluated (error set); desc/rec are copy keys + params."""
    rule_id: str
    severity: Severity | None
    desc_key: str
    rec_key: str
    params: dict[str, Any]
    error: str | None = None


def ranked(outcomes: list[RuleOutcome]) -> list[RuleOutcome]:
    """Most severe first, then by rule id; rules that could not be evaluated last."""
    return sorted(outcomes, key=lambda o: (o.severity is None, SEVERITY_RANK.get(o.severity, 9) if o.severity else 9,
                                           o.rule_id))
