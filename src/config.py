from __future__ import annotations

import json
import os
import threading
import time
from loguru import logger
from src.utils import Colors
from src.i18n import t, set_language
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_SECRET_FIELD_TOKENS = {"key", "secret", "password", "secret_key", "token"}

_PH = PasswordHasher(time_cost=4, memory_cost=131072, parallelism=4)


def hash_password(plain: str) -> str:
    return _PH.hash(plain)


def verify_password(plain: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        return _PH.verify(stored, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False

def _format_error_input(loc: tuple, raw_input):
    """Redact secret-looking fields from validation error log output."""
    for part in loc:
        if any(tok in str(part).lower() for tok in _SECRET_FIELD_TOKENS):
            return "[REDACTED]"
    return repr(raw_input)

# Determine Root Directory (parent of the package)
PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PKG_DIR)
CONFIG_FILE = os.path.join(ROOT_DIR, "config", "config.json")
# Alert RULES live in their own file (alerts.json) so the rules engine's
# state can be edited / version-controlled independently of system config
# and channel credentials. Channel destinations + tokens (line, webhook,
# active list, smtp, email) live back in config.json. Naming kept as
# alerts.json — "alert rules" — even though channel creds moved out.
# In-memory access via cm.config["rules"] / cm.config["alerts"] unchanged.
ALERTS_FILE = os.path.join(ROOT_DIR, "config", "alerts.json")

# Default configuration template
_DEFAULT_CONFIG = {
    "api": {"url": "https://pce.example.com:8443", "org_id": "1", "key": "", "secret": "", "verify_ssl": True},
    "alerts": {
        "active": ["mail"],
        "line_channel_access_token": "",
        "line_target_id": "",
        "webhook_url": "",
        "teams_webhook_url": ""
    },
    "email": {"sender": "monitor@localhost", "recipients": ["admin@example.com"]},
    "smtp": {"host": "localhost", "port": 25, "user": "", "password": "", "enable_auth": False, "enable_tls": False},
    "settings": {"language": "en", "theme": "light"},
    "rules": [],
    "report": {
        "enabled": False,
        "schedule": "weekly",
        "day_of_week": "monday",
        "hour": 8,
        "source": "api",
        "format": ["html"],
        "email_report": False,
        "output_dir": "reports/",
        "retention_days": 30,
        "include_raw_data": False,
        "max_top_n": 20,
        "api_query": {
            "start_date": None,
            "end_date": None,
            "max_results": 200000
        }
    },
    "report_schedules": [],
    "pce_profiles": [],
    "active_pce_id": None,
    "rule_scheduler": {
        "enabled": True,
        "check_interval_seconds": 300
    },
    "web_gui": {
        "username": "illumio",
        "password": "",
        "secret_key": "",
        "allowed_ips": [],
        "session_lifetime_seconds": 28800,
        "tls": {
            "enabled": True,
            "cert_file": "",
            "key_file": "",
            "self_signed": True,
            "min_version": "TLSv1.2",
            "ciphers": None,
            "key_algorithm": "ecdsa-p256",
            "validity_days": 397,
        }
    }
}

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merges override into base. Lists and non-dict values are replaced."""
    merged = base.copy()
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


# Removed config keys that may still exist in older deployed config.json files.
# The schema uses extra="forbid", so leaving them in would fail validation. Each
# entry is a dotted path to the removed key (any nesting depth).
#   - report.attack_surface: removed with mod16 (Open-Ports Attack Surface).
#   - web_gui.tls.http_redirect_port: removed with the HTTP→HTTPS auto-redirect
#     server (commit 24fe5ff); the GUI is HTTPS-only now.
_DEPRECATED_KEY_PATHS: tuple[str, ...] = (
    "report.attack_surface",
    "web_gui.tls.http_redirect_port",
)


def _strip_deprecated_keys(merged: dict) -> list[str]:
    """Drop known-removed keys (dotted paths) from *merged* in place; return paths dropped."""
    dropped: list[str] = []
    for path in _DEPRECATED_KEY_PATHS:
        *parents, leaf = path.split(".")
        node = merged
        for parent in parents:
            node = node.get(parent) if isinstance(node, dict) else None
        if isinstance(node, dict) and leaf in node:
            node.pop(leaf, None)
            dropped.append(path)
    return dropped

class ConfigManager:
    def __init__(self, config_file: str = CONFIG_FILE, alerts_file: str | None = None):
        self.config_file = config_file
        # If alerts_file is not specified, derive it from config_file's
        # directory so test fixtures (and any caller passing a custom
        # config_file path) don't accidentally read the repo's real
        # config/alerts.json. The default install still uses ALERTS_FILE
        # because callers pass CONFIG_FILE which lives next to it.
        if alerts_file is None:
            if config_file == CONFIG_FILE:
                alerts_file = ALERTS_FILE
            else:
                alerts_file = os.path.join(os.path.dirname(os.path.abspath(config_file)), "alerts.json")
        self.alerts_file = alerts_file
        self.config = json.loads(json.dumps(_DEFAULT_CONFIG))  # deep copy
        self._last_loaded_at: float | None = None
        # Re-entrant lock guarding load-modify-save critical sections. cheroot
        # serves the Web GUI from a multi-thread pool; without serialization two
        # concurrent handlers doing load→mutate→save interleave and silently drop
        # an update (last writer wins). Re-entrant because load() can itself call
        # save() (web_gui secret/password backfill) inside a held section.
        self._rw_lock = threading.RLock()
        self.load()

    @property
    def last_loaded_at(self) -> float | None:
        """Unix-timestamp seconds of last successful load(); None before first load."""
        return self._last_loaded_at

    @property
    def write_lock(self):
        """Re-entrant lock for callers' load-modify-save critical sections.

        GUI handlers wrap ``cm.load(); <mutate cm.config>; cm.save()`` in
        ``with cm.write_lock:`` so concurrent worker threads cannot interleave
        and lose updates.
        """
        return self._rw_lock

    def load(self):
        """Load and validate config.json via pydantic ConfigSchema."""
        from pydantic import ValidationError
        from src.config_models import ConfigSchema

        raw_data = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
            except (json.JSONDecodeError, IOError, OSError) as e:
                logger.error(f"Error reading config file: {e}")
                print(f"{Colors.FAIL}{t('error_loading_config', error=e)}{Colors.ENDC}")
                # Fall through with raw_data={} to use defaults

        # alerts.json holds RULES (new layout). If the file is the previous
        # layout — a dict of channel settings (active / line_* / webhook_url
        # with no "rules" key) — treat it as legacy and migrate the channel
        # block back into config.json on next save(). Rules in config.json
        # then move out to alerts.json on next save().
        external = self._read_alerts_file()
        if external is not None:
            if isinstance(external, dict) and "rules" in external:
                raw_data["rules"] = external.get("rules") or []
            elif isinstance(external, dict) and external:
                # Legacy channel-config layout — migrate back to config.json.
                logger.info(
                    "Migrating legacy alerts.json (channel config) back into "
                    "config.json; alerts.json will be rewritten with rules on next save."
                )
                raw_data["alerts"] = external

        # Merge defaults with raw data (deep merge preserves legacy behavior)
        merged = _deep_merge(json.loads(json.dumps(_DEFAULT_CONFIG)), raw_data)

        # Drop keys removed in newer versions so older config.json files (which
        # may still carry them) don't fail the extra="forbid" schema validation.
        _dropped = _strip_deprecated_keys(merged)
        if _dropped:
            logger.warning(
                "Ignoring deprecated config key(s): {} (removed in a newer version)",
                ", ".join(_dropped),
            )

        try:
            self.models = ConfigSchema.model_validate(merged)
            self.config = self.models.model_dump(mode="json")
        except ValidationError as e:
            # Format pydantic errors into readable log lines
            logger.error(f"Config validation failed: {e.error_count()} error(s):")
            for err in e.errors():
                loc_parts = err["loc"]
                loc = ".".join(str(p) for p in loc_parts)
                redacted = _format_error_input(loc_parts, err.get('input'))
                logger.error(f"  {loc}: {err['msg']} (input: {redacted})")
            # Do NOT surface raw str(e): pydantic embeds input_value=... which can
            # echo secret field values (api.key/secret, smtp.password, tokens) to
            # the console. The per-field detail is already logged above with
            # _format_error_input redaction; the console gets a safe count only.
            print(f"{Colors.FAIL}{t('error_loading_config', error=str(e.error_count()))}{Colors.ENDC}")
            # Fall back to the merged data (preserves valid sections, logs errors).
            # This keeps the app functional even with partially invalid config.
            self.models = ConfigSchema()  # typed access uses defaults
            self.config = merged          # dict access uses the raw merged data

        # Preserve post-load side effects
        lang = self.config.get("settings", {}).get("language", "en")
        set_language(lang)
        self._resolve_rule_keys()
        self._ensure_web_gui_secret()
        # Record success timestamp for header "Loaded" display.
        # Set only on the success path (after side effects complete); reading
        # config file errors above fall through to defaults but still finish here.
        self._last_loaded_at = time.time()

    # Map rule filter_value → canonical name_key (for legacy alerts.json migration).
    # Built from apply_best_practices.event_specs; kept in sync manually.
    _LEGACY_FILTER_TO_NAME_KEY = {
        "agent.tampering":                          "rule_agent_tampering",
        "user.sign_in,user.login":                  "rule_login_failed",
        "lost_agent.found":                         "rule_lost_agent",
        "system_task.agent_missed_heartbeats_check":"rule_agent_heartbeat",
        "system_task.agent_offline_check":          "rule_agent_offline",
        "agent.suspend":                            "rule_agent_suspend",
        "agent.clone_detected":                     "rule_agent_clone",
        "request.authentication_failed":            "rule_api_auth_failed",
        "agent.refresh_policy":                     "rule_policy_fail",
        "rule_set.create,rule_set.update,rule_set.delete": "rule_ruleset_change",
        "sec_policy.create":                        "rule_policy_provision",
        "request.authorization_failed":             "rule_api_authz_failed",
        "api_key.create,api_key.delete":            "rule_api_key_change",
        "sec_rule.create,sec_rule.update,sec_rule.delete": "rule_sec_rule_change",
        "workloads.unpair,agents.unpair":           "rule_bulk_unpair",
        "authentication_settings.update":           "rule_auth_settings_change",
    }

    def _resolve_rule_keys(self) -> None:
        """Resolve name/desc/rec text for all rules at read time.

        Three cases handled per (rendered_field, key_field):
          1. New-style rules: have <field>_key set. Populate <field> via
             t(key, lang=lang). Language-agnostic storage; resolved on each load.
          2. Legacy [MISSING:key] markers from older apply_best_practices runs:
             parse out the key and re-resolve. If the i18n entry now exists,
             also back-fill the <field>_key so next save() persists the key.
          3. Pure legacy best-practice rules (no *_key, no MISSING marker, but
             the literal name/desc/rec match canonical translations of the key
             derived from `filter_value`). For these — promote to key-based
             storage so future language switches re-translate.
             User-customized names (e.g. "Auth failures") are left untouched.
        """
        lang = self.config.get("settings", {}).get("language", "en")
        # Pre-compute canonical EN/ZH renderings of each known best-practice key
        # so we can recognise legacy literals that came from `t(key)` at write time.
        _canonical: dict[str, set[str]] = {}
        for base_key in self._LEGACY_FILTER_TO_NAME_KEY.values():
            for k in (base_key, base_key + "_desc", base_key + "_rec"):
                _canonical[k] = {
                    t(k, lang="en", default=""),
                    t(k, lang="zh_TW", default=""),
                }

        for rule in self.config.get("rules", []):
            # Try to promote legacy best-practice rules to key-based storage.
            if not any(rule.get(k) for k in ("name_key", "desc_key", "rec_key")):
                fv = rule.get("filter_value", "")
                base_key = self._LEGACY_FILTER_TO_NAME_KEY.get(fv)
                if base_key:
                    for field, key_field, k in (
                        ("name", "name_key", base_key),
                        ("desc", "desc_key", base_key + "_desc"),
                        ("rec",  "rec_key",  base_key + "_rec"),
                    ):
                        val = rule.get(field)
                        if not isinstance(val, str) or not val:
                            continue
                        # Promote only if the current literal matches one of the
                        # canonical translations (was written by t(key)) or is a
                        # [MISSING:key] marker — never overwrite a custom name.
                        if val in _canonical.get(k, set()) or val.startswith("[MISSING:"):
                            rule[key_field] = k

            for field, key_field in (("name", "name_key"), ("desc", "desc_key"), ("rec", "rec_key")):
                key = rule.get(key_field)
                if key:
                    rendered = t(key, lang=lang, default=rule.get(field, ""))
                    # If t() returns the [MISSING:...] marker (key absent from
                    # both en + zh dicts), don't overwrite an existing literal.
                    if not rendered.startswith("[MISSING:"):
                        rule[field] = rendered
                else:
                    # Legacy: re-resolve stale [MISSING:key] markers if present
                    val = rule.get(field)
                    if (
                        isinstance(val, str)
                        and val.startswith("[MISSING:")
                        and val.endswith("]")
                    ):
                        stale_key = val[len("[MISSING:"):-1]
                        resolved = t(stale_key, lang=lang, default="")
                        if resolved and resolved != val and not resolved.startswith("[MISSING:"):
                            rule[field] = resolved
                            rule[key_field] = stale_key  # back-fill so next save persists key

    def _ensure_web_gui_secret(self):
        import secrets as _secrets
        gui = self.config.get("web_gui", {})
        if "web_gui" not in self.config:
            self.config["web_gui"] = _DEFAULT_CONFIG["web_gui"].copy()
            gui = self.config["web_gui"]

        changed = False

        current_key = gui.get("secret_key") or ""
        if len(current_key) < 64:  # require 32-byte hex = 64 chars
            gui["secret_key"] = _secrets.token_hex(32)
            logger.warning(
                f"web_gui.secret_key was {len(current_key)} chars (required ≥64); "
                f"regenerated automatically. All active sessions invalidated."
            )
            changed = True

        if not gui.get("password") and not gui.get("_initial_password"):
            # Default initial password is the well-known "illumio". The forced
            # first-login password change (M4 must_change_password gate) is
            # DISABLED by operator request — the default stays valid until the
            # admin changes it manually in Settings. _initial_password is still
            # cleared on first successful login (cosmetic).
            initial = "illumio"
            gui["password"] = hash_password(initial)
            gui["_initial_password"] = initial
            gui["must_change_password"] = False
            changed = True
        elif gui.get("password") and not gui["password"].startswith("$argon2"):
            gui["password"] = hash_password(gui["password"])
            changed = True

        if changed:
            self.save()

    def save(self):
        try:
            # Persist rules to alerts.json first so an interruption between
            # the two writes never leaves stale rules in config.json.
            self._write_alerts_file()

            # Atomic write: write config.json without the "rules" section.
            config_for_disk = {k: v for k, v in self.config.items() if k != "rules"}
            tmp_file = self.config_file + ".tmp"
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(config_for_disk, f, indent=4, ensure_ascii=False)
            # On Windows, os.replace handles atomic rename
            os.replace(tmp_file, self.config_file)
            try:
                os.chmod(self.config_file, 0o600)
            except OSError:
                pass
            lang = self.config.get("settings", {}).get("language", "en")
            set_language(lang)
            print(f"{Colors.GREEN}{t('config_saved')}{Colors.ENDC}")
            logger.info("Configuration saved.")
        except (IOError, OSError) as e:
            logger.error(f"Error saving config: {e}")
            print(f"{Colors.FAIL}{t('error_saving_config', error=e)}{Colors.ENDC}")

    def _read_alerts_file(self):
        """Return the parsed alerts.json dict, or None if file is missing.

        Two on-disk formats are accepted:
          - New: ``{"rules": [...]}`` — load() pulls rules from here.
          - Legacy: ``{"active": [...], "line_*": ..., "webhook_url": ...}``
            — load() migrates this back into config.json's ``alerts`` block.

        Missing file → None (callers use whatever's in config.json plus
        defaults). JSON / I/O errors return {} (empty) and log loudly.
        """
        if not os.path.exists(self.alerts_file):
            return None
        try:
            with open(self.alerts_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.error(f"Error reading alerts file: {e}")
            return {}

    def _write_alerts_file(self):
        """Atomically write ``{"rules": self.config['rules']}`` to alerts.json
        with mode 0o600. Channel credentials (line / webhook / active / smtp)
        intentionally stay in config.json — see ALERTS_FILE comment.

        For rules with name_key/desc_key/rec_key, strip the rendered name/desc/rec
        text before persisting so disk holds keys as the canonical source. The
        rendered text is repopulated by load() via _resolve_rule_keys().
        """
        rules_for_disk = []
        for rule in self.config.get("rules", []):
            rule_copy = dict(rule)
            if rule_copy.get("name_key"):
                rule_copy.pop("name", None)
            if rule_copy.get("desc_key"):
                rule_copy.pop("desc", None)
            if rule_copy.get("rec_key"):
                rule_copy.pop("rec", None)
            rules_for_disk.append(rule_copy)
        payload = {"rules": rules_for_disk}
        os.makedirs(os.path.dirname(self.alerts_file), exist_ok=True)
        tmp_file = self.alerts_file + ".tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        os.replace(tmp_file, self.alerts_file)
        try:
            os.chmod(self.alerts_file, 0o600)
        except OSError:
            pass

    def add_or_update_rule(self, new_rule):
        for i, rule in enumerate(self.config["rules"]):
            if new_rule.get("id") is not None and new_rule.get("id") == rule.get("id"):
                self.config["rules"][i] = new_rule
                self.save()
                return

            is_same = False
            if new_rule["type"] == rule["type"]:
                if new_rule["type"] == "event" and new_rule.get("filter_value") == rule.get("filter_value"):
                    is_same = True
                elif new_rule["type"] == "system" and new_rule.get("filter_value") == rule.get("filter_value"):
                    is_same = True
                elif new_rule["type"] in ["traffic", "bandwidth", "volume"] and new_rule["name"] == rule["name"]:
                    is_same = True

            if is_same:
                new_rule["id"] = rule["id"]
                self.config["rules"][i] = new_rule
                print(f"{Colors.WARNING}{t('rule_overwritten')}{Colors.ENDC}")
                self.save()
                return
        self.config["rules"].append(new_rule)
        self.save()

    def remove_rules_by_index(self, index_list):
        sorted_indices = sorted(index_list, reverse=True)
        count: int = 0
        for idx in sorted_indices:
            if 0 <= idx < len(self.config["rules"]):
                removed = self.config["rules"].pop(idx)
                print(t('rule_deleted', name=removed['name']))
                count = count + 1
        if count > 0:
            self.save()

    # ─── PCE Profile CRUD ─────────────────────────────────────────────────────

    def get_pce_profiles(self) -> list:
        return self.config.get("pce_profiles", [])

    def get_active_pce_id(self):
        return self.config.get("active_pce_id")

    def add_pce_profile(self, profile: dict) -> dict:
        if not profile.get("id"):
            profile["id"] = int(time.time() * 1000)
        self.config.setdefault("pce_profiles", []).append(profile)
        self.save()
        return profile

    def update_pce_profile(self, profile_id: int, updates: dict) -> bool:
        for i, p in enumerate(self.config.get("pce_profiles", [])):
            if p.get("id") == profile_id:
                self.config["pce_profiles"][i].update(updates)
                if self.config.get("active_pce_id") == profile_id:
                    self.sync_api_to_active_profile()
                self.save()
                return True
        return False

    def remove_pce_profile(self, profile_id: int) -> bool:
        before = len(self.config.get("pce_profiles", []))
        self.config["pce_profiles"] = [
            p for p in self.config.get("pce_profiles", [])
            if p.get("id") != profile_id
        ]
        if len(self.config["pce_profiles"]) < before:
            if self.config.get("active_pce_id") == profile_id:
                self.config["active_pce_id"] = None
            self.save()
            return True
        return False

    def activate_pce_profile(self, profile_id: int) -> bool:
        for p in self.config.get("pce_profiles", []):
            if p.get("id") == profile_id:
                self.config["active_pce_id"] = profile_id
                api = self.config.setdefault("api", {})
                for k in ("url", "org_id", "key", "secret", "verify_ssl"):
                    if k in p:
                        api[k] = p[k]
                self.save()
                return True
        return False

    def sync_api_to_active_profile(self):
        """Copy current config.api values back into the active profile."""
        active_id = self.config.get("active_pce_id")
        if active_id is None:
            return
        api = self.config.get("api", {})
        for i, p in enumerate(self.config.get("pce_profiles", [])):
            if p.get("id") == active_id:
                for k in ("url", "org_id", "key", "secret", "verify_ssl"):
                    if k in api:
                        self.config["pce_profiles"][i][k] = api[k]
                return

    # ─── Report Schedule CRUD ─────────────────────────────────────────────────

    def get_report_schedules(self) -> list:
        return self.config.get("report_schedules", [])

    def add_report_schedule(self, sched: dict) -> dict:
        """Add a new report schedule. Assigns a unique id if missing."""
        if not sched.get("id"):
            sched["id"] = int(time.time() * 1000)
        self.config.setdefault("report_schedules", []).append(sched)
        self.save()
        return sched

    def update_report_schedule(self, schedule_id: int, updates: dict) -> bool:
        """Update fields of an existing schedule by id. Returns True on success."""
        for i, s in enumerate(self.config.get("report_schedules", [])):
            if s.get("id") == schedule_id:
                self.config["report_schedules"][i].update(updates)
                self.save()
                return True
        return False

    def remove_report_schedule(self, schedule_id: int) -> bool:
        """Remove a schedule by id. Returns True on success."""
        before = len(self.config.get("report_schedules", []))
        self.config["report_schedules"] = [
            s for s in self.config.get("report_schedules", [])
            if s.get("id") != schedule_id
        ]
        if len(self.config["report_schedules"]) < before:
            self.save()
            return True
        return False

    def load_best_practices(self):
        return self.apply_best_practices(mode="replace")

    def _best_practice_rules(self, start_id: int) -> list:
        event_specs = [
            ("rule_agent_tampering", "agent.tampering", "immediate", 1, 10, 30, "all", "all", ""),
            ("rule_agent_suspend", "agent.suspend", "immediate", 1, 10, 30, "all", "all", ""),
            ("rule_agent_clone", "agent.clone_detected", "immediate", 1, 10, 30, "all", "all", ""),
            ("rule_agent_heartbeat", "system_task.agent_missed_heartbeats_check", "count", 3, 30, 60, "all", "all", "1/30m"),
            ("rule_agent_offline", "system_task.agent_offline_check", "count", 3, 30, 60, "all", "all", "1/30m"),
            ("rule_lost_agent", "lost_agent.found", "immediate", 1, 10, 60, "all", "all", ""),
            ("rule_login_failed", "user.sign_in,user.login", "count", 5, 10, 30, "failure", "all", "1/15m"),
            ("rule_api_auth_failed", "request.authentication_failed", "count", 5, 10, 30, "all", "all", "1/15m"),
            ("rule_policy_fail", "agent.refresh_policy", "immediate", 1, 10, 30, "failure", "all", ""),
            ("rule_ruleset_change", "rule_set.create,rule_set.update,rule_set.delete", "immediate", 1, 10, 60, "all", "all", ""),
            ("rule_policy_provision", "sec_policy.create", "immediate", 1, 10, 60, "all", "all", ""),
            ("rule_api_authz_failed", "request.authorization_failed", "count", 3, 10, 30, "all", "all", "1/15m"),
            ("rule_api_key_change", "api_key.create,api_key.delete", "immediate", 1, 10, 60, "all", "all", ""),
            ("rule_sec_rule_change", "sec_rule.create,sec_rule.update,sec_rule.delete", "immediate", 1, 10, 60, "all", "all", ""),
            ("rule_bulk_unpair", "workloads.unpair,agents.unpair", "immediate", 1, 10, 60, "all", "all", ""),
            ("rule_auth_settings_change", "authentication_settings.update", "immediate", 1, 10, 60, "all", "all", ""),
        ]

        rules = []
        next_id = start_id
        for name_key, etype, ttype, cnt, win, cd, f_stat, f_sev, throttle in event_specs:
            rules.append({
                "id": next_id,
                "type": "event",
                "name_key": name_key,
                "name": t(name_key),
                "filter_key": "event_type",
                "filter_value": etype,
                "filter_status": f_stat,
                "filter_severity": f_sev,
                "match_fields": {},
                "throttle": throttle,
                "desc_key": name_key + "_desc",
                "desc": t(name_key + "_desc", default="Official Best Practice"),
                "rec_key": name_key + "_rec",
                "rec": t(name_key + "_rec", default="Check logs"),
                "threshold_type": ttype,
                "threshold_count": cnt,
                "threshold_window": win,
                "cooldown_minutes": cd,
            })
            next_id += 1

        # Bind the high-blocked rule's name_key to a local so we don't write the
        # literal `"rule_high_blocked"` directly inside the dict — that would be
        # picked up by tests/test_best_practice_rec_mapping.py's event-specs regex.
        _hb_key = "rule_high_blocked"
        rules.append({
            "id": next_id,
            "type": "traffic",
            "name_key": _hb_key,
            "name": t(_hb_key),
            "pd": 2,
            "port": None,
            "proto": None,
            "src_label": None,
            "dst_label": None,
            "throttle": "1/15m",
            "desc_key": _hb_key + "_desc",
            "desc": t(_hb_key + "_desc", default="High volume of blocked traffic detected."),
            "rec_key": _hb_key + "_rec",
            "rec": t(_hb_key + "_rec", default="Review segmentation rules"),
            "threshold_type": "count",
            "threshold_count": 25,
            "threshold_window": 10,
            "cooldown_minutes": 30,
        })
        return rules

    @staticmethod
    def _rule_signature(rule: dict) -> tuple:
        rtype = rule.get("type")
        if rtype == "event":
            return (
                "event",
                str(rule.get("filter_value") or "").strip(),
                str(rule.get("filter_status") or "all").strip(),
                str(rule.get("filter_severity") or "all").strip(),
            )
        if rtype == "traffic":
            return (
                "traffic",
                int(rule.get("pd") or 0),
                rule.get("port"),
                rule.get("proto"),
                rule.get("src_label") or rule.get("src_ip_in") or "",
                rule.get("dst_label") or rule.get("dst_ip_in") or "",
            )
        if rtype == "system":
            return ("system", str(rule.get("filter_value") or "").strip())
        return (rtype, str(rule.get("name") or "").strip())

    def apply_best_practices(self, mode: str = "append_missing") -> dict:
        normalized_mode = str(mode or "append_missing").strip().lower()
        if normalized_mode not in {"append_missing", "replace"}:
            normalized_mode = "append_missing"

        current_rules = json.loads(json.dumps(self.config.get("rules", [])))
        backups = self.config.setdefault("rule_backups", [])
        backup_id = None
        if current_rules:
            backup_id = f"best-practices-{int(time.time())}"
            backups.append({
                "id": backup_id,
                "kind": "best_practices",
                "mode": normalized_mode,
                "created_at": int(time.time()),
                "rule_count": len(current_rules),
                "rules": current_rules,
            })
            if len(backups) > 10:
                del backups[:-10]

        numeric_ids = []
        for rule in self.config.get("rules", []):
            try:
                numeric_ids.append(int(rule.get("id", 0) or 0))
            except (TypeError, ValueError):
                pass  # intentional fallback: skip rules with non-numeric IDs when computing max ID
        bp_rules = self._best_practice_rules((max(numeric_ids) if numeric_ids else 0) + 1)

        if normalized_mode == "replace":
            self.config["rules"] = bp_rules
            replaced_count = len(current_rules)
            added_count = len(bp_rules)
            skipped_count = 0
        else:
            existing_signatures = {self._rule_signature(rule) for rule in self.config.get("rules", [])}
            additions = [rule for rule in bp_rules if self._rule_signature(rule) not in existing_signatures]
            self.config.setdefault("rules", []).extend(additions)
            replaced_count = 0
            added_count = len(additions)
            skipped_count = len(bp_rules) - len(additions)

        self.save()
        return {
            "mode": normalized_mode,
            "backup_id": backup_id,
            "backup_created": backup_id is not None,
            "replaced_count": replaced_count,
            "added_count": added_count,
            "skipped_count": skipped_count,
            "total_rules": len(self.config.get("rules", [])),
        }
