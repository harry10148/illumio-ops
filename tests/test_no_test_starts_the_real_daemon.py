"""沒有任何測試可以在這個 checkout 裡啟動真的常駐模式。

2026-09-12 的事故：`test_cli_backwards_compat.py` 為了證明 argparse 還認得
`--monitor -i 1`，直接 `Popen([python, "illumio-ops.py", "--monitor", "-i", "1"])`
跑三秒再 terminate。三秒足夠完成一個 monitor cycle——而子行程讀的是**安裝好的**
`config/config.json`（真的 LINE token、真的 SMTP）與 `logs/state.json`。於是每跑一次
全套測試，就有一則「[重大] PCE 連線看門狗」真的送到操作者的 LINE 和信箱。使用者
為此花了一小時在五台機器上找「那台發警的 appliance」，而那則告警一直是我們自己
的測試機跑測試時發的。

**為什麼不能靠環境變數或 cwd 隔離**：設定檔路徑由**套件位置**決定
（`src/config.py` 的 `ROOT_DIR = dirname(dirname(__file__))`），沒有任何 env 或
cwd 能改掉它。只要是在這個 checkout 裡以真常駐模式起來的子行程，用的就是真的
收件設定。所以規則不是「隔離好再跑」，是**不要跑**。

這支掃的是整個 tests/ 目錄，不是那一支檔案——同一種寫法在別處出現一樣要擋下。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent

# 會真的做事、會讀真設定、會對外發送的執行模式。`--help` / `version` / `status`
# 不在此列：它們讀設定但不派送，也不進入排程迴圈。
RUN_MODE_FLAGS = frozenset({
    "--monitor", "--monitor-gui", "--gui", "--report",
    "monitor", "monitor-gui", "gui", "report",
})
ENTRY_NAMES = ("illumio-ops.py", "illumio_ops.py", "src/main.py", "src.main")

_SPAWNERS = {"Popen", "run", "call", "check_call", "check_output"}


def _string_literals(node: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _spawn_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in _SPAWNERS:
            yield node


def _offending(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # 不是這支測試該管的問題
        return []
    out = []
    for call in _spawn_calls(tree):
        literals = _string_literals(call)
        # 進入點可能以變數帶入（ENTRY = REPO_ROOT / "illumio-ops.py"），所以
        # 只要**這個呼叫**裡出現任何一個執行模式旗標就算命中——一個測試沒有
        # 理由把 "--monitor" 交給子行程，除非它就是要起那個模式。
        if any(lit in RUN_MODE_FLAGS for lit in literals):
            out.append(f"{path.name}:{call.lineno}")
    return out


def test_no_test_spawns_the_app_in_a_run_mode():
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        offenders.extend(_offending(path))
    assert not offenders, (
        "這些測試把執行模式旗標交給了子行程：" + ", ".join(offenders) + "。"
        "在這個 checkout 裡起真常駐模式＝用真的 LINE／SMTP 設定發真的告警"
        "（設定路徑綁套件位置，env 與 cwd 都改不掉）。"
        "要驗參數就問 src.main.build_legacy_parser()；要驗行為就注入假的 Reporter。"
    )


def test_the_gate_would_catch_the_original_defect(tmp_path):
    """反向驗證：把當初那段寫回去，這道閘門必須紅。"""
    offender = tmp_path / "test_reintroduced.py"
    offender.write_text(
        "import subprocess, sys\n"
        "def test_x():\n"
        "    subprocess.Popen([sys.executable, 'illumio-ops.py', '--monitor', '-i', '1'])\n",
        encoding="utf-8",
    )
    assert _offending(offender), "閘門對原始缺陷無感，等於沒有閘門"


@pytest.mark.parametrize("snippet", [
    "subprocess.run([sys.executable, ENTRY, 'version'])",
    "subprocess.run([sys.executable, ENTRY, '--help'])",
    "subprocess.run([sys.executable, ENTRY, 'status'])",
])
def test_the_gate_leaves_the_harmless_invocations_alone(tmp_path, snippet):
    ok = tmp_path / "test_ok.py"
    ok.write_text(f"import subprocess, sys\nENTRY='x'\ndef test_x():\n    {snippet}\n",
                  encoding="utf-8")
    assert not _offending(ok)


# ── 第二半：測試不得寫進這個 checkout 的 state ──────────────────────────────
# 同一種病的輕症。daemon 那條路會真的對外發送；這條路只寫檔，但寫的是同一個
# `logs/state.json`：dispatch_history 只留 50 筆，跑一次測試就把真實派送紀錄擠
# 掉（2026-09-12 就是這樣把當天那筆真 LINE 派送的證據洗掉的），而看門狗的計數與
# 冷卻時戳也在同一個檔案裡——測試可以決定一個真部署的下一次告警發不發得出來。

def test_the_state_file_is_not_the_one_in_this_checkout():
    """斷言的是**執行當下的實際值**，不是 conftest 裡有沒有那支 fixture。"""
    import src.analyzer
    import src.reporter

    repo_logs = (Path(__file__).resolve().parent.parent / "logs").resolve()
    for module in (src.reporter, src.analyzer):
        actual = Path(module.STATE_FILE).resolve()
        assert repo_logs not in actual.parents, (
            f"{module.__name__}.STATE_FILE 指向 {actual}——測試會寫進這個 checkout "
            "真正在用的 state：dispatch_history 會被擠掉，看門狗計數與冷卻時戳會被"
            "改掉。見 tests/conftest.py 的 _isolate_state_file。"
        )


def test_every_state_resolver_is_redirected():
    """五個 writer、三種解析方式，一個漏掉就等於沒隔離。

    2026-09-12 第一版只改了 reporter/analyzer 的模組常數，全套跑完
    `logs/state.json` 仍然被動到——`adhoc_report_jobs`、`posture_summary`、
    `rule_schedule_states` 各自走別的路徑。斷言解析**結果**，不是解析方式。
    """
    import src.analyzer
    import src.reporter
    from src.config import resolve_state_file
    from src.rule_scheduler import _resolve_rule_state_file
    from src.gui._helpers import _resolve_state_file

    repo_logs = (Path(__file__).resolve().parent.parent / "logs").resolve()
    resolved = {
        "config.resolve_state_file": resolve_state_file(),
        "gui._helpers._resolve_state_file": _resolve_state_file(),
        "rule_scheduler._resolve_rule_state_file": _resolve_rule_state_file(),
        "reporter.STATE_FILE": src.reporter.STATE_FILE,
        "analyzer.STATE_FILE": src.analyzer.STATE_FILE,
    }
    # ReportScheduler 把路徑存成 instance 屬性，不是模組層的東西——真的建一個
    # 出來問它。第一版的閘門只掃模組層，把 report_scheduler 放過去了。
    from unittest.mock import MagicMock

    from src.report_scheduler import ReportScheduler

    resolved["ReportScheduler._state_file"] = ReportScheduler(
        MagicMock(), MagicMock())._state_file

    leaking = {k: v for k, v in resolved.items()
               if repo_logs in Path(v).resolve().parents}
    assert not leaking, f"這些仍指向這個 checkout 的 logs/：{leaking}"


def test_the_override_reaches_every_resolver_in_a_fresh_process():
    """只設環境變數、不靠 conftest 的 monkeypatch，五個解析點必須一致。

    Codex review P2：`reporter.STATE_FILE` / `analyzer.STATE_FILE` 原本自己拼
    `ROOT_DIR/logs/state.json`，不走 resolver，所以即使在 import 前設好環境變數，
    scheduler／GUI 會用新路徑、watchdog 與派送紀錄仍寫進 checkout 的舊檔——
    **狀態分裂**，而 conftest 額外 monkeypatch 兩個常數正好把這個缺口蓋住。
    這支不吃 conftest 的 fixture，開一個乾淨行程問。
    """
    import json
    import subprocess
    import sys

    target = "/tmp/illumio-ops-state-override-probe.json"
    out = subprocess.run(
        [sys.executable, "-c",
         "import json, src.reporter, src.analyzer\n"
         "from src.config import resolve_state_file\n"
         "from src.rule_scheduler import _resolve_rule_state_file\n"
         "print(json.dumps({'resolver': resolve_state_file(),\n"
         "  'rule': _resolve_rule_state_file(),\n"
         "  'reporter': src.reporter.STATE_FILE,\n"
         "  'analyzer': src.analyzer.STATE_FILE}))"],
        cwd=str(Path(__file__).resolve().parent.parent),
        env={**os.environ, "ILLUMIO_OPS_STATE_FILE": target},
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    resolved = json.loads(out.stdout.strip().splitlines()[-1])
    assert set(resolved.values()) == {target}, f"路徑分裂：{resolved}"
