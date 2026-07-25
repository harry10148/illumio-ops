"""Concurrency tests for the shared JSON stores (in-process AND cross-process).

Two layers are pinned here:

1. In-process (cheroot's multi-thread pool). Handlers that do load→mutate→save
   on the shared ConfigManager must serialize that section, or two concurrent
   writers interleave (load A, load B, mutate, mutate, save A, save B) and
   silently drop one update — hence ``cm.write_lock`` and the AST invariant
   below that every ``cm.save()`` in a GUI route sits inside it.

2. Cross-process. ``threading.RLock`` does nothing between processes, but the
   shipped topology is a permanently running ``--monitor-gui`` service PLUS
   operator CLI invocations (``illumio-ops config set``, the interactive menus,
   the rule-scheduler menu) writing the SAME whole-file JSON stores. Those tests
   spawn a REAL subprocess, because that is the only way to exercise
   ``src.file_lock`` and the stale-snapshot guard.
"""
import ast
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run_child(body: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    """Run `body` in a real child process with the repo on sys.path."""
    code = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n" + body
    return subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=timeout)


def _make_cm(tmp_path):
    from src.config import ConfigManager
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s"},
        "settings": {"dashboard_queries": []},
        "rules": [],
    }), encoding="utf-8")
    return ConfigManager(config_file=str(cfg))


def test_write_lock_present_and_reentrant(tmp_path):
    cm = _make_cm(tmp_path)
    assert hasattr(cm, "write_lock")
    # Re-entrant: load() can call save() while a handler already holds the lock,
    # so nested acquisition must not deadlock.
    with cm.write_lock:
        with cm.write_lock:
            pass


def test_concurrent_saves_do_not_lose_updates(tmp_path):
    cm = _make_cm(tmp_path)

    n = 8
    barrier = threading.Barrier(n)
    errors: list[str] = []

    def worker(i: int) -> None:
        try:
            barrier.wait()  # release all threads together to maximize overlap
            # Mirror the GUI handlers' load→mutate→save critical section.
            with cm.write_lock:
                cm.load()
                cm.config.setdefault("settings", {}).setdefault(
                    "dashboard_queries", []).append({"name": f"q{i}"})
                time.sleep(0.01)  # widen the race window
                cm.save()
        except Exception as exc:  # pragma: no cover - surfaced via assert below
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors

    cm.load()
    names = {q["name"] for q in cm.config["settings"]["dashboard_queries"]}
    assert names == {f"q{i}" for i in range(n)}, f"lost updates, only kept: {names}"


# ── Cross-process: the file lock itself ──────────────────────────────────────

def test_file_lock_is_exclusive_across_processes(tmp_path):
    """兩個行程不可同時持有同一把 file_lock（否則整檔覆寫的儲存體全裸奔）。"""
    from src.file_lock import file_lock, has_os_backend

    if not has_os_backend():
        pytest.skip("no OS-level lock backend (fcntl/msvcrt) on this platform")

    lock_path = tmp_path / "x.lock"
    ready = tmp_path / "ready"
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time\n"
         f"sys.path.insert(0, {str(ROOT)!r})\n"
         "from src.file_lock import file_lock\n"
         f"with file_lock({str(lock_path)!r}):\n"
         f"    open({str(ready)!r}, 'w').close()\n"
         "    time.sleep(3)\n"],
        cwd=str(ROOT))
    try:
        deadline = time.time() + 20
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "child never acquired the lock"
        with pytest.raises(TimeoutError):
            with file_lock(str(lock_path), timeout=0.5):
                pass
    finally:
        child.kill()
        child.wait(timeout=10)

    # 子行程結束後鎖必須自動釋放（flock/byte-range lock 由 OS 回收）。
    with file_lock(str(lock_path), timeout=5):
        pass


def test_file_lock_is_reentrant_for_the_same_thread(tmp_path):
    """ConfigManager.load() 在鎖內會呼叫 save()（secret 補寫），巢狀不得死鎖。"""
    from src.file_lock import file_lock
    p = str(tmp_path / "y.lock")
    with file_lock(p, timeout=5):
        with file_lock(p, timeout=5):
            pass


# ── High: config.json / alerts.json cross-process serialization ──────────────

