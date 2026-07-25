"""自簽憑證續期必須帶入 operator 設定的 validity_days / key_algorithm。

不帶的話，續期會悄悄退回函式預設值（397 天 / ecdsa-p256），把設定洗掉——
而且最容易發生在啟動路徑以外的續期觸發點（每日 job、GUI 手動、CLI 選單），
因為那些地方的 tls 設定不在手邊。這裡除了行為測試，另加一條 AST 不變量
掃描全部呼叫點，避免「修點不修類」再漏一處。
"""
import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

# 續期／重簽的呼叫一律必須明示這兩個參數
_RENEW_FUNCS = {"_maybe_auto_renew_self_signed", "_generate_self_signed_cert"}
_REQUIRED_KWARGS = {"days", "key_algorithm"}


def _renew_call_sites():
    """回傳 src/ 底下所有「會真的重簽」的呼叫點 (path, lineno, kwargs)。

    只看重簽路徑：_maybe_auto_renew_self_signed 一律算；
    _generate_self_signed_cert 只有帶 force=True 或本來就會落檔的呼叫算。
    """
    for py in _SRC.rglob("*.py"):
        # utf-8-sig：src/reporter.py 帶 BOM，utf-8 讀進來 ast.parse 會炸
        tree = ast.parse(py.read_text(encoding="utf-8-sig"), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if name not in _RENEW_FUNCS:
                continue
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            # 函式自身的預設參數轉呼叫（_helpers 內部那層）也要帶，故不排除
            yield py.relative_to(_SRC.parent), node.lineno, kwargs


def test_all_cert_renew_call_sites_pass_config_values():
    offenders = [
        f"{path}:{lineno} 缺少 {sorted(_REQUIRED_KWARGS - kwargs)}"
        for path, lineno, kwargs in _renew_call_sites()
        if not _REQUIRED_KWARGS <= kwargs
    ]
    assert not offenders, (
        "以下憑證重簽呼叫點沒帶 validity_days / key_algorithm，"
        "續期會把 operator 設定洗回預設值：\n  " + "\n  ".join(offenders)
    )


def test_call_site_scan_actually_finds_the_known_sites():
    """防止掃描器本身壞掉後這條不變量變成空跑。"""
    files = {str(path) for path, _, _ in _renew_call_sites()}
    for expected in ("src/scheduler/jobs.py", "src/gui/routes/config.py",
                     "src/cli/menus/web_gui.py", "src/gui/__init__.py",
                     "src/gui/_helpers.py"):
        assert expected in files, f"掃描器沒看到已知呼叫點 {expected}"


def test_daily_renew_job_passes_configured_days_and_algorithm(monkeypatch):
    """每日續期 job 是實際的續期主要觸發點——它必須帶設定值。"""
    import src.gui._helpers as helpers
    from src.scheduler.jobs import run_tls_renew_check

    captured = {}

    def _fake_renew(cert_dir, threshold_days=30, days=None, key_algorithm=None):
        captured.update(cert_dir=cert_dir, threshold_days=threshold_days,
                        days=days, key_algorithm=key_algorithm)
        return False, 100

    monkeypatch.setattr(helpers, "_maybe_auto_renew_self_signed", _fake_renew)

    class _CM:
        config = {"web_gui": {"tls": {
            "enabled": True, "self_signed": True, "auto_renew": True,
            "auto_renew_days": 14, "validity_days": 90,
            "key_algorithm": "rsa-2048",
        }}}

    run_tls_renew_check(_CM())

    assert captured["threshold_days"] == 14
    assert captured["days"] == 90, "續期沒帶設定的 validity_days"
    assert captured["key_algorithm"] == "rsa-2048", "續期沒帶設定的 key_algorithm"


def test_daily_renew_job_falls_back_to_defaults_when_unset(monkeypatch):
    import src.gui._helpers as helpers
    from src.scheduler.jobs import run_tls_renew_check

    captured = {}

    def _fake_renew(cert_dir, threshold_days=30, days=None, key_algorithm=None):
        captured.update(days=days, key_algorithm=key_algorithm)
        return False, 100

    monkeypatch.setattr(helpers, "_maybe_auto_renew_self_signed", _fake_renew)

    class _CM:
        config = {"web_gui": {"tls": {"enabled": True, "self_signed": True}}}

    run_tls_renew_check(_CM())

    assert captured["days"] == helpers._SELF_SIGNED_VALIDITY_DAYS
    assert captured["key_algorithm"] == "ecdsa-p256"


def test_manual_gui_renew_passes_configured_values(app_persistent, temp_config_file,
                                                   monkeypatch):
    """GUI 的「立即續期」按鈕同樣不得把設定洗掉（真的打 route）。"""
    import json
    import src.gui.routes.config as routes_config

    app_persistent.config["WTF_CSRF_ENABLED"] = False

    # route 開頭會 cm.load() 重讀，所以直接寫進設定檔即可
    with open(temp_config_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("web_gui", {})["tls"] = {
        "enabled": True, "self_signed": True,
        "validity_days": 90, "key_algorithm": "rsa-2048",
    }
    with open(temp_config_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    captured = {}

    def _fake_generate(cert_dir, force=False, days=None, key_algorithm=None):
        captured.update(force=force, days=days, key_algorithm=key_algorithm)
        return "/tmp/cert.pem", "/tmp/key.pem"

    monkeypatch.setattr(routes_config, "_generate_self_signed_cert", _fake_generate)
    monkeypatch.setattr(routes_config, "_get_cert_info", lambda p: {"path": p})

    client = app_persistent.test_client()
    client.post("/api/login", json={"username": "admin", "password": "testpass"})
    res = client.post("/api/tls/renew", json={})

    assert res.status_code == 200, res.get_data(as_text=True)
    assert captured["force"] is True
    assert captured["days"] == 90, "手動續期沒帶設定的 validity_days"
    assert captured["key_algorithm"] == "rsa-2048", "手動續期沒帶設定的 key_algorithm"
