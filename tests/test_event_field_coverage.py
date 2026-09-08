"""每一個 PCE 事件欄位，都要嘛有人讀，要嘛有人簽名說不讀。

2026-09-08 的成因：PCE 26.2 給 `agent.tampering` 的 `notifications[].info` 加了
五個欄位（含「這次竄改有沒有被自動還原」），正規化器整包丟掉。4700 支測試綠、
十道閘門綠、畫面只是少了一句話。**沒有任何機制在看「PCE 給了什麼、我們讀了
什麼」的差集**，而 PCE 每次升版都會再動一次。

這個檔案把那個差集變成常態閘門：`tests/data/pce_event_shapes.json` 是從測試機
真機抓來的**路徑**語料（29 個 event_type、只有鍵沒有值，所以不含任何事件內容），
對照 `src/events/field_coverage.py` 的帳本。多出一條沒登記的路徑就紅，逼人做一次
決定：讀它，或寫下不讀的理由。

語料更新：`PYTHONPATH=. venv/bin/python tools/audit_event_fields.py --days 90
--write-shapes`（PCE 升版後跑）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from src.events.field_coverage import (
    FIELD_LEDGER, KNOWN_RESOURCE_TYPES, leaf_paths, unledgered,
)
from src.events.normalizer import normalize_event

SHAPES_FILE = pathlib.Path(__file__).parent / "data" / "pce_event_shapes.json"
SHAPES: dict[str, list[str]] = json.loads(SHAPES_FILE.read_text(encoding="utf-8"))


def test_the_corpus_is_real_and_broad_enough_to_mean_something():
    """一份只有兩個型別的語料會讓下面每一條都變成裝飾。"""
    assert len(SHAPES) >= 20, f"只有 {len(SHAPES)} 個 event_type，語料太窄"
    assert sum(len(v) for v in SHAPES.values()) >= 300


def test_the_corpus_carries_no_values_only_paths():
    """語料進 repo 的前提是它不含任何事件內容。"""
    for paths in SHAPES.values():
        for path in paths:
            assert "=" not in path and " " not in path.replace(" / ", ""), path


@pytest.mark.parametrize("event_type", sorted(SHAPES))
def test_every_field_this_pce_sends_is_accounted_for(event_type):
    missing = unledgered(SHAPES[event_type])
    assert not missing, (
        f"{event_type} 有 {len(missing)} 個沒人看、也沒人簽名的欄位：{missing}\n"
        "到 src/events/field_coverage.py 的 FIELD_LEDGER 逐條決定：讀它，"
        "或寫下不讀的理由。")


class TestTheExemptionsStillHoldTheirPremises:
    """三個無界家族的豁免各自綁著一個實作前提。前提沒了，豁免就是在說謊——
    而說謊的方向正好是「新欄位無聲消失」，也就是這整個機制要防的那件事。"""

    def test_notification_info_is_still_taken_wholesale(self):
        """前提：任意純量鍵都會被收下，不是白名單。"""
        ev = {"event_type": "agent.tampering", "timestamp": "2026-09-06T14:15:47Z",
              "notifications": [{"notification_type": "x",
                                 "info": {"a_field_nobody_has_seen": 42}}]}
        assert normalize_event(ev)["notification_info"]["a_field_nobody_has_seen"] == 42

    def test_resource_changes_are_still_only_counted(self):
        """前提：沒有任何行為依賴某個屬性名，所以多一個屬性不會壞掉。"""
        ev = {"event_type": "workload.update", "timestamp": "2026-09-06T14:15:47Z",
              "resource_changes": [{"resource_type": "workload",
                                    "changes": {"whatever": {"before": 1, "after": 2}}}]}
        assert normalize_event(ev)["resource_changes_count"] == 1

    def test_an_unknown_resource_type_is_still_reported(self):
        """<type> 底下放行，但 <type> 本身不是無界的：PCE 開始送一種沒見過的
        資源型別是值得知道的事。"""
        known = unledgered(["resource_changes[].resource.workload.name"])
        unknown = unledgered(["resource_changes[].resource.quantum_thing.name"])
        assert known == []
        assert unknown == ["resource_changes[].resource.quantum_thing.name"]
        assert "quantum_thing" not in KNOWN_RESOURCE_TYPES


class TestTheWalkerItself:
    def test_lists_collapse_to_one_shape(self):
        paths = leaf_paths({"a": [{"b": 1}, {"b": 2}, {"c": 3}]})
        assert paths == ["a[].b", "a[].c"]

    def test_empty_containers_are_shapes_too(self):
        assert leaf_paths({"a": [], "b": {}}) == ["a[]", "b"]

    def test_a_ledger_entry_without_a_reason_is_not_possible(self):
        """帳本的值不是布林，是理由——空字串等於沒簽名。"""
        for path, reason in FIELD_LEDGER.items():
            assert isinstance(reason, str) and reason.strip(), path
