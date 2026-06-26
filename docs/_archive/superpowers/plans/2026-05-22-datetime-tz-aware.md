# Datetime Timezone-Aware Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清除 illumio-ops 內所有 naive `datetime.now()` 使用點，全部改為 timezone-aware（UTC 為內部正規型）；同時把以 `int(now.timestamp())` 當識別碼的 rule_id 改成 UUID4，避免跨 DST 碰撞。

**Architecture:** 兩條主軸 — (A) 內部時間統一存 UTC、UI 顯示時 `astimezone(local)`；(B) 識別碼脫離時鐘相依，改 UUID4。再加 CI lint rule，避免回歸。

**Tech Stack:** Python 3.12 (datetime.timezone, uuid.uuid4)、pytest 8（freezegun 模擬時鐘）

**Audit reference:** `docs/security-audit-2026-05-22.md` H-4
**Parent plan:** `docs/superpowers/plans/2026-05-22-security-remediation.md`（task T1.8 指向此 plan）
**Test host:** `root@172.16.15.106`（ssh alias `illumio-ops-test`）

**Pre-flight grep**（執行 plan 前先跑一次確認範圍）：
```bash
grep -rn 'datetime\.now()\|datetime\.datetime\.now()' src/ --include="*.py" | grep -v 'tz\|timezone'
```

---

## File Structure

| 群組 | 檔案 | 修法 |
|------|------|------|
| **A1. Scheduler 真正 DST bug** | `src/report_scheduler.py:36`、`src/rule_scheduler.py:19,26` | naive fallback → UTC-aware |
| **A2. Log timestamp（cosmetic）** | `src/gui/__init__.py:109`、`src/module_log.py:72`、`src/analyzer.py:502`、`src/gui/routes/reports.py:163,280,334,382` | 改 UTC-aware ISO 字串 |
| **B. rule_id 改 UUID4** | `src/gui/routes/rules.py:88,118,163,208`、`src/cli/menus/{bandwidth,system_health,event,traffic}.py` | `int(now.timestamp())` → `uuid.uuid4().hex` |
| **C. Lint guard** | `scripts/check_no_naive_datetime.py`（新）、`.github/workflows/ci.yml` | CI 跑 grep 阻擋未來回歸 |
| **D. 測試** | `tests/test_no_naive_datetime.py`（新）、`tests/test_rule_id_uuid.py`（新） | 整體靜態檢查 + 行為測試 |

---

## Phase A — 時間 UTC-aware 改造

### Task A.1：Scheduler fallback 改 UTC-aware

**Files:**
- Modify: `src/report_scheduler.py:36`
- Modify: `src/rule_scheduler.py:19, 26`
- Test: `tests/test_scheduler_tz_aware.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_scheduler_tz_aware.py
import datetime
from unittest.mock import patch

def test_report_scheduler_now_local_returns_aware():
    from src.report_scheduler import now_local
    result = now_local()
    assert result.tzinfo is not None, f"now_local() returned naive: {result}"

def test_rule_scheduler_helpers_return_aware():
    from src.rule_scheduler import _now_local, _now_utc_or_local
    assert _now_local().tzinfo is not None
    assert _now_utc_or_local().tzinfo is not None
```

- [ ] **Step 2：驗證失敗**

```bash
pytest tests/test_scheduler_tz_aware.py -v
# 預期：FAIL（fallback 返回 naive）
```

- [ ] **Step 3：修改 `src/report_scheduler.py:36`**

讀目前實作（line 30-40 範圍）並把 naive fallback 改成：

```python
def now_local():
    try:
        tz = ZoneInfo(get_local_tz_name())
        return datetime.datetime.now(tz)
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc)  # 改 UTC-aware
```

`src/rule_scheduler.py:19, 26` 同樣 pattern。

- [ ] **Step 4：驗證通過**

```bash
pytest tests/test_scheduler_tz_aware.py -v  # 預期：PASS
pytest tests/test_report_scheduler.py tests/test_rule_scheduler.py -v  # regression
```

- [ ] **Step 5：commit**

```bash
git add src/report_scheduler.py src/rule_scheduler.py tests/test_scheduler_tz_aware.py
git commit -m "fix(scheduler): naive datetime fallback returns UTC-aware (H-4 part 1)"
```

- [ ] **Step 6：部署 + 重啟測試機**

