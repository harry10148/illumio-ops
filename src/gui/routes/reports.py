"""Reports Blueprint: report generation, listing, schedules (/api/reports*, /reports/<path>, /api/report-schedules*, /api/audit_report/generate, /api/ven_status_report/generate, /api/policy_usage_report/generate)."""
from __future__ import annotations

import datetime
import json
import os
import threading
import uuid

from flask import Blueprint, jsonify, request, send_from_directory
from loguru import logger
from werkzeug.utils import secure_filename

from src.config import ConfigManager
from src.i18n import t
from src.state_store import load_state_file, update_state_file
from src.gui._helpers import (
    _ALLOWED_REPORT_FORMATS,
    _resolve_reports_dir,
    _resolve_config_dir,
    _resolve_state_file,
    _err_with_log,
    _write_audit_dashboard_summary,
    _write_policy_usage_dashboard_summary,
)

# state.json key holding ad-hoc traffic-report job records (most recent 20 kept).
_ADHOC_JOBS_KEY = "adhoc_report_jobs"
_ADHOC_JOBS_MAX = 20


from src.report.cache_support import resolve_data_source, cache_available


def _data_source_from_payload(payload: dict, cache_ok: bool) -> tuple[bool, bool, str | None]:
    """Resolve (use_cache, clip_to_cache, warning) from a report request payload.

    Prefers explicit 'data_source'; falls back to legacy use_cache/clip_to_cache
    so older GUI clients keep working. Values may be strings (from JSON form).
    """
    ds = payload.get("data_source")
    if ds is None:
        if str(payload.get("use_cache", "true")).lower() in ("false", "0", "off", "no"):
            ds = "live"
        elif str(payload.get("clip_to_cache", "")).lower() in ("true", "1", "on"):
            ds = "cache-only"
        else:
            ds = "hybrid"
    return resolve_data_source(ds, cache_ok)


def _load_adhoc_jobs() -> dict:
    """Return the adhoc_report_jobs map from state.json ({} when absent)."""
    return load_state_file(_resolve_state_file()).get(_ADHOC_JOBS_KEY, {}) or {}


def _save_adhoc_job(job_id: str, record: dict) -> None:
    """Merge a single job record into state.json under the shared state lock.

    Pruning keeps only the _ADHOC_JOBS_MAX most-recent jobs by ``started_at``.
    """
    def _merge(existing):
        data = dict(existing)
        jobs = dict(data.get(_ADHOC_JOBS_KEY, {}) or {})
        jobs[job_id] = record
        if len(jobs) > _ADHOC_JOBS_MAX:
            # Keep newest by started_at; missing/blank started_at sorts oldest.
            ordered = sorted(jobs.items(),
                             key=lambda kv: kv[1].get("started_at") or "",
                             reverse=True)
            jobs = dict(ordered[:_ADHOC_JOBS_MAX])
        data[_ADHOC_JOBS_KEY] = jobs
        return data

    update_state_file(_resolve_state_file(), _merge)


