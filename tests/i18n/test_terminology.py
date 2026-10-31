"""Traditional Chinese terminology (spec §6.2 用語, user 2026-10-29): what the PCE console shows stays as it shows it —
the console has no Chinese UI, so a customer reading "可能被擋" cannot find it there — and general prose is Chinese.
Each pattern is a spelling that must not appear in zh_TW; the comment names the one to use."""
import json
import re
from pathlib import Path

import pytest

ZH = json.loads((Path(__file__).resolve().parents[2] / "illumio_ops" / "i18n" / "zh_TW.json").read_text())

BANNED = {
    # policy decisions: the console's own words
    r"可能被擋|potentially[_ ]blocked|Potentially blocked": "Potentially Blocked",
    r"\bblocked\b|\bBlock\b": "Blocked（判定）或「擋下」（動作）",
    r"\ballowed\b|\bAllow\b|\ballow\b": "Allowed（判定）或「規則允許」",
    # enforcement modes and states
    r"\bfull\b|\bselective\b|\bidle\b|visibility[_ ]only|完全強制|僅可見|閒置|test 模式|測試模式": "Full／Selective／Idle／Visibility Only",
    r"\benforce[ds]?\b|\benforcement\b|\bEnforcement\b": "強制",
    # objects and products
    r"\bworkloads?\b|\bWorkloads\b|工作負載": "主機（一般）或 Workload（PCE 物件）",
    r"\blabels?\b|標籤": "Label",
    r"\bagent\b": "VEN",
    r"規則集|\brule-?sets?\b": "Ruleset",
    r"\bdeny 規則|\bdeny rules?\b|拒絕規則|\boverride deny\b": "Deny Rule／Override Deny",
    r"\bboundary\b|enforcement boundary": "Deny Rule 或「邊界」",
    r"\b[Ss]ervices?\b": "服務",
    r"\b[Pp]olicy\b": "政策",
    r"\b[Uu]nmanaged\b|\b[Mm]anaged\b": "非受管／受管",
    r"\bManage\b": "管理",
    r"草稿|已佈署|佈署": "Draft／Active／Provision",
    r"可見度": "Visibility",
    r"連接埠|(?<!主)埠": "port",
}


def _words(text: str) -> str:
    return re.sub(r"\{\w+\}", " ", text)  # placeholders ({service}, {full}) are names, not words


@pytest.mark.parametrize("pattern", list(BANNED))
def test_zh_terminology(pattern):
    hits = sorted(k for k, v in ZH.items() if re.search(pattern, _words(v)))
    assert hits == [], f"use {BANNED[pattern]!r}: {hits}"


def test_gate_catches_an_old_spelling():
    """The gate itself: a value written the old way is caught, a placeholder is not."""
    assert re.search(r"可能被擋|potentially[_ ]blocked", _words("{pb} 筆流量可能被擋"))
    assert not re.search(r"\b[Ss]ervices?\b", _words("新的 {service} 連線"))