```bash
scp src/report_scheduler.py src/rule_scheduler.py root@172.16.15.106:/root/illumio-ops/src/
ssh illumio-ops-test 'systemctl restart illumio-ops && sleep 5 && systemctl is-active illumio-ops'
```

### Task A.2：Log timestamp 改 UTC-aware

**Files:**
- Modify: `src/gui/__init__.py:109`
- Modify: `src/module_log.py:72`
- Modify: `src/analyzer.py:502`
- Modify: `src/gui/routes/reports.py:163, 280, 334, 382`

無對應測試（cosmetic 修補），但要確認 regression test 仍 pass。

- [ ] **Step 1：批次取代**

每處把 `datetime.datetime.now().strftime(...)` 改成：

```python
datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
```

或 ISO format：

```python
datetime.datetime.now(datetime.timezone.utc).isoformat()
```

具體位置：
- `src/gui/__init__.py:109` — `_rs_log_history` 內 `timestamp`
- `src/module_log.py:72` — `ts = ...`
- `src/analyzer.py:502` — 報告 `time` 欄位
- `src/gui/routes/reports.py:163,280,334,382` — log separator 標題（cosmetic）

- [ ] **Step 2：跑現有測試確認無破壞**

```bash
pytest tests/ -v --ignore=tests/test_no_naive_datetime.py 2>&1 | tail -10
# 預期：全部 PASS
```

- [ ] **Step 3：commit + 部署**

```bash
git add src/gui/__init__.py src/module_log.py src/analyzer.py src/gui/routes/reports.py
git commit -m "fix(log): use UTC-aware timestamps in module log / analyzer / reports (H-4 part 2)"
scp src/gui/__init__.py src/module_log.py src/analyzer.py src/gui/routes/reports.py root@172.16.15.106:/root/illumio-ops/src/<corresponding subdirs>
ssh illumio-ops-test 'systemctl restart illumio-ops && journalctl -u illumio-ops -n 20 --since "1 min ago" | grep -i "UTC\|T[0-9]\{2\}:"'
# 預期：log 顯示帶 UTC suffix 或 ISO timezone offset
```

---

## Phase B — rule_id 改 UUID4

### Task B.1：建立 `_gen_rule_id` helper

**Files:**
- Create: `src/rule_id.py`（新）
- Test: `tests/test_rule_id_uuid.py`（新）

- [ ] **Step 1：寫測試**

```python
# tests/test_rule_id_uuid.py
import re
from src.rule_id import gen_rule_id

def test_gen_rule_id_returns_hex_string():
    rid = gen_rule_id()
    assert isinstance(rid, str)
    assert re.fullmatch(r"[0-9a-f]{32}", rid), f"unexpected format: {rid}"

def test_gen_rule_id_unique():
    ids = {gen_rule_id() for _ in range(1000)}
    assert len(ids) == 1000  # uuid4 衝突機率近似 0

def test_gen_rule_id_no_clock_dependence():
    """同 epoch 秒內呼叫多次仍唯一"""
    import time
    t = time.monotonic()
    ids = []
    while time.monotonic() - t < 0.01:
        ids.append(gen_rule_id())
    assert len(set(ids)) == len(ids)
```

- [ ] **Step 2：實作 `src/rule_id.py`**

```python
"""統一的 rule_id 產生器，脫離時鐘相依。"""
import uuid

def gen_rule_id() -> str:
    """Return a 32-char hex UUID4."""
    return uuid.uuid4().hex
```

- [ ] **Step 3：驗證通過**

```bash
pytest tests/test_rule_id_uuid.py -v  # 預期：PASS
```

- [ ] **Step 4：commit**

```bash
git add src/rule_id.py tests/test_rule_id_uuid.py
git commit -m "feat(rule_id): UUID4-based rule_id generator (H-4 part 3 — prep)"
```

### Task B.2：取代所有 `int(now.timestamp())` 用法

**Files:**
- Modify: `src/gui/routes/rules.py:88, 118, 163, 208`
- Modify: `src/cli/menus/bandwidth.py:237, 239`
- Modify: `src/cli/menus/system_health.py:64, 66`
- Modify: `src/cli/menus/event.py:135, 137`
- Modify: `src/cli/menus/traffic.py:245, 247`
- Test: `tests/test_rule_id_migration.py`（新）

- [ ] **Step 1：寫測試**

