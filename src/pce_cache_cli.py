"""Interactive menu for PCE Cache."""
from __future__ import annotations

from src.config_models import PceCacheSettings
from src.gui.settings_helpers import save_section
from src.cli.object_picker import pick_objects
from src.i18n import t


def manage_pce_cache_menu(cm) -> None:
    while True:
        print(t("pcc_menu"))
        try:
            choice = input("> ").strip()
            if choice == "0":
                return
            elif choice == "1":
                _view_status(cm)
            elif choice == "2":
                _edit_core_settings(cm)
            elif choice == "3":
                _edit_traffic_filter(cm)
            elif choice == "4":
                _edit_traffic_sampling(cm)
            elif choice == "5":
                _run_backfill(cm)
            elif choice == "6":
                _run_retention(cm)
            else:
                print(t("pcc_invalid_choice"))
        except EOFError:
            # EOF (Ctrl-D / piped input end): leave the submenu cleanly.
            print()
            return
        except KeyboardInterrupt:
            # Ctrl-C cancels the current action and returns to this menu,
            # rather than aborting the whole application.
            print("\n" + t("pcc_cancelled"))


def _pick_or_cancel(api, cats, title, preselected=None, label_key_filter=None):
    """包 pick_objects：TTY 下 Ctrl-C 會拋 KeyboardInterrupt（見 src/cli/menus/traffic.py
    同名函式），這裡接住並回傳 None，呼叫端據此保留該 key 原值，不中斷整個選單。"""
    try:
        return pick_objects(api, cats=cats, title=title, preselected=preselected, label_key_filter=label_key_filter)
    except KeyboardInterrupt:
        return None


def _prompt(name, current, cast=str):
    raw = input(t("pcc_prompt_fmt", name=name, current=current)).strip()
    if raw == "":
        return current
    if cast is bool:
        return raw.lower() in ("1", "true", "y", "yes")
    try:
        return cast(raw)
    except ValueError:
        print(t("pcc_prompt_invalid_keeping", name=name, current=current))
        return current


def _edit_core_settings(cm):
    print()
    print(t("pcc_core_title"))
    print(t("pcc_hr"))
    print(t("pcc_core_help"))
    print()
    print(t("pcc_retention_title"))
    print(t("pcc_hr"))
    print(t("pcc_retention_help"))
    print()
    print(t("pcc_polling_title"))
    print(t("pcc_hr"))
    print(t("pcc_polling_help"))
    print(t("pcc_hr"))
    print()
    c = cm.models.pce_cache.model_dump(mode="json")
    c["enabled"] = _prompt("enabled", c["enabled"], bool)
    c["db_path"] = _prompt("db_path", c["db_path"])
    c["events_retention_days"] = _prompt("events_retention_days", c["events_retention_days"], int)
    c["traffic_raw_retention_days"] = _prompt("traffic_raw_retention_days", c["traffic_raw_retention_days"], int)
    c["traffic_agg_retention_days"] = _prompt("traffic_agg_retention_days", c["traffic_agg_retention_days"], int)
    c["events_poll_interval_seconds"] = _prompt("events_poll_interval_seconds", c["events_poll_interval_seconds"], int)
    c["traffic_poll_interval_seconds"] = _prompt("traffic_poll_interval_seconds", c["traffic_poll_interval_seconds"], int)
    c["rate_limit_per_minute"] = _prompt("rate_limit_per_minute", c["rate_limit_per_minute"], int)
    c["async_threshold_events"] = _prompt("async_threshold_events", c["async_threshold_events"], int)
    _persist(cm, c)


