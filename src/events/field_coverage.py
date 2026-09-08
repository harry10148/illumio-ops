"""哪些 PCE 事件欄位沒有人在看。

**這個模組存在的理由**（2026-09-08）：PCE 26.2 給 `agent.tampering` 的
`notifications[].info` 加了五個欄位，正規化器整包丟掉，四千多支測試全綠、十道
閘門全綠，畫面上只是少了「這次竄改有沒有被自動還原」這句話。沒有任何一個機制
在看「PCE 給了什麼、我們讀了什麼」這個差集——而 PCE 每次升版都會再動一次。

作法：把一個真實事件攤成**葉路徑**（`notifications[].info.num_events` 這種），
減掉這份帳本裡登記過的路徑，剩下的就是沒有人看的欄位。帳本裡的每一條都要嘛是
「正規化器讀了它」，要嘛是「看過、決定不讀，理由是 X」——跟 repo 既有的色碼
ratchet 同一個形狀：**沉默的漏接會變成一條需要有人簽名的新條目**。

怎麼用：
  · `tools/audit_event_fields.py` 對真機（或一份事件 dump）跑一次，列出未登記
    的路徑，依 event_type 分組。PCE 升版後跑它。
  · `tests/test_event_field_coverage.py` 拿 `tests/data/pce_event_shapes.json`
    （只有路徑、沒有值，所以不含任何客戶資料）當語料跑同一件事，於 CI 常態擋。

值一律不進來：這裡只處理**路徑**。
"""
from __future__ import annotations

from typing import Any, Iterable

# 陣列一律以 `[]` 表示，不帶索引——第 0 筆與第 7 筆是同一個欄位。
LIST_MARK = "[]"


def leaf_paths(obj: Any, prefix: str = "") -> list[str]:
    """把一個事件攤成葉路徑。空 dict/list 自己就是一個葉（它也是一種形狀）。"""
    out: list[str] = []
    if isinstance(obj, dict):
        if not obj:
            return [prefix] if prefix else []
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            out.extend(leaf_paths(value, child))
        return out
    if isinstance(obj, list):
        if not obj:
            return [prefix + LIST_MARK] if prefix else []
        seen: set[str] = set()
        for item in obj:
            for path in leaf_paths(item, prefix + LIST_MARK):
                if path not in seen:
                    seen.add(path)
                    out.append(path)
        return out
    return [prefix] if prefix else []


# ── 帳本 ────────────────────────────────────────────────────────────────────
# 值＝這條路徑的處置。READ 表示正規化器真的讀了它；其餘字串是「看過、不讀」的
# 理由，寫給下一個人看的。新增條目請寫理由，不要只求測試變綠。
READ = "read by events/normalizer.py"

FIELD_LEDGER: dict[str, str] = {
    # —— 事件本體 ——
    "href": READ,
    "timestamp": READ,
    "event_type": READ,
    "status": READ,
    "severity": READ,
    "version": "PCE event schema version; nothing branches on it, and a shape change surfaces here anyway",
    "org_id": "single-org deployment; there is no second value to tell apart",
    "pce_fqdn": "cache binding keys on the /orgs/<id>/ href inside raw_json, not on this field",
    "task_name": "PCE-internal task name; means nothing to an operator",
    "uuid": "identity comes from href (poller.event_identity)",
    # —— created_by ——
    "created_by.agent.href": READ,
    "created_by.agent.hostname": READ,
    "created_by.ven.href": READ,
    "created_by.ven.hostname": READ,
    "created_by.user.href": READ,
    "created_by.user.username": READ,
    "created_by.user.full_name": "display always uses username; printing both only costs width",
    "created_by.system": READ,
    "created_by.container_cluster.href": READ,
    "created_by.container_cluster.name": READ,
    "created_by.service_account.href": READ,
    "created_by.service_account.name": READ,
    # —— action ——
    "action.uuid": "PCE-internal correlation id for the events of one action; we do not stitch those",
    "action.api_endpoint": READ,
    "action.api_method": READ,
    "action.http_status_code": "the status field already says success or failure",
    "action.src_ip": READ,
    "action": "an empty action dict: an event with no API call at all; _extract_action returns empty strings",
    "action.errors[].message": "the error the PCE returned to the caller; status already"
                               " says it failed, and the text was for whoever made that call",
    "action.errors[].token": "the PCE error token (e.g. lock_error); same reason as the message above",
    "action.info.api_key_id": "the key id on api_key events: deliberately neither stored"
                              " nor displayed, credential identifiers do not land",
    # —— notifications ——
    "notifications[]": "an empty notifications array; notifications_count already covers it",
    "notifications[].info": "an empty info (a notification carrying no fields); the wholesale path yields an empty dict",
    "notifications[].uuid": "the notification's own id; nothing reads it",
    "notifications[].notification_type": READ,
    "notifications[].info.user.href": READ,
    "notifications[].info.user.username": READ,
    "notifications[].info.user.full_name": "same as created_by.user.full_name",
    # —— resource_changes ——
    "resource_changes[]": READ,
    "resource_changes[].uuid": "the change's own id; nothing reads it",
    "resource_changes[].changes": "an empty changes bag (a change with no attributes listed); the count already covers it",
    "resource_changes[].resource_type": READ,
    "resource_changes[].change_type": READ,
}

