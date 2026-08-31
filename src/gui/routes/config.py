"""Config Blueprint: security, settings, alert-plugins, TLS, and PCE-profile routes."""
from __future__ import annotations

import json
import os
import urllib.parse

from flask import Blueprint, jsonify, request
from loguru import logger

from src.config import ConfigManager, hash_password, verify_password
from src.alerts import PLUGIN_METADATA, plugin_config_path
from src.i18n import t
from src.pce_target import normalize_org_id, normalize_pce_url, pce_target_changed
from src.gui._helpers import (
    _err,
    _err_with_log,
    _redact_secrets,
    _strip_redaction_placeholders,
    _check_ip_allowed,
    _validate_allowed_ips,
    _is_forbidden_report_output_dir,
    _SETTINGS_ALLOWLISTS,
    _plugin_config_roots,
    _ROOT_DIR,
    _SELF_SIGNED_VALIDITY_DAYS,
    _generate_self_signed_cert,
    _generate_csr,
    _import_signed_cert,
    _get_cert_info,
    _cert_days_remaining,
    _resolve_state_file,
)


def make_config_blueprint(
    cm: ConfigManager,
    csrf,           # flask_wtf.csrf.CSRFProtect instance (unused here, kept for consistent signature)
    limiter,        # flask_limiter.Limiter instance
    login_required,  # flask_login.login_required decorator
) -> Blueprint:
    bp = Blueprint("config", __name__)

    # ── API: Security ──────────────────────────────────────────────────────────

    @bp.route('/api/security', methods=['GET'])
    def api_security_get():
        cm.load()
        gui_cfg = cm.config.get('web_gui', {})
        return jsonify({
            "username": gui_cfg.get("username", "illumio"),
            "allowed_ips": gui_cfg.get("allowed_ips", []),
            "auth_setup": bool(gui_cfg.get("password"))
        })

    @bp.route('/api/security', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_security_post():
        d = request.json or {}
        # 以共用 config 鎖序列化整段 load→mutate→save，避免併發存檔
        # （cheroot 多執行緒 pool）互相交錯而丟失更新
        # （比照下方 api_save_settings 的既有做法）。
        with cm.write_lock:
            cm.load()
            lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
            # scratch：web_gui 底下每個欄位都是純量或整包替換的 list（沒有
            # 巢狀 dict 會被就地修改），淺拷貝即可把驗證失敗前的暫存變更
            # 隔離在 scratch，通過才整批寫回 cm.config——避免被拒絕的欄位
            # （例如 username）留在共用的 cm.config 物件裡被併發 GET 看到。
            gui_scratch = dict(cm.config.get("web_gui", {}))

            if "username" in d:
                # 型別/內容驗證：非字串（int/null/list）或空/超長 username 存檔
                # 後，下次登入 auth.py 的 saved_username.strip() 會 AttributeError
                # → 全域 500 鎖死登入，且 load() 不會修復 web_gui 欄位。
                u = d["username"]
                if not isinstance(u, str) or not (1 <= len(u.strip()) <= 128):
                    logger.warning("api_security_post rejected invalid username "
                                   "(type={}, len={})", type(u).__name__,
                                   len(u) if isinstance(u, str) else "-")
                    return jsonify({"ok": False, "error": t("gui_err_generic", lang=lang)}), 400
                gui_scratch["username"] = u.strip()

            if "allowed_ips" in d:
                allowed_ips, invalid_ips = _validate_allowed_ips(d["allowed_ips"])
                if invalid_ips:
                    return jsonify({
                        "ok": False,
                        "error": t("gui_err_invalid_allowlist_entries", lang=lang, entries=', '.join(invalid_ips))
                    }), 400
                # 自鎖防護：非空清單必須涵蓋當前請求來源 IP。security_check 對
                # 非清單 IP 直接 TCP RST（無任何 HTTP 回應），typo 清單一旦存檔
                # GUI 立即無聲斷線，只能上主機改 config.json 復原。
                if allowed_ips and not _check_ip_allowed(allowed_ips, request.remote_addr):
                    logger.warning("api_security_post rejected allowed_ips not covering "
                                   "requester {}", request.remote_addr)
                    return jsonify({"ok": False, "error": t("gui_err_ip_not_allowed", lang=lang)}), 400
                gui_scratch["allowed_ips"] = allowed_ips

            if d.get("new_password"):
                must_change = bool(gui_scratch.get("must_change_password", False))
                if not must_change:
                    old_pw = d.get("old_password") or ""
                    if not old_pw:
                        return jsonify({"ok": False, "error": t("gui_err_old_password_required", lang=lang)}), 400
                    if not verify_password(old_pw, gui_scratch.get("password", "")):
                        return jsonify({"ok": False, "error": t("gui_err_old_password_incorrect", lang=lang)}), 400
                new_pw = d["new_password"]
                confirm_pw = d.get("confirm_password", new_pw)
                if not (12 <= len(new_pw) <= 512) or new_pw != confirm_pw:
                    return jsonify({"ok": False, "error": t("gui_err_invalid_password_form", lang=lang)}), 400
                gui_scratch["password"] = hash_password(new_pw)
                gui_scratch.pop("_initial_password", None)
                gui_scratch.pop("must_change_password", None)
                # 密碼變更即撤銷所有既存 session：輪替 session 簽章 secret，讓
                # 舊 cookie（可能已外洩、正是改密碼的動機）立即失效。標記本請求
                # session 已修改，回應時以新 key 重簽 cookie，改密碼的操作者
                # 自己保持登入；其他先前簽發的 session 全數作廢。
                import secrets as _secrets
                from flask import current_app, session as _session
                _new_secret = _secrets.token_hex(32)
                gui_scratch["secret_key"] = _new_secret
                current_app.secret_key = _new_secret
                _session.modified = True

            cm.config["web_gui"] = gui_scratch
            cm.save()
        return jsonify({"ok": True})

    # ── API: Settings ──────────────────────────────────────────────────────────

    @bp.route('/api/settings')
    def api_get_settings():
        cm.load()
        rpt = cm.config.get("report", {})
        payload = {
            "api": cm.config.get("api", {}),
            "email": cm.config.get("email", {}),
            "smtp": cm.config.get("smtp", {}),
            "alerts": cm.config.get("alerts", {}),
            "settings": cm.config.get("settings", {}),
            "report": {
                "output_dir":      rpt.get("output_dir", "reports/"),
                "retention_days":  rpt.get("retention_days", 30),
            },
        }
        for root in _plugin_config_roots():
            payload.setdefault(root, cm.config.get(root, {}))
        return jsonify(_redact_secrets(payload))

    @bp.route('/api/alert-plugins')
    def api_alert_plugins():
        lang = (request.args.get('lang') or cm.config.get('settings', {}).get('language', 'en') or 'en')
        return jsonify({
            "plugins": {
                name: {
                    "name": meta.name,
                    "display_name": meta.resolved_display_name(lang=lang),
                    "description": meta.resolved_description(lang=lang),
                    "fields": [
                        {
                            "key": key,
                            "label": field.resolved_label(lang=lang),
                            "help": field.resolved_help(lang=lang),
                            "required": field.required,
                            "secret": field.secret,
                            "placeholder": field.placeholder,
                            "input_type": field.input_type,
                            "value_type": field.value_type,
                            "list_delimiter": field.list_delimiter,
                            "config_path": list(plugin_config_path(name, key)),
                        }
                        for key, field in meta.fields.items()
                    ],
                }
                for name, meta in PLUGIN_METADATA.items()
            }
        })

    @bp.route('/api/settings', methods=['POST'])
    @limiter.limit("30 per hour")
    def api_save_settings():
        d = _strip_redaction_placeholders(request.json or {})
        # Serialize the whole load→mutate→save under the shared config lock so
        # concurrent saves (cheroot multi-thread pool) cannot lose updates.
        with cm.write_lock:
            cm.load()
            lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
            # scratch：對整份 cm.config 做深拷貝（json round-trip，沿用
            # ConfigManager 既有慣例，見 apply_best_practices / __init__ 的
            # 深拷貝寫法）。這個 handler 一次可能同時處理 api / email / smtp /
            # alerts / settings / report / 外掛設定等多個區塊，其中不只一個
            # 區塊會做「先寫入再驗證、失敗才 400」——用淺拷貝只隔離得了單一
            # 頂層鍵，遇到巢狀結構（例如 api 區塊本身）還是可能把中間狀態寫進
            # 共用的 cm.config。所有欄位變更只落在 scratch，全部驗證通過才
            # 整批寫回 cm.config + save；任何一個 400 都讓 cm.config 維持
            # load() 剛讀回的原狀，不會有欄位被併發 GET 看到或誤存。
            scratch = json.loads(json.dumps(cm.config))
            # Set when the operator chose "flush" — carried down to just
            # before the save below rather than run here, because the rest
            # of this handler can still reject the request (invalid api
            # block, forbidden report dir, ...) after this point. Flushing
            # eagerly would empty a cache that still belongs to the PCE the
            # appliance stays pointed at once the save fails.
            _do_pce_flush = False
            _do_pce_rebind = False
            _restart_required = False
            if 'api' in d:
                api_in = d['api']
                api_allowlist = _SETTINGS_ALLOWLISTS["api"]
                # Normalize before anything reads these: the comparison below,
                # the echo in the 409 body and the value stored further down
                # must all be the same string, or the next edit compares what
                # was typed against what was stored and the guard misfires
                # (src/pce_target.py's module docstring).
                if 'url' in api_in:
                    api_in['url'] = normalize_pce_url(api_in['url'])
                if 'org_id' in api_in:
                    api_in['org_id'] = normalize_org_id(api_in['org_id'])
                # Validate url scheme before accepting it
                if 'url' in api_in:
                    _url_val = api_in['url']
                    _scheme = urllib.parse.urlparse(_url_val).scheme.lower()
                    if _scheme not in ('http', 'https'):
                        return jsonify({"ok": False, "error": t("gui_err_api_url_scheme", lang=lang)}), 400
                    if _scheme == 'http':
                        logger.warning("api.url uses plain HTTP — TLS verification cannot be performed")
                _old_api = dict(scratch.get('api', {}))
                _candidate_api = dict(_old_api)
                for k in api_allowlist:
                    if k in api_in:
                        _candidate_api[k] = api_in[k]
                # Validate the complete merged candidate before the target-change
                # response can echo any requested URL. Invalid values must never
                # reach the choice/flush path or mutate the scratch configuration.
                from pydantic import ValidationError as _ValidationError
                from src.config_models import ApiSettings
                try:
                    _validated_api = ApiSettings.model_validate(_candidate_api)
                except _ValidationError as ve:
                    reason = ve.errors()[0]['msg'] if ve.errors() else str(ve)
                    return jsonify({
                        "ok": False,
                        "error": t("gui_err_api_invalid_config", lang=lang, reason=reason),
                    }), 400
                _validated_api_dict = _validated_api.model_dump()

                # Changing which PCE this appliance talks to is not an edit —
                # the cache, the ingestion positions, the archive files and the
                # schedules all carry the previous PCE's data with no marker
                # saying so. Make the operator say what should happen to it.
                _target_changed = pce_target_changed(
                    _old_api,
                    _validated_api_dict['url'] if 'url' in api_in else None,
                    _validated_api_dict['org_id'] if 'org_id' in api_in else None,
                )
                _choice = d.get('pce_target_change')
                if _target_changed:
                    if _choice is None:
                        return jsonify({
                            "ok": False,
                            "pce_target_changed": True,
                            "old": {"url": _old_api.get('url', ''), "org_id": _old_api.get('org_id', '')},
                            "new": {"url": _validated_api_dict['url'],
                                    "org_id": _validated_api_dict['org_id']},
                            "error": t("gui_err_pce_target_needs_choice", lang=lang),
                        }), 409
                    if _choice not in ("flush", "same-pce"):
                        return jsonify({"ok": False,
                                        "error": t("gui_err_pce_target_bad_choice", lang=lang)}), 400
                    if _choice == "flush":
                        _do_pce_flush = True
                    else:
                        # same-pce: one PCE at a new address, data still theirs.
                        # The binding has to move with it or every ingest after
                        # this save refuses to write — a supported answer would
                        # silently stop monitoring. Deferred past cm.save() below
                        # for the same reason as the CLI path.
                        _do_pce_rebind = True
                # Persist the schema's normalized form for fields present in
                # this request (notably console_url's stripped trailing slash),
                # while leaving omitted fields untouched.
                for k in api_allowlist:
                    if k in api_in:
                        scratch['api'][k] = _validated_api_dict[k]
                _runtime_connection_changed = any(
                    k in api_in and _old_api.get(k, _validated_api_dict[k]) != _validated_api_dict[k]
                    for k in ("deployment_type", "console_url")
                )
                _restart_required = _target_changed or _runtime_connection_changed
            if 'email' in d:
                email_in = d['email']
                if 'sender' in email_in:
                    scratch['email']['sender'] = email_in['sender']
                if 'recipients' in email_in:
                    scratch['email']['recipients'] = email_in['recipients']
            if 'smtp' in d:
                allowlist = _SETTINGS_ALLOWLISTS["smtp"]
                filtered = {k: v for k, v in d['smtp'].items() if k in allowlist}
                scratch.setdefault('smtp', {}).update(filtered)
            if 'alerts' in d:
                allowlist = _SETTINGS_ALLOWLISTS["alerts"]
                filtered = {k: v for k, v in d['alerts'].items() if k in allowlist}
                scratch.setdefault('alerts', {}).update(filtered)
            if 'settings' in d:
                allowlist = _SETTINGS_ALLOWLISTS["settings"]
                filtered = {k: v for k, v in d['settings'].items() if k in allowlist}
                scratch.setdefault('settings', {}).update(filtered)
            if 'report' in d:
                rpt_in = d['report']
                rpt_cfg = scratch.setdefault('report', {})
                if 'output_dir' in rpt_in:
                    candidate_dir = rpt_in['output_dir']
                    # 只擋「新設定」：不強制驗證既有已存在 cm.config 的
                    # output_dir（load() 不呼叫這個檢查），避免升級後既有
                    # 自訂路徑（例如剛好落在某個前綴下）讓 GUI 直接自鎖。
                    if _is_forbidden_report_output_dir(candidate_dir):
                        return jsonify({
                            "ok": False,
                            "error": t("gui_err_report_output_dir_forbidden", lang=lang),
                        }), 400
                    rpt_cfg['output_dir'] = candidate_dir
                if 'retention_days' in rpt_in:
                    try:
                        rpt_cfg['retention_days'] = max(0, int(rpt_in['retention_days']))
                    except (TypeError, ValueError):
                        pass  # intentional fallback: keep existing retention_days if new value is not numeric
            known_roots = {'api', 'email', 'smtp', 'alerts', 'settings', 'report'}
            for root in _plugin_config_roots():
                if root in known_roots or root not in d:
                    continue
                incoming = d.get(root)
                if isinstance(incoming, dict):
                    scratch.setdefault(root, {}).update(incoming)
                else:
                    scratch[root] = incoming
            # Every 400 return above this point has already exited the
            # handler, so reaching here means the save is going through.
            # Only now is it safe to flush — before that, the PCE this
            # appliance is still pointed at (on save failure) would lose its
            # own cache and ingestion position.
            #
            # And still BEFORE the save, which is the order both CLI paths
            # follow too (src/cli/config.py, src/cli/menus/_root.py): past the
            # save the stored connection names the new PCE, the guard never
            # fires for this edit again, and nothing would ever come back to
            # finish an interrupted clear — the old PCE's cache and fetch
            # positions would stay for good. Failing here costs a retry, whose
            # clear is idempotent.
            if _do_pce_flush:
                from src.pce_cache.flush import flush_pce_derived_state
                _cache_cfg = cm.models.pce_cache
                try:
                    flush_pce_derived_state(_cache_cfg.db_path, _resolve_state_file())
                except Exception as exc:
                    logger.exception("PCE cache flush failed, settings not saved: {}", exc)
                    return jsonify({
                        "ok": False,
                        "error": t("gui_err_pce_flush_failed", lang=lang),
                    }), 500
            cm.config = scratch
            cm.save()
            if _do_pce_rebind:
                # After the save, unlike the flush above: the rows stay either
                # way, and binding to a target that had not been persisted would
                # name a PCE the appliance is not using.
                from src.pce_cache.provenance import rebind
                try:
                    rebind(cm.models.pce_cache.db_path, cm.config["api"])
                except Exception as exc:  # noqa: BLE001
                    # The connection is saved and correct; a stale binding shows
                    # up as a loud ingest refusal, not as silent contamination,
                    # so this is reported rather than failing a good save.
                    logger.warning("PCE cache re-bind failed after same-pce save: {}", exc)
        response = {"ok": True}
        if _restart_required:
            response["restart_required"] = True
        return jsonify(response)

    # ── TLS Certificate Management ─────────────────────────────────────────────

    @bp.route('/api/tls/status', methods=['GET'])
    def api_tls_status():
        cm.load()
        tls_cfg = cm.config.get("web_gui", {}).get("tls", {})
        result = {
            "enabled": bool(tls_cfg.get("enabled")),
            "self_signed": bool(tls_cfg.get("self_signed")),
            "cert_file": tls_cfg.get("cert_file", ""),
            "key_file": tls_cfg.get("key_file", ""),
            # Default auto_renew=True so new installs get protected out of
            # the box; users who explicitly disabled it keep their choice.
            "auto_renew": bool(tls_cfg.get("auto_renew", True)),
            "auto_renew_days": int(tls_cfg.get("auto_renew_days", 30)),
            "default_validity_days": _SELF_SIGNED_VALIDITY_DAYS,
        }
        cert_path = None
        if tls_cfg.get("self_signed"):
            cert_path = os.path.join(_ROOT_DIR, "config", "tls", "self_signed.pem")
            result["cert_info"] = _get_cert_info(cert_path)
        elif tls_cfg.get("cert_file"):
            cert_path = tls_cfg["cert_file"]
            result["cert_info"] = _get_cert_info(cert_path)
        if cert_path:
            result["days_remaining"] = _cert_days_remaining(cert_path)
        return jsonify(result)

    @bp.route('/api/tls/config', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_tls_config():
        d = request.json or {}
        # 以共用 config 鎖序列化整段 load→mutate→save，避免併發存檔
        # （cheroot 多執行緒 pool）互相交錯而丟失更新
        # （比照上方 api_save_settings 的既有做法）。
        with cm.write_lock:
            cm.load()
            lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
            gui_cfg = cm.config.setdefault("web_gui", {})
            tls = gui_cfg.setdefault("tls", {})
            tls["enabled"] = bool(d.get("enabled", False))
            tls["self_signed"] = bool(d.get("self_signed", False))
            tls["cert_file"] = str(d.get("cert_file", "")).strip()
            tls["key_file"] = str(d.get("key_file", "")).strip()
            tls["auto_renew"] = bool(d.get("auto_renew", True))
            # Clamp the threshold into a sensible range so the UI can't push a
            # zero (auto-renew every restart) or a negative value.
            try:
                days = int(d.get("auto_renew_days", 30))
            except (TypeError, ValueError):
                days = 30
            tls["auto_renew_days"] = max(1, min(days, 365))
            cm.save()
        return jsonify({"ok": True, "message": t("gui_tls_saved_restart_hint", lang=lang)})

    @bp.route('/api/tls/renew', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_tls_renew():
        cm.load()
        lang = cm.config.get('settings', {}).get('language', 'en')
        tls_cfg = cm.config.get("web_gui", {}).get("tls", {})
        if not tls_cfg.get("self_signed"):
            return jsonify({"ok": False, "error": t("gui_err_renew_self_signed_only", lang=lang)}), 400
        cert_dir = os.path.join(_ROOT_DIR, "config", "tls")
        try:
            # 帶入設定的效期／金鑰演算法，否則手動續期會把 operator 設定的
            # validity_days / key_algorithm 洗回函式預設值。
            cert_path, key_path = _generate_self_signed_cert(
                cert_dir, force=True,
                days=int(tls_cfg.get("validity_days", _SELF_SIGNED_VALIDITY_DAYS)),
                key_algorithm=tls_cfg.get("key_algorithm", "ecdsa-p256"),
            )
            info = _get_cert_info(cert_path)
            return jsonify({
                "ok": True,
                "message": t("gui_msg_cert_renewed_restart", lang=lang),
                "cert_info": info,
            })
        except RuntimeError as e:
            return _err_with_log("cert_renew", e, lang=lang)

    @bp.route('/api/tls/generate-csr', methods=['POST'])
    @limiter.limit("20 per hour")
    @login_required
    def api_tls_generate_csr():
        cm.load()
        lang = cm.config.get('settings', {}).get('language', 'en')
        d = request.json or {}
        cn = str(d.get('cn', '')).strip()
        if not cn:
            return jsonify({"ok": False, "error": t("gui_err_cn_required", lang=lang)}), 400
        cert_dir = os.path.join(_ROOT_DIR, "config", "tls")
        san_dns = [s.strip() for s in str(d.get('san_dns', '')).split(',') if s.strip()]
        san_ip = [s.strip() for s in str(d.get('san_ip', '')).split(',') if s.strip()]
        try:
            csr_pem, key_path = _generate_csr(
                cert_dir,
                cn=cn,
                o=str(d.get('o', '')).strip(),
                ou=str(d.get('ou', '')).strip(),
                c=str(d.get('c', '')).strip(),
                san_dns=san_dns,
                san_ip=san_ip,
                key_algorithm=str(d.get('key_algorithm', 'rsa-2048')),
            )
            return jsonify({"ok": True, "csr_pem": csr_pem, "key_path": key_path})
        except Exception as e:
            return _err_with_log("csr_generate", e, lang=lang)

    @bp.route('/api/tls/import-cert', methods=['POST'])
    @limiter.limit("20 per hour")
    @login_required
    def api_tls_import_cert():
        cm.load()
        lang = cm.config.get('settings', {}).get('language', 'en')
        d = request.json or {}
        cert_pem = str(d.get('cert_pem', '')).strip()
        if not cert_pem:
            return jsonify({"ok": False, "error": t("gui_err_cert_pem_required", lang=lang)}), 400
        cert_dir = os.path.join(_ROOT_DIR, "config", "tls")
        try:
            cert_info = _import_signed_cert(cert_dir, cert_pem)
            # 以共用 config 鎖序列化 load→mutate→save（比照 api_tls_config）：
            # cm.load() 會整個換掉 cm.config 物件，鎖外抓到的 gui_cfg/tls 可能
            # 已是孤兒 dict——那樣這裡回 {"ok": true, cert_file...} 但磁碟上仍是
            # self_signed，操作者重啟後還是舊憑證且毫無錯誤訊息。
            with cm.write_lock:
                cm.load()
                gui_cfg = cm.config.setdefault("web_gui", {})
                tls = gui_cfg.setdefault("tls", {})
                tls["self_signed"] = False
                tls["cert_file"] = os.path.join(cert_dir, "ca_signed.pem")
                tls["key_file"] = os.path.join(cert_dir, "csr_key.pem")
                cm.save()
            return jsonify({
                "ok": True,
                "cert_info": cert_info,
                "cert_file": tls["cert_file"],
                "key_file": tls["key_file"],
                "message": t("gui_tls_saved_restart_hint", lang=lang),
            })
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except Exception as e:
            return _err_with_log("cert_import", e, lang=lang)

    return bp
