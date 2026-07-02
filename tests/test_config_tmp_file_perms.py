"""ConfigManager.save() 不可再以預設 umask（通常 0644）建立 config.json /
alerts.json 的 .tmp 暫存檔。兩個檔案都含機密（api.key/secret、smtp.password、
web_gui.password/secret_key、line/webhook token），暫存檔必須「建檔當下」就是
0600，而不是等 os.replace() 落地後才 chmod。write() 與 replace() 之間若程序崩潰，
絕不能留下 world/group 可讀、內含機密的暫存檔。
"""
import json
import os
import stat


def _make_cm(tmp_path):
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "rules": [{"id": 1, "type": "event", "name": "r1", "filter_value": "x"}],
    }), encoding="utf-8")
    return ConfigManager(config_file=str(cfg))


def test_save_creates_tmp_files_with_0600_before_replace(tmp_path, monkeypatch):
    """攔截 os.replace，在暫存檔即將被改名落地的當下檢查其權限——也就是在
    post-replace chmod 有機會執行之前。config.json 與 alerts.json 的暫存檔
    在此時點都必須已經是 0600。
    """
    cm = _make_cm(tmp_path)

    captured = []
    real_replace = os.replace

    def spy_replace(src, dst):
        mode = stat.S_IMODE(os.stat(src).st_mode)
        captured.append((os.path.basename(dst), mode))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    cm.save()

    dsts = {name for name, _ in captured}
    assert {"config.json", "alerts.json"} <= dsts, f"expected both files replaced, saw {captured}"
    for name, mode in captured:
        assert mode == 0o600, f"{name} tmp file was created with mode {oct(mode)}, expected 0o600"
