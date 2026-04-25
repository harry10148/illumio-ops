from __future__ import annotations

from datetime import datetime, timezone, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required
from loguru import logger

from src.siem.tester import send_test_event

bp = Blueprint("siem", __name__, url_prefix="/api/siem")


def _get_siem_cfg():
    from src.config import ConfigManager
    return ConfigManager().models.siem


def _get_sf():
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.config import ConfigManager
    from src.pce_cache.schema import init_schema
    cm = ConfigManager()
    cfg = cm.models.pce_cache
    os.makedirs(os.path.dirname(os.path.abspath(cfg.db_path)), exist_ok=True)
    engine = create_engine(f"sqlite:///{cfg.db_path}")
    init_schema(engine)
    return sessionmaker(engine)


@bp.route("/destinations", methods=["GET"])
@login_required
def list_destinations():
    try:
        cfg = _get_siem_cfg()
        dests = [d.model_dump() for d in cfg.destinations]
        return jsonify({"destinations": dests})
    except Exception as exc:
        logger.exception("siem list_destinations error: {}", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/destinations", methods=["POST"])
@login_required
def add_destination():
    try:
        from src.config_models import SiemDestinationSettings, SiemForwarderSettings
        from src.gui.settings_helpers import save_section
        cm = current_app.config['CM']
        data = request.get_json(force=True) or {}
        SiemDestinationSettings(**data)  # validate first
        current = cm.models.siem.model_dump(mode="json")
        if any(d["name"] == data.get("name") for d in current.get("destinations", [])):
            return jsonify({"ok": False, "error": "destination name already exists"}), 409
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
        data["name"] = name
        SiemDestinationSettings(**data)  # validate
        current = cm.models.siem.model_dump(mode="json")
        dests = current.get("destinations", [])
        idx = next((i for i, d in enumerate(dests) if d["name"] == name), None)
        if idx is None:
            return jsonify({"ok": False, "error": "destination not found"}), 404
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
        current = cm.models.siem.model_dump(mode="json")
        before = len(current.get("destinations", []))
        current["destinations"] = [d for d in current.get("destinations", []) if d["name"] != name]
        if len(current["destinations"]) == before:
            return jsonify({"ok": False, "error": "destination not found"}), 404
        result = save_section(cm, "siem", current, SiemForwarderSettings)
        if result["ok"]:
            cm.load()
        return jsonify(result), (200 if result["ok"] else 422)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@bp.route("/status", methods=["GET"])
@login_required
def dispatch_status():
    try:
        from sqlalchemy import func, select
        from src.pce_cache.models import DeadLetter, SiemDispatch
        sf = _get_sf()
        result = []
        with sf() as s:
            dests = s.execute(select(SiemDispatch.destination).distinct()).scalars().all()
            for dest in dests:
                counts = {}
                for st in ["pending", "sent", "failed"]:
                    cnt = s.execute(
                        select(func.count()).select_from(SiemDispatch)
                        .where(SiemDispatch.destination == dest)
                        .where(SiemDispatch.status == st)
                    ).scalar() or 0
                    counts[st] = cnt
                dlq_cnt = s.execute(
                    select(func.count()).select_from(DeadLetter)
                    .where(DeadLetter.destination == dest)
                ).scalar() or 0
                result.append({"destination": dest, **counts, "dlq": dlq_cnt})
        return jsonify({"status": result})
    except Exception as exc:
        logger.exception("siem dispatch_status error: {}", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/dlq", methods=["GET"])
@login_required
def list_dlq():
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
        return jsonify({"error": str(exc)}), 500


@bp.route("/dlq/replay", methods=["POST"])
@login_required
def replay_dlq():
    try:
        from src.siem.dlq import DeadLetterQueue
        data = request.get_json(force=True) or {}
        dest = data.get("dest", "")
        limit = min(int(data.get("limit", 100)), 1000)
        sf = _get_sf()
        dlq = DeadLetterQueue(sf)
        count = dlq.replay(dest, limit=limit)
        return jsonify({"status": "ok", "requeued": count})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/dlq/purge", methods=["POST"])
@login_required
def purge_dlq():
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
        return jsonify({"error": str(exc)}), 500


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
                row.quarantined_at.isoformat(),
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
    dest = next((d for d in cm.models.siem.destinations
                 if d.name == name), None)
    if dest is None:
        return jsonify({"ok": False, "error": "destination not found"}), 404
    r = send_test_event(dest)
    return jsonify({"ok": r.ok, "error": r.error, "latency_ms": r.latency_ms}), 200
