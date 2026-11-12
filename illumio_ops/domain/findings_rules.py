"""The findings rules carried over from 5.x (src/report/rules_engine.py B001–B009, L001–L010, 5.x 3758c4b8): their
ids, categories, copy keys and the port sets they read. The evaluation is in services.reports.findings; what changed
from 5.x is said there, rule by rule."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
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


Technique = tuple[str, str]  # MITRE ATT&CK (id, official English name)


@dataclass(frozen=True)
class RuleInfo:
    rule_id: str
    category: str  # ransomware | exposure | coverage | lateral | data | hygiene
    name_key: str
    how_key: str
    why_key: str  # why the rule's finding matters: one fixed sentence
    techniques: tuple[Technique, ...] = ()


# MITRE ATT&CK techniques per rule, as 5.x src/report/analysis/mitre_map.py mapped them (3225b1d9). Governance rules
# carry none on purpose (B005 policy coverage, B009 cross-environment volume, L008 lateral ports in test mode):
# forcing a technique onto them would mislead a SOC reader.
_ENCRYPT: Technique = ("T1486", "Data Encrypted for Impact")
_REMOTE: Technique = ("T1021", "Remote Services")
_EXPLOIT: Technique = ("T1210", "Exploitation of Remote Services")
_EXFIL: Technique = ("T1048", "Exfiltration Over Alternative Protocol")
TECHNIQUES: dict[str, tuple[Technique, ...]] = {
    "B001": (_ENCRYPT, ("T1021.002", "SMB/Windows Admin Shares")),
    "B002": (_ENCRYPT, ("T1219", "Remote Access Software")),
    "B003": (_ENCRYPT,),
    "B004": (("T1046", "Network Service Discovery"),),
    "B006": (_REMOTE,),
    "B007": (("T1078", "Valid Accounts"),),
    "B008": (_EXFIL,),
    "L001": (("T1040", "Network Sniffing"),),
    "L002": (("T1557.001", "LLMNR/NBT-NS Poisoning and SMB Relay"),),
    "L003": (_EXPLOIT,),
    "L004": (_EXPLOIT,),
    "L005": (("T1558", "Steal or Forge Kerberos Tickets"),),
    "L006": (_REMOTE,),
    "L007": (_EXPLOIT,),
    "L009": (_EXFIL,),
    "L010": (_REMOTE, ("T1570", "Lateral Tool Transfer")),
}


# Copy keys are spelled out: the i18n gate counts a key as used only where it appears as a literal.
_LISTED: tuple[RuleInfo, ...] = (
    RuleInfo("B001", "ransomware", "rpt_rule_b001_name", "rpt_rule_b001_how",
             "rpt_rule_b001_why"),
    RuleInfo("B002", "ransomware", "rpt_rule_b002_name", "rpt_rule_b002_how",
             "rpt_rule_b002_why"),
    RuleInfo("B003", "exposure", "rpt_rule_b003_name", "rpt_rule_b003_how",
             "rpt_rule_b003_why"),
    RuleInfo("B004", "exposure", "rpt_rule_b004_name", "rpt_rule_b004_how",
             "rpt_rule_b004_why"),
    RuleInfo("B005", "coverage", "rpt_rule_b005_name", "rpt_rule_b005_how",
             "rpt_rule_b005_why"),
    RuleInfo("B006", "lateral", "rpt_rule_b006_name", "rpt_rule_b006_how",
             "rpt_rule_b006_why"),
    RuleInfo("B007", "lateral", "rpt_rule_b007_name", "rpt_rule_b007_how",
             "rpt_rule_b007_why"),
    RuleInfo("B008", "data", "rpt_rule_b008_name", "rpt_rule_b008_how",
             "rpt_rule_b008_why"),
    RuleInfo("B009", "hygiene", "rpt_rule_b009_name", "rpt_rule_b009_how",
             "rpt_rule_b009_why"),
    RuleInfo("L001", "exposure", "rpt_rule_l001_name", "rpt_rule_l001_how",
             "rpt_rule_l001_why"),
    RuleInfo("L002", "exposure", "rpt_rule_l002_name", "rpt_rule_l002_how",
             "rpt_rule_l002_why"),
    RuleInfo("L003", "lateral", "rpt_rule_l003_name", "rpt_rule_l003_how",
             "rpt_rule_l003_why"),
    RuleInfo("L004", "lateral", "rpt_rule_l004_name", "rpt_rule_l004_how",
             "rpt_rule_l004_why"),
    RuleInfo("L005", "lateral", "rpt_rule_l005_name", "rpt_rule_l005_how",
             "rpt_rule_l005_why"),
    RuleInfo("L006", "lateral", "rpt_rule_l006_name", "rpt_rule_l006_how",
             "rpt_rule_l006_why"),
    RuleInfo("L007", "lateral", "rpt_rule_l007_name", "rpt_rule_l007_how",
             "rpt_rule_l007_why"),
    RuleInfo("L008", "lateral", "rpt_rule_l008_name", "rpt_rule_l008_how",
             "rpt_rule_l008_why"),
    RuleInfo("L009", "data", "rpt_rule_l009_name", "rpt_rule_l009_how",
             "rpt_rule_l009_why"),
    RuleInfo("L010", "lateral", "rpt_rule_l010_name", "rpt_rule_l010_how",
             "rpt_rule_l010_why"),
)
RULES: tuple[RuleInfo, ...] = tuple(replace(r, techniques=TECHNIQUES.get(r.rule_id, ())) for r in _LISTED)
BY_ID = {r.rule_id: r for r in RULES}
CATEGORY_KEYS = {"ransomware": "rpt_rule_cat_ransomware", "exposure": "rpt_rule_cat_exposure",
                 "coverage": "rpt_rule_cat_coverage", "lateral": "rpt_rule_cat_lateral", "data": "rpt_rule_cat_data",
                 "hygiene": "rpt_rule_cat_hygiene"}

# What to do about a finding, as a code (domain/actions.py): findings with the same code are one thing to do. Keyed by
# (rule, the recommendation the rule chose): one rule recommends different things for different data (B001 allowed
# across environments, allowed inside one, or not yet blocked). Every recommendation key the engine can return is here.
ACTION_CODES: Mapping[tuple[str, str], str] = {
    ("B001", "rpt_rule_b001_rec_pb"): "enforce",
    ("B001", "rpt_rule_b001_rec_pb_cross_env"): "enforce",
    ("B003", "rpt_rule_b003_rec"): "enforce",
    ("B006", "rpt_rule_b006_rec_pb"): "enforce",
    ("L005", "rpt_rule_l005_rec_pb"): "enforce",
    ("L008", "rpt_rule_l008_rec"): "enforce",
    ("B001", "rpt_rule_b001_rec_critical_cross_env"): "cross_env_rules",
    ("B009", "rpt_rule_b009_rec"): "cross_env_rules",
    ("L004", "rpt_rule_l004_rec"): "cross_env_rules",
    ("L010", "rpt_rule_l010_rec"): "cross_env_rules",
    ("B001", "rpt_rule_b001_rec_allowed"): "narrow_rules",
    ("B002", "rpt_rule_b002_rec"): "narrow_rules",
    ("B006", "rpt_rule_b006_rec_allowed"): "narrow_rules",
    ("L003", "rpt_rule_l003_rec"): "narrow_rules",
    ("L005", "rpt_rule_l005_rec_allowed"): "narrow_rules",
    ("L006", "rpt_rule_l006_rec"): "narrow_rules",
    ("B005", "rpt_rule_b005_rec"): "write_rules",
    ("B004", "rpt_rule_b004_rec"): "unmanaged",
    ("L007", "rpt_rule_l007_rec"): "unmanaged",
    ("B007", "rpt_rule_b007_rec"): "accounts",
    ("B008", "rpt_rule_b008_rec"): "transfers",
    ("L009", "rpt_rule_l009_rec"): "transfers",
    ("L001", "rpt_rule_l001_rec"): "legacy_protocols",
    ("L002", "rpt_rule_l002_rec"): "legacy_protocols",
}
# The one imperative sentence of each code the rules use (the key is rpt_act_<code>, spelled out for the i18n gate).
ACTION_SHORT_KEYS: Mapping[str, str] = {
    "enforce": "rpt_act_enforce", "cross_env_rules": "rpt_act_cross_env_rules", "narrow_rules": "rpt_act_narrow_rules",
    "write_rules": "rpt_act_write_rules", "unmanaged": "rpt_act_unmanaged", "accounts": "rpt_act_accounts",
    "transfers": "rpt_act_transfers", "legacy_protocols": "rpt_act_legacy_protocols",
}
SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


@dataclass(frozen=True)
class RuleOutcome:
    """A rule that fired (severity set) or could not be evaluated (error set); desc/rec are copy keys + params.
    focus: the one the rule found most of (a host, an account, a pair of environments), taken from the first row of
    the ranking the rule already reads; empty for a rule that has no "who"."""
    rule_id: str
    severity: Severity | None
    desc_key: str
    rec_key: str
    params: dict[str, Any]
    error: str | None = None
    focus: str = ""


def ranked(outcomes: list[RuleOutcome]) -> list[RuleOutcome]:
    """Most severe first, then by rule id; rules that could not be evaluated last."""
    return sorted(outcomes, key=lambda o: (o.severity is None, SEVERITY_RANK.get(o.severity, 9) if o.severity else 9,
                                           o.rule_id))
