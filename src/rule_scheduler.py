"""
Illumio Rule Scheduler — Core Engine
Ported from illumio_Rule-Scheduler/src/core.py, adapted for illumio_ops's ApiClient.
"""
import os
import re
import json
import datetime
import tempfile
import threading
from loguru import logger
from src.file_lock import file_lock
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

# 純 last_checked 心跳的落盤節流（秒）：有動作/錯誤/成員變動照舊立即寫
_CHECK_PERSIST_GAP_S = 900


def truncate(text, width):
    """Truncate text to width, stripping schedule tags."""
    if not text:
        return " " * width
    text = str(text).replace("\n", " ")
    text = re.sub(r'\[📅 .*?\]', '', text).strip()
    text = re.sub(r'\[⏳ .*?\]', '', text).strip()
    text = re.sub(r'\[⏰ .*?\]', '', text).strip()
    if not text:
        return "-"
    if len(text) > width:
        return text[:width - 3] + "..."
    return text.ljust(width)

# ==========================================
# Schedule Database
# ==========================================

# ScheduleDB 寫入序列化：ScheduleDB 是「整檔覆寫」（load→改記憶體 dict→save
# 全量重寫 rule_schedules.json），本身無跨 instance 鎖，而每個寫入者都各自新
# 建 instance——任何兩個寫入者交錯，後存檔的一方會用自己「開始時」的過期快照
# 整檔蓋掉前者（新建的 schedule 憑空消失、到期已刪的 one_time 復活）。
#
# 這把鎖住在 ScheduleDB 所在模組而非 GUI blueprint，因為 `--monitor-gui`
# （正式部署模式）把 APScheduler 跑在背景 thread、Flask 跑在主 thread，
# **同一個行程**：排程器 tick 的 engine.check 與 GUI route 是真正的併發寫入
# 者，必須共用同一把鎖才有意義。所有寫入一律：持鎖 → 鎖內 load() 重讀 →
# 改動 → save。
#
# 用 RLock：GUI 端有「持鎖後再呼叫下面 helper」的巢狀用法。
#
# 這把鎖只擋得住同一行程的 thread。真正的第三個寫入者是**獨立行程**的
# src/rule_scheduler_cli.py（互動式選單，快照可留數分鐘）——它連 _rs_db_lock
# 都拿不到。因此 ScheduleDB 自己再上一層跨行程檔案鎖（file_lock），且
# put()/delete() 一律「鎖內重讀 → 只套用這一筆 → 寫回」，讓任何寫入者的
# 過期快照都不可能整檔蓋掉別人的變更。
_rs_db_lock = threading.RLock()


def _rs_db_set_status(db, href, status):
    """pce_status 對帳寫回：鎖內 re-load 後只改該 entry 的 pce_status。
    條目已被併發刪除時直接略過——不得用過期快照把它復活。"""
    with _rs_db_lock, file_lock(db.lock_path):
        db.load()
        fresh = db.db.get(href)
        if fresh is not None and fresh.get('pce_status') != status:
            fresh['pce_status'] = status
            db.save()


def _rs_db_delete(db, href):
    """鎖內 re-load 後刪除單一條目，避免用過期快照整檔覆寫掉併發新增的排程。
    實作已下沉到 ScheduleDB.delete()（同時涵蓋 CLI 這個獨立行程的寫入者）。"""
    return db.delete(href)