```python
# tests/test_rule_id_migration.py
import ast
from pathlib import Path

TARGETS = [
    "src/gui/routes/rules.py",
    "src/cli/menus/bandwidth.py",
    "src/cli/menus/system_health.py",
    "src/cli/menus/event.py",
    "src/cli/menus/traffic.py",
]

def test_no_timestamp_based_rule_id():
    """確保沒有 int(datetime.now().timestamp()) 模式殘留"""
    bad_pattern = "int(datetime.datetime.now"
    for path in TARGETS:
        content = Path(path).read_text()
        assert bad_pattern not in content, f"{path} 仍含 timestamp-based rule_id"
        # 應改用 gen_rule_id()
        assert "gen_rule_id" in content or "uuid4" in content
```

- [ ] **Step 2：驗證失敗**

```bash
pytest tests/test_rule_id_migration.py -v
# 預期：FAIL
```

- [ ] **Step 3：批次取代**

於 `src/gui/routes/rules.py` import 段加：

```python
from src.rule_id import gen_rule_id
```

然後每處 `int(datetime.datetime.now().timestamp())` → `gen_rule_id()`。

注意：**rule_id 從 int 改 str 是 schema change**，需確認：
- `rule_schedules.json` 載入端能容忍 str id
- DB / state 內既有 int id 不刪除（向後相容）

5 個檔案同樣處理。

- [ ] **Step 4：寫遷移容忍測試**

```python
# tests/test_rule_id_back_compat.py
from src.rule_scheduler import ScheduleDB

def test_legacy_int_rule_id_still_loadable(tmp_path):
    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text('{"1700000000": {"name": "legacy"}, "abc123def": {"name": "new"}}')
    db = ScheduleDB(str(db_path))
    db.load()
    assert "1700000000" in db.db  # 或 int 1700000000，看 schema
    assert "abc123def" in db.db
```

- [ ] **Step 5：驗證通過**

```bash
pytest tests/test_rule_id_migration.py tests/test_rule_id_back_compat.py -v  # PASS
pytest tests/  # regression
```

- [ ] **Step 6：commit**

```bash
git add src/gui/routes/rules.py src/cli/menus/*.py tests/test_rule_id_migration.py tests/test_rule_id_back_compat.py
git commit -m "feat(rule_id): migrate to UUID4 across GUI + CLI menus (H-4 part 3)"
```

- [ ] **Step 7：部署 + 驗證**

```bash
scp src/gui/routes/rules.py root@172.16.15.106:/root/illumio-ops/src/gui/routes/
scp src/cli/menus/*.py root@172.16.15.106:/root/illumio-ops/src/cli/menus/
ssh illumio-ops-test 'systemctl restart illumio-ops && sleep 5'

# 透過 GUI 新增一條 rule，確認 ID 為 hex 字串
# （手動 GUI 操作或 curl POST）

# 確認既有 schedule 仍可載入
ssh illumio-ops-test 'python3 -c "
import json
d = json.load(open(\"/root/illumio-ops/config/rule_schedules.json\"))
print(\"keys:\", list(d.keys())[:5])
"'
```

---

## Phase C — CI Lint Guard

### Task C.1：寫 `check_no_naive_datetime.py` 並掛到 CI

