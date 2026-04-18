"""
Illumio Rule Scheduler — Core Engine
Ported from illumio_Rule-Scheduler/src/core.py, adapted for illumio_ops's ApiClient.
"""
import os
import re
import json
import datetime
from loguru import logger
from src.utils import Colors
from src.i18n import t

def _now_in_tz(tz_str: str) -> datetime.datetime:
    """Return current naive datetime in the configured schedule timezone."""
    import datetime as _dt
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    if not tz_str or tz_str == 'local':
        return _dt.datetime.now()
    if tz_str == 'UTC':
        return now_utc.replace(tzinfo=None)
    m = re.match(r'^UTC([+-])(\d+(?:\.\d+)?)$', tz_str)
    if m:
        offset = _dt.timedelta(hours=float(m.group(1) + m.group(2)))
        return (now_utc + offset).replace(tzinfo=None)
    return _dt.datetime.now()

def truncate(text, width):
    """Truncate text to width, stripping schedule tags."""
    if not text:
        return " " * width
    text = str(text).replace("\n", " ")
    text = re.sub(r'\[📅 .*?\]', '', text).strip()
    text = re.sub(r'\[⏳ .*?\]', '', text).strip()
    if not text:
        return "-"
    if len(text) > width:
        return text[:width - 3] + "..."
    return text.ljust(width)

def extract_id(href):
    """Extract the last segment from an Illumio HREF path."""
    return href.split('/')[-1] if href else ""

