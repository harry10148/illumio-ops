import json
import sys
import pathlib

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[2] / "design" / "v2" / "tools"
sys.path.insert(0, str(TOOLS))
import capture_snapshots as cs  # noqa: E402


def test_manifest_loads_and_has_no_placeholders():
    entries = cs.load_manifest(TOOLS / "endpoints.yaml")
    assert len(entries) >= 30
    assert "FROM_STEP1" not in (TOOLS / "endpoints.yaml").read_text()
    for e in entries:
        assert e["method"] in ("GET", "POST") and e["path"].startswith("/")


def test_manifest_ids_are_unique():
    entries = cs.load_manifest(TOOLS / "endpoints.yaml")
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))


def test_path_from_entries_reference_a_path_placeholder():
    entries = cs.load_manifest(TOOLS / "endpoints.yaml")
    for e in entries:
        if "path_from" in e:
            assert "{" in e["path"] and "}" in e["path"]


def test_capture_writes_masked_json(tmp_path, monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return {"api_key": "SECRET", "rows": [1, 2]}

    monkeypatch.setattr(cs, "_request", lambda sess, base, e, csrf: FakeResp())
    out = cs.capture_one(None, "https://x", {"id": "demo", "method": "GET", "path": "/api/x"},
                          tmp_path, csrf="t")
    assert out is True
    data = (tmp_path / "demo.json").read_text()
    assert "SECRET" not in data and "***MASKED***" in data


def test_catalog_entries_flagged_in_manifest():
    # ui_translations/event_catalog/alert_plugins 的字典鍵是 identifier 或
    # 表單 schema 描述，不是機密欄位名——三者都必須標 mask: catalog，
    # capture_one 才會走 mask_values_only。
    entries = {e["id"]: e for e in cs.load_manifest(TOOLS / "endpoints.yaml")}
    assert entries["ui_translations"].get("mask") == "catalog"
    assert entries["event_catalog"].get("mask") == "catalog"
    assert entries["alert_plugins"].get("mask") == "catalog"


def test_capture_one_uses_mask_values_only_for_catalog_entries(tmp_path, monkeypatch):
    # gui_password/api_key 這種鍵名在一般端點會被語意規則遮掉，但在
    # mask: catalog 端點上是 i18n key，值（真正的顯示文字）必須保留。
    class FakeResp:
        status_code = 200

        def json(self):
            return {"gui_password": "密碼", "api_key": "API 金鑰說明文字"}

    monkeypatch.setattr(cs, "_request", lambda sess, base, e, csrf: FakeResp())
    out = cs.capture_one(
        None, "https://x",
        {"id": "ui_translations", "method": "GET", "path": "/api/ui_translations", "mask": "catalog"},
        tmp_path, csrf="t")
    assert out is True
    data = json.loads((tmp_path / "ui_translations.json").read_text())
    assert data == {"gui_password": "密碼", "api_key": "API 金鑰說明文字"}


def test_capture_one_returns_false_on_non_200(tmp_path, monkeypatch):
    class FakeResp:
        status_code = 500

        def json(self):
            return {}

    monkeypatch.setattr(cs, "_request", lambda sess, base, e, csrf: FakeResp())
    out = cs.capture_one(None, "https://x", {"id": "demo", "method": "GET", "path": "/api/x"},
                          tmp_path, csrf="t")
    assert out is False
    assert not (tmp_path / "demo.json").exists()


def test_resolve_path_from_substitutes_id_from_prior_snapshot(tmp_path):
    (tmp_path / "rs_rulesets.json").write_text(
        json.dumps({"items": [{"id": "rs-42"}, {"id": "rs-99"}]}))
    entry = {
        "id": "rs_ruleset_detail",
        "method": "GET",
        "path": "/api/rule_scheduler/rulesets/{rs_id}",
        "path_from": "rs_rulesets.items[0].id",
    }
    resolved = cs.resolve_path_from(entry, tmp_path)
    assert resolved == "/api/rule_scheduler/rulesets/rs-42"


def test_resolve_path_from_supports_dotted_field_and_module_name(tmp_path):
    (tmp_path / "logs_index.json").write_text(
        json.dumps({"ok": True, "modules": [{"name": "scheduler", "count": 3}]}))
    entry = {
        "id": "module_log_sample",
        "method": "GET",
        "path": "/api/logs/{module_name}",
        "path_from": "logs_index.modules[0].name",
    }
    resolved = cs.resolve_path_from(entry, tmp_path)
    assert resolved == "/api/logs/scheduler"


def test_resolve_path_from_missing_snapshot_raises(tmp_path):
    entry = {
        "id": "rs_ruleset_detail",
        "path": "/api/rule_scheduler/rulesets/{rs_id}",
        "path_from": "rs_rulesets.items[0].id",
    }
    with pytest.raises(FileNotFoundError):
        cs.resolve_path_from(entry, tmp_path)


def test_capture_one_resolves_path_from_before_requesting(tmp_path, monkeypatch):
    (tmp_path / "rs_rulesets.json").write_text(json.dumps({"items": [{"id": "rs-7"}]}))
    seen_paths = []

    class FakeResp:
        status_code = 200

        def json(self):
            return {"ok": True}

    def fake_request(sess, base, e, csrf):
        seen_paths.append(e["path"])
        return FakeResp()

    monkeypatch.setattr(cs, "_request", fake_request)
    entry = {
        "id": "rs_ruleset_detail",
        "method": "GET",
        "path": "/api/rule_scheduler/rulesets/{rs_id}",
        "path_from": "rs_rulesets.items[0].id",
    }
    out = cs.capture_one(None, "https://x", entry, tmp_path, csrf="t")
    assert out is True
    assert seen_paths == ["/api/rule_scheduler/rulesets/rs-7"]