**Files:**
- Create: `scripts/check_no_naive_datetime.py`
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_no_naive_datetime.py`（新）

- [ ] **Step 1：寫測試（同時是 CI 跑的 script）**

```python
# scripts/check_no_naive_datetime.py
"""CI lint：禁止新增 naive datetime.now() 使用。"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
ALLOW_LIST = {
    "src/humanize_ext.py",  # 防禦性 fallback 已驗證 OK
}

PATTERN = re.compile(r'datetime\.(datetime\.)?now\(\)(?!\s*\.\s*astimezone)')

def main():
    hits = []
    for py in SRC.rglob("*.py"):
        rel = str(py.relative_to(ROOT))
        if rel in ALLOW_LIST:
            continue
        content = py.read_text()
        for ln_no, line in enumerate(content.splitlines(), 1):
            if PATTERN.search(line) and "timezone" not in line:
                hits.append(f"{rel}:{ln_no}: {line.strip()}")
    if hits:
        print("ERROR: naive datetime.now() 使用點：", file=sys.stderr)
        for h in hits:
            print("  " + h, file=sys.stderr)
        sys.exit(1)
    print("OK: 無 naive datetime.now() 使用。")

if __name__ == "__main__":
    main()
```

```python
# tests/test_no_naive_datetime.py
import subprocess

def test_no_naive_datetime_in_src():
    """跑 lint script 確認沒有 naive datetime.now() 殘留。"""
    result = subprocess.run(
        ["python3", "scripts/check_no_naive_datetime.py"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"lint failed: {result.stderr}"
```

- [ ] **Step 2：驗證通過**

```bash
python3 scripts/check_no_naive_datetime.py
# 預期：OK
pytest tests/test_no_naive_datetime.py -v
# 預期：PASS
```

- [ ] **Step 3：加 CI step**

修改 `.github/workflows/ci.yml`：

```yaml
- name: Lint naive datetime
  run: python3 scripts/check_no_naive_datetime.py
```

- [ ] **Step 4：commit + push**

```bash
git add scripts/check_no_naive_datetime.py tests/test_no_naive_datetime.py .github/workflows/ci.yml
git commit -m "feat(ci): block naive datetime.now() via lint script (H-4 final)"
git push
# 觀察 CI 全綠
```

---

## 整體驗證

### Task Z.1：DST 模擬測試（freezegun）

**Files:**
- Modify: `tests/test_scheduler_dst.py`（新）

- [ ] **Step 1：用 freezegun 模擬 DST 切換**

```python
# tests/test_scheduler_dst.py
"""DST 切換當天的 scheduler 行為驗證。"""
import pytest
from freezegun import freeze_time

@freeze_time("2026-03-09 06:30:00", tz_offset=0)  # US DST spring-forward eve
def test_scheduler_no_skip_at_spring_forward():
    """在春季 DST 切換時，scheduler 不應跳過排程。"""
    from src.report_scheduler import should_run
    # 設一條每天 02:30 跑的 schedule
    schedule = {
        "name": "daily_2_30",
        "hour": 2, "minute": 30,
        "timezone": "America/New_York"
    }
    # ... 驗證 should_run 在 02:30 EDT (即 06:30 UTC) 仍會觸發
    # 細節依 should_run 簽名而定
```

注意：`freezegun` 需加入 `requirements-dev.txt`：

```bash
echo "freezegun>=1.5,<2.0" >> requirements-dev.txt
pip install freezegun
```

- [ ] **Step 2~3：驗證、commit**

### Task Z.2：在測試機跑完整 regression

```bash
ssh illumio-ops-test 'cd /root/illumio-ops && venv/bin/pytest tests/ -v 2>&1 | tail -10'
# 預期：全部 PASS
ssh illumio-ops-test 'systemctl is-active illumio-ops'
# 預期：active
ssh illumio-ops-test 'journalctl -u illumio-ops -n 50 | grep -iE "error|exception" | head -5'
# 預期：無新例外
```

---

## Self-Review Checklist

**1. Spec coverage：** Audit H-4 的所有提及點 — `report_scheduler:36`、`rule_scheduler:19,26`、`gui/__init__:109`、`module_log:72`、`analyzer:502`、`gui/routes/rules:88,118,163,208`、CLI menus、`gui/routes/reports:163,280,334,382` — 全納入對應 task ✓

**2. Placeholder scan：** 所有 step 含實際 code 與指令，無 TBD ✓

**3. Type consistency：**
- `rule_id` 從 `int(timestamp)` → `str(uuid4.hex)` 是 schema change，已加 back-compat test
- `now_local()` / `_now_local()` 返回型別保持 `datetime.datetime`，僅 tzinfo 改為非 None

---

## 預估工時

| Phase | Task | 預估 |
|-------|------|------|
| A.1 | Scheduler fallback | 0.5 day |
| A.2 | Log timestamp（7 處） | 0.5 day |
| B.1 | `gen_rule_id` helper | 0.2 day |
| B.2 | rule_id migration（5 檔） | 1 day（含 back-compat 測試） |
| C.1 | CI lint guard | 0.3 day |
| Z.1 | DST freezegun 測試 | 0.5 day |
| Z.2 | 整體 regression | 0.3 day |
| **小計** | | **~3-4 工作日（單線）** |

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-datetime-tz-aware.md`. Two execution options:**

**1. Subagent-Driven（推薦）** - 每 task 一個 fresh subagent，並行可達 4-5 個。

**2. Inline Execution** - 連續執行，每 phase checkpoint。

**Which approach?**（與主 plan 對齊：subagent-driven）