def make_reports_blueprint(
    cm: ConfigManager,
    csrf,           # flask_wtf.csrf.CSRFProtect instance (unused here, kept for consistent signature)
    limiter,        # flask_limiter.Limiter instance
    login_required,  # flask_login.login_required decorator (unused here, kept for consistent signature)
) -> Blueprint:
    bp = Blueprint("reports", __name__)

    # ── API: Reports ──────────────────────────────────────────────────────────

    @bp.route('/api/reports', methods=['GET'])
    def api_list_reports():
        cm.load()
        reports_dir = _resolve_reports_dir(cm)

        if not os.path.exists(reports_dir):
            return jsonify({"ok": True, "reports": []})

        reports = []
        for f in os.listdir(reports_dir):
            if f.endswith(('.html', '.zip', '.pdf', '.xlsx')):
                report_path = os.path.join(reports_dir, f)
                stat = os.stat(report_path)
                metadata = {}
                metadata_path = report_path + ".metadata.json"
                if os.path.isfile(metadata_path):
                    try:
                        with open(metadata_path, "r", encoding="utf-8") as mf:
                            metadata = json.load(mf) or {}
                    except Exception:
                        metadata = {}
                reports.append({
                    "filename": f,
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                    "report_type": metadata.get("report_type", ""),
                    "summary": metadata.get("summary", ""),
                    "attack_summary": metadata.get("attack_summary", {}),
                    "attack_summary_counts": metadata.get("attack_summary_counts", {}),
                    "execution_stats": metadata.get("execution_stats", {}),
                    "reused_rule_details": metadata.get("reused_rule_details", []),
                    "pending_rule_details": metadata.get("pending_rule_details", []),
                    "failed_rule_details": metadata.get("failed_rule_details", []),
                })

        reports.sort(key=lambda x: x['mtime'], reverse=True)
        return jsonify({"ok": True, "reports": reports})

    @bp.route('/api/reports/<path:filename>', methods=['DELETE'])
    def api_delete_report(filename):
        lang = (request.get_json(silent=True) or {}).get('lang') or cm.config.get('settings', {}).get('language', 'en')
        cm.load()
        reports_dir = _resolve_reports_dir(cm)
        # Prevent path traversal
        target = os.path.realpath(os.path.join(reports_dir, filename))
        if not target.startswith(os.path.realpath(reports_dir) + os.sep):
            return jsonify({"ok": False, "error": t("gui_invalid_filename", lang=lang)}), 400
        if not os.path.isfile(target):
            return jsonify({"ok": False, "error": t("gui_file_not_found", lang=lang)}), 404
        os.remove(target)
        metadata_path = target + ".metadata.json"
        if os.path.isfile(metadata_path):
            try:
                os.remove(metadata_path)
            except OSError:
                pass  # intentional fallback: metadata file deletion is best-effort
        return jsonify({"ok": True})

    @bp.route('/api/reports/bulk-delete', methods=['POST'])
    def api_bulk_delete_reports():
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        filenames = d.get('filenames', [])
        if not filenames:
            return jsonify({"ok": False, "error": t("gui_err_no_filenames", lang=lang)}), 400

        cm.load()
        reports_dir = _resolve_reports_dir(cm)

        resolved_reports_dir = os.path.realpath(reports_dir)

        success_count = 0
        errors = []

        for filename in filenames:
            try:
                target = os.path.realpath(os.path.join(reports_dir, filename))
                if not target.startswith(resolved_reports_dir + os.sep):
                    errors.append(f"{filename}: {t('gui_invalid_filename', lang=lang)}")
                    continue
                if not os.path.isfile(target):
                    errors.append(f"{filename}: {t('gui_file_not_found', lang=lang)}")
                    continue
                os.remove(target)
                metadata_path = target + ".metadata.json"
                if os.path.isfile(metadata_path):
                    try:
                        os.remove(metadata_path)
                    except OSError:
                        pass  # intentional fallback: metadata file deletion is best-effort in bulk delete
                success_count += 1
            except Exception as e:
                errors.append(f"{filename}: {str(e)}")

        return jsonify({"ok": True, "deleted": success_count, "errors": errors})

    @bp.route('/reports/<path:filename>', methods=['GET'])
    def api_serve_report(filename):
        lang = (request.get_json(silent=True) or {}).get('lang') or cm.config.get('settings', {}).get('language', 'en')
        if '..' in filename or filename.startswith('/'):
            return jsonify({"ok": False, "error": t("gui_err_invalid_path", lang=lang)}), 403
        cm.load()
        reports_dir = _resolve_reports_dir(cm)
        # Path traversal protection: ensure resolved path stays within reports_dir
        target = os.path.realpath(os.path.join(reports_dir, filename))
        if not target.startswith(os.path.realpath(reports_dir) + os.sep):
            return jsonify({"ok": False, "error": t("gui_err_invalid_path", lang=lang)}), 403
        as_download = request.args.get('download') == '1'
        return send_from_directory(reports_dir, filename, as_attachment=as_download)

    def _run_adhoc(job_id: str, payload: dict):
        """Generate the ad-hoc traffic report in a daemon thread.

        Writes status running→done/error (with files/error/finished_at) into
        state.json so the frontend can poll /api/reports/jobs/<job_id>. Runs
        outside any Flask request context — uses only the captured ``payload``
        and module-level path/config helpers (no ``request`` access here).
        """
        record = payload["record"]
        lang = payload["lang"]
        _rlog = None
        try:
            from src.report.report_generator import ReportGenerator
            from src.api_client import ApiClient
            from src.reporter import Reporter
            try:
                from src.module_log import ModuleLog as _ML
                _rlog = _ML.get("reports")
                _rlog.separator(f"Traffic Report {datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')} UTC")
                _rlog.info(f"source={payload['source']} format={payload['fmt']} range={payload.get('start_date')}~{payload.get('end_date')}")
            except Exception:
                pass  # intentional fallback: ModuleLog is optional; report generation must not fail if logging setup fails

            cm.load()
            config_dir = _resolve_config_dir()
            api = ApiClient(cm)
            reporter = Reporter(cm)
            from src.main import _make_cache_reader
            gen = ReportGenerator(cm, api_client=api, config_dir=config_dir,
                                  cache_reader=_make_cache_reader(cm))

            traffic_report_profile = payload['traffic_report_profile']
            if payload['source'] == 'csv':
                temp_path = payload['temp_path']
                try:
                    result = gen.generate_from_csv(temp_path, traffic_report_profile=traffic_report_profile, lang=lang)
                finally:
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass  # intentional fallback: temp file cleanup is best-effort
            else:
                result = gen.generate_from_api(
                    start_date=payload.get('start_date'), end_date=payload.get('end_date'),
                    filters=payload.get('filters'), traffic_report_profile=traffic_report_profile,
                    lang=lang, clip_to_cache=payload.get('clip_to_cache', False),
                    use_cache=payload.get('use_cache', True))

            if result.record_count == 0:
                record.update({"status": "error", "error": t("gui_no_traffic_data", lang=lang),
                               "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
                _save_adhoc_job(job_id, record)
                return

            output_dir = _resolve_reports_dir(cm)
            paths = gen.export(result, fmt=payload['fmt'], output_dir=output_dir,
                               send_email=payload['send_email'], reporter=reporter,
                               traffic_report_profile=traffic_report_profile, lang=lang)
            export_errors = getattr(gen, 'last_export_errors', {}) or {}
            filenames = [os.path.basename(p) for p in paths]
            try:
                if _rlog:
                    _rlog.info(f"Completed: {filenames}"
                               + (f" errors={export_errors}" if export_errors else ""))
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort

            record.update({
                "files": filenames,
                "record_count": result.record_count,
                "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
            if export_errors or not filenames:
                record["status"] = "error"
                record["errors"] = export_errors
                record["error"] = "; ".join(f"{k}: {v}" for k, v in export_errors.items()) or "export produced no files"
            else:
                record["status"] = "done"
            _save_adhoc_job(job_id, record)
        except Exception as e:
            try:
                if _rlog:
                    _rlog.error(f"Traffic report failed: {e}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            logger.exception(f"Ad-hoc traffic report job {job_id} failed: {e}")
            record.update({"status": "error", "error": str(e),
                           "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            try:
                _save_adhoc_job(job_id, record)
            except Exception:
                logger.error(f"Could not persist failure for job {job_id}")

    @bp.route('/api/reports/generate', methods=['POST'])
    @limiter.limit("30 per hour")
    def api_generate_report():
        if request.is_json:
            d = request.json or {}
        else:
            d = request.form.to_dict()

        cm.load()

        source = d.get('source', 'api')
        _VALID_PROFILES = ("security_risk", "network_inventory")
        traffic_report_profile = d.get('traffic_report_profile', 'security_risk')
        if traffic_report_profile not in _VALID_PROFILES:
            traffic_report_profile = 'security_risk'

        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'

        fmt = d.get('format', 'all')
        fmt = fmt if fmt in _ALLOWED_REPORT_FORMATS else 'all'

        # ── Synchronous validation (still returns 400/415 for bad input) ──
        payload = {
            "source": source,
            "fmt": fmt,
            "lang": lang,
            "traffic_report_profile": traffic_report_profile,
            "send_email": str(d.get('send_email', '')).lower() == 'true',
        }

        if source == 'csv':
            import tempfile
            if 'file' not in request.files:
                return jsonify({"ok": False, "error": t("gui_err_no_csv", lang=lang)})
            csv_file = request.files['file']
            if csv_file.filename == '':
                return jsonify({"ok": False, "error": t("gui_err_empty_csv", lang=lang)})
            if csv_file.mimetype not in {
                'text/csv', 'application/vnd.ms-excel',
                'text/plain', 'application/octet-stream',
            }:
                return jsonify({"ok": False, "error": t("gui_err_invalid_file_type", lang=lang)}), 415
            # Persist the upload now (request-scoped) so the worker thread can read it.
            safe_filename = secure_filename(csv_file.filename) or 'upload.csv'
            temp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{safe_filename}")
            csv_file.save(temp_path)
            payload["temp_path"] = temp_path
        else:
            payload["start_date"] = d.get('start_date')
            payload["end_date"] = d.get('end_date')

            # Extract optional traffic filters (API source only)
            report_filters = None
            raw_filters = d.get('filters') or {}
            if raw_filters:
                report_filters = {
                    'policy_decisions': raw_filters.get('policy_decisions') or None,
                    'src_labels': [s for s in (raw_filters.get('src_labels') or []) if s],
                    'dst_labels': [s for s in (raw_filters.get('dst_labels') or []) if s],
                    'src_ip': (raw_filters.get('src_ip') or '').strip(),
                    'dst_ip': (raw_filters.get('dst_ip') or '').strip(),
                    'port': (raw_filters.get('port') or '').strip(),
                    'proto': raw_filters.get('proto'),
                    'ex_src_labels': [s for s in (raw_filters.get('ex_src_labels') or []) if s],
                    'ex_dst_labels': [s for s in (raw_filters.get('ex_dst_labels') or []) if s],
                    'ex_src_ip': (raw_filters.get('ex_src_ip') or '').strip(),
                    'ex_dst_ip': (raw_filters.get('ex_dst_ip') or '').strip(),
                    'ex_port': (raw_filters.get('ex_port') or '').strip(),
                }
                if not any(v for v in report_filters.values() if v):
                    report_filters = None
            payload["filters"] = report_filters
            # Resolve the 3-mode data_source (falls back to legacy use_cache/clip_to_cache).
            _uc, _clip, _ds_warn = _data_source_from_payload(d, cache_available(cm))
            payload["use_cache"], payload["clip_to_cache"] = _uc, _clip
            if _ds_warn:
                logger.warning("Report data-source fallback: {}", _ds_warn)

        # ── Validation passed: create job, spawn worker, return job_id ──
        job_id = uuid.uuid4().hex[:12]
        record = {
            "status": "running",
            "files": [],
            "error": "",
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "finished_at": None,
        }
        payload["record"] = record
        try:
            _save_adhoc_job(job_id, record)
        except Exception as e:
            return _err_with_log("report_traffic_generate", e, lang=lang)

        threading.Thread(target=_run_adhoc, args=(job_id, payload), daemon=True).start()
        return jsonify({"ok": True, "job_id": job_id})

    @bp.route('/api/reports/jobs/<job_id>', methods=['GET'])
    def api_report_job_status(job_id):
        jobs = _load_adhoc_jobs()
        if job_id not in jobs:
            lang = request.args.get('lang') or cm.config.get('settings', {}).get('language', 'en')
            return jsonify({"ok": False, "error": t("gui_err_unknown_job", lang=lang)}), 404
        return jsonify({"ok": True, **jobs[job_id]})

    @bp.route('/api/audit_report/generate', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_generate_audit_report():
        d = request.json or {}
        _arlog = None
        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'
        try:
            from src.report.audit_generator import AuditGenerator
            from src.api_client import ApiClient
            try:
                from src.module_log import ModuleLog as _ML
                _arlog = _ML.get("reports")
                _arlog.separator(f"Audit Report {datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')} UTC")
                _arlog.info(f"range={d.get('start_date')}~{d.get('end_date')}")
            except Exception:
                pass  # intentional fallback: ModuleLog is optional; audit report must not fail if logging setup fails

            cm.load()
            config_dir = _resolve_config_dir()
            api = ApiClient(cm)
            from src.main import _make_cache_reader
            gen = AuditGenerator(cm, api_client=api, config_dir=config_dir,
                                 cache_reader=_make_cache_reader(cm))

            start_date = d.get('start_date')
            end_date = d.get('end_date')

            result = gen.generate_from_api(start_date, end_date, lang=lang)

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_audit_data", lang=lang)})

            output_dir = _resolve_reports_dir(cm)
            fmt = d.get('format', 'html')
            fmt = fmt if fmt in _ALLOWED_REPORT_FORMATS else 'html'
            paths = gen.export(result, fmt=fmt, output_dir=output_dir, lang=lang)
            _write_audit_dashboard_summary(output_dir, result)
            filenames = [os.path.basename(p) for p in paths]
            try:
                if _arlog:
                    _arlog.info(f"Saved: {filenames}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return jsonify({"ok": True, "files": filenames, "record_count": result.record_count})
        except Exception as e:
            try:
                if _arlog:
                    _arlog.error(f"Audit report generation failed: {e}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return _err_with_log("report_audit_generate", e, lang=lang)

    # ── API: Policy Diff Report ──────────────────────────────────────────────
    @bp.route('/api/policy_diff_report/generate', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_generate_policy_diff_report():
        d = request.json or {}
        _pdlog = None
        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'
        try:
            from src.report.policy_diff_report import PolicyDiffReport
            from src.api_client import ApiClient
            try:
                from src.module_log import ModuleLog as _ML
                _pdlog = _ML.get("reports")
                _pdlog.separator(f"Policy Diff Report {datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')} UTC")
                _pdlog.info(f"format={d.get('format')} lang={lang}")
            except Exception:
                pass  # intentional fallback: ModuleLog is optional; policy diff report must not fail if logging setup fails

            cm.load()
            config_dir = _resolve_config_dir()
            api = ApiClient(cm)
            from src.main import _make_cache_reader
            rep = PolicyDiffReport(cm, api_client=api, config_dir=config_dir,
                                   cache_reader=_make_cache_reader(cm))

            fmt = d.get('format', 'html')
            fmt = fmt if fmt in ('html', 'csv') else 'html'
            output_dir = _resolve_reports_dir(cm)
            path = rep.run(output_dir=output_dir, lang=lang, fmt=fmt)
            paths = path if isinstance(path, list) else [path]
            filenames = [os.path.basename(p) for p in paths]
            try:
                if _pdlog:
                    _pdlog.info(f"Saved: {filenames}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return jsonify({"ok": True, "files": filenames})
        except Exception as e:
            try:
                if _pdlog:
                    _pdlog.error(f"Policy diff report generation failed: {e}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return _err_with_log("report_policy_diff_generate", e, lang=lang)

    # ── API: Policy Resolver Report ──────────────────────────────────────────
    @bp.route('/api/policy_resolver_report/generate', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_generate_policy_resolver_report():
        d = request.json or {}
        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'
        try:
            from src.report.policy_resolver_report import PolicyResolverReport
            from src.api_client import ApiClient
            cm.load()
            config_dir = _resolve_config_dir()
            from src.main import _make_cache_reader
            rep = PolicyResolverReport(cm, api_client=ApiClient(cm), config_dir=config_dir,
                                       cache_reader=_make_cache_reader(cm))
            fmt = d.get('format', 'all')
            fmt = fmt if fmt in ('json', 'csv', 'all') else 'all'
            output_dir = _resolve_reports_dir(cm)
            paths = rep.run(output_dir=output_dir, lang=lang, fmt=fmt)
            if not paths:
                return jsonify({"ok": True, "files": [], "empty": True})
            return jsonify({"ok": True, "files": [os.path.basename(p) for p in paths]})
        except Exception as e:
            return _err_with_log("report_policy_resolver_generate", e, lang=lang)

    # ── API: Labels (for App Summary app/env dropdowns) ──────────────────────
    @bp.route('/api/labels', methods=['GET'])
    @limiter.limit("60 per hour")
    def api_list_labels():
        key = request.args.get('key', 'app')
        if key not in ('app', 'env', 'role', 'loc'):
            lang = request.args.get('lang') or cm.config.get('settings', {}).get('language', 'en')
            return jsonify({"ok": False, "error": t("gui_err_invalid_label_key", lang=lang)}), 400
        try:
            from src.api_client import ApiClient
            cm.load()
            labels = ApiClient(cm).get_labels(key)
            values = sorted({l.get('value', '') for l in labels if l.get('value')})
            return jsonify({"ok": True, "labels": values})
        except Exception as e:
            return _err_with_log("list_labels", e)

    # ── API: App Summary Report ───────────────────────────────────────────────
    @bp.route('/api/app_report/generate', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_generate_app_report():
        d = request.json or {}
        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'

        app = (d.get('app') or '').strip()
        if not app:
            return jsonify({"ok": False, "error": t("gui_app_required", lang=lang)}), 400

        # ── Validation passed: create job, spawn worker, return job_id ──
        _uc, _clip, _ds_warn = _data_source_from_payload(d, cache_available(cm))
        if _ds_warn:
            logger.warning("App report data-source fallback: {}", _ds_warn)
        payload = {"app": app, "env": d.get('env') or None, "lang": lang,
                   "start_date": d.get('start_date'), "end_date": d.get('end_date'),
                   "use_cache": _uc}
        job_id = uuid.uuid4().hex[:12]
        record = {
            "status": "running",
            "files": [],
            "error": "",
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "finished_at": None,
        }
        try:
            _save_adhoc_job(job_id, record)
        except Exception as e:
            return _err_with_log("report_app_summary_generate", e, lang=lang)

        def _run_app_summary(jid, p):
            try:
                from src.report.app_summary_report import AppSummaryReport
                from src.api_client import ApiClient
                cm.load()
                from src.main import _make_cache_reader
                rep = AppSummaryReport(cm, api_client=ApiClient(cm),
                                       config_dir=_resolve_config_dir(),
                                       cache_reader=_make_cache_reader(cm))
                path = rep.run(app=p["app"], env=p["env"], output_dir=_resolve_reports_dir(cm),
                               lang=p["lang"], start_date=p["start_date"], end_date=p["end_date"],
                               use_cache=p.get("use_cache", True))
                paths = path if isinstance(path, list) else [path]
                record.update({"status": "done",
                               "files": [os.path.basename(pp) for pp in paths],
                               "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
                _save_adhoc_job(jid, record)
            except Exception as e:  # noqa: BLE001
                logger.exception(f"App summary job {jid} failed: {e}")
                record.update({"status": "error", "error": str(e),
                               "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
                try:
                    _save_adhoc_job(jid, record)
                except Exception:
                    logger.error(f"Could not persist failure for job {jid}")

        threading.Thread(target=_run_app_summary, args=(job_id, payload), daemon=True).start()
        return jsonify({"ok": True, "job_id": job_id})

    # ── API: VEN Status Report ────────────────────────────────────────────────
    @bp.route('/api/ven_status_report/generate', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_generate_ven_status_report():
        d = request.json or {}
        _vrlog = None
        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'
        try:
            from src.report.ven_status_generator import VenStatusGenerator
            from src.api_client import ApiClient
            try:
                from src.module_log import ModuleLog as _ML
                _vrlog = _ML.get("reports")
                _vrlog.separator(f"VEN Status Report {datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')} UTC")
            except Exception:
                pass  # intentional fallback: ModuleLog is optional; VEN status report must not fail if logging setup fails

            cm.load()
            api = ApiClient(cm)
            gen = VenStatusGenerator(cm, api_client=api)

            result = gen.generate(lang=lang)

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_ven_data", lang=lang)})

            output_dir = _resolve_reports_dir(cm)
            fmt = d.get('format', 'html')
            fmt = fmt if fmt in _ALLOWED_REPORT_FORMATS else 'html'
            paths = gen.export(result, fmt=fmt, output_dir=output_dir, lang=lang)
            filenames = [os.path.basename(p) for p in paths]
            kpis = result.module_results.get('kpis', [])
            try:
                if _vrlog:
                    _vrlog.info(f"Saved: {filenames}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return jsonify({"ok": True, "files": filenames, "record_count": result.record_count, "kpis": kpis})
        except Exception as e:
            try:
                if _vrlog:
                    _vrlog.error(f"VEN status report generation failed: {e}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return _err_with_log("report_ven_status_generate", e, lang=lang)

    # ── API: Policy Usage Report ──────────────────────────────────────────────
    @bp.route('/api/policy_usage_report/generate', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_generate_policy_usage_report():
        d = request.get_json(silent=True) or request.form.to_dict() or {}
        _pulog = None
        lang = d.get('lang', 'en')
        if lang not in ('en', 'zh_TW'):
            lang = 'en'
        try:
            from src.report.policy_usage_generator import PolicyUsageGenerator
            from src.api_client import ApiClient
            try:
                from src.module_log import ModuleLog as _ML
                _pulog = _ML.get("reports")
                _pulog.separator(f"Policy Usage Report {datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')} UTC")
                _pulog.info(f"range={d.get('start_date')}~{d.get('end_date')}")
            except Exception:
                pass  # intentional fallback: ModuleLog is optional; policy usage report must not fail if logging setup fails

            cm.load()
            api = ApiClient(cm)
            config_dir = _resolve_config_dir()
            gen = PolicyUsageGenerator(cm, api_client=api, config_dir=config_dir)

            start_date = d.get('start_date')
            end_date   = d.get('end_date')

            source = d.get('source', 'api')
            if source == 'csv':
                import tempfile
                if 'file' not in request.files or request.files['file'].filename == '':
                    return jsonify({"ok": False, "error": t("gui_err_no_csv", lang=lang)})
                csv_file = request.files['file']
                safe_name = secure_filename(csv_file.filename) or 'upload.csv'
                temp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{safe_name}")
                csv_file.save(temp_path)
                try:
                    result = gen.generate_from_csv(temp_path, lang=lang)
                finally:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
            else:
                result = gen.generate_from_api(start_date=start_date, end_date=end_date, lang=lang)

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_pu_data", lang=lang)})

            output_dir = _resolve_reports_dir(cm)
            fmt = d.get('format', 'html')
            fmt = fmt if fmt in _ALLOWED_REPORT_FORMATS else 'html'
            paths = gen.export(result, fmt=fmt, output_dir=output_dir, lang=lang)
            _write_policy_usage_dashboard_summary(output_dir, result)
            filenames = [os.path.basename(p) for p in paths]
            mod00 = result.module_results.get('mod00', {})
            kpis = mod00.get('kpis', [])
            execution_stats = getattr(result, "execution_stats", {}) or mod00.get("execution_stats", {})
            execution_notes = mod00.get("execution_notes", [])

            try:
                if _pulog:
                    _pulog.info(f"Saved: {filenames}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return jsonify({"ok": True, "files": filenames,
                            "record_count": result.record_count, "kpis": kpis,
                            "execution_stats": execution_stats, "execution_notes": execution_notes,
                            "reused_rule_details": execution_stats.get("reused_rule_details", []),
                            "pending_rule_details": execution_stats.get("pending_rule_details", []),
                            "failed_rule_details": execution_stats.get("failed_rule_details", [])})
        except Exception as e:
            try:
                if _pulog:
                    _pulog.error(f"Policy usage report generation failed: {e}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return _err_with_log("report_policy_usage_generate", e, lang=lang)

    # ── API: Report Schedules ─────────────────────────────────────────────────

    @bp.route('/api/report-schedules', methods=['GET'])
    def api_list_report_schedules():
        cm.load()
        schedules = cm.get_report_schedules()
        # Enrich with last-run state from state.json
        state_file = _resolve_state_file()
        states = {}
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    states = json.load(f).get("report_schedule_states", {})
            except Exception:
                pass  # intentional fallback: state enrichment is best-effort; schedules still listed without last-run state
        result = []
        for s in schedules:
            sid = str(s.get("id", ""))
            state = states.get(sid, {})
            entry = dict(s)
            entry["last_run"] = state.get("last_run")
            entry["last_status"] = state.get("status")
            entry["last_error"] = state.get("error", "")
            result.append(entry)
        return jsonify({"ok": True, "schedules": result})

    @bp.route('/api/report-schedules', methods=['POST'])
    def api_create_report_schedule():
        d = request.json or {}
        try:
            cm.load()
            # Preserve optional traffic filters if provided
            raw_filters = d.get('filters') or {}
            if raw_filters:
                d['filters'] = raw_filters
            elif 'filters' in d:
                del d['filters']
            sched = cm.add_report_schedule(d)
            return jsonify({"ok": True, "schedule": sched})
        except Exception as e:
            return _err_with_log("report_schedule_create", e, 400)

    @bp.route('/api/report-schedules/<int:schedule_id>', methods=['PUT'])
    def api_update_report_schedule(schedule_id):
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        try:
            cm.load()
            ok = cm.update_report_schedule(schedule_id, d)
            if not ok:
                return jsonify({"ok": False, "error": t("gui_schedule_not_found", lang=lang)}), 404
            return jsonify({"ok": True})
        except Exception as e:
            return _err_with_log("report_schedule_update", e, 400, lang=lang)

    @bp.route('/api/report-schedules/<int:schedule_id>', methods=['DELETE'])
    def api_delete_report_schedule(schedule_id):
        lang = (request.get_json(silent=True) or {}).get('lang') or cm.config.get('settings', {}).get('language', 'en')
        try:
            cm.load()
            ok = cm.remove_report_schedule(schedule_id)
            if not ok:
                return jsonify({"ok": False, "error": t("gui_schedule_not_found", lang=lang)}), 404
            return jsonify({"ok": True})
        except Exception as e:
            return _err_with_log("report_schedule_delete", e, 400, lang=lang)

    @bp.route('/api/report-schedules/<int:schedule_id>/toggle', methods=['POST'])
    def api_toggle_report_schedule(schedule_id):
        lang = (request.get_json(silent=True) or {}).get('lang') or cm.config.get('settings', {}).get('language', 'en')
        try:
            cm.load()
            schedules = cm.get_report_schedules()
            sched = next((s for s in schedules if s.get("id") == schedule_id), None)
            if not sched:
                return jsonify({"ok": False, "error": t("gui_schedule_not_found", lang=lang)}), 404
            new_enabled = not sched.get("enabled", False)
            cm.update_report_schedule(schedule_id, {"enabled": new_enabled})
            return jsonify({"ok": True, "enabled": new_enabled})
        except Exception as e:
            return _err_with_log("report_schedule_toggle", e, 400, lang=lang)

    @bp.route('/api/report-schedules/<int:schedule_id>/run', methods=['POST'])
    @limiter.limit("20 per hour")
    def api_run_report_schedule(schedule_id):
        lang = (request.get_json(silent=True) or {}).get('lang') or cm.config.get('settings', {}).get('language', 'en')
        try:
            cm.load()
            schedules = cm.get_report_schedules()
            sched = next((s for s in schedules if s.get("id") == schedule_id), None)
            if not sched:
                return jsonify({"ok": False, "error": t("gui_schedule_not_found", lang=lang)}), 404

            from src.report_scheduler import ReportScheduler
            from src.reporter import Reporter
            reporter = Reporter(cm)
            scheduler = ReportScheduler(cm, reporter)
            scheduler._state_file = _resolve_state_file()
            now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
            scheduler._save_state(schedule_id, now_str, "running")

            def _run():
                try:
                    scheduler.run_schedule(sched)
                    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    scheduler._save_state(schedule_id, now_str, "success")
                except Exception as e:
                    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    scheduler._save_state(schedule_id, now_str, "failed", str(e))
                    logger.exception(f"GUI-triggered schedule {schedule_id} failed: {e}")

            t_thread = threading.Thread(target=_run, daemon=True)
            t_thread.start()
            return jsonify({"ok": True, "message": t("gui_msg_sched_started", lang=lang)})
        except Exception as e:
            return _err_with_log("report_schedule_run", e, 400, lang=lang)

    @bp.route('/api/report-schedules/<int:schedule_id>/history', methods=['GET'])
    def api_report_schedule_history(schedule_id):
        state_file = _resolve_state_file()
        try:
            if not os.path.exists(state_file):
                return jsonify({"ok": True, "history": []})
            with open(state_file, "r", encoding="utf-8") as f:
                states = json.load(f).get("report_schedule_states", {})
            entry = states.get(str(schedule_id), {})
            return jsonify({"ok": True, "history": [entry] if entry else []})
        except Exception as e:
            lang = (request.get_json(silent=True) or {}).get('lang') or cm.config.get('settings', {}).get('language', 'en')
            return _err_with_log("report_schedule_history", e, 400, lang=lang)

    return bp
