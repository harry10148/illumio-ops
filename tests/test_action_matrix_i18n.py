"""Action Matrix recommendation strings must come from the i18n table,
not from hardcoded Python tuples."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = ROOT / "src" / "i18n_en.json"
ZH = ROOT / "src" / "i18n_zh_TW.json"
MOD12 = ROOT / "src" / "report" / "analysis" / "mod12_executive_summary.py"

EXPECTED_KEYS = [
    "rpt_actmtx_ransomware_msg",
    "rpt_actmtx_ransomware_reco",
    "rpt_actmtx_lateral_msg",
    "rpt_actmtx_lateral_reco",
    "rpt_actmtx_unmanaged_msg",
    "rpt_actmtx_unmanaged_reco",
    "rpt_actmtx_data_volume_msg",
    "rpt_actmtx_data_volume_reco",
]


def test_action_matrix_keys_in_both_locales() -> None:
    en = json.loads(EN.read_text(encoding="utf-8"))
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    for k in EXPECTED_KEYS:
        assert k in en, f"missing in en: {k}"
        assert k in zh, f"missing in zh_TW: {k}"


def test_lateral_zh_recommendation_well_formed() -> None:
    """The recommendation for 'lateral' should describe applying micro-
    segmentation to RDP/SSH/SMB, not the broken phrase '橫向通信窗用'."""
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    reco = zh["rpt_actmtx_lateral_reco"]
    assert "RDP" in reco and "SSH" in reco and "SMB" in reco
    assert "微分段" in reco
    assert "通信窗用" not in reco, f"old broken phrase still present: {reco!r}"


def test_mod12_uses_t_helper_not_hardcoded() -> None:
    src = MOD12.read_text(encoding="utf-8")
    # The recommendation must come through i18n now
    assert "rpt_actmtx_lateral_reco" in src, (
        "expected mod12 to reference rpt_actmtx_lateral_reco via i18n.t()"
    )
