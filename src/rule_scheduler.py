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
from src.href_utils import extract_id  # canonical — also re-exported for rule_scheduler_cli.py
from src.tz_utils import resolve_tz

def _now_in_tz(tz_str: str) -> datetime.datetime:
    """Return current naive datetime in the configured schedule timezone.

    'local'/unset 保留原本的 aware-UTC fallback（避免 naive/DST 比較問題，
    A1 已鎖定 one_time 比較不得回歸）。'UTC'/'UTC±N'/IANA 名稱一律經
    tz_utils.resolve_tz 解析成 tzinfo，取該時區「真正」的當下牆鐘再去
    tzinfo——修正過去 IANA 名稱被靜默當成偏移 0 (UTC) 的問題。
    """
    if not tz_str or tz_str == 'local':
        return datetime.datetime.now(datetime.timezone.utc)  # UTC-aware fallback (avoids DST ambiguity)
    tz_obj = resolve_tz(tz_str)
    return datetime.datetime.now(tz_obj).replace(tzinfo=None)

_WEEKDAY_INDEX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def compute_next_trigger(schedules, now=None):
    """Return the nearest future trigger time across all schedules as an ISO
    string, or None if nothing is upcoming.

    Pure function — ``now`` (a naive wall-clock datetime) may be injected for
    deterministic testing. When omitted, each schedule is evaluated against the
    current wall-clock in its own timezone via ``_now_in_tz``.

    - recurring: the earliest ``start`` (HH:MM) on one of its ``days`` within the
      next 7 days (today-later counts; today-earlier rolls to next week).
    - one_time: its ``expire_at`` if still in the future; past one-times
      contribute nothing.
    """
    candidates = []
    for conf in (schedules or {}).values():
        stype = conf.get("type")
        item_tz = conf.get("timezone", "local")
        ref = now if now is not None else _now_in_tz(item_tz)
        # Compare on naive wall-clock to match the engine's _now_in_tz semantics.
        if ref.tzinfo is not None:
            ref = ref.replace(tzinfo=None)

        if stype == "recurring":
            days = conf.get("days") or []
            start = conf.get("start")
            if not days or not start:
                continue
            try:
                hh, mm = (int(x) for x in start.split(":"))
            except (ValueError, AttributeError):
                continue
            day_indices = {
                _WEEKDAY_INDEX[ScheduleEngine.normalize_day(d)]
                for d in days
                if ScheduleEngine.normalize_day(d) in _WEEKDAY_INDEX
            }
            if not day_indices:
                continue
            today = ref.replace(hour=hh, minute=mm, second=0, microsecond=0)
            for delta in range(0, 8):
                cand = today + datetime.timedelta(days=delta)
                if cand.weekday() in day_indices and cand > ref:
                    candidates.append(cand)
                    break

        elif stype == "one_time":
            expire_raw = conf.get("expire_at")
            if not expire_raw:
                continue
            try:
                expire_dt = datetime.datetime.fromisoformat(expire_raw)
            except (ValueError, TypeError):
                continue
            if expire_dt.tzinfo is not None:
                expire_dt = expire_dt.replace(tzinfo=None)
            if expire_dt > ref:
                candidates.append(expire_dt)

    if not candidates:
        return None
    return min(candidates).isoformat()


def _resolve_rule_state_file() -> str:
    """rule 排程執行狀態存 logs/state.json（與 report scheduler 同檔異 key）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "logs", "state.json")


_RULE_STATE_KEY = "rule_schedule_states"


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

# ==========================================
# Schedule Database
# ==========================================
class ScheduleDB:
    """Manages the local JSON-based storage for configured rule schedules."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db = {}

    def load(self):
        if not os.path.exists(self.db_path):
            self.db = {}
            return self.db
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"ScheduleDB root must be dict, got {type(data).__name__}")
            self.db = data
        except (json.JSONDecodeError, ValueError, OSError) as e:
            import time as _time
            corrupt_path = f"{self.db_path}.corrupt.{int(_time.time())}"
            try:
                os.rename(self.db_path, corrupt_path)
            except OSError as rename_err:
                logger.error(f"ScheduleDB load failed and quarantine rename also failed: {rename_err}")
            else:
                logger.error(f"ScheduleDB corrupt; quarantined to {corrupt_path}: {e}")
            raise ValueError(f"ScheduleDB corrupt: {e}") from e
        return self.db

    def save(self):
        """Atomic write via tmp + os.replace. Failure raises — no fallback."""
        tmp_path = self.db_path + ".tmp"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.db, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.db_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise  # NO fallback — atomic failure must surface to caller

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
        tick_states = {}

        for href, c in list(db_data.items()):
            now_z = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            tick_states[href] = {"last_checked": now_z}
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
                    # 正規化 aware/naive 再比較（同型修法見 report_scheduler.py:133-139
                    # 與 compute_next_trigger 的 strip）：item_now 在 tz='local' 時是
                    # aware UTC，expire_at 多半是 naive wall-clock，直接比較會丟
                    # TypeError，且該例外會被下方的 per-item except 吃掉。
                    if expire_dt.tzinfo is not None:
                        expire_dt = expire_dt.replace(tzinfo=None)
                    item_now_cmp = item_now.replace(tzinfo=None) if item_now.tzinfo is not None else item_now
                    if item_now_cmp > expire_dt:
                        log(f"{Colors.FAIL}[EXPIRED] {c['name']} (ID:{extract_id(href)}) {t('rs_expired', default='has expired.')}{Colors.ENDC}")
                        self.api.toggle_and_provision(href, False, c.get('is_ruleset'))
                        self.api.update_rule_note(href, "", remove=True)
                        expired_hrefs.append(href)
                        tick_states[href].update({"last_action": "expire", "last_result": "ok"})
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
                        action_label = "enable" if target else "disable"
                        if self.api.toggle_and_provision(href, target, c.get('is_ruleset')):
                            log(f"{Colors.GREEN}[SUCCESS] {t('rs_provisioned', default='Provisioned successfully')}{Colors.ENDC}")
                            tick_states[href].update({"last_action": action_label, "last_result": "ok"})
                        else:
                            log(f"{Colors.FAIL}[FAILED] Toggle/provision failed for {r_name} (ID:{extract_id(href)}){Colors.ENDC}")
                            tick_states[href].update({
                                "last_action": action_label, "last_result": "error",
                                "error": "Toggle/provision failed"[:300],
                            })
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
                tick_states[href]["last_result"] = "error"
                tick_states[href]["error"] = str(_item_err)[:300]

        # Clean up expired one-time schedules
        for h in expired_hrefs:
            self.db.delete(h)
        if expired_hrefs:
            log(f"{Colors.WARNING}[CLEANUP] {t('rs_cleanup', default='Removed')} {len(expired_hrefs)} {t('rs_expired_schedules', default='expired schedule(s)')}.{Colors.ENDC}")

        if tick_states:
            try:
                from src.state_store import update_state_file

                def _merge(data):
                    live_hrefs = set(self.db.get_all())
                    states = dict(data.get(_RULE_STATE_KEY) or {})
                    for h in list(states):
                        if h not in live_hrefs and h not in tick_states:
                            states.pop(h)
                    for h, st in tick_states.items():
                        cur = dict(states.get(h) or {})
                        cur.update(st)
                        states[h] = cur
                    data[_RULE_STATE_KEY] = states
                    return data

                update_state_file(_resolve_rule_state_file(), _merge)
            except Exception:
                logger.opt(exception=True).debug("rule schedule state persist failed")

        return logs
