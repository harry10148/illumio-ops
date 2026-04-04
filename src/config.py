import json
import os
import time
import logging
from src.utils import Colors
from src.i18n import t, set_language

logger = logging.getLogger(__name__)

# Determine Root Directory (parent of the package)
PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PKG_DIR)
CONFIG_FILE = os.path.join(ROOT_DIR, "config", "config.json")

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
    "settings": {"enable_health_check": True, "language": "en", "theme": "light"},
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
        "enabled": False,
        "check_interval_seconds": 300
    },
    "web_gui": {
        "username": "admin",
        "password_hash": "",
        "password_salt": "",
        "secret_key": "",
        "allowed_ips": []
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
    def __init__(self, config_file: str = CONFIG_FILE):
        self.config_file = config_file
        self.config = json.loads(json.dumps(_DEFAULT_CONFIG))  # deep copy
        self.load()

    def load(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.config = _deep_merge(self.config, data)
            except (json.JSONDecodeError, IOError, OSError) as e:
                logger.error(f"Error loading config: {e}")
                print(f"{Colors.FAIL}{t('error_loading_config', error=e)}{Colors.ENDC}")
            finally:
                lang = self.config.get("settings", {}).get("language", "en")
                set_language(lang)
                self._ensure_web_gui_secret()

    def _ensure_web_gui_secret(self):
        gui = self.config.get("web_gui", {})
        if "web_gui" not in self.config:
            self.config["web_gui"] = _DEFAULT_CONFIG["web_gui"].copy()
            gui = self.config["web_gui"]
            
        changed = False
        import secrets
        import hashlib
        
        if not gui.get("secret_key"):
            gui["secret_key"] = secrets.token_hex(32)
            changed = True
            
        if not gui.get("password_hash"):
            salt = secrets.token_hex(8)
            gui["username"] = "illumio"
            gui["password_salt"] = salt
            gui["password_hash"] = hashlib.sha256((salt + "illumio").encode('utf-8')).hexdigest()
            changed = True
            
        if changed:
            self.save()

    def save(self):
        try:
            # Atomic write: write to temp file first, then rename
            tmp_file = self.config_file + ".tmp"
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            # On Windows, os.replace handles atomic rename
            os.replace(tmp_file, self.config_file)
            lang = self.config.get("settings", {}).get("language", "en")
            set_language(lang)
            print(f"{Colors.GREEN}{t('config_saved')}{Colors.ENDC}")
            logger.info("Configuration saved.")
        except (IOError, OSError) as e:
            logger.error(f"Error saving config: {e}")
            print(f"{Colors.FAIL}{t('error_saving_config', error=e)}{Colors.ENDC}")

    def add_or_update_rule(self, new_rule):
        for i, rule in enumerate(self.config["rules"]):
            is_same = False
            if new_rule["type"] == rule["type"]:
                if new_rule["type"] == "event" and new_rule.get("filter_value") == rule.get("filter_value"):
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
        print(f"{Colors.BLUE}{t('loading_best_practices')}{Colors.ENDC}")
        self.config["rules"] = []
        ts = int(time.time())
        # type, name, threshold_type, threshold_count, threshold_window, cooldown_minutes, filter_status, filter_severity
        # Note: ACTION_EVENTS (user/API-initiated) support filter_status; DISCOVERY_EVENTS (system-generated) do not.
        bps = [
            # ── Agent Security ──────────────────────────────────────────────────────
            ("rule_agent_tampering",  "agent.tampering",          "immediate", 1,  10, 30,  "all",     "all"),
            ("rule_agent_suspend",    "agent.suspend",            "immediate", 1,  10, 30,  "all",     "all"),
            ("rule_agent_clone",      "agent.clone_detected",     "immediate", 1,  10, 30,  "all",     "all"),
            # ── Agent Health ────────────────────────────────────────────────────────
            ("rule_agent_heartbeat",  "system_task.agent_missed_heartbeats_check", "count", 3, 30, 60, "all", "all"),
            ("rule_agent_offline",    "system_task.agent_offline_check",           "count", 3, 30, 60, "all", "all"),
            ("rule_lost_agent",       "lost_agent.found",         "immediate", 1,  10, 60,  "all",     "all"),
            # ── User & API Auth (support status filter) ─────────────────────────────
            ("rule_login_failed",     "user.sign_in,user.login",  "count",     5,  10, 30,  "failure", "all"),
            ("rule_api_auth_failed",  "request.authentication_failed", "count", 5, 10, 30,  "all",     "all"),
            # ── Policy & Enforcement ─────────────────────────────────────────────────
            ("rule_policy_fail",      "agent.refresh_policy",     "immediate", 1,  10, 30,  "failure", "all"),
            ("rule_ruleset_change",   "rule_set.create,rule_set.update,rule_set.delete", "immediate", 1, 10, 60, "all", "all"),
            ("rule_policy_provision", "sec_policy.create",        "immediate", 1,  10, 60,  "all",     "all"),
            # ── API & Auth ───────────────────────────────────────────────────────────
            ("rule_api_authz_failed",       "request.authorization_failed",                    "count",     3,  10, 30, "all", "all"),
            ("rule_api_key_change",         "api_key.create,api_key.delete",                   "immediate", 1,  10, 60, "all", "all"),
            # ── Policy Security ───────────────────────────────────────────────────────
            ("rule_sec_rule_change",        "sec_rule.create,sec_rule.update,sec_rule.delete", "immediate", 1,  10, 60, "all", "all"),
            ("rule_bulk_unpair",            "workloads.unpair,agents.unpair",                  "immediate", 1,  10, 60, "all", "all"),
            ("rule_auth_settings_change",   "authentication_settings.update",                  "immediate", 1,  10, 60, "all", "all"),
        ]

        for i, (name_key, etype, ttype, cnt, win, cd, f_stat, f_sev) in enumerate(bps):
            self.config["rules"].append({
                "id": ts + i, "type": "event", "name": t(name_key),
                "filter_key": "event_type", "filter_value": etype,
                "filter_status": f_stat, "filter_severity": f_sev,
                "desc": t(name_key + "_desc", default="Official Best Practice"),
                "rec": t(name_key + "_rec", default="Check logs"),
                "threshold_type": ttype, "threshold_count": cnt,
                "threshold_window": win, "cooldown_minutes": cd
            })
            
        self.config["rules"].append({
            "id": ts + 100, "type": "traffic", "name": t("rule_high_blocked"), "pd": 2,
            "port": None, "proto": None, "src_label": None, "dst_label": None,
            "desc": t("rule_high_blocked_desc", default="High volume of blocked traffic detected."),
            "rec": t("rule_high_blocked_rec", default="Review segmentation rules"),
            "threshold_type": "count", "threshold_count": 25,
            "threshold_window": 10, "cooldown_minutes": 30
        })
        self.save()