def test_config_save_refuses_stale_snapshot_written_by_another_process(tmp_path):
    """CLI 的過期快照不得整檔覆寫掉服務/GUI 剛寫入的變更（含密碼輪替）。

    這裡刻意用真的子行程：`threading.RLock` 對它完全無效，只有磁碟指紋守門
    擋得住。舊行為是靜默還原（CLI 還印 config_saved）；新行為是 fail loud。
    """
    from src.exceptions import ConfigError

    cm = _make_cm(tmp_path)
    cfg = tmp_path / "config.json"

    from src.config import verify_password

    # 另一個行程（= 執行中的服務 / Web GUI）輪替了密碼。
    child = _run_child(
        "from src.config import ConfigManager, hash_password\n"
        f"cm = ConfigManager(config_file={str(cfg)!r})\n"
        "cm.config.setdefault('web_gui', {})['password'] = hash_password('ROTATED')\n"
        "cm.save()\n")
    assert child.returncode == 0, child.stderr

    # 我們手上的快照已過期；整檔覆寫會把輪替後的密碼洗掉 → 必須拒絕。
    cm.config.setdefault("settings", {})["language"] = "zh_TW"
    with pytest.raises(ConfigError):
        cm.save()

    on_disk = json.loads(cfg.read_text(encoding="utf-8"))
    assert verify_password("ROTATED", on_disk["web_gui"]["password"]), \
        "另一個行程的密碼輪替被過期快照還原了"

    # 重新載入後可以正常存檔（守門不是死路）。
    cm.load()
    cm.config.setdefault("settings", {})["language"] = "zh_TW"
    cm.save()
    on_disk = json.loads(cfg.read_text(encoding="utf-8"))
    assert on_disk["settings"]["language"] == "zh_TW"
    assert verify_password("ROTATED", on_disk["web_gui"]["password"])


def test_config_save_takes_a_cross_process_lock(tmp_path):
    """save() 必須在跨行程檔案鎖內執行，否則兩個行程的 os.replace 會互相蓋。"""
    from src.file_lock import file_lock, has_os_backend

    if not has_os_backend():
        pytest.skip("no OS-level lock backend (fcntl/msvcrt) on this platform")

    cm = _make_cm(tmp_path)
    assert os.path.basename(cm._lock_path) == "config.json.lock"

    # 另一個行程佔住鎖 → save() 必須被擋住直到對方釋放。
    ready = tmp_path / "ready2"
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time\n"
         f"sys.path.insert(0, {str(ROOT)!r})\n"
         "from src.file_lock import file_lock\n"
         f"with file_lock({cm._lock_path!r}):\n"
         f"    open({str(ready)!r}, 'w').close()\n"
         "    time.sleep(2)\n"],
        cwd=str(ROOT))
    try:
        deadline = time.time() + 20
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "child never acquired the lock"
        started = time.monotonic()
        cm.save()
        blocked_for = time.monotonic() - started
    finally:
        child.kill()
        child.wait(timeout=10)

    assert blocked_for >= 1.0, (
        f"save() 只花了 {blocked_for:.2f}s——沒有等另一個行程釋放鎖，"
        "代表 config 寫入沒有走跨行程檔案鎖")


# ── Medium/gate: every GUI route's cm.save() must sit inside cm.write_lock ───

def test_every_gui_route_cm_save_is_inside_write_lock():
    """通用不變式（取代兩則針對特定 handler 的字串 grep）。

    任何 ``cm.save()`` 都必須在同一個函式內、且被 ``with cm.write_lock:``
    包住。新加的 handler 若忘了，這裡直接紅——不需要再補一條字串斷言。
    """
    targets = sorted((ROOT / "src" / "gui" / "routes").glob("*.py"))
    targets.append(ROOT / "src" / "gui" / "settings_helpers.py")

    def _is_write_lock_with(node: ast.AST) -> bool:
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            return False
        for item in node.items:
            ctx = item.context_expr
            if isinstance(ctx, ast.Attribute) and ctx.attr == "write_lock":
                return True
            # `with cm.write_lock, other:` 也算
        return False

    def _is_cm_save(node: ast.AST) -> bool:
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "save"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "cm")

    offenders: list[str] = []
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"))

        def walk(node, locked: bool):
            for child in ast.iter_child_nodes(node):
                if _is_cm_save(child):
                    if not locked:
                        offenders.append(
                            f"{path.relative_to(ROOT)}:{child.lineno}")
                walk(child, locked or _is_write_lock_with(child))

        walk(tree, False)

    assert not offenders, (
        "cm.save() outside `with cm.write_lock:` — concurrent cheroot workers "
        "will silently drop one update:\n  " + "\n  ".join(offenders))


