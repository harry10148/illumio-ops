from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required

from src.i18n import t
from src.siem.tester import send_test_event
from src.gui._helpers import _err_with_log

bp = Blueprint("siem", __name__, url_prefix="/api/siem")

_SF_KEY = "_siem_Session"
_LOCK_KEY = "_siem_sf_lock"


def _get_siem_cfg():
    from src.config import ConfigManager
    return ConfigManager().models.siem


def _get_sf():
    sf = current_app.config.get(_SF_KEY)
    if sf is not None:
        return sf
    lock = current_app.config.setdefault(_LOCK_KEY, threading.Lock())
    with lock:
        sf = current_app.config.get(_SF_KEY)
        if sf is not None:
            return sf
        import os
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.pce_cache.schema import init_schema
        cm = current_app.config["CM"]
        cfg = cm.models.pce_cache
        os.makedirs(os.path.dirname(os.path.abspath(cfg.db_path)), exist_ok=True)
        engine = create_engine(f"sqlite:///{cfg.db_path}")
        init_schema(engine)
        current_app.config[_SF_KEY] = sessionmaker(engine)
    return current_app.config[_SF_KEY]


@bp.route("/destinations", methods=["GET"])
@login_required
def list_destinations():
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        cfg = _get_siem_cfg()
        dests = [d.model_dump() for d in cfg.destinations]
        return jsonify({"destinations": dests})
    except Exception as exc:
        return _err_with_log("siem_list_destinations", exc, lang=lang)


@bp.route("/destinations", methods=["POST"])
@login_required
def add_destination():
    try:
        from src.config_models import SiemDestinationSettings, SiemForwarderSettings
        from src.gui.settings_helpers import save_section
        cm = current_app.config['CM']
        data = request.get_json(force=True) or {}
        lang = data.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        SiemDestinationSettings(**data)  # validate first
        current = cm.models.siem.model_dump(mode="json")
        if any(d["name"] == data.get("name") for d in current.get("destinations", [])):
            return jsonify({"ok": False, "error": t("gui_err_siem_dest_exists", lang=lang)}), 409
        current.setdefault("destinations", []).append(data)
        result = save_section(cm, "siem", current, SiemForwarderSettings)
        if result["ok"]:
            cm.load()
        return jsonify(result), (200 if result["ok"] else 422)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@bp.route("/destinations/<name>", methods=["PUT"])
@login_required
def update_destination(name: str):
    try:
        from src.config_models import SiemDestinationSettings, SiemForwarderSettings
        from src.gui.settings_helpers import save_section
        cm = current_app.config['CM']
        data = request.get_json(force=True) or {}
        lang = data.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        data["name"] = name
        SiemDestinationSettings(**data)  # validate
        current = cm.models.siem.model_dump(mode="json")
        dests = current.get("destinations", [])
        idx = next((i for i, d in enumerate(dests) if d["name"] == name), None)
        if idx is None:
            return jsonify({"ok": False, "error": t("gui_err_siem_dest_not_found", lang=lang)}), 404
        dests[idx] = data
        result = save_section(cm, "siem", current, SiemForwarderSettings)
        if result["ok"]:
            cm.load()
        return jsonify(result), (200 if result["ok"] else 422)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@bp.route("/destinations/<name>", methods=["DELETE"])
@login_required
def delete_destination(name: str):
    try:
        from src.config_models import SiemForwarderSettings
        from src.gui.settings_helpers import save_section
        cm = current_app.config['CM']
        lang = cm.config.get('settings', {}).get('language', 'en')
        current = cm.models.siem.model_dump(mode="json")
        before = len(current.get("destinations", []))
        current["destinations"] = [d for d in current.get("destinations", []) if d["name"] != name]
        if len(current["destinations"]) == before:
            return jsonify({"ok": False, "error": t("gui_err_siem_dest_not_found", lang=lang)}), 404
        result = save_section(cm, "siem", current, SiemForwarderSettings)
        if result["ok"]:
            cm.load()
        return jsonify(result), (200 if result["ok"] else 422)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def _siem_window_totals(s):
    """Return aggregate sent_1h, failed_1h, denom, dlq across ALL destinations.

    Intended for consumers that need a fleet-wide health signal rather than
    per-destination breakdown (e.g. /api/cache/health).
    Returns a dict with keys: sent_1h, failed_1h, denom, dlq.
    Must be called inside an open SQLAlchemy session context.
    """
    import datetime as _dt
    from sqlalchemy import func, select
    from src.pce_cache.models import DeadLetter, SiemDispatch

    now = _dt.datetime.now(_dt.timezone.utc)
    hr = now - _dt.timedelta(hours=1)
    sent_1h = s.execute(
        select(func.count()).select_from(SiemDispatch)
        .where(SiemDispatch.status == "sent")
        .where(SiemDispatch.sent_at >= hr)
    ).scalar() or 0
    failed_1h = s.execute(
        select(func.count()).select_from(SiemDispatch)
        .where(SiemDispatch.status == "failed")
        .where(SiemDispatch.queued_at >= hr)
    ).scalar() or 0
    dlq = s.execute(select(func.count()).select_from(DeadLetter)).scalar() or 0
    return {"sent_1h": sent_1h, "failed_1h": failed_1h, "denom": sent_1h + failed_1h, "dlq": dlq}