# ==========================================
# Schedule Database
# ==========================================
class ScheduleDB:
    """Manages the local JSON-based storage for configured rule schedules."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db = {}

    def load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    self.db = json.load(f)
            except Exception:
                self.db = {}
        else:
            self.db = {}
        return self.db

    def save(self):
        """Atomic write via tmp + os.replace."""
        tmp_path = self.db_path + ".tmp"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.db, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, self.db_path)
        except Exception:
            # Fallback: direct write
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(self.db, f, indent=4, ensure_ascii=False)

    def get_all(self):
        if not self.db:
            self.load()
        return self.db

    def get(self, href):
        return self.get_all().get(href)

    def put(self, href, data):
        self.get_all()[href] = data
        self.save()

    def delete(self, href):
        db = self.get_all()
        if href in db:
            del db[href]
            self.save()
            return True
        return False

    def get_schedule_type(self, rs):
        """0=no schedule, 1=self (ruleset only), 2=child rule scheduled (takes display priority)"""
        db_keys = list(self.get_all().keys())
        # Check child rules first — child schedule takes display priority over ruleset schedule
        for r in rs.get('rules', []):
            if r['href'] in db_keys:
                return 2
        # Prefix fallback: handles ruleset listings that don't include rules inline
        prefix = rs['href'].rstrip('/') + '/'
        if any(k.startswith(prefix) for k in db_keys):
            return 2
        # Check ruleset itself
        if rs['href'] in db_keys:
            return 1
        return 0

# ==========================================
# Schedule Engine (Core Logic)
# ==========================================
class ScheduleEngine:
    """Analyzes schedule timings and executes API enforcement actions upon matching."""

    DAY_MAP = {
        "mon": "monday", "tue": "tuesday", "wed": "wednesday",
        "thu": "thursday", "fri": "friday", "sat": "saturday", "sun": "sunday"
    }

    def __init__(self, db: ScheduleDB, api_client):
        self.db = db
        self.api = api_client

    @staticmethod
    def normalize_day(day_str: str) -> str:
        d = day_str.lower().strip()
        return ScheduleEngine.DAY_MAP.get(d[:3], d)

    def check(self, silent: bool = False, tz_str: str = 'local'):
        """Main scheduling loop: evaluate all schedules and toggle rules as needed.
        Returns list of log messages."""
        db_data = self.db.get_all()
        now = _now_in_tz(tz_str)
        curr_t = now.strftime("%H:%M")
        curr_d = now.strftime("%A").lower()
        prev_d = (now - datetime.timedelta(days=1)).strftime("%A").lower()

        logs = []

        def log(msg):
            logs.append(msg)
            if not silent:
                print(msg, flush=True)

        tz_label = tz_str if tz_str and tz_str != 'local' else 'Local'
        log(f"[{now.strftime('%Y-%m-%d %H:%M:%S')} {tz_label}] {t('rs_checking', default='Checking schedules...')}")

        expired_hrefs = []

        for href, c in list(db_data.items()):
            try:
                is_allow = (c.get('action', 'allow') == 'allow')
                in_window = False
                target = False

                # Use per-schedule timezone (fallback to global tz_str for backward compatibility)
                item_tz = c.get('timezone', tz_str)
                item_now = _now_in_tz(item_tz) if item_tz != tz_str else now
                item_curr_t = item_now.strftime("%H:%M")
                item_curr_d = item_now.strftime("%A").lower()
                item_prev_d = (item_now - datetime.timedelta(days=1)).strftime("%A").lower()

                if c['type'] == 'recurring':
                    days_list = [self.normalize_day(d) for d in c['days']]
                    day_match = item_curr_d in days_list
                    prev_day_match = item_prev_d in days_list
                    start_t, end_t = c['start'], c['end']

                    if start_t <= end_t:
                        # Normal window (e.g., 08:00-18:00)
                        in_window = day_match and (start_t <= item_curr_t < end_t)
                    else:
                        # Midnight wraparound (e.g., 22:00-06:00)
                        in_window = (day_match and item_curr_t >= start_t) or \
                                    (prev_day_match and item_curr_t < end_t)

                    target = in_window if is_allow else (not in_window)

                elif c['type'] == 'one_time':
                    expire_dt = datetime.datetime.fromisoformat(c['expire_at'])
                    if item_now > expire_dt:
                        log(f"{Colors.FAIL}[EXPIRED] {c['name']} (ID:{extract_id(href)}) {t('rs_expired', default='has expired.')}{Colors.ENDC}")
                        self.api.toggle_and_provision(href, False, c.get('is_ruleset'))
                        self.api.update_rule_note(href, "", remove=True)
                        expired_hrefs.append(href)
                        continue
                    else:
                        target = True

                # Check PCE state (draft check first, covering parent ruleset natively)
                if self.api.has_draft_changes(href):
                    name_str = c.get('detail_name', c['name'])
                    log(f"{Colors.FAIL}{t('rs_engine_skip_draft', name=name_str, id=extract_id(href))}{Colors.ENDC}")
                    continue

                # If no pending draft, check active state to determine toggle
                status, data = self.api.get_live_item(href)
                if status == 200 and data:
                    # Clear deleted flag if item was previously marked deleted but is now found
                    if c.get('pce_status') == 'deleted':
                        c['pce_status'] = 'active'
                        self.db.put(href, c)
                    curr_status = data.get('enabled')
                    if curr_status == target:
                        r_name = c.get('detail_name', c['name'])
                        log(f"[OK] {r_name} (ID:{extract_id(href)}) already in target state ({'enabled' if target else 'disabled'}), no action needed.")
                    else:
                        r_name = c.get('detail_name', c['name'])
                        status_str = f"{Colors.GREEN}Enabled{Colors.ENDC}" if target else f"{Colors.FAIL}Disabled{Colors.ENDC}"
                        log(f"[ACTION] {t('rs_toggle', default='Toggle')} -> {status_str} (ID: {Colors.CYAN}{extract_id(href)}{Colors.ENDC}) - {r_name}")
                        if self.api.toggle_and_provision(href, target, c.get('is_ruleset')):
                            log(f"{Colors.GREEN}[SUCCESS] {t('rs_provisioned', default='Provisioned successfully')}{Colors.ENDC}")
                        else:
                            log(f"{Colors.FAIL}[FAILED] Toggle/provision failed for {r_name} (ID:{extract_id(href)}){Colors.ENDC}")
                elif status == 404:
                    r_name = c.get('detail_name', c['name'])
                    log(f"{Colors.WARNING}{t('rs_target_not_found', name=r_name, id=extract_id(href), default='[SKIP] {name} (ID:{id}) not found on PCE (deleted?). No action taken.')}{Colors.ENDC}")
                    if c.get('pce_status') != 'deleted':
                        c['pce_status'] = 'deleted'
                        self.db.put(href, c)
                    continue
                else:
                    r_name = c.get('detail_name', c['name'])
                    log(f"{Colors.FAIL}[ERROR] API returned HTTP {status} for {r_name} (ID:{extract_id(href)}). Check PCE credentials/connectivity.{Colors.ENDC}")
            except Exception as _item_err:
                r_name = c.get('detail_name', c.get('name', href))
                log(f"{Colors.FAIL}[ERROR] Exception processing {r_name} (ID:{extract_id(href)}): {_item_err}{Colors.ENDC}")

        # Clean up expired one-time schedules
        for h in expired_hrefs:
            self.db.delete(h)
        if expired_hrefs:
            log(f"{Colors.WARNING}[CLEANUP] {t('rs_cleanup', default='Removed')} {len(expired_hrefs)} {t('rs_expired_schedules', default='expired schedule(s)')}.{Colors.ENDC}")

        return logs