# ── High: rule_schedules.json cross-process serialization ────────────────────

def test_schedule_db_put_does_not_clobber_another_process_write(tmp_path):
    """CLI 選單的分鐘級過期快照不得刪掉服務端這期間新增的排程。"""
    from src.rule_scheduler import ScheduleDB

    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text(json.dumps({"/a": {"name": "a"}}), encoding="utf-8")

    db = ScheduleDB(str(db_path))
    db.load()  # 開啟互動式選單時的快照：只有 /a

    child = _run_child(
        "from src.rule_scheduler import ScheduleDB\n"
        f"db = ScheduleDB({str(db_path)!r})\n"
        "db.put('/b', {'name': 'b'})\n")
    assert child.returncode == 0, child.stderr

    db.put("/c", {"name": "c"})

    on_disk = json.loads(db_path.read_text(encoding="utf-8"))
    assert set(on_disk) == {"/a", "/b", "/c"}, \
        f"併發行程新增的排程被過期快照蓋掉了: {sorted(on_disk)}"


def test_schedule_db_delete_only_removes_the_target(tmp_path):
    from src.rule_scheduler import ScheduleDB

    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text(json.dumps({"/a": {"name": "a"}}), encoding="utf-8")
    db = ScheduleDB(str(db_path))
    db.load()

    child = _run_child(
        "from src.rule_scheduler import ScheduleDB\n"
        f"db = ScheduleDB({str(db_path)!r})\n"
        "db.put('/b', {'name': 'b'})\n")
    assert child.returncode == 0, child.stderr

    assert db.delete("/a") is True
    on_disk = json.loads(db_path.read_text(encoding="utf-8"))
    assert set(on_disk) == {"/b"}, f"併發新增的排程被復活/刪除: {sorted(on_disk)}"


def test_schedule_db_save_uses_a_unique_tmp_file(tmp_path):
    """固定的 '<db>.tmp' 是共用檔名：兩個行程同時存檔會把彼此的輸出交錯進同一個
    inode，替換後的檔案是壞 JSON，下次 load() 會把它隔離掉（＝排程全失）。"""
    import inspect
    from src.rule_scheduler import ScheduleDB

    src = inspect.getsource(ScheduleDB.save)
    assert "mkstemp" in src, "ScheduleDB.save() 必須用 tempfile.mkstemp 取得專屬暫存檔"
    assert '".tmp"' not in src.replace('suffix=".tmp"', ""), \
        "ScheduleDB.save() 仍在組固定的共用暫存檔名"


def test_schedule_db_read_error_does_not_quarantine_the_file(tmp_path):
    """讀取失敗（EACCES/EMFILE/EIO）不是內容壞掉：檔案必須原封不動。

    舊行為把 OSError 也當 corrupt 隔離走，之後每次 load() 都是「檔案不存在
    → {}」，所有排程永久消失且到期規則留在 PCE 上 enabled。"""
    from src.rule_scheduler import ScheduleDB

    if os.name != "posix" or os.geteuid() == 0:
        pytest.skip("needs POSIX permissions and a non-root user")

    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text(json.dumps({"/a": {"name": "a"}}), encoding="utf-8")
    os.chmod(db_path, 0o000)
    try:
        db = ScheduleDB(str(db_path))
        with pytest.raises(OSError):
            db.load()
        assert db_path.exists(), "讀取失敗竟然把完好的排程檔隔離走了"
        assert not list(tmp_path.glob("rule_schedules.json.corrupt.*"))
    finally:
        os.chmod(db_path, 0o600)


# ── High: GUI "restart daemon" must not leave two live schedulers ────────────

