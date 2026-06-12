"""Every mapped technique id is well-formed; governance rules stay unmapped."""
import re

from src.report.analysis.mitre_map import RULE_TECHNIQUES, techniques_for

_TID = re.compile(r"^T\d{4}(\.\d{3})?$")


def test_all_technique_ids_well_formed():
    for rule_id, techs in RULE_TECHNIQUES.items():
        for tid, name in techs:
            assert _TID.match(tid), f"{rule_id}: bad technique id {tid}"
            assert name


def test_lookup_known_and_unknown():
    assert techniques_for("B006")          # lateral movement 必有對應
    assert techniques_for("B005") == ()    # 治理型規則不對應
    assert techniques_for("NOPE") == ()