class ScheduleDB:
    """Manages the local JSON-based storage for configured rule schedules."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db = {}
        # 跨行程鎖檔：GUI/排程器（同一行程）與 rule_scheduler_cli（另一行程）
        # 都寫這個檔案，只靠 _rs_db_lock 擋不到後者。
        self.lock_path = os.path.abspath(db_path) + ".lock"

    def load(self):
        with file_lock(self.lock_path):
            return self._load_unlocked()

    def _load_unlocked(self):
        if not os.path.exists(self.db_path):
            self.db = {}
            return self.db
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                raw = f.read()
        except OSError as e:
            # 讀取失敗（EACCES / EMFILE / EIO …）不等於「內容壞掉」：位元組根本
            # 沒被讀進來。若比照 parse 失敗把檔案 rename 走，之後每次 load 都會
            # 走「檔案不存在 → {}」，所有排程永久消失（到期的 one_time 規則留在
            # PCE 上 enabled、註記還掛著）。比照 ConfigManager._load_impl：
            # fail closed，檔案原封不動。
            logger.error(f"ScheduleDB read failed ({e}); file left untouched")
            raise
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError(f"ScheduleDB root must be dict, got {type(data).__name__}")
            self.db = data
        except (json.JSONDecodeError, ValueError) as e:
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
        """Atomic write via unique tmp + os.replace. Failure raises — no fallback."""
        with file_lock(self.lock_path):
            # mkstemp：固定的 "<db>.tmp" 是**共用檔名**，兩個行程同時存檔時後者
            # 的 'w' 會截斷前者正在寫的同一個 inode，兩份輸出交錯後被 os.replace
            # 裝進正式路徑，下次 load() 就把它當 corrupt 隔離掉（＝全部排程遺失）。
            # 比照 config.py / state_store.py 改用每個寫入者專屬的暫存檔。
            db_dir = os.path.dirname(os.path.abspath(self.db_path)) or "."
            os.makedirs(db_dir, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=db_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
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
        """單筆寫入：鎖內重讀磁碟後只套用這一筆。

        呼叫端（GUI route、rule_scheduler_cli 互動式選單）手上的 self.db 可能是
        數分鐘前的快照；直接整檔覆寫會刪掉這期間其他寫入者新增的排程。
        """
        with _rs_db_lock, file_lock(self.lock_path):
            self._load_unlocked()
            self.db[href] = data
            self.save()

    def delete(self, href):
        """單筆刪除：同 put()，鎖內重讀後只移除這一筆。"""
        with _rs_db_lock, file_lock(self.lock_path):
            self._load_unlocked()
            if href in self.db:
                del self.db[href]
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
                        expire_ok = self.api.toggle_and_provision(href, False, c.get('is_ruleset'))
                        if expire_ok:
                            # 只有 disable 成功才移除排程並清 note——失敗時保留排程，
                            # 下 tick 重試，否則規則留在 PCE enabled 卻被 scheduler
                            # 遺忘（2026-07-24 審查 BUG-1，安全相關）
                            self.api.update_rule_note(href, "", remove=True)
                            expired_hrefs.append(href)
                            tick_states[href].update({"last_action": "expire", "last_result": "ok"})
                        else:
                            tick_states[href].update({
                                "last_action": "expire", "last_result": "error",
                                "error": "toggle_and_provision failed",
                            })
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
                        _rs_db_set_status(self.db, href, 'active')
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
                        _rs_db_set_status(self.db, href, 'deleted')
                    continue
                else:
                    r_name = c.get('detail_name', c['name'])
                    log(f"{Colors.FAIL}[ERROR] API returned HTTP {status} for {r_name} (ID:{extract_id(href)}). Check PCE credentials/connectivity.{Colors.ENDC}")
                    tick_states[href].update({"last_result": "error", "error": f"HTTP {status}"[:300]})
            except Exception as _item_err:
                r_name = c.get('detail_name', c.get('name', href))
                log(f"{Colors.FAIL}[ERROR] Exception processing {r_name} (ID:{extract_id(href)}): {_item_err}{Colors.ENDC}")
                tick_states[href]["last_result"] = "error"
                tick_states[href]["error"] = str(_item_err)[:300]

        # Clean up expired one-time schedules（鎖內 re-load 後刪，避免用 tick
        # 開始時的快照整檔覆寫掉這段期間 GUI 新增的排程）
        for h in expired_hrefs:
            _rs_db_delete(self.db, h)
        if expired_hrefs:
            log(f"{Colors.WARNING}[CLEANUP] {t('rs_cleanup', default='Removed')} {len(expired_hrefs)} {t('rs_expired_schedules', default='expired schedule(s)')}.{Colors.ENDC}")

        if tick_states:
            try:
                from src.state_store import load_state_file, update_state_file

                state_file = _resolve_rule_state_file()
                prev_states = (load_state_file(state_file) or {}).get(_RULE_STATE_KEY) or {}
                live_hrefs = set(self.db.get_all())
                # 「有料」= 任一條目帶動作/結果/錯誤、成員新增、或有待修剪殘留
                meaningful = (
                    any(set(st) - {"last_checked"} for st in tick_states.values())
                    or any(h not in prev_states for h in tick_states)
                    or any(h not in live_hrefs and h not in tick_states
                           for h in prev_states)
                )
                skip = False
                if not meaningful:
                    # 純心跳：至多每 _CHECK_PERSIST_GAP_S 落盤一次，避免每個
                    # tick 全量重寫共享 state.json（2026-07-23 觀測性殘債）
                    newest = max((str(st.get("last_checked") or "")
                                  for st in prev_states.values()), default="")
                    try:
                        newest_dt = datetime.datetime.strptime(
                            newest, "%Y-%m-%dT%H:%M:%SZ").replace(
                            tzinfo=datetime.timezone.utc)
                        age = (datetime.datetime.now(datetime.timezone.utc)
                               - newest_dt).total_seconds()
                        skip = age < _CHECK_PERSIST_GAP_S
                    except ValueError:
                        skip = False  # 無法解析（含空檔）一律落盤修復

                if not skip:
                    def _merge(data):
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

                    update_state_file(state_file, _merge)
            except Exception:
                logger.opt(exception=True).debug("rule schedule state persist failed")

        return logs