# ── 三個無界家族 ────────────────────────────────────────────────────────────
# 有三處的鍵本來就是開放集合，逐一登記只會變成一份永遠追不上的清單。它們各自
# 的豁免都綁著一個**實作前提**——前提沒了，這裡就是在說謊，所以每一條都有一支
# 測試盯著那個前提（tests/test_event_field_coverage.py）。
#
# 1. notifications[].info.*
#    PCE 隨版本在這裡長新欄位（26.2 的 tampering_revert_succeeded /
#    event_classification / num_events …）。前提：normalizer 的
#    _extract_notification_info **整包收下所有純量**，顯示端認不得的也照樣列。
#    實作若退回白名單，這個豁免就必須跟著撤掉——否則新欄位又會無聲消失，而這
#    整個模組正是為了那件事存在的。
#
# 2. resource_changes[].changes.*
#    被改動資源的屬性 diff（before/after）。鍵是那個資源自己的 schema，隨資源
#    型別而異、隨 PCE 版本增長。前提：我們只**計數**（normalized 的
#    resource_changes_count），不對個別屬性分支——沒有任何行為依賴某個屬性名，
#    所以多一個屬性不會讓任何東西壞掉。
#
# 3. resource_changes[].resource.<type>.*
#    被改動資源的完整物件。前提：我們只從它取一個**顯示名稱**
#    （normalizer._resource_name：name / key+value / hostname / href 四選一），
#    不讀個別屬性。但 <type> 本身**不是**無界的——PCE 開始送一種沒見過的資源
#    型別是值得知道的事，所以型別要登記，型別底下才放行。
KNOWN_RESOURCE_TYPES: frozenset[str] = frozenset({
    "agent", "ven", "workload", "kubernetes_workload", "container_cluster",
    "container_workload_profile", "cluster", "label", "label_group",
    "label_dimension", "org", "org_setting", "user", "service_account",
    "permission", "rule_set", "sec_rule", "sec_policy", "ip_list", "service",
    "network_device", "virtual_service", "virtual_server", "domain", "group",
    "pairing_profile", "firewall_settings", "authentication_settings",
    "api_key", "vulnerability", "syslog_destination",
})

_INFO_PREFIX = "notifications[].info."
_CHANGES_PREFIX = "resource_changes[].changes."
_RESOURCE_PREFIX = "resource_changes[].resource."


def _is_open_family(path: str) -> bool:
    if path.startswith(_INFO_PREFIX) or path.startswith(_CHANGES_PREFIX):
        return True
    if path.startswith(_RESOURCE_PREFIX):
        rest = path[len(_RESOURCE_PREFIX):]
        rtype = rest.split(".", 1)[0].removesuffix(LIST_MARK)
        # 型別已知才放行；沒見過的型別要浮出來，所以回 False 讓它被回報。
        return rtype in KNOWN_RESOURCE_TYPES
    return False


def unledgered_paths(event: dict[str, Any]) -> list[str]:
    """這個事件上沒有人在看、也沒有人簽過名的欄位路徑。"""
    return unledgered(leaf_paths(event))


def unledgered(paths: Iterable[str]) -> list[str]:
    out = []
    for path in paths:
        if path in FIELD_LEDGER:
            continue
        if _is_open_family(path):
            continue
        out.append(path)
    return sorted(set(out))
