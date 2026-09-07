"""規則模擬一筆都沒命中時，畫面必須說出是哪一道篩選擋下的。

成因（2026-09-08）：測試機的 traffic 規則永遠不觸發，模擬印的是

    [時間篩選] 原始：31698 -> 規則視窗（10080 分鐘）：剩餘 0 筆

那行字掛著「時間篩選」的名字，印的卻是**過完所有條件之後**的筆數。真正的
原因是這個環境一筆 blocked 流量都沒有，而規則篩的正是 blocked——把視窗從
10 分鐘調到 7 天當然沒有用，但畫面上沒有任何一行字會反駁那個猜測。診斷訊息
把人送去錯的地方，比沒有訊息更貴。

斷言對準「操作者看完能不能知道要去改什麼」，不是對準字串長相。
"""
import datetime
from unittest.mock import MagicMock

from src.analyzer import Analyzer
from src.i18n import t


class _DebugApi:
    def __init__(self, flows):
        self._flows = flows

    def fetch_events(self, since):
        return []

    def execute_traffic_query_stream(self, start, end, pds):
        return iter(self._flows)


def _rule(**over):
    rule = {
        "id": "tr1", "name": "blocked watcher", "type": "traffic",
        "threshold_type": "count", "threshold_count": 25,
        "threshold_window": 10, "pd": 2, "cooldown_minutes": 0,
    }
    rule.update(over)
    return rule


def _flow(decision, *, minutes_ago=1):
    ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago)
    stamp = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "timestamp_range": {"first_detected": stamp, "last_detected": stamp},
        "policy_decision": decision,
        "num_connections": 3,
        "src": {}, "dst": {}, "service": {},
    }


def _analyzer(rules, flows):
    cm = MagicMock()
    cm.config = {"rules": rules}
    az = Analyzer(cm, _DebugApi(flows), MagicMock())
    az.save_state = MagicMock()
    az.load_state = MagicMock()
    return az


def _stages(**kw):
    """用同一支 t() 組出那一行——斷言鎖的是**數字**，不是某一種語言的字面。"""
    return t('debug_zero_match_stages', **kw)


def test_when_the_decision_is_what_excludes_everything_the_window_is_not_blamed(capsys):
    """視窗留得下流量、判定留不下 —— 畫面要說出這個分野。"""
    flows = [_flow("potentially_blocked") for _ in range(7)] + [_flow("allowed")]
    az = _analyzer([_rule()], flows)

    az.run_debug_mode(mins=12, pd_sel=3, interactive=False)
    out = capsys.readouterr().out

    # 逐層數字：8 筆進來，8 筆在視窗內，0 筆帶著規則要的判定。
    assert _stages(total=8, win=10, after_window=8, after_pd=0, decision="blocked") in out, out
    # 這批流量實際有的判定必須被列出來——「這裡根本沒有 blocked」才是答案。
    assert "potentially_blocked=7" in out, out
    assert "allowed=1" in out, out


def test_when_the_window_is_what_excludes_everything_it_says_so(capsys):
    """反向：真的是視窗太小時，第一段就要掉到 0，操作者才知道該調視窗。"""
    flows = [_flow("blocked", minutes_ago=600) for _ in range(5)]
    az = _analyzer([_rule()], flows)

    az.run_debug_mode(mins=1200, pd_sel=3, interactive=False)
    out = capsys.readouterr().out

    assert _stages(total=5, win=10, after_window=0, after_pd=0, decision="blocked") in out, out
    # 判定分佈仍然要印，且顯示這裡有 blocked——排除「沒有 blocked」這個誤判。
    assert "blocked=5" in out, out


def test_a_rule_that_does_match_prints_no_breakdown(capsys):
    """有命中就不該再印一段拆解——診斷訊息只在需要時出現。"""
    az = _analyzer([_rule()], [_flow("blocked") for _ in range(3)])

    az.run_debug_mode(mins=12, pd_sel=3, interactive=False)
    out = capsys.readouterr().out

    assert _stages(total=3, win=10, after_window=3, after_pd=3, decision="blocked") not in out
    assert "Stage by stage" not in out
    assert "逐層拆解" not in out


def test_the_summary_line_no_longer_calls_itself_a_time_filter(capsys):
    """那一行印的是過完所有條件的筆數，就不可以叫「時間篩選」——這正是把人
    送去調視窗的那個名字。"""
    az = _analyzer([_rule()], [_flow("allowed")])

    az.run_debug_mode(mins=12, pd_sel=3, interactive=False)
    out = capsys.readouterr().out

    assert "時間篩選" not in out
    assert "[Filters]" in out or "[篩選]" in out


def test_a_flow_carrying_only_the_pd_ordinal_zero_is_not_reported_as_unknown(capsys):
    """`pd` 是 0（allowed）時，`policy_decision or pd` 會把它當假值跳過，
    分佈行就會印成 `?=N`——正好是判定分佈最該說清楚的那一格。"""
    flows = [{"timestamp": datetime.datetime.now(datetime.timezone.utc)
              .strftime("%Y-%m-%dT%H:%M:%SZ"),
              "pd": 0, "num_connections": 1,
              "src": {}, "dst": {}, "service": {}} for _ in range(4)]
    az = _analyzer([_rule(pd=2)], flows)

    az.run_debug_mode(mins=12, pd_sel=3, interactive=False)
    out = capsys.readouterr().out

    assert "allowed=4" in out, out
    assert "?=4" not in out, out
