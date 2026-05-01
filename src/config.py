import json
import os
import time
from loguru import logger
from src.utils import Colors
from src.i18n import t, set_language
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_SECRET_FIELD_TOKENS = {"key", "secret", "password", "secret_key", "token"}

_PH = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


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
# Alerts (notification destinations + tokens) live in their own file so
# that secret values can be rotated/locked-down independently of the
# system config. In-memory access via cm.config["alerts"] is unchanged.
ALERTS_FILE = os.path.join(ROOT_DIR, "config", "alerts.json")

# Default configuration template
_DEFAULT_CONFIG = {
    "api": {"url": "https://pce.example.com:8443", "org_id": "1", "key": "", "secret": "", "verify_ssl": True},
    "alerts": {
        "active": ["mail"],
        "line_channel_access_token": "",
        "line_target_id": "",
        "webhook_url": ""
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
        "tls": {
            "enabled": True,
            "cert_file": "",
            "key_file": "",
            "self_signed": False,
            "min_version": "TLSv1.2",
            "ciphers": None,
            "key_algorithm": "ecdsa-p256",
            "validity_days": 397,
            "http_redirect_port": 80,
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
        self.load()

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

        # Alerts live in their own file. If alerts.json exists, it wins;
        # otherwise inherit any "alerts" still present in config.json (so
        # an existing single-file install migrates transparently — the
        # next save() will write alerts.json and strip from config.json).
        alerts_data = self._read_alerts_file()
        if alerts_data is not None:
            raw_data["alerts"] = alerts_data

        # Merge defaults with raw data (deep merge preserves legacy behavior)
        merged = _deep_merge(json.loads(json.dumps(_DEFAULT_CONFIG)), raw_data)

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
            print(f"{Colors.FAIL}{t('error_loading_config', error=str(e)[:200])}{Colors.ENDC}")
            # Fall back to the merged data (preserves valid sections, logs errors).
            # This keeps the app functional even with partially invalid config.
            self.models = ConfigSchema()  # typed access uses defaults
            self.config = merged          # dict access uses the raw merged data

        # Preserve post-load side effects
        lang = self.config.get("settings", {}).get("language", "en")
        set_language(lang)
        self._ensure_web_gui_secret()

    def _ensure_web_gui_secret(self):
        import secrets as _secrets
        gui = self.config.get("web_gui", {})
        if "web_gui" not in self.config:
            self.config["web_gui"] = _DEFAULT_CONFIG["web_gui"].copy()
            gui = self.config["web_gui"]

        changed = False

        if not gui.get("secret_key"):
            gui["secret_key"] = _secrets.token_hex(32)
            changed = True

        if not gui.get("password") and not gui.get("_initial_password"):
            # Default initial password is the well-known "illumio". The
            # must_change_password gate (M4) forces a change on first login,
            # so this fixed default is only ever valid for the very first
            # session. _initial_password is also cleared on first successful
            # login so the password ceases to be discoverable from disk.
            initial = "illumio"
            gui["password"] = hash_password(initial)
            gui["_initial_password"] = initial
            gui["must_change_password"] = True
            changed = True
        elif gui.get("password") and not gui["password"].startswith("$argon2"):
            gui["password"] = hash_password(gui["password"])
            changed = True

        if changed:
            self.save()

    def save(self):
        try:
            # Persist alerts to its own file first so an interruption between
            # the two writes never leaves stale alerts in config.json.
            self._write_alerts_file()

            # Atomic write: write config.json without the "alerts" section.
            config_for_disk = {k: v for k, v in self.config.items() if k != "alerts"}
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
        """Return alerts dict from alerts.json, or None if file is missing.

        Missing file is the migration trigger: callers fall back to whatever
        "alerts" still lives in config.json, then the next save() splits it
        out. JSON / I/O errors return {} (empty alerts) and log loudly so
        the user sees the corruption rather than silently using defaults.
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
        """Atomically write self.config['alerts'] to alerts.json with 0o600."""
        alerts = self.config.get("alerts", {})
        os.makedirs(os.path.dirname(self.alerts_file), exist_ok=True)
        tmp_file = self.alerts_file + ".tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(alerts, f, indent=4, ensure_ascii=False)
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
                "name": t(name_key),
                "filter_key": "event_type",
                "filter_value": etype,
                "filter_status": f_stat,
                "filter_severity": f_sev,
                "match_fields": {},
                "throttle": throttle,
                "desc": t(name_key + "_desc", default="Official Best Practice"),
                "rec": t(name_key + "_rec", default="Check logs"),
                "threshold_type": ttype,
                "threshold_count": cnt,
                "threshold_window": win,
                "cooldown_minutes": cd,
            })
            next_id += 1

        rules.append({
            "id": next_id,
            "type": "traffic",
            "name": t("rule_high_blocked"),
            "pd": 2,
            "port": None,
            "proto": None,
            "src_label": None,
            "dst_label": None,
            "throttle": "1/15m",
            "desc": t("rule_high_blocked_desc", default="High volume of blocked traffic detected."),
            "rec": t("rule_high_blocked_rec", default="Review segmentation rules"),
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
