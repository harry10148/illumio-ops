"""部分成功的報表產出不得在 GUI 上長得跟整份失敗一樣。

audit / policy_usage 端點在「HTML 產出了但 xlsx 匯出失敗」時回
``{ok:false, partial:true, files:[...], failed_formats:[...]}``。前端若只看
``r.ok``，操作者只會看到一則錯誤 toast、清單不會刷新，已經落地的檔案完全看不
到——看起來像整份沒產出，操作者就重跑一次。

Phase 2A Task 11：守門對象從已刪除的 src/static/js/dashboard.js
（``_doGenerateAudit`` / ``_doGeneratePolicyUsage`` /
``_doGeneratePolicyUsageClean`` 三個 handler 各自的 ``else if (r.partial)``
分支，加上共用的 ``_handlePartialReport``）改為
src/static/js/v2/areas/reports.mjs。v2 只有一條產生路徑（``finishGenerate``），
三個 handler 收斂成一個分支，所以「每個 handler 都要接上」那條變成「唯一的
那條要接上」；其餘四項斷言（命名失敗格式、warn 而非 err、刷新清單、用
gui_toast_report_partial）逐條保留。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "src" / "static" / "js" / "v2" / "areas" / "reports.mjs"
ROUTES = ROOT / "src" / "gui" / "routes" / "reports.py"


def _partial_branch(js: str) -> str:
    """The `if (res && res.partial) { ... }` block of finishGenerate()."""
    start = js.index("if (res && res.partial) {")
    return js[start:js.index("\n  }", start)]


def test_backend_still_emits_the_partial_shape():
    """守門對象存在才有意義：端點必須仍回 partial + failed_formats + files。"""
    src = ROUTES.read_text(encoding="utf-8")
    assert src.count('"ok": False, "partial": True, "files": filenames') == 2
    assert src.count('"failed_formats": sorted(export_errors)') == 2


def test_generate_result_branches_on_partial_before_the_failure_path():
    """partial 必須在通用失敗分支之前被攔下，否則就被當成整份失敗。"""
    js = JS.read_text(encoding="utf-8")
    partial_at = js.index("if (res && res.partial) {")
    fail_at = js.index('const msg = (res && res.error) || t(TOAST_FAIL[rt.id]')
    assert partial_at < fail_at, "partial 分支必須早於通用失敗分支"


def test_partial_handler_warns_names_formats_and_refreshes_the_list():
    body = _partial_branch(JS.read_text(encoding="utf-8"))
    assert "res.failed_formats" in body, "the warning must name which formats failed"
    assert "toast.warn(" in body, "partial success is a warning, not a plain error toast"
    assert "refreshList()" in body, "the files that did land must still be listed"
    assert 'tf("gui_toast_report_partial"' in body


def test_partial_branch_does_not_reuse_the_total_failure_toast():
    """partial 分支不得落回 crit toast，否則跟整份失敗無法區分。"""
    body = _partial_branch(JS.read_text(encoding="utf-8"))
    assert "toast.crit(" not in body
