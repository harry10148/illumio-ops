"""Interactive menu for SIEM Forwarder."""
from __future__ import annotations

from src.config_models import SiemDestinationSettings, SiemForwarderSettings
from src.gui.settings_helpers import save_section
from src.i18n import t


def manage_siem_menu(cm) -> None:
    while True:
        print(t("sic_menu"))
        choice = input("> ").strip()
        if choice == "0":
            return
        elif choice == "1":
            _view_status(cm)
        elif choice == "2":
            _edit_forwarder(cm)
        elif choice == "3":
            _list_destinations(cm)
        elif choice == "4":
            _add_destination(cm)
        elif choice == "5":
            _edit_destination(cm)
        elif choice == "6":
            _delete_destination(cm)
        elif choice == "7":
            _test_destination(cm)
        elif choice == "8":
            _dlq_submenu(cm)
        else:
            print(t("sic_invalid_choice"))


def _prompt(name, current, cast=str, secret=False):
    shown = ("*" * min(len(str(current)), 8)) if (secret and current) else current
    raw = input(t("sic_prompt_fmt", name=name, shown=shown)).strip()
    if raw == "":
        return current
    if cast is bool:
        return raw.lower() in ("1", "true", "y", "yes")
    try:
        return cast(raw)
    except ValueError:
        print(t("sic_prompt_invalid_keeping", name=name, current=current))
        return current


def _view_status(cm):
    s = cm.models.siem
    print(t("sic_status_enabled", value=s.enabled))
    print(t("sic_status_tick", value=s.dispatch_tick_seconds))
    print(t("sic_status_dlq_max", value=s.dlq_max_per_dest))
    print(t("sic_status_destinations", value=len(s.destinations)))


def _edit_forwarder(cm):
    print()
    print(t("sic_fwd_title"))
    print(t("sic_hr"))
    print(t("sic_fwd_help"))
    print(t("sic_hr"))
    print()
    c = cm.models.siem.model_dump(mode="json")
    c["enabled"] = _prompt("enabled", c["enabled"], bool)
    c["dispatch_tick_seconds"] = _prompt("dispatch_tick_seconds", c["dispatch_tick_seconds"], int)
    c["dlq_max_per_dest"] = _prompt("dlq_max_per_dest", c["dlq_max_per_dest"], int)
    r = save_section(cm, "siem", c, SiemForwarderSettings)
    _report(r)


def _report(r):
    if r["ok"]:
        print(t("sic_saved"))
    else:
        for path, msg in r["errors"].items():
            print(t("sic_field_row", path=path, msg=msg))


def _list_destinations(cm):
    for d in cm.models.siem.destinations:
        status = t("sic_dest_enabled") if d.enabled else t("sic_dest_disabled")
        print(t("sic_dest_row", name=d.name, transport=d.transport, format=d.format,
                endpoint=d.endpoint, status=status))
    input(t("sic_press_enter"))


def _prompt_destination(existing=None):
    print()
    print(t("sic_dest_config_title"))
    print(t("sic_hr"))
    print(t("sic_dest_config_help"))
    print(t("sic_hr"))
    print()
    existing = existing or {}
    name = _prompt("name", existing.get("name", ""))
    enabled = _prompt("enabled", existing.get("enabled", True), bool)
    transport = _prompt("transport (udp/tcp/tls/hec)", existing.get("transport", "udp"))
    format_ = _prompt("format (cef/json/syslog_cef/syslog_json)", existing.get("format", "cef"))
    endpoint = _prompt("endpoint", existing.get("endpoint", ""))
    tls_verify = _prompt("tls_verify", existing.get("tls_verify", True), bool)
    tls_ca_bundle = _prompt("tls_ca_bundle", existing.get("tls_ca_bundle") or "")
    hec_token = _prompt("hec_token", existing.get("hec_token") or "", secret=True)
    batch_size = _prompt("batch_size", existing.get("batch_size", 100), int)
    raw = input(t("sic_source_types_prompt",
                  cur=','.join(existing.get('source_types', ['audit', 'traffic'])))).strip()
    source_types = (
        [x.strip() for x in raw.split(",") if x.strip()]
        if raw else existing.get("source_types", ["audit", "traffic"])
    )
    max_retries = _prompt("max_retries", existing.get("max_retries", 10), int)
    return {
        "name": name,
        "enabled": enabled,
        "transport": transport,
        "format": format_,
        "endpoint": endpoint,
        "tls_verify": tls_verify,
        "tls_ca_bundle": tls_ca_bundle or None,
        "hec_token": hec_token or None,
        "batch_size": batch_size,
        "source_types": source_types,
        "max_retries": max_retries,
    }


def _add_destination(cm):
    data = _prompt_destination()
    try:
        SiemDestinationSettings(**data)
    except Exception as exc:
        print(t("sic_validation_error", exc=exc))
        return
    siem = cm.models.siem.model_dump(mode="json")
    siem.setdefault("destinations", []).append(data)
    _report(save_section(cm, "siem", siem, SiemForwarderSettings))


def _edit_destination(cm):
    name = input(t("sic_edit_which")).strip()
    siem = cm.models.siem.model_dump(mode="json")
    dests = siem.get("destinations", [])
    for i, d in enumerate(dests):
        if d.get("name") == name:
            dests[i] = _prompt_destination(d)
            siem["destinations"] = dests
            _report(save_section(cm, "siem", siem, SiemForwarderSettings))
            return
    print(t("sic_not_found"))