@bp.route("/status", methods=["GET"])
@login_required
def dispatch_status():
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        from sqlalchemy import func, select
        from src.pce_cache.models import DeadLetter, SiemDispatch
        sf = _get_sf()
        result = []
        import datetime as _dt
        _7d_ago = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=7)
        with sf() as s:
            dests = s.execute(select(SiemDispatch.destination).distinct()).scalars().all()
            for dest in dests:
                counts = {}
                for st in ["pending", "failed"]:
                    cnt = s.execute(
                        select(func.count()).select_from(SiemDispatch)
                        .where(SiemDispatch.destination == dest)
                        .where(SiemDispatch.status == st)
                    ).scalar() or 0
                    counts[st] = cnt
                counts["sent"] = s.execute(
                    select(func.count()).select_from(SiemDispatch)
                    .where(SiemDispatch.destination == dest)
                    .where(SiemDispatch.status == "sent")
                    .where(SiemDispatch.sent_at >= _7d_ago)
                ).scalar() or 0
                dlq_cnt = s.execute(
                    select(func.count()).select_from(DeadLetter)
                    .where(DeadLetter.destination == dest)
                ).scalar() or 0
                result.append({"destination": dest, **counts, "dlq": dlq_cnt})
            import datetime as _dt
            from sqlalchemy import func
            now = _dt.datetime.now(_dt.timezone.utc); hr = now - _dt.timedelta(hours=1)
            for entry in result:
                dest = entry["destination"]
                sent_1h = s.execute(select(func.count()).select_from(SiemDispatch)
                    .where(SiemDispatch.destination == dest)
                    .where(SiemDispatch.status == "sent").where(SiemDispatch.sent_at >= hr)).scalar() or 0
                failed_1h = s.execute(select(func.count()).select_from(SiemDispatch)
                    .where(SiemDispatch.destination == dest)
                    .where(SiemDispatch.status == "failed").where(SiemDispatch.queued_at >= hr)).scalar() or 0
                denom = sent_1h + failed_1h
                lat = s.execute(select(func.avg(
                        func.julianday(SiemDispatch.sent_at) - func.julianday(SiemDispatch.queued_at)))
                    .where(SiemDispatch.destination == dest)
                    .where(SiemDispatch.status == "sent").where(SiemDispatch.sent_at >= hr)).scalar()
                entry["sent_1h"] = sent_1h
                entry["failed_1h"] = failed_1h
                entry["success_1h"] = round(sent_1h / denom * 100, 1) if denom else 100.0
                entry["avg_latency_ms"] = int(lat * 86400 * 1000) if lat else None
        return jsonify({"status": result})
    except Exception as exc:
        return _err_with_log("siem_dispatch_status", exc, lang=lang)


@bp.route("/dlq", methods=["GET"])
@login_required
def list_dlq():
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        from src.siem.dlq import DeadLetterQueue
        dest = request.args.get("dest", "")
        limit = min(int(request.args.get("limit", 50)), 500)
        sf = _get_sf()
        dlq = DeadLetterQueue(sf)
        entries = dlq.list_entries(dest, limit=limit)
        return jsonify({
            "destination": dest,
            "entries": [
                {
                    "id": e.id,
                    "destination": e.destination,
                    "source_table": e.source_table,
                    "source_id": e.source_id,
                    "retries": e.retries,
                    "last_error": e.last_error,
                    "payload_preview": e.payload_preview,
                    "quarantined_at": e.quarantined_at.isoformat() if e.quarantined_at else None,
                }
                for e in entries
            ]
        })
    except Exception as exc:
        return _err_with_log("siem_list_dlq", exc, lang=lang)


@bp.route("/dlq/<int:dl_id>", methods=["GET"])
@login_required
def get_dlq_item(dl_id):
    from src.pce_cache.models import DeadLetter, PceEvent, PceTrafficFlowRaw
    sf = _get_sf()
    with sf() as s:
        dl = s.get(DeadLetter, dl_id)
        if dl is None:
            return jsonify({"error": "not found"}), 404
        out = {
            "id": dl.id,
            "destination": dl.destination,
            "source_table": dl.source_table,
            "source_id": dl.source_id,
            "retries": dl.retries,
            "last_error": dl.last_error,
            "quarantined_at": dl.quarantined_at.isoformat() if dl.quarantined_at else None,
            "payload": None,
            "payload_source": None,
        }
        model = {"pce_events": PceEvent, "pce_traffic_flows_raw": PceTrafficFlowRaw}.get(dl.source_table)
        src = s.get(model, dl.source_id) if model else None
        if src is not None:
            out["payload"] = src.raw_json
            out["payload_source"] = "rebuilt"
        else:
            out["payload"] = dl.payload_preview
            out["payload_source"] = "preview (source gone)" if model else "preview (unknown table)"
    return jsonify(out)


