"""部分成功的報表產出不得在 GUI 上長得跟整份失敗一樣。

audit / policy_usage 端點在「HTML 產出了但 xlsx 匯出失敗」時回
``{ok:false, partial:true, files:[...], failed_formats:[...]}``。dashboard.js
以前只看 ``r.ok``，於是操作者只看到一則錯誤 toast、``loadReports()`` 不會被
呼叫，已經落地的檔案完全看不到——看起來像整份沒產出，操作者就重跑一次。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "src" / "static" / "js" / "dashboard.js"
ROUTES = ROOT / "src" / "gui" / "routes" / "reports.py"

# JS handler -> the endpoint it posts to (both endpoints can reply partial).
PARTIAL_HANDLERS = {
    "_doGenerateAudit": "/api/audit_report/generate",
    "_doGeneratePolicyUsage": "/api/policy_usage_report/generate",
    "_doGeneratePolicyUsageClean": "/api/policy_usage_report/generate",
}


def _handler_body(js: str, name: str) -> str:
    start = js.index(f"async function {name}(")
    nxt = js.find("\nasync function ", start + 1)
    return js[start:nxt if nxt != -1 else len(js)]


def test_backend_still_emits_the_partial_shape():
    """守門對象存在才有意義：端點必須仍回 partial + failed_formats + files。"""
    src = ROUTES.read_text(encoding="utf-8")
    assert src.count('"ok": False, "partial": True, "files": filenames') == 2
    assert src.count('"failed_formats": sorted(export_errors)') == 2


def test_each_partial_capable_handler_branches_on_partial():
    js = JS.read_text(encoding="utf-8")
    for name, endpoint in PARTIAL_HANDLERS.items():
        body = _handler_body(js, name)
        assert endpoint in body, f"{name} no longer posts to {endpoint}"
        assert re.search(r"else if \(r\.partial\)\s*\{\s*_handlePartialReport\(r\);", body), (
            f"{name} must route the partial response to _handlePartialReport, "
            "otherwise a partial success is shown as a total failure"
        )


def test_partial_handler_warns_names_formats_and_refreshes_the_list():
    js = JS.read_text(encoding="utf-8")
    start = js.index("function _handlePartialReport(")
    body = js[start:js.index("\n}", start)]
    assert "r.failed_formats" in body, "the warning must name which formats failed"
    assert "'warn'" in body, "partial success is a warning, not a plain error toast"
    assert "loadReports()" in body, "the files that did land must still be listed"
    assert "_t('gui_toast_report_partial')" in body


def test_partial_branch_does_not_reuse_the_total_failure_toast():
    """partial 分支不得落回 err toast，否則跟整份失敗無法區分。"""
    js = JS.read_text(encoding="utf-8")
    start = js.index("function _handlePartialReport(")
    body = js[start:js.index("\n}", start)]
    assert "'err'" not in body
