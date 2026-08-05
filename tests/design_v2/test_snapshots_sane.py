import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[2] / "design" / "v2"
sys.path.insert(0, str(ROOT / "tools"))
from masking import (
    is_sensitive_key, _HEXY_VALUE_RE, _PII_VALUE_GATED_KEYS, _PII_PATHS,
    _looks_like_pii_value, _child_path,
)
import yaml


def _manifest():
    return yaml.safe_load((ROOT / "tools" / "endpoints.yaml").read_text())


def _catalog_ids():
    # manifest `mask: catalog`（見 endpoints.yaml 註解）：這些端點的字典鍵名
    # 本身是 identifier（i18n key／event type key），不是機密欄位名，抓取時
    # 走 masking.mask_values_only（只掃 hex 值，不做 key 判定）——稽核在這裡
    # 也要對稱地跳過 key-based 斷言，否則會誤判「gui_password 沒被遮」。
    return {e["id"] for e in _manifest() if e.get("mask") == "catalog"}


def _snaps():
    files = sorted((ROOT / "snapshots").glob("*.json"))
    assert files, "no snapshots captured"
    return files


def test_every_manifest_entry_has_snapshot():
    ids = {e["id"] for e in _manifest()}
    have = {p.stem for p in _snaps()}
    assert ids <= have, f"missing snapshots: {ids - have}"


def test_no_unmasked_sensitive_values():
    catalog_ids = _catalog_ids()
    for p in _snaps():
        skip_key_audit = p.stem in catalog_ids

        def walk(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    if not skip_key_audit and is_sensitive_key(k):
                        assert v == "***MASKED***", f"{p.name}:{path}/{k} unmasked"
                    if isinstance(v, str):
                        assert not _HEXY_VALUE_RE.match(v), \
                            f"{p.name}:{path}/{k} hex-looking value unmasked"
                    walk(v, f"{path}/{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o): walk(v, f"{path}[{i}]")
        walk(json.loads(p.read_text()))


def test_last_target_and_line_target_id_masked_at_any_depth():
    # PII 專屬稽核（2026-08-03 使用者裁決 last_target 遮罩＋盤點時發現的
    # line_target_id 同源洩漏面）：這兩個鍵名一定是個資（收件 email／LINE
    # 使用者 ID），不論在哪個端點、哪個深度都必須是 MASK token；就算未來
    # 哪個端點被標成 mask: catalog（key 判定被跳過），這兩個鍵仍不可豁免——
    # 跟一般機密 key 稽核分開跑，故意不受 skip_key_audit 影響。
    pii_keys = {"last_target", "line_target_id"}
    for p in _snaps():
        def walk(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in pii_keys:
                        assert v == "***MASKED***", f"{p.name}:{path}/{k} PII unmasked"
                    walk(v, f"{path}/{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o): walk(v, f"{path}[{i}]")
        walk(json.loads(p.read_text()))


def test_pii_value_gated_keys_never_leak_email_or_line_uid_shaped_values():
    # 盤點時發現超出原始「只有 last_target」範圍的洩漏面：dashboard_overview
    # /alerts/recent[].target、status /dispatch_history[].target、settings
    # /email/recipients 都用泛用鍵名帶同一顆真實 email／LINE 使用者 ID。
    # 泛用鍵名不能無條件遮（posture.remediation[].target 是數字目標值），
    # 遮罩改採「值形狀」二次確認（見 masking.py `_looks_like_pii_value`）——
    # 這裡反向稽核：已抓取的快照裡，這些鍵名底下不該再殘留任何 email 或
    # LINE 使用者 ID 形狀的值（代表遮罩沒生效）。
    for p in _snaps():
        def walk(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in _PII_VALUE_GATED_KEYS:
                        assert not _looks_like_pii_value(v), \
                            f"{p.name}:{path}/{k} PII-shaped value unmasked"
                    walk(v, f"{path}/{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o): walk(v, f"{path}[{i}]")
        walk(json.loads(p.read_text()))


def test_pii_paths_are_masked_in_every_snapshot():
    # 2026-08-05 使用者裁決把寄件設定納入同一個 PII 類別。sender/user 走上面
    # 的值形狀規則；smtp.host 的鍵名與值形狀都分不出「個人郵件網域」與「機房
    # 主機」，只能靠精確路徑（masking._PII_PATHS）。這裡用同一支路徑組裝函式
    # 反向稽核，避免稽核與遮罩對路徑的算法各寫一套而對不上。
    for p in _snaps():
        def walk(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    child = _child_path(path, k)
                    if child in _PII_PATHS:
                        assert v == "***MASKED***", f"{p.name}:{child} PII unmasked"
                    walk(v, child)
            elif isinstance(o, list):
                for v in o: walk(v, path)
        walk(json.loads(p.read_text()))


# 快照裡允許出現的 email 網域：實驗室假網域與 RFC 2606 保留示例網域。
# 這條清單刻意不寫「禁止哪個網域」——把使用者的個人網域寫進測試等於它還留在
# repo 裡（`git grep` 仍然找得到），與遮罩的目的自相矛盾。改成正面表列：任何
# 不在清單上的網域都算外流，未來新端點漏掛規則也會在這裡炸。
_ALLOWED_EMAIL_DOMAINS = {"lab.local", "example.com", "example.net", "example.org"}


def test_no_snapshot_carries_a_real_world_email_domain():
    import re as _re
    email = _re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    for p in _snaps():
        def walk(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items(): walk(v, f"{path}/{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o): walk(v, f"{path}[{i}]")
            elif isinstance(o, str) and email.match(o):
                domain = o.rsplit("@", 1)[-1].lower()
                assert domain in _ALLOWED_EMAIL_DOMAINS, \
                    f"{p.name}:{path} 帶真實 email 網域（{domain}）"
        walk(json.loads(p.read_text()))