@bp.route("/dlq/replay", methods=["POST"])
@login_required
def replay_dlq():
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        from src.siem.dlq import DeadLetterQueue
        data = request.get_json(force=True) or {}
        if data.get("ids"):
            results = DeadLetterQueue(_get_sf()).replay_ids(data["ids"])
            return jsonify({"status": "ok", "requeued": results})
        dest = data.get("dest", "")
        limit = min(int(data.get("limit", 100)), 1000)
        sf = _get_sf()
        dlq = DeadLetterQueue(sf)
        count = dlq.replay(dest, limit=limit)
        return jsonify({"status": "ok", "requeued": count})
    except Exception as exc:
        return _err_with_log("siem_replay_dlq", exc, lang=lang)


@bp.route("/dlq/purge", methods=["POST"])
@login_required
def purge_dlq():
    lang = current_app.config["CM"].config.get('settings', {}).get('language', 'en')
    try:
        from src.siem.dlq import DeadLetterQueue
        data = request.get_json(force=True) or {}
        dest = data.get("dest", "")
        older_than_days = int(data.get("older_than_days", 30))
        sf = _get_sf()
        dlq = DeadLetterQueue(sf)
        removed = dlq.purge(dest, older_than_days=older_than_days)
        return jsonify({"status": "ok", "removed": removed})
    except Exception as exc:
        return _err_with_log("siem_purge_dlq", exc, lang=lang)


@bp.route("/dlq/export", methods=["GET"])
@login_required
def dlq_export():
    from flask import Response
    import csv, io
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.models import DeadLetter
    from src.pce_cache.schema import init_schema

    import os
    destination = request.args.get("dest", "").strip()
    reason = request.args.get("reason", "").strip()
    cm = current_app.config["CM"]
    cfg = cm.models.pce_cache
    os.makedirs(os.path.dirname(os.path.abspath(cfg.db_path)), exist_ok=True)
    engine = create_engine(f"sqlite:///{cfg.db_path}")
    init_schema(engine)
    Session = sessionmaker(engine)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "destination", "source_table", "source_id",
                "retries", "last_error", "payload_preview", "quarantined_at"])
    with Session() as s:
        q = select(DeadLetter)
        if destination:
            q = q.where(DeadLetter.destination == destination)
        if reason:
            q = q.where(DeadLetter.last_error.like(f"%{reason}%"))
        for row in s.scalars(q):
            w.writerow([
                row.id, row.destination, row.source_table, row.source_id,
                row.retries, row.last_error, row.payload_preview,
                row.quarantined_at.isoformat() if row.quarantined_at else "",
            ])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=dlq.csv"})


@bp.route("/forwarder", methods=["GET"])
@login_required
def get_forwarder():
    cm = current_app.config['CM']
    s = cm.models.siem
    return jsonify({"enabled": s.enabled,
                    "dispatch_tick_seconds": s.dispatch_tick_seconds,
                    "dlq_max_per_dest": s.dlq_max_per_dest})


@bp.route("/forwarder", methods=["PUT"])
@login_required
def put_forwarder():
    from src.config_models import SiemForwarderSettings
    from src.gui.settings_helpers import save_section
    cm = current_app.config['CM']
    incoming = request.get_json(silent=True) or {}
    current = cm.models.siem.model_dump(mode="json")
    for k in ("enabled", "dispatch_tick_seconds", "dlq_max_per_dest"):
        if k in incoming:
            current[k] = incoming[k]
    result = save_section(cm, "siem", current, SiemForwarderSettings)
    if result["ok"]:
        cm.load()
    return jsonify(result), (200 if result["ok"] else 422)


@bp.route("/destinations/<name>/test", methods=["POST"])
@login_required
def test_destination(name: str):
    cm = current_app.config['CM']
    lang = cm.config.get('settings', {}).get('language', 'en')
    dest = next((d for d in cm.models.siem.destinations
                 if d.name == name), None)
    if dest is None:
        return jsonify({"ok": False, "error": t("gui_err_siem_dest_not_found", lang=lang)}), 404
    r = send_test_event(dest)
    return jsonify({"ok": r.ok, "error": r.error, "latency_ms": r.latency_ms}), 200
