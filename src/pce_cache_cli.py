"""Interactive menu for PCE Cache."""
from __future__ import annotations

from src.config_models import PceCacheSettings
from src.gui.settings_helpers import save_section


MENU = (
    "PCE Cache Menu:\n"
    "  1. View status\n"
    "  2. Edit settings (basic / retention / polling / throughput)\n"
    "  3. Edit traffic filter\n"
    "  4. Edit traffic sampling\n"
    "  5. Backfill (interactive)\n"
    "  6. Run retention now\n"
    "  0. Back\n"
)


def manage_pce_cache_menu(cm) -> None:
    while True:
        print(MENU)
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
            print("invalid choice; please enter 0-6")


def _prompt(name, current, cast=str):
    raw = input(f"  {name} [{current}]: ").strip()
    if raw == "":
        return current
    if cast is bool:
        return raw.lower() in ("1", "true", "y", "yes")
    try:
        return cast(raw)
    except ValueError:
        print(f"  invalid {name}; keeping {current}")
        return current


def _edit_core_settings(cm):
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
    c = cm.models.pce_cache.model_dump(mode="json")
    tf = c.setdefault("traffic_filter", {})
    for key in ("actions", "protocols", "workload_label_env", "exclude_src_ips"):
        cur = tf.get(key, [])
        raw = input(f"  {key} (comma, [{','.join(str(x) for x in cur)}]): ").strip()
        if raw:
            tf[key] = [x.strip() for x in raw.split(",") if x.strip()]
    cur_ports = tf.get("ports", [])
    raw = input(f"  ports (comma, [{','.join(str(p) for p in cur_ports)}]): ").strip()
    if raw:
        try:
            tf["ports"] = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            print("  invalid ports; keeping previous")
    _persist(cm, c)


def _edit_traffic_sampling(cm):
    c = cm.models.pce_cache.model_dump(mode="json")
    ts = c.setdefault("traffic_sampling", {})
    ts["sample_ratio_allowed"] = _prompt("sample_ratio_allowed", ts.get("sample_ratio_allowed", 1), int)
    ts["max_rows_per_batch"] = _prompt("max_rows_per_batch", ts.get("max_rows_per_batch", 200000), int)
    _persist(cm, c)


def _persist(cm, data):
    result = save_section(cm, "pce_cache", data, PceCacheSettings)
    if result["ok"]:
        print("[!] Settings saved. Restart monitor to apply scheduling changes.")
    else:
        print("[x] Validation error:")
        for path, msg in result["errors"].items():
            print(f"    {path}: {msg}")


def _view_status(cm):
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import PceEvent, PceTrafficFlowRaw
    cfg = cm.models.pce_cache
    print(f"  enabled: {cfg.enabled}")
    print(f"  db_path: {cfg.db_path}")
    try:
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        with sessionmaker(engine)() as s:
            n_ev = s.scalar(select(func.count()).select_from(PceEvent)) or 0
            n_tr = s.scalar(select(func.count()).select_from(PceTrafficFlowRaw)) or 0
            print(f"  events rows: {n_ev}")
            print(f"  traffic_raw rows: {n_tr}")
    except Exception as exc:
        print(f"  (status unavailable: {exc})")


def _run_backfill(cm):
    start = input("  start (YYYY-MM-DD): ").strip()
    end = input("  end (YYYY-MM-DD): ").strip()
    if not start or not end:
        print("  cancelled")
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
        print(f"  events: {ev_result.inserted} inserted, {ev_result.duplicates} duplicates")
        print(f"  traffic: {tr_result.inserted} inserted, {tr_result.duplicates} duplicates")
        print("  backfill complete")
    except Exception as exc:
        print(f"  backfill failed: {exc}")


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
        )
        print(f"  retention complete: {results}")
    except Exception as exc:
        print(f"  retention failed: {exc}")