def _edit_traffic_filter(cm):
    print()
    print(t("pcc_filter_title"))
    print(t("pcc_hr"))
    print(t("pcc_filter_help"))
    print(t("pcc_hr"))
    print()
    c = cm.models.pce_cache.model_dump(mode="json")
    tf = c.setdefault("traffic_filter", {})
    for key in ("actions", "protocols"):
        cur = tf.get(key, [])
        raw = input(t("pcc_comma_prompt", field=key, cur=','.join(str(x) for x in cur))).strip()
        if raw:
            tf[key] = [x.strip() for x in raw.split(",") if x.strip()]

    from src.api_client import ApiClient
    api = ApiClient(cm)

    # workload_label_env：候選只列 env dimension（label_key_filter="env"）。
    # picker 內部以 "env=value" 候選格式往返，但既有 config 只存 value 字串，
    # preselected 時包回 "env=X" 形餵給 picker，存檔前再剝除 "env=" 前綴。
    cur_env = tf.get("workload_label_env", [])
    picked_env = _pick_or_cancel(
        api, cats=("label",), title="workload_label_env",
        preselected={"labels": [f"env={v}" for v in cur_env]} if cur_env else None,
        label_key_filter="env",
    )
    if picked_env is not None:
        tf["workload_label_env"] = [
            v[len("env="):] if v.startswith("env=") else v for v in picked_env.get("labels", [])
        ]

    cur_ips = tf.get("exclude_src_ips", [])
    picked_ips = _pick_or_cancel(
        api, cats=("ip",), title="exclude_src_ips",
        preselected={"ips": cur_ips} if cur_ips else None,
    )
    if picked_ips is not None:
        tf["exclude_src_ips"] = picked_ips.get("ips", [])

    cur_ports = tf.get("ports", [])
    raw = input(t("pcc_comma_prompt", field="ports", cur=','.join(str(p) for p in cur_ports))).strip()
    if raw:
        try:
            tf["ports"] = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            print(t("pcc_invalid_ports"))
    _persist(cm, c)


def _edit_traffic_sampling(cm):
    print()
    print(t("pcc_sampling_title"))
    print(t("pcc_hr"))
    print(t("pcc_sampling_help"))
    print(t("pcc_hr"))
    print()
    c = cm.models.pce_cache.model_dump(mode="json")
    ts = c.setdefault("traffic_sampling", {})
    ts["sample_ratio_allowed"] = _prompt("sample_ratio_allowed", ts.get("sample_ratio_allowed", 1), int)
    ts["max_rows_per_batch"] = _prompt("max_rows_per_batch", ts.get("max_rows_per_batch", 200000), int)
    _persist(cm, c)


def _persist(cm, data):
    result = save_section(cm, "pce_cache", data, PceCacheSettings)
    if result["ok"]:
        print(t("pcc_saved"))
    else:
        print(t("pcc_validation_error"))
        for path, msg in result["errors"].items():
            print(t("pcc_field_row", path=path, msg=msg))


def _view_status(cm):
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import PceEvent, PceTrafficFlowRaw
    cfg = cm.models.pce_cache
    print(t("pcc_status_enabled", value=cfg.enabled))
    print(t("pcc_status_db_path", value=cfg.db_path))
    try:
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        with sessionmaker(engine)() as s:
            n_ev = s.scalar(select(func.count()).select_from(PceEvent)) or 0
            n_tr = s.scalar(select(func.count()).select_from(PceTrafficFlowRaw)) or 0
            print(t("pcc_status_events_rows", count=n_ev))
            print(t("pcc_status_traffic_rows", count=n_tr))
    except Exception as exc:
        print(t("pcc_status_unavailable", exc=exc))


def _run_backfill(cm):
    start = input(t("pcc_backfill_start")).strip()
    end = input(t("pcc_backfill_end")).strip()
    if not start or not end:
        print(t("pcc_backfill_cancelled"))
        return
    try:
        from datetime import datetime, timezone
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.schema import init_schema
        from src.pce_cache.backfill import BackfillRunner
        from src.api_client import ApiClient
        cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        api = ApiClient(cm)
        since = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        until = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        runner = BackfillRunner(api, sf, rate_limit_per_minute=cfg.rate_limit_per_minute)
        ev_result = runner.run_events(since, until)
        tr_result = runner.run_traffic(since, until)
        print(t("pcc_backfill_events", inserted=ev_result.inserted, duplicates=ev_result.duplicates))
        print(t("pcc_backfill_traffic", inserted=tr_result.inserted, duplicates=tr_result.duplicates))
        print(t("pcc_backfill_complete"))
    except Exception as exc:
        print(t("pcc_backfill_failed", exc=exc))


def _run_retention(cm):
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.schema import init_schema
        from src.pce_cache.retention import RetentionWorker
        cfg = cm.models.pce_cache
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        sf = sessionmaker(engine)
        results = RetentionWorker(sf).run_once(
            events_days=cfg.events_retention_days,
            traffic_raw_days=cfg.traffic_raw_retention_days,
            traffic_agg_days=cfg.traffic_agg_retention_days,
            archive_enabled=cfg.archive_enabled,
        )
        print(t("pcc_retention_complete", results=results))
    except Exception as exc:
        print(t("pcc_retention_failed", exc=exc))
