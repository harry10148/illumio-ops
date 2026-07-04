# tests/test_mod_drift_noise_filter.py
"""Baseline drift: noise-pair filtering + (unlabeled)->(unlabeled) collapse (spec L2).

Filtering must be symmetric on current AND prev signature sets *inside*
baseline_drift — filtering only the producer side (current) would still
report noise signatures unique to a stale/unfiltered prev baseline file as
"disappeared", which is the exact false-positive this spec closes.
"""
import pandas as pd

from src.report.analysis.mod_drift import _is_noise_signature, baseline_drift


def _current_df():
    return pd.DataFrame([
        # 正常配對：一筆延續、一筆本期新出現
        {"src_app": "Web", "dst_app": "DB", "port": 3306, "proto": "TCP", "num_connections": 40},
        {"src_app": "Web", "dst_app": "Cache", "port": 6379, "proto": "TCP", "num_connections": 7},
        # 本期獨有的雜訊配對——不應算作 new
        {"src_app": "Host9", "dst_app": "Host10", "port": 0, "proto": "TCP", "num_connections": 5},
        {"src_app": "Host11", "dst_app": "Host12", "port": 60000, "proto": "TCP", "num_connections": 5},
        {"src_app": "HostA", "dst_app": "HostB", "port": 8, "proto": "ICMP", "num_connections": 5},
        # 本期獨有的 unlabeled 配對——應收合，不進表
        {"src_app": "", "dst_app": "", "port": 80, "proto": "TCP", "num_connections": 2},
    ])


_PREV = {
    "Web|DB|3306|TCP",                     # 延續，無漂移
    "Batch|DB|3306|TCP",                   # 上期獨有的正常配對——應算 disappeared
    "HostC|HostD|8|ICMP",                  # 上期獨有的雜訊（ICMP）——不應算 disappeared
    "HostE|HostF|0|TCP",                   # 上期獨有的雜訊（port 0）——不應算 disappeared
    "HostG|HostH|55000|TCP",               # 上期獨有的雜訊（ephemeral port）——不應算 disappeared
    "(unlabeled)|(unlabeled)|443|TCP",     # 上期獨有的 unlabeled 配對——應收合
}


def _result():
    return baseline_drift(_current_df(), prev_signatures=set(_PREV), prev_generated_at="2026-06-01T00:00:00")


def test_noise_pairs_excluded_from_tables_and_count():
    res = _result()
    assert res["new_count"] == 1
    new_rows = res["new_pairs"]
    assert list(new_rows["Src App"]) == ["Web"]
    assert list(new_rows["Dst App"]) == ["Cache"]
    # 雜訊 src app 不應出現在表格任何一列
    assert "Host9" not in list(new_rows["Src App"])
    assert "Host11" not in list(new_rows["Src App"])
    assert "HostA" not in list(new_rows["Src App"])


def test_symmetric_filtering_prev_only_noise_not_disappeared():
    """核心對稱性測試：prev 獨有的雜訊簽名不得被誤判為 disappeared。

    若過濾僅套用在 current（產生端過濾），HostC/HostE/HostG 這三筆
    prev 獨有的雜訊仍會被判定為「消失」，因為它們從未出現在 current 裡。
    對稱過濾（both current 與 prev 都先濾除雜訊再做差集）才能避免這個誤判。
    """
    res = _result()
    assert res["disappeared_count"] == 1
    gone_rows = res["disappeared_pairs"]
    assert list(gone_rows["Src App"]) == ["Batch"]
    for noisy_src in ("HostC", "HostE", "HostG"):
        assert noisy_src not in list(gone_rows["Src App"])


def test_unlabeled_pairs_collapsed_on_both_sides():
    res = _result()
    assert res["new_unlabeled_collapsed"] == 1
    assert res["disappeared_unlabeled_collapsed"] == 1
    # 收合的 unlabeled 配對不應出現在表格裡
    new_rows = res["new_pairs"]
    gone_rows = res["disappeared_pairs"]
    assert not ((new_rows["Src App"] == "(unlabeled)") & (new_rows["Dst App"] == "(unlabeled)")).any()
    assert not ((gone_rows["Src App"] == "(unlabeled)") & (gone_rows["Dst App"] == "(unlabeled)")).any()
    # 且未計入 new_count / disappeared_count（僅計有效配對）
    assert res["new_count"] == 1
    assert res["disappeared_count"] == 1


def test_is_noise_signature_unit_cases():
    assert _is_noise_signature("A|B|443|TCP") is False
    assert _is_noise_signature("A|B|8|ICMP") is True
    assert _is_noise_signature("A|B|8|ICMPv6") is True
    assert _is_noise_signature("A|B|0|TCP") is True
    assert _is_noise_signature("A|B|55000|TCP") is True
    assert _is_noise_signature("A|B|49152|TCP") is True          # 邊界：ephemeral 起點
    assert _is_noise_signature("A|B|49151|TCP") is False         # 邊界：起點前一個 port
    assert _is_noise_signature("malformed") is True              # 解析失敗 → 視為雜訊
    assert _is_noise_signature("A|B|notanumber|TCP") is True     # port 非數字 → 視為雜訊