def test_gui_daemon_restart_shuts_down_the_previously_running_scheduler(monkeypatch):
    """第一次按下「重啟 daemon」也必須關掉 daemon thread 建的那個 scheduler。

    舊行為只看 src.gui._DAEMON_SCHEDULER，而它要等第一次重啟**完成**才會被
    指派 → 第一次重啟不關舊的，同一行程同時跑兩個 scheduler、每個 job 跑兩次
    （SIEM 重送、排程報表重寄、pce_cache 單一 writer 不變式失效）。
    """
    import src.gui as gui
    import src.scheduler
    from src.cli import _runtime

    built = []

    class _FakeSched:
        def __init__(self):
            self.running = False
            self.shutdown_calls = 0

        def start(self):
            self.running = True

        def shutdown(self, wait=True):
            self.shutdown_calls += 1
            self.running = False

    def _build(cm, interval_minutes=10):
        s = _FakeSched()
        built.append(s)
        return s

    monkeypatch.setattr(src.scheduler, "build_scheduler", _build)
    monkeypatch.setattr(gui, "HAS_FLASK", True)
    monkeypatch.setattr(gui, "launch_gui", lambda cm, **kw: None)
    monkeypatch.setattr(gui, "_GUI_OWNS_DAEMON", False, raising=False)
    monkeypatch.setattr(gui, "_DAEMON_RESTART_FN", None, raising=False)
    monkeypatch.setattr(gui, "_DAEMON_SCHEDULER", None, raising=False)
    monkeypatch.setattr(_runtime, "_register_signals", lambda: None)
    monkeypatch.setattr(_runtime, "run_daemon_loop", lambda *a, **k: None)

    class _CmStub:
        def load(self):
            return None

    _runtime.run_daemon_with_gui(_CmStub(), interval=5, port=5099, host="127.0.0.1")

    restart_fn = gui._DAEMON_RESTART_FN
    assert callable(restart_fn)

    # 模擬 daemon thread 已建立並登記自己的 scheduler（真實情況下
    # _DAEMON_SCHEDULER 仍是 None——這正是舊守門失效的原因）。
    daemon_sched = _FakeSched()
    daemon_sched.start()
    _runtime._publish_scheduler(daemon_sched)
    try:
        new_sched = restart_fn()

        assert daemon_sched.shutdown_calls == 1, \
            "重啟沒有關掉原本在跑的 scheduler → 兩個 scheduler 同時存活"
        assert daemon_sched.running is False
        assert new_sched.running is True
        assert _runtime._current_scheduler() is new_sched, \
            "新 scheduler 未登記 → 下一次重啟又會漏掉它"
    finally:
        _runtime._publish_scheduler(None)


# ── Windows / degraded backends（Linux CI 上只能以代理方式驗證）─────────────

def test_windows_msvcrt_branch_locks_and_unlocks(monkeypatch, tmp_path):
    """本專案有 Windows 安裝路徑，msvcrt 分支必須是可執行的程式碼。

    Linux CI 上沒有 msvcrt，只能把 fcntl 關掉並注入一個記錄呼叫的假 msvcrt，
    確認 file_lock 走的是 LK_NBLCK 取鎖 / LK_UNLCK 釋放、且鎖檔內有可鎖位元組
    （Windows 的 byte-range lock 需要）。
    """
    import src.file_lock as fl

    calls = []

    class _FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 0

        @staticmethod
        def locking(fd, mode, nbytes):
            calls.append((mode, nbytes, os.lseek(fd, 0, os.SEEK_CUR)))

    monkeypatch.setattr(fl, "_fcntl", None)
    monkeypatch.setattr(fl, "_msvcrt", _FakeMsvcrt)

    lock_path = tmp_path / "win.lock"
    with fl.file_lock(str(lock_path), timeout=1):
        pass

    assert calls == [(_FakeMsvcrt.LK_NBLCK, 1, 0), (_FakeMsvcrt.LK_UNLCK, 1, 0)], calls
    assert lock_path.stat().st_size >= 1, "鎖檔沒有可鎖的位元組"


def test_no_lock_backend_degrades_instead_of_crashing(monkeypatch, tmp_path):
    """兩種 backend 都不可用時退化成行程內鎖，不得讓寫入路徑整個爆掉。"""
    import src.file_lock as fl

    monkeypatch.setattr(fl, "_fcntl", None)
    monkeypatch.setattr(fl, "_msvcrt", None)
    monkeypatch.setattr(fl, "_warned_degraded", False, raising=False)

    with fl.file_lock(str(tmp_path / "none.lock"), timeout=1):
        pass
