"""Traditional Chinese terminology (spec §6.2 用語, user 2026-10-29; purpose-led UI spec §5.6, user 2026-11-12): general
prose is Chinese, and what the PCE console shows is written as the console shows it — it has no Chinese UI, so a
customer reading "可能被擋" cannot find it there. Where a policy decision or an enforcement mode is a name (a table
cell, a filter option, a state, a column, a number's name, a chapter or table title) it is said in plain words with the
console's word in brackets after it: 「開始擋之後會被擋（Potentially Blocked）」, the term_decision_* and term_mode_*
keys. Inside a sentence the console's word stands alone.
Each pattern is a spelling that must not appear in zh_TW, in a name or in a sentence; the comment names the one to use."""
import json
import re
from pathlib import Path

import pytest

ZH = json.loads((Path(__file__).resolve().parents[2] / "illumio_ops" / "i18n" / "zh_TW.json").read_text())

BANNED = {
    # policy decisions: the console's own words
    r"可能被擋|potentially[_ ]blocked|Potentially blocked": "「開始擋之後會被擋（Potentially Blocked）」（名稱）或 Potentially Blocked（句子裡）",
    r"\bblocked\b|\bBlock\b": "Blocked（判定）或「擋下」（動作）",
    r"\ballowed\b|\bAllow\b|\ballow\b": "Allowed（判定）或「規則允許」",
    r"^允許$|^被擋$|^被擋（|允許$(?<=Deny Rule 允許)":
        "判定值當名稱時寫白話加括號原文（「有規則允許（Allowed）」「已被擋下（Blocked）」，term_decision_*）；句子裡寫 Allowed／Blocked",
    # enforcement modes and states
    r"\bfull\b|\bselective\b|\bidle\b|visibility[_ ]only|完全強制|選擇性強制|僅可見|僅可視|閒置|test 模式|測試模式": "Full／Selective／Idle／Visibility Only",
    r"\benforce[ds]?\b|\benforcement\b|\bEnforcement\b": "強制",
    # objects and products
    r"\bworkloads?\b|\bWorkloads\b|工作負載": "主機（一般）或 Workload（PCE 物件）",
    r"\blabels?\b|標籤": "Label",
    r"\bagent\b|(?<!Lost )\bAgent\b": "VEN（PCE 的事件名 Lost Agent 除外）",
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
    # a sentence states what was observed or a fixed rule, never a guess at the cause (user 2026-11-03)
    r"多半|可能代表|攻擊者已|人或腳本": "只寫觀察到的事實或固定規則，不寫推論",
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


def test_a_decision_name_is_plain_words_then_the_pce_word():
    """Where a decision is a name, the reader who does not know Illumio gets it in plain words and the one checking
    against the PCE console gets the console's word in brackets."""
    assert {k: ZH[k] for k in ZH if k.startswith("term_decision_")} == {
        "term_decision_allowed": "有規則允許（Allowed）",
        "term_decision_potentially_blocked": "開始擋之後會被擋（Potentially Blocked）",
        "term_decision_blocked": "已被擋下（Blocked）"}