def _delete_destination(cm):
    name = input(t("sic_delete_which")).strip()
    if input(t("sic_confirm_delete", name=name)).strip().lower() != "yes":
        print(t("sic_cancelled"))
        return
    siem = cm.models.siem.model_dump(mode="json")
    siem["destinations"] = [d for d in siem.get("destinations", []) if d.get("name") != name]
    _report(save_section(cm, "siem", siem, SiemForwarderSettings))


def _test_destination(cm):
    from src.siem.tester import send_test_event
    name = input(t("sic_test_which")).strip()
    dest = next((d for d in cm.models.siem.destinations if d.name == name), None)
    if dest is None:
        print(t("sic_not_found"))
        return
    r = send_test_event(dest)
    if r.ok:
        print(t("sic_test_ok", ms=r.latency_ms))
    else:
        print(t("sic_test_failed", error=r.error))


def _dlq_submenu(cm):
    while True:
        print(t("sic_dlq_menu"))
        c = input(t("sic_dlq_prompt")).strip().lower()
        if c == "0":
            return
        elif c == "a":
            _dlq_list(cm)
        elif c == "b":
            _dlq_bulk(cm, action="replay")
        elif c == "c":
            _dlq_bulk(cm, action="purge")
        elif c == "d":
            _dlq_purge_all(cm)
        elif c == "e":
            _dlq_export(cm)


def _dlq_engine(cm):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{cm.models.pce_cache.db_path}")
    init_schema(engine)
    return sessionmaker(engine)


def _dlq_list(cm):
    from sqlalchemy import select
    from src.pce_cache.models import DeadLetter
    with _dlq_engine(cm)() as s:
        for row in s.scalars(select(DeadLetter).limit(50)):
            print(t("sic_dlq_row", id=row.id, destination=row.destination))


def _dlq_bulk(cm, action):
    from src.siem.dlq import DeadLetterQueue

    action_label = t("sic_dlq_action_replay") if action == "replay" else t("sic_dlq_action_purge")
    raw = input(t("sic_dlq_ids_prompt", action=action_label)).strip()
    if not raw:
        return
    try:
        ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        print(t("sic_dlq_invalid_ids"))
        return
    sf = _dlq_engine(cm)
    if action == "replay":
        for r in DeadLetterQueue(sf).replay_ids(ids):
            result = t("sic_dlq_replayed") if r["ok"] else r["error"]
            print(t("sic_dlq_replay_row", id=r['id'], result=result))
    else:  # purge: 逐筆刪除選定的 DLQ id（dlq.py 的 purge() 只支援依 destination+
        # 天數批次刪除，選取特定 id 屬於獨立語意，直接刪除即可，不需擴充 dlq.py）。
        # 刪除不可逆，照本檔既有安全模式（_delete_destination 的 yes 確認）先確認。
        id_list = ", ".join(str(i) for i in ids)
        # 確認模式：選定 id 清單風險範圍明確（僅這批 id），用 yes 二字確認即可。
        if input(t("sic_dlq_confirm_purge", count=len(ids), ids=id_list)).strip().lower() != "yes":
            print(t("sic_cancelled"))
            return
        from sqlalchemy import delete
        from src.pce_cache.models import DeadLetter
        with sf.begin() as s:
            result = s.execute(delete(DeadLetter).where(DeadLetter.id.in_(ids)))
        # 請求數與實刪數可能不同（部分 id 早已不存在），訊息同時呈現兩者避免誤解。
        print(t("sic_dlq_purged_count", requested=len(ids), purged=result.rowcount))


def _dlq_purge_all(cm):
    from src.siem.dlq import DeadLetterQueue

    name = input(t("sic_dlq_dest_prompt")).strip()
    # 確認模式：清空整個 destination 的 DLQ 影響範圍較大，要求輸入完整名稱以降低誤刪風險。
    if input(t("sic_dlq_type_confirm", name=name)).strip() != name:
        print(t("sic_cancelled"))
        return
    # older_than_days=0：cutoff 等於現在，既有的 quarantined_at 一定早於現在，
    # 等同清空該 destination 的全部 DLQ 項目。
    removed = DeadLetterQueue(_dlq_engine(cm)).purge(name, older_than_days=0)
    print(t("sic_dlq_purged_dest", count=removed, name=name))


def _dlq_export(cm):
    import csv
    from sqlalchemy import select
    from src.pce_cache.models import DeadLetter
    path = input(t("sic_dlq_export_path")).strip()
    if not path:
        return
    try:
        with open(path, "w") as f:
            w = csv.writer(f)
            w.writerow(["id", "destination", "source_id", "last_error", "quarantined_at"])
            with _dlq_engine(cm)() as s:
                for row in s.scalars(select(DeadLetter)):
                    w.writerow([
                        row.id, row.destination, row.source_id, row.last_error,
                        row.quarantined_at.isoformat() if row.quarantined_at else "",
                    ])
    except OSError as exc:
        print(t("sic_dlq_export_failed", exc=exc))
        return
    print(t("sic_dlq_exported", path=path))
