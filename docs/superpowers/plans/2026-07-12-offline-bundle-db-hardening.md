# Offline Bundle DB 防護與 Schema 遷移強化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除「舊 SQLite / 舊 DB schema / 舊套件 + 新程式碼」在離線部署上造成的隱性小問題：加入 SQLite 版本 fail-fast 與 CLI wrapper 杜絕誤用系統 Python、讓升級的套件更新具決定性、補齊升級防呆與安裝後檢測、修正 schema 遷移機制的結構性弱點，並同步更新操作文件。

**Architecture:** 不改變既有「惰性遷移」設計（`init_schema()` 於服務啟動時就地升級 DB）。改善分四層：(1) 執行環境層——entry point 檢查 SQLite 版本下限、install.sh 安裝 CLI wrapper；(2) schema 層——`_ADDED_COLUMNS` 一般化為跨表登記，並以凍結的 baseline schema fixture 做漂移防護測試；(3) 套件生命週期層——升級時以 `rsync --delete` 還原 pristine Python runtime 後全量重裝 bundle wheels（決定性）、app 端清除殭屍模組、加 downgrade 與服務運行防呆、安裝後自動驗證；(4) 可觀測層——siem CLI 不再吞掉非首次執行的 `OperationalError`、user_version 過新時記 warning、preflight 報告 bundled SQLite 版本與既有 DB 狀態、文件與實作對齊。

**Tech Stack:** Python 3.12 / SQLAlchemy 2.x / SQLite / loguru / click + pytest；bash（install.sh / preflight.sh / uninstall.sh）。

## Global Constraints

- SQLite 版本下限為 **3.35.0**（`INSERT ... RETURNING`，見 `src/pce_cache/ingestor_events.py:137`、`src/pce_cache/ingestor_traffic.py:267`）；所有檢查一律用這個值。
- Bundle 內建 Python 為 python-build-standalone 3.12.7，服務 ExecStart 固定為 `$INSTALL_ROOT/python/bin/python3`（`deploy/illumio-ops.service:12`）。
- Commit message 用英文 conventional commits；所有輸出（程式、註解、docs、commit）一律不用 emoji。
- 文件為中英雙語成對檔（`getting-started.md` / `getting-started_zh.md`），改一邊必須同步另一邊（repo 有 doc coverage 檢查）。
- 測試指令：於 repo root 執行 `python3 -m pytest <path> -v`。
- baseline fixture（Task 3 產生的 `tests/fixtures/pce_cache_baseline_schema.sql`）一旦提交即**凍結**：日後在 models.py 加欄位時**不得**重新產生它——重新產生會讓漂移防護測試失去意義。

## 背景：問題清單與任務對應

| # | 問題（來源：2026-07-12 offline bundle 部署機制分析） | 任務 |
|---|---|---|
| 1 | 誤用系統 Python 時，舊發行版 SQLite（RHEL 8 = 3.26、Ubuntu 20.04 = 3.31）< 3.35 導致 ingest 的 `RETURNING` 失敗，症狀隱晦 | Task 1（fail-fast）、Task 5（wrapper）、Task 6（preflight） |
| 2 | `create_all()` 永不 ALTER 既有表；新欄位靠人工登記 `_ADDED_COLUMNS`，忘了登記時舊 DB 會 `no such column`，且登記機制寫死只支援 `pce_traffic_flows_raw` 一張表 | Task 2、Task 3 |
| 3 | `src/cli/siem.py:141` 把任何 `OperationalError` 當「DB 未初始化」顯示零值，schema 問題被吞掉 | Task 4 |
| 4 | 新 DB（user_version 較大）搭舊程式碼（downgrade）無任何警示 | Task 3 |
| 5 | preflight 無 SQLite 版本、既有 DB 可開啟性/user_version 檢查 | Task 6 |
| 6 | 升級時 pip 無 `--upgrade`、requirements 全為範圍寫法——已裝版本滿足範圍時 bundle 內較新的 wheel 不會被安裝，安全修補不落地 | Task 7 |
| 7 | `rsync -a` 無 `--delete`——被刪除/改名的 src 模組以殭屍 `.py` 檔留存且仍可 import；pip 從不移除已下架的相依（如 plotly 68MB） | Task 7 |
| 8 | install.sh 升級路徑無防呆（不擋 downgrade、不管服務是否運行中）、無安裝後檢測（`verify_deps.py --offline-bundle` 現成但從未被呼叫） | Task 8 |
| 9 | uninstall 非 `--purge` 模式保留 `config/` 但會刪掉 `data/`（DB）與 `reports/`，語意易誤解 | Task 9 |
| 10 | 文件與實作不符：`release-process.md` 稱 installer 升級時會自動 restart 服務（實際沒有）；升級 SOP 未涵蓋本案新增的防呆/檢測行為 | Task 10 |

**明確不做（out of scope）：**
- `_ensure_schema_once` 的 db_path 快取邊界（process 存活中外部抽換 DB 檔）——程式碼註解已載明此既有假設，正常升級（restart）不受影響。
- Windows 端 parity（`install.ps1` 的 wrapper、`--delete` 重裝、防呆與驗證）——Task 1 的 Python 層 fail-fast 已涵蓋兩平台；其餘 Windows 對應列為 follow-up（本案目標環境為 Linux 離線機）。
- `pysqlite3-binary` / `LD_PRELOAD` 備案——bundle 已含 PBS Python，無此需求。
- requirements 改成精確 pin（lock 化）——bundle 內 wheel 版本由建置時決定並有 SBOM 紀錄；Task 7 的「pristine 重裝」已保證部署端與 bundle 一致，pin 策略另案討論。

---

### Task 1: SQLite 版本 fail-fast（entry point 防護）

**Files:**
- Create: `src/runtime_checks.py`
- Modify: `illumio-ops.py:54-56`（`__main__` 區塊開頭）
- Test: `tests/test_runtime_checks.py`

**Interfaces:**
- Produces: `src.runtime_checks.MIN_SQLITE_VERSION: tuple[int, int, int]`（Task 6 的 preflight 檢查與本任務共用同一個下限值 3.35.0，但 preflight 是 bash，值為複製；若日後調整需兩處同步——在兩處都寫上互相指向的註解）
- Produces: `src.runtime_checks.sqlite_version_error() -> str | None`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_runtime_checks.py`：

```python
import sqlite3

from src.runtime_checks import MIN_SQLITE_VERSION, sqlite_version_error


def test_min_version_is_returning_floor():
    # INSERT ... RETURNING (ingestor_events/ingestor_traffic) 需要 3.35.0
    assert MIN_SQLITE_VERSION == (3, 35, 0)


def test_current_runtime_passes():
    # 開發機/bundle Python 的 SQLite 都 >= 3.45，健康環境必須回 None
    assert sqlite_version_error() is None


def test_old_sqlite_rejected(monkeypatch):
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 26, 0))
    monkeypatch.setattr(sqlite3, "sqlite_version", "3.26.0")
    msg = sqlite_version_error()
    assert msg is not None
    assert "3.26.0" in msg          # 實際版本要出現在訊息裡
    assert "3.35.0" in msg          # 需求下限要出現在訊息裡
    assert "python/bin/python3" in msg  # 指引 operator 用 bundle Python
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_runtime_checks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.runtime_checks'`

- [ ] **Step 3: 實作 `src/runtime_checks.py`**

```python
"""Runtime environment guards for the app entry point.

Offline-bundle deployments always run on the bundled python-build-standalone
interpreter, whose SQLite is modern. These guards exist for the failure mode
where an operator bypasses the bundle and runs the app with the system
python3 — old enterprise distros (RHEL 8: SQLite 3.26, Ubuntu 20.04: 3.31)
lack INSERT ... RETURNING (needs >= 3.35.0) used by the ingestors.
"""
from __future__ import annotations

# INSERT ... RETURNING (src/pce_cache/ingestor_events.py,
# src/pce_cache/ingestor_traffic.py) requires SQLite >= 3.35.0.
# Keep in sync with the bash-side copy in scripts/preflight.sh.
MIN_SQLITE_VERSION = (3, 35, 0)


def sqlite_version_error() -> str | None:
    """Return a human-readable error when the linked SQLite is too old.

    Returns None when the runtime is acceptable. Plain English (no i18n):
    this runs before any app import, where the i18n engine may not even be
    importable under a broken interpreter.
    """
    import sqlite3

    if sqlite3.sqlite_version_info >= MIN_SQLITE_VERSION:
        return None
    want = ".".join(str(p) for p in MIN_SQLITE_VERSION)
    return (
        f"Error: this Python links SQLite {sqlite3.sqlite_version}, but "
        f"illumio-ops requires SQLite >= {want} (INSERT ... RETURNING).\n"
        "You are probably running the system python3 instead of the bundled "
        "runtime. Re-run with the bundle interpreter, e.g.:\n"
        "  /opt/illumio-ops/python/bin/python3 /opt/illumio-ops/illumio-ops.py"
    )
```

- [ ] **Step 4: 執行測試，確認通過**

Run: `python3 -m pytest tests/test_runtime_checks.py -v`
Expected: 3 passed

- [ ] **Step 5: 接上 entry point**

`illumio-ops.py` 的 `__main__` 區塊，在 `install_top_level_handler()` 之前插入檢查。修改前（`illumio-ops.py:54-56`）：

```python
if __name__ == "__main__":
    from src.cli._errors import install_top_level_handler
    install_top_level_handler()
```

修改後：

```python
if __name__ == "__main__":
    from src.runtime_checks import sqlite_version_error
    _sqlite_err = sqlite_version_error()
    if _sqlite_err:
        print(_sqlite_err, file=sys.stderr)
        sys.exit(1)
    from src.cli._errors import install_top_level_handler
    install_top_level_handler()
```

- [ ] **Step 6: 驗證健康環境不受影響**

Run: `python3 illumio-ops.py --help`
Expected: 正常印出 usage、exit code 0（guard 未誤觸發）。

- [ ] **Step 7: Commit**

```bash
git add src/runtime_checks.py illumio-ops.py tests/test_runtime_checks.py
git commit -m "feat(runtime): fail fast when linked SQLite is older than 3.35.0"
```

---

### Task 2: `_ADDED_COLUMNS` 一般化為跨表登記

**Files:**
- Modify: `src/pce_cache/schema.py:46-77`
- Test: `tests/test_schema_added_columns.py`

**Interfaces:**
- Produces: `_ADDED_COLUMNS` 新格式為 `(table, column, sqltype)` 三元組：`(("pce_traffic_flows_raw", "report_json", "TEXT"),)`。Task 3 的漂移防護測試依賴此格式。
- Consumes: 無（獨立重構）。

- [ ] **Step 1: 寫測試（round-trip：缺欄位的舊表經 init_schema 後補齊）**

建立 `tests/test_schema_added_columns.py`：

```python
import sqlite3

from sqlalchemy import create_engine, inspect

from src.pce_cache.schema import _ADDED_COLUMNS, init_schema


def test_added_columns_registry_is_table_qualified():
    # 登記格式必須含表名，未來對其他表加欄位時不需要改 _ensure_added_columns
    for entry in _ADDED_COLUMNS:
        assert len(entry) == 3, (
            f"_ADDED_COLUMNS entry {entry!r} must be (table, column, sqltype)"
        )


def test_legacy_table_missing_registered_column_gets_it_back(tmp_path):
    # 模擬 Tier-2a 之前的舊 DB：先建出完整 schema，再拔掉 report_json
    db = tmp_path / "legacy.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    init_schema(engine)
    engine.dispose()

    conn = sqlite3.connect(db)
    # SQLite 拒絕 DROP 被索引引用的欄位——ix_raw_report_json_null 是
    # `WHERE report_json IS NULL` 的 partial index，得先拔索引再拔欄位。
    # init_schema 的 _ensure_added_indexes 之後會把索引重建回來。
    conn.execute("DROP INDEX IF EXISTS ix_raw_report_json_null")
    conn.execute("ALTER TABLE pce_traffic_flows_raw DROP COLUMN report_json")
    conn.commit()
    conn.close()

    engine2 = create_engine(f"sqlite:///{db}")
    init_schema(engine2)
    cols = {c["name"] for c in inspect(engine2).get_columns("pce_traffic_flows_raw")}
    engine2.dispose()
    assert "report_json" in cols
```

- [ ] **Step 2: 執行測試，確認第一個測試失敗**

Run: `python3 -m pytest tests/test_schema_added_columns.py -v`
Expected: `test_added_columns_registry_is_table_qualified` FAIL（現行格式是二元組）；`test_legacy_table_missing_registered_column_gets_it_back` PASS（現行行為已正確，作為重構的回歸網）。

- [ ] **Step 3: 重構 `src/pce_cache/schema.py`**

把 `schema.py:46-77` 的 `_ADDED_COLUMNS` 與 `_ensure_added_columns` 整段改為：

```python
# Columns added to a table after it first shipped. create_all() never ALTERs
# an existing table, so add missing columns explicitly (idempotently). SQLite
# ADD COLUMN is a cheap metadata-only op. Entries are (table, column, sqltype)
# so future additions to ANY table only need a new tuple here — forgetting to
# register a new model column is caught by tests/test_schema_drift_guard.py.
_ADDED_COLUMNS = (
    # Tier-2a report-ready flatten cache.
    ("pce_traffic_flows_raw", "report_json", "TEXT"),
)


def _ensure_added_columns(engine: Engine) -> None:
    from sqlalchemy.exc import OperationalError

    with engine.begin() as conn:
        for table, name, sqltype in _ADDED_COLUMNS:
            existing = {
                r[1] for r in conn.execute(
                    text(f"PRAGMA table_info({table})")
                )
            }
            if name in existing:
                continue
            try:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}"
                ))
            except OperationalError as exc:
                # SQLite has no "ADD COLUMN IF NOT EXISTS". When init_schema runs
                # concurrently from two threads (daemon ingestion + a web request
                # under monitor-gui), both can pass the PRAGMA check above before
                # either ALTERs, so the loser hits "duplicate column name". The
                # column exists either way — swallow only that race, re-raise else.
                if "duplicate column name" not in str(exc).lower():
                    raise
```

- [ ] **Step 4: 執行測試，確認全部通過**

Run: `python3 -m pytest tests/test_schema_added_columns.py -v`
Expected: 2 passed

- [ ] **Step 5: 跑既有 schema 相關測試，確認重構無回歸**

Run: `python3 -m pytest tests/ -k "schema or pce_cache" -q`
Expected: all passed（數量依現況，不得有 fail）

- [ ] **Step 6: Commit**

```bash
git add src/pce_cache/schema.py tests/test_schema_added_columns.py
git commit -m "refactor(schema): table-qualify _ADDED_COLUMNS registry"
```

---

### Task 3: 凍結 baseline schema 的漂移防護測試 + downgrade 警示

**Files:**
- Create: `tests/fixtures/pce_cache_baseline_schema.sql`（產生後凍結）
- Create: `tests/test_schema_drift_guard.py`
- Modify: `src/pce_cache/schema.py:142-158`（`_normalize_agg_bucket_day` 加 downgrade 警示）與檔頭 import

**Interfaces:**
- Consumes: Task 2 的三元組 `_ADDED_COLUMNS` 格式（漂移測試的失敗訊息會指引開發者去登記）。
- Produces: `tests/fixtures/pce_cache_baseline_schema.sql` — 代表「目前已出貨的最舊可升級 schema」的凍結 DDL。

- [ ] **Step 1: 產生 baseline fixture（一次性，之後凍結）**

於 repo root 執行：

```bash
mkdir -p tests/fixtures
python3 - <<'EOF'
import pathlib
import sqlite3
import tempfile

from sqlalchemy import create_engine

from src.pce_cache.schema import init_schema

with tempfile.TemporaryDirectory() as td:
    db = f"{td}/baseline.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    init_schema(engine)
    engine.dispose()
    conn = sqlite3.connect(db)
    ddl = ";\n".join(
        row[0]
        for row in conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE sql IS NOT NULL ORDER BY type DESC, name"
        )
    ) + ";\n"
    conn.close()
out = pathlib.Path("tests/fixtures/pce_cache_baseline_schema.sql")
out.write_text(
    "-- FROZEN baseline: pce_cache schema as shipped on 2026-07-12.\n"
    "-- Do NOT regenerate when adding model columns — this file simulates an\n"
    "-- already-deployed old DB so test_schema_drift_guard.py can prove that\n"
    "-- init_schema upgrades it. Regenerating would defeat the guard.\n"
    + ddl
)
print(f"wrote {out} ({out.stat().st_size} bytes)")
EOF
```

Expected: 印出 `wrote tests/fixtures/pce_cache_baseline_schema.sql (...)`；檔案內含 7 張表（`pce_events`、`pce_traffic_flows_raw`、`pce_traffic_flows_agg`、`ingestion_cursors`、`ingestion_watermarks`、`siem_dispatch`、`dead_letter`）的 CREATE TABLE 與各 CREATE INDEX。用 `head -30 tests/fixtures/pce_cache_baseline_schema.sql` 目視確認。

- [ ] **Step 2: 寫漂移防護測試**

建立 `tests/test_schema_drift_guard.py`：

```python
"""Drift guard: a legacy DB (frozen baseline DDL) run through init_schema()
must end up with every column the current models declare.

If this test fails after you added a column to src/pce_cache/models.py, the
fix is to register the column in _ADDED_COLUMNS (src/pce_cache/schema.py) —
NOT to regenerate the baseline fixture.
"""
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from src.pce_cache.models import Base
from src.pce_cache.schema import init_schema

BASELINE = Path(__file__).parent / "fixtures" / "pce_cache_baseline_schema.sql"


@pytest.fixture
def upgraded_engine(tmp_path):
    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(BASELINE.read_text())
    conn.commit()
    conn.close()
    engine = create_engine(f"sqlite:///{db}")
    init_schema(engine)
    yield engine
    engine.dispose()


def test_baseline_db_upgraded_to_full_model_schema(upgraded_engine):
    insp = inspect(upgraded_engine)
    for table in Base.metadata.tables.values():
        actual = {c["name"] for c in insp.get_columns(table.name)}
        expected = {c.name for c in table.columns}
        missing = expected - actual
        assert not missing, (
            f"table {table.name} is missing columns {sorted(missing)} after "
            "init_schema on a legacy DB — register them in _ADDED_COLUMNS "
            "(src/pce_cache/schema.py); do NOT regenerate the baseline fixture"
        )


def test_baseline_db_gets_migration_marker_and_indexes(upgraded_engine):
    with upgraded_engine.connect() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar()
    assert version >= 1  # _MIGRATION_AGG_BUCKET_DAY ran on the legacy DB
    raw_indexes = {
        ix["name"]
        for ix in inspect(upgraded_engine).get_indexes("pce_traffic_flows_raw")
    }
    assert "ix_raw_last_action" in raw_indexes
```

- [ ] **Step 3: 執行測試，確認通過（此為防未來的守門測試，現況即應綠燈）**

Run: `python3 -m pytest tests/test_schema_drift_guard.py -v`
Expected: 2 passed

- [ ] **Step 4: 手動驗證守門有效（臨時弄髒，驗後還原）**

在 `src/pce_cache/models.py` 的 `PceTrafficFlowRaw` 任意加一行 `dummy_guard_check = mapped_column(Text, nullable=True)`（比照該檔既有欄位寫法），重跑：

Run: `python3 -m pytest tests/test_schema_drift_guard.py -v`
Expected: `test_baseline_db_upgraded_to_full_model_schema` FAIL，訊息含 `missing columns ['dummy_guard_check']` 與「register them in _ADDED_COLUMNS」指引。

驗證後 **還原 models.py**（`git checkout -- src/pce_cache/models.py`），重跑確認回綠。

- [ ] **Step 5: 寫 downgrade 警示的失敗測試**

附加到 `tests/test_schema_drift_guard.py`：

```python
def test_newer_db_user_version_logs_downgrade_warning(tmp_path):
    from loguru import logger

    from src.pce_cache.schema import _normalize_agg_bucket_day

    db = tmp_path / "newer.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    init_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA user_version = 99"))

    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        _normalize_agg_bucket_day(engine)
    finally:
        logger.remove(sink_id)
    engine.dispose()
    assert any("user_version=99" in m for m in messages), messages
```

- [ ] **Step 6: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_schema_drift_guard.py::test_newer_db_user_version_logs_downgrade_warning -v`
Expected: FAIL — 無 warning 訊息（現行程式碼靜默 return）。

- [ ] **Step 7: 實作 downgrade 警示**

`src/pce_cache/schema.py` 檔頭 import 區（`from sqlalchemy import event, text` 之前）加：

```python
from loguru import logger
```

`_normalize_agg_bucket_day` 內（`schema.py:155-158`）把：

```python
    with engine.begin() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar()
        if version >= _MIGRATION_AGG_BUCKET_DAY:
            return
```

改為：

```python
    with engine.begin() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar()
        if version > _MIGRATION_AGG_BUCKET_DAY:
            # DB 曾被更新版程式碼遷移過（downgrade 情境）。repo 不支援
            # downgrade——不動資料、只警示，讓 operator 有跡可循。
            logger.warning(
                "pce_cache db user_version={} is newer than this build "
                "understands (max {}); the DB was migrated by newer code and "
                "downgrade is unsupported — upgrade this installation",
                version, _MIGRATION_AGG_BUCKET_DAY,
            )
            return
        if version >= _MIGRATION_AGG_BUCKET_DAY:
            return
```

- [ ] **Step 8: 執行測試，確認通過**

Run: `python3 -m pytest tests/test_schema_drift_guard.py -v`
Expected: 3 passed

- [ ] **Step 9: Commit**

```bash
git add tests/fixtures/pce_cache_baseline_schema.sql tests/test_schema_drift_guard.py src/pce_cache/schema.py
git commit -m "test(schema): frozen-baseline drift guard; warn on newer db user_version"
```

---

### Task 4: siem CLI 收窄 OperationalError 兜底

**Files:**
- Modify: `src/cli/siem.py:141-162`（status）、`src/cli/siem.py:210-213`（replay）
- Test: `tests/test_siem_cli_operational_error.py`

**Interfaces:**
- Produces: `src/cli/siem.py` 模組層私有函式 `_is_first_run_db_error(exc: OperationalError) -> bool`。
- Consumes: 既有 `echo_error`、`EXIT_SOFTWARE`（`src/cli/_exit_codes.py`）、`from src.cli.root import cli`。

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_siem_cli_operational_error.py`：

```python
"""siem status/replay must only render the zero-count fallback for genuine
first-run states (db file absent). Schema mismatches must surface as errors —
previously any OperationalError silently rendered zeros (analysis 2026-07-12).
"""
import sqlite3
from types import SimpleNamespace

from click.testing import CliRunner
from sqlalchemy.exc import OperationalError

from src.cli._exit_codes import EXIT_SOFTWARE
from src.cli.root import cli
from src.cli.siem import _is_first_run_db_error


def _op_error(msg: str) -> OperationalError:
    return OperationalError(msg, None, Exception(msg))


def test_first_run_signatures_classified():
    assert _is_first_run_db_error(_op_error("no such table: siem_dispatch"))
    assert _is_first_run_db_error(_op_error("unable to open database file"))
    assert not _is_first_run_db_error(
        _op_error("no such column: siem_dispatch.destination")
    )
    assert not _is_first_run_db_error(_op_error("database disk image is malformed"))


class _StubCM:
    def __init__(self, db_path: str):
        self.models = SimpleNamespace(
            pce_cache=SimpleNamespace(db_path=db_path),
            siem=SimpleNamespace(destinations=[]),
        )


def test_status_surfaces_schema_mismatch(tmp_path, monkeypatch):
    # 造一張缺欄位的 siem_dispatch 舊表，並讓 init_schema 不修它，
    # 模擬「schema 異常但兜底把它吞掉」的原始情境。
    db = tmp_path / "stale.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE siem_dispatch (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr("src.config.ConfigManager", lambda: _StubCM(str(db)))
    monkeypatch.setattr("src.pce_cache.schema.init_schema", lambda engine: None)

    result = CliRunner().invoke(cli, ["siem", "status"])
    assert result.exit_code == EXIT_SOFTWARE
    assert "no such column" in result.output


def test_status_zero_fallback_when_db_absent(tmp_path, monkeypatch):
    db = tmp_path / "nonexistent-dir" / "cache.sqlite"  # 目錄不存在 → 開檔失敗
    monkeypatch.setattr("src.config.ConfigManager", lambda: _StubCM(str(db)))

    result = CliRunner().invoke(cli, ["siem", "status"])
    assert result.exit_code == 0  # 首次執行情境維持原有的優雅降級
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_siem_cli_operational_error.py -v`
Expected: FAIL — `ImportError: cannot import name '_is_first_run_db_error'`

- [ ] **Step 3: 實作**

`src/cli/siem.py` 在 `_render_status_table`（siem.py:168）之前加入：

```python
def _is_first_run_db_error(exc: OperationalError) -> bool:
    """True only when the OperationalError means the cache DB doesn't exist
    yet (first run before any collection) — the sole case where a zero-count
    fallback is honest. Schema mismatches ("no such column") and corruption
    must surface as errors instead of silently rendering zeros."""
    msg = str(exc).lower()
    return "no such table" in msg or "unable to open database file" in msg
```

status 的兜底（siem.py:141-144）把：

```python
    except OperationalError:
        # SIEM cache db not initialized — first-run / pre-collect path.
        # Still surface configured destinations with zero counts so the CLI
        # agrees with the WebUI's configured-destinations view.
```

改為：

```python
    except OperationalError as exc:
        if not _is_first_run_db_error(exc):
            # Schema mismatch / corruption — surface it; zeros would lie.
            echo_error(ctx, str(exc))
            ctx.exit(EXIT_SOFTWARE)
        # SIEM cache db not initialized — first-run / pre-collect path.
        # Still surface configured destinations with zero counts so the CLI
        # agrees with the WebUI's configured-destinations view.
```

replay 的兜底（siem.py:210-213）把：

```python
    except OperationalError:
        # SIEM cache db not initialized — replay needs existing dispatch records.
        echo_error(ctx, t("cli_siem_err_no_replay_data", dest=dest))
        ctx.exit(1)
```

改為：

```python
    except OperationalError as exc:
        if not _is_first_run_db_error(exc):
            echo_error(ctx, str(exc))
            ctx.exit(EXIT_SOFTWARE)
        # SIEM cache db not initialized — replay needs existing dispatch records.
        echo_error(ctx, t("cli_siem_err_no_replay_data", dest=dest))
        ctx.exit(1)
```

注意：`ctx.exit()` 會拋 SystemExit/click 例外，click 的 CliRunner 與正式執行都會正確結束，不會落到同一個 try 的 `except Exception` 分支（`ctx.exit` 拋的是 `click.exceptions.Exit`，不被 `except Exception as exc` 之前的 OperationalError handler 重複處理；實作後以測試驗證 exit code 為準）。

- [ ] **Step 4: 執行測試，確認通過**

Run: `python3 -m pytest tests/test_siem_cli_operational_error.py -v`
Expected: 3 passed

- [ ] **Step 5: 跑既有 siem CLI 測試，確認無回歸**

Run: `python3 -m pytest tests/ -k "siem" -q`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/cli/siem.py tests/test_siem_cli_operational_error.py
git commit -m "fix(cli): surface non-first-run OperationalError in siem status/replay"
```

---

### Task 5: install.sh 安裝 CLI wrapper、uninstall.sh 移除、文件同步

**Files:**
- Modify: `scripts/install.sh:186-200`（systemd 區塊之後、結尾訊息之前）
- Modify: `scripts/uninstall.sh:37-38`（service 移除區塊）
- Modify: `docs/getting-started.md`（install 章節，約 L110 的 code block 之後）
- Modify: `docs/getting-started_zh.md`（同位置，中文版）
- Test: `tests/test_install_wrapper_contract.py`

**Interfaces:**
- Produces: 目標機上的 `/usr/local/bin/illumio-ops` wrapper（exec bundle Python）。
- Consumes: 無。

- [ ] **Step 1: 寫失敗的契約測試**

比照 `tests/test_build_offline_bundle_doc.py` 的靜態契約測試模式，建立 `tests/test_install_wrapper_contract.py`：

```python
"""Contract: install.sh must install a /usr/local/bin/illumio-ops wrapper that
execs the bundled Python (system python3 on old distros has SQLite < 3.35 and
breaks INSERT ... RETURNING), and uninstall.sh must remove it."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_install_creates_cli_wrapper():
    src = (ROOT / "scripts" / "install.sh").read_text()
    assert "/usr/local/bin/illumio-ops" in src
    assert 'exec "$INSTALL_ROOT/python/bin/python3"' in src


def test_uninstall_removes_cli_wrapper():
    src = (ROOT / "scripts" / "uninstall.sh").read_text()
    assert "rm -f /usr/local/bin/illumio-ops" in src
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_install_wrapper_contract.py -v`
Expected: 2 FAIL（兩個腳本目前都沒有 wrapper 內容）

- [ ] **Step 3: 修改 install.sh**

在 `scripts/install.sh:188`（`systemctl daemon-reload` 之後、`if [ "$IS_UPGRADE" = true ]` 之前）插入：

```bash
# CLI wrapper: give operators a stable `illumio-ops` command that always uses
# the bundled Python. Running the app with the system python3 breaks on old
# distros (system SQLite < 3.35 lacks INSERT ... RETURNING).
WRAPPER=/usr/local/bin/illumio-ops
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
exec "$INSTALL_ROOT/python/bin/python3" "$INSTALL_ROOT/illumio-ops.py" "\$@"
EOF
chmod 0755 "$WRAPPER"
```

並在結尾兩個分支的訊息各加一行（upgrade 分支加在 `Restart service` 行後、fresh 分支加在 `Start service` 行後）：

```bash
    echo "    CLI usage    : illumio-ops --help   (wrapper installed at /usr/local/bin/illumio-ops)"
```

- [ ] **Step 4: 修改 uninstall.sh**

`scripts/uninstall.sh:37` 的 `rm -f "$SERVICE_FILE"` 之後加：

```bash
rm -f /usr/local/bin/illumio-ops
```

- [ ] **Step 5: 語法檢查與測試**

Run: `bash -n scripts/install.sh && bash -n scripts/uninstall.sh && python3 -m pytest tests/test_install_wrapper_contract.py -v`
Expected: bash -n 無輸出；2 passed

- [ ] **Step 6: 同步文件（中英成對）**

`docs/getting-started.md` 在 install 章節的 `sudo ./install.sh` code block（約 L110）之後加一段：

```markdown
After installation a CLI wrapper is available as `illumio-ops` (installed to
`/usr/local/bin/illumio-ops`). Always use the wrapper (or the bundled
interpreter at `/opt/illumio-ops/python/bin/python3`) for manual CLI
operations — the system `python3` on older distros links a SQLite that is too
old for this application (>= 3.35.0 required) and the app will refuse to start.
```

`docs/getting-started_zh.md` 同位置加：

```markdown
安裝完成後會提供 `illumio-ops` CLI wrapper（位於
`/usr/local/bin/illumio-ops`）。手動執行 CLI 操作時一律使用 wrapper（或
bundle 內建直譯器 `/opt/illumio-ops/python/bin/python3`）——舊發行版的系統
`python3` 連結的 SQLite 版本過舊（本應用需要 >= 3.35.0），應用程式會拒絕啟動。
```

Run: `bash scripts/check_doc_coverage.sh && python3 scripts/docs_check.py`
Expected: 皆通過（雙語文件同步檢查不噴錯）

- [ ] **Step 7: Commit**

```bash
git add scripts/install.sh scripts/uninstall.sh tests/test_install_wrapper_contract.py docs/getting-started.md docs/getting-started_zh.md
git commit -m "feat(install): install /usr/local/bin/illumio-ops CLI wrapper (bundled python)"
```

---

### Task 6: preflight.sh 加 SQLite 版本檢查與既有 DB 回報

**Files:**
- Modify: `scripts/preflight.sh:79-96`（bundled Python 檢查之後、port 檢查之前）
- Test: `tests/test_preflight_contract.py`

**Interfaces:**
- Consumes: 下限 3.35.0（與 `src/runtime_checks.py` 的 `MIN_SQLITE_VERSION` 同值，bash 側為複製，兩處註解互相指向）。
- Produces: preflight 輸出兩個新檢查項：`Bundled SQLite` 與 `Existing cache DB`。

- [ ] **Step 1: 寫失敗的契約測試**

建立 `tests/test_preflight_contract.py`：

```python
"""Contract: preflight.sh must check the bundled Python's SQLite floor
(3.35.0, mirror of src/runtime_checks.MIN_SQLITE_VERSION) and report the
existing cache DB state on upgrades."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_preflight_checks_bundled_sqlite_floor():
    compact = (ROOT / "scripts" / "preflight.sh").read_text().replace(" ", "")
    assert "sqlite_version_info>=(3,35,0)" in compact
    assert "BundledSQLite" in compact  # pass/fail 標籤存在


def test_preflight_reports_existing_cache_db():
    src = (ROOT / "scripts" / "preflight.sh").read_text()
    assert "data/pce_cache.sqlite" in src
    assert "user_version" in src
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_preflight_contract.py -v`
Expected: 2 FAIL

- [ ] **Step 3: 修改 preflight.sh**

在 `scripts/preflight.sh:81`（`Bundled Python` 檢查的 `fi` 之後）插入：

```bash
# 6b. Bundled Python SQLite floor — INSERT ... RETURNING needs >= 3.35.0.
# Mirror of MIN_SQLITE_VERSION in src/runtime_checks.py; keep in sync.
if [ -x "$BUNDLED_PY" ]; then
    SQLITE_VER=$("$BUNDLED_PY" -c 'import sqlite3; print(sqlite3.sqlite_version)' 2>/dev/null || echo "unknown")
    SQLITE_OK=$("$BUNDLED_PY" -c 'import sqlite3; print(1 if sqlite3.sqlite_version_info >= (3, 35, 0) else 0)' 2>/dev/null || echo 0)
    if [ "$SQLITE_OK" = "1" ]; then pass "Bundled SQLite: $SQLITE_VER (>= 3.35.0 required)"
    else fail "Bundled SQLite: $SQLITE_VER — requires >= 3.35.0"; fi
fi
```

在升級偵測區塊（`scripts/preflight.sh:84-89` 的 `fi` 之後）插入：

```bash
# 7b. Existing cache DB (upgrade only, informational). Requires read access —
# run preflight with sudo on upgrades for an accurate result.
DB_FILE="$INSTALL_ROOT/data/pce_cache.sqlite"
if [ -f "$DB_FILE" ] && [ -x "$BUNDLED_PY" ]; then
    DB_USER_VERSION=$("$BUNDLED_PY" -c "
import sqlite3, sys
conn = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True)
print(conn.execute('PRAGMA user_version').fetchone()[0])
" "$DB_FILE" 2>/dev/null || echo "unreadable")
    if [ "$DB_USER_VERSION" = "unreadable" ]; then
        warn "Existing cache DB at $DB_FILE could not be opened read-only — check permissions (re-run with sudo) or corruption before upgrading"
    else
        pass "Existing cache DB: user_version=$DB_USER_VERSION (schema migrates automatically on next service start)"
    fi
fi
```

- [ ] **Step 4: 語法檢查、契約測試、實跑**

Run: `bash -n scripts/preflight.sh && python3 -m pytest tests/test_preflight_contract.py -v`
Expected: bash -n 無輸出；2 passed

Run: `bash scripts/preflight.sh --install-root /tmp/preflight-smoke-$$ ; echo "exit=$?"`
Expected: 各檢查逐項輸出；新項目 `Bundled SQLite` 在開發機沒有 bundle 目錄時不輸出（`BUNDLED_PY` 不存在即跳過），不得產生語法錯誤。exit code 依環境（缺 bundle 目錄會 FAIL 屬預期，重點是腳本能跑完並輸出報告）。

- [ ] **Step 5: Commit**

```bash
git add scripts/preflight.sh tests/test_preflight_contract.py
git commit -m "feat(preflight): check bundled SQLite floor and report existing cache DB"
```

---

### Task 7: 升級套件更新決定性（pristine runtime 重裝 + 殭屍模組清除）

**Files:**
- Modify: `scripts/install.sh:133`（python rsync）、`scripts/install.sh:135-140`（upgrade 分支 app rsync）、`scripts/install.sh:146-148`（pip 註解）
- Test: `tests/test_install_lifecycle_contract.py`（新建，Task 8 也會擴充此檔）

**Interfaces:**
- Produces: 升級後 `INSTALL_ROOT/python/` 與 site-packages 保證與 bundle 完全一致；`INSTALL_ROOT` 下不再殘留已刪除的 src 模組。
- Consumes: 無。

- [ ] **Step 1: 寫失敗的契約測試**

建立 `tests/test_install_lifecycle_contract.py`：

```python
"""Contract: install.sh upgrades must be deterministic.

- python/ is rsynced with --delete: restores a pristine bundled runtime
  (including its site-packages), so the following pip install from bundle
  wheels yields exactly the bundle's package set — no stale versions
  (range specs like `requests>=2.31,<3.0` would otherwise let pip skip
  already-satisfied packages), no orphaned packages (e.g. removed plotly).
- app rsync on upgrade uses --delete with operator/runtime dirs excluded,
  so renamed/deleted src modules cannot linger as importable zombies.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _install_sh() -> str:
    return (ROOT / "scripts" / "install.sh").read_text()


def test_python_runtime_rsync_restores_pristine():
    assert 'rsync -a --delete "$SRC/python/" "$INSTALL_ROOT/python/"' in _install_sh()


def test_upgrade_app_rsync_deletes_stale_files_with_guards():
    src = _install_sh()
    # upgrade 分支必須帶 --delete，且逐一排除 operator/runtime 目錄
    assert "rsync -a --delete \\" in src
    for excl in ("config/", "data/", "logs/", "reports/", "python/",
                 "MIGRATED_FROM", "uninstall.sh"):
        assert f"--exclude='{excl}'" in src, f"missing --exclude for {excl}"
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_install_lifecycle_contract.py -v`
Expected: 2 FAIL

- [ ] **Step 3: 修改 install.sh**

`scripts/install.sh:133` 把：

```bash
rsync -a "$SRC/python/" "$INSTALL_ROOT/python/"
```

改為：

```bash
# --delete restores a pristine bundled runtime each install/upgrade. This is
# what makes the dependency refresh deterministic: site-packages is reset to
# the bundle's baseline, then pip below installs exactly the bundled wheels.
# Without it, range specs in requirements-offline.txt let pip keep stale
# already-satisfied versions, and removed dependencies linger forever.
rsync -a --delete "$SRC/python/" "$INSTALL_ROOT/python/"
```

`scripts/install.sh:135-140` 的 upgrade 分支把：

```bash
if [ "$IS_UPGRADE" = true ]; then
    # Preserve all of config/ on upgrade — never overwrite operator-owned files
    rsync -a --exclude='config/' "$SRC/app/" "$INSTALL_ROOT/"
```

改為：

```bash
if [ "$IS_UPGRADE" = true ]; then
    # Preserve all of config/ on upgrade — never overwrite operator-owned files.
    # --delete removes app files that no longer exist in the new release:
    # renamed/deleted src modules would otherwise linger as importable zombie
    # .py files. Operator/runtime dirs are excluded from deletion.
    rsync -a --delete \
        --exclude='config/' --exclude='data/' --exclude='logs/' \
        --exclude='reports/' --exclude='python/' \
        --exclude='MIGRATED_FROM' --exclude='uninstall.sh' \
        "$SRC/app/" "$INSTALL_ROOT/"
```

`scripts/install.sh:146-148` 的 pip 呼叫前加註解（指令本身不變——runtime 已 pristine，無需 `--upgrade`）：

```bash
# site-packages was reset by the python/ rsync above, so this installs the
# bundle's exact wheel set (deterministic; no --upgrade needed).
```

- [ ] **Step 4: 語法檢查與測試**

Run: `bash -n scripts/install.sh && python3 -m pytest tests/test_install_lifecycle_contract.py -v`
Expected: bash -n 無輸出；2 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/install.sh tests/test_install_lifecycle_contract.py
git commit -m "fix(install): deterministic dependency refresh and stale-file cleanup on upgrade"
```

---

### Task 8: 升級防呆（downgrade 阻擋、服務運行守衛）與安裝後檢測

**Files:**
- Modify: `scripts/install.sh:10-15`（參數解析加 `--allow-downgrade`）、`scripts/install.sh:124-127`（IS_UPGRADE 偵測之後插入守衛）、`scripts/install.sh:168` 之後（config 遷移後插入安裝後檢測）
- Test: `tests/test_install_lifecycle_contract.py`（擴充）

**Interfaces:**
- Consumes: bundle 根目錄 `VERSION` 檔（`build_offline_bundle.sh:74` 產生）；已安裝版本自 `$INSTALL_ROOT/src/__init__.py` 的 `__version__` 讀取（與 `scripts/resolve_version.sh:19` 同一 sed 模式）；`scripts/verify_deps.py --offline-bundle`（bundle 已含 scripts/）。
- Produces: 升級防呆行為——bundle 版本較舊時拒絕安裝（除非 `--allow-downgrade`）；服務運行中自動停止並提示；安裝後相依驗證 + app 煙霧測試，失敗即中止。

- [ ] **Step 1: 擴充契約測試**

附加到 `tests/test_install_lifecycle_contract.py`：

```python
def test_upgrade_has_downgrade_guard():
    src = _install_sh()
    assert "--allow-downgrade" in src
    assert "sort -V" in src  # 版本比較
    assert "__version__" in src  # 讀取已安裝版本


def test_upgrade_stops_running_service():
    src = _install_sh()
    assert 'systemctl is-active --quiet "$SERVICE_NAME"' in src


def test_post_install_verification_runs():
    src = _install_sh()
    assert "verify_deps.py" in src
    assert "--offline-bundle" in src
    assert "illumio-ops.py --help" in src  # app 煙霧測試
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_install_lifecycle_contract.py -v`
Expected: 新增 3 個測試 FAIL（Task 7 的 2 個 PASS）

- [ ] **Step 3: 實作 install.sh 守衛與檢測**

參數解析（`scripts/install.sh:9-15`）改為：

```bash
INSTALL_ROOT="/opt/illumio-ops"
ALLOW_DOWNGRADE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-root) INSTALL_ROOT="$2"; shift 2 ;;
        --allow-downgrade) ALLOW_DOWNGRADE=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done
```

`IS_UPGRADE` 偵測（`install.sh:124-125`）之後、`echo "==> Installing ..."` 之前插入：

```bash
# --- Upgrade guards ---------------------------------------------------------
if [ "$IS_UPGRADE" = true ]; then
    # Downgrade guard: db schema migrations are forward-only (PRAGMA
    # user_version); installing an older bundle over a newer install is
    # unsupported. Compare base versions (strip +hash dev suffix).
    BUNDLE_BASE="$(cat "$SRC/VERSION" 2>/dev/null || echo unknown)"
    BUNDLE_BASE="${BUNDLE_BASE%%+*}"
    INSTALLED_VERSION=$(sed -n 's/^__version__ *= *["'"'"']\([^"'"'"']*\)["'"'"'].*/\1/p' \
        "$INSTALL_ROOT/src/__init__.py" 2>/dev/null || true)
    if [ -n "$INSTALLED_VERSION" ] && [ "$BUNDLE_BASE" != "unknown" ] \
       && [ "$BUNDLE_BASE" != "$INSTALLED_VERSION" ] \
       && [ "$(printf '%s\n%s\n' "$BUNDLE_BASE" "$INSTALLED_VERSION" | sort -V | tail -1)" = "$INSTALLED_VERSION" ]; then
        if [ "$ALLOW_DOWNGRADE" != true ]; then
            echo "ERROR: bundle version $BUNDLE_BASE is older than installed $INSTALLED_VERSION." >&2
            echo "       Downgrade is unsupported (db schema migrations are forward-only)." >&2
            echo "       Re-run with --allow-downgrade to proceed anyway." >&2
            exit 1
        fi
        echo "WARNING: downgrading $INSTALLED_VERSION -> $BUNDLE_BASE (--allow-downgrade given)."
    fi
    # Service guard: upgrading files under a running service risks a torn
    # state (old process, new site-packages). Stop it; operator restarts
    # after reviewing the install output (docs already instruct this).
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        echo "==> Stopping running service for upgrade"
        systemctl stop "$SERVICE_NAME" || {
            echo "ERROR: failed to stop $SERVICE_NAME; stop it manually and re-run." >&2
            exit 1
        }
        echo "    NOTE: restart after install: sudo systemctl restart $SERVICE_NAME"
    fi
fi
```

config 遷移區塊結尾（`install.sh:168` 的 `fi` 之後）、`useradd` 之前插入（放在 `chown -R` 之前，驗證過程產生的 `__pycache__` 會被後續 chown 一併修正擁有者）：

```bash
# --- Post-install verification -----------------------------------------------
echo "==> Verifying installed dependencies"
"$INSTALL_ROOT/python/bin/python3" "$INSTALL_ROOT/scripts/verify_deps.py" --offline-bundle || {
    echo "ERROR: dependency verification failed — installation is incomplete." >&2
    exit 1
}
(cd "$INSTALL_ROOT" && ./python/bin/python3 illumio-ops.py --help >/dev/null) || {
    echo "ERROR: app smoke check failed (illumio-ops.py --help)." >&2
    exit 1
}
echo "    Dependency and smoke checks passed."
```

- [ ] **Step 4: 語法檢查與測試**

Run: `bash -n scripts/install.sh && python3 -m pytest tests/test_install_lifecycle_contract.py -v`
Expected: bash -n 無輸出；5 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/install.sh tests/test_install_lifecycle_contract.py
git commit -m "feat(install): downgrade guard, running-service guard, post-install verification"
```

---

### Task 9: uninstall 非 purge 模式保留 data/

**Files:**
- Modify: `scripts/uninstall.sh:40-48`
- Test: `tests/test_install_lifecycle_contract.py`（擴充）

**Interfaces:**
- Produces: 非 `--purge` 移除時 `config/` 與 `data/`（含 DB）皆保留；`--purge` 行為不變（全刪）。
- Consumes: 無。

- [ ] **Step 1: 擴充契約測試**

附加到 `tests/test_install_lifecycle_contract.py`：

```python
def test_uninstall_preserves_data_by_default():
    src = (ROOT / "scripts" / "uninstall.sh").read_text()
    assert "! -name 'config' ! -name 'data'" in src
    assert "Data preserved" in src
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `python3 -m pytest tests/test_install_lifecycle_contract.py::test_uninstall_preserves_data_by_default -v`
Expected: FAIL

- [ ] **Step 3: 修改 uninstall.sh**

`scripts/uninstall.sh:43-48` 的 else 分支把：

```bash
    echo "==> Removing $INSTALL_ROOT (preserving config/)"
    find "$INSTALL_ROOT" -mindepth 1 -maxdepth 1 ! -name 'config' -exec rm -rf {} +
    echo "    Config preserved at: $INSTALL_ROOT/config/"
    echo "    To fully remove:     sudo rm -rf $INSTALL_ROOT"
```

改為：

```bash
    echo "==> Removing $INSTALL_ROOT (preserving config/ and data/)"
    find "$INSTALL_ROOT" -mindepth 1 -maxdepth 1 ! -name 'config' ! -name 'data' -exec rm -rf {} +
    echo "    Config preserved at: $INSTALL_ROOT/config/"
    echo "    Data preserved at:   $INSTALL_ROOT/data/  (cache DB; reinstall picks it up)"
    echo "    To fully remove:     sudo rm -rf $INSTALL_ROOT"
```

- [ ] **Step 4: 語法檢查與測試**

Run: `bash -n scripts/uninstall.sh && python3 -m pytest tests/test_install_lifecycle_contract.py -v`
Expected: bash -n 無輸出；6 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/uninstall.sh tests/test_install_lifecycle_contract.py
git commit -m "feat(uninstall): preserve data/ alongside config/ unless --purge"
```

---

### Task 10: 文件更新——升級 SOP、防呆/檢測說明、修正文實不符

**Files:**
- Modify: `docs/getting-started.md`（Upgrade 章節，約 L214-235）
- Modify: `docs/getting-started_zh.md`（同章節中文版）
- Modify: `docs/contributing/release-process.md`（約 L120-135 的 installer 行為描述）

**Interfaces:**
- Consumes: Tasks 5、7、8、9 的最終行為（wrapper、決定性套件更新、防呆與檢測、data 保留）。
- Produces: 三份文件與實作一致；中英成對檔同步。

- [ ] **Step 1: 更新 getting-started.md Upgrade 章節**

在「Files preserved across upgrades: ...」段落之後新增：

```markdown
**What the installer does on upgrade** (`install.sh` built-in guards):

1. Refuses to install a bundle older than the installed version
   (db schema migrations are forward-only). Override with
   `sudo ./install.sh --allow-downgrade` only if you know what you are doing.
2. Stops the service automatically if it is running (you restart it after
   reviewing the output).
3. Restores a pristine bundled Python runtime and reinstalls the exact wheel
   set shipped in the bundle — dependency versions on the box always match
   the bundle after an upgrade, and files removed in the new release are
   cleaned up.
4. Verifies the installation before finishing: every production dependency
   must import (`scripts/verify_deps.py --offline-bundle`) and the app must
   answer `illumio-ops.py --help`. A failed check aborts the install with a
   non-zero exit code.

**Uninstall** keeps `config/` and `data/` (the cache DB) unless you pass
`--purge`; a later reinstall picks both up automatically.
```

- [ ] **Step 2: 同步 getting-started_zh.md**

同位置新增：

```markdown
**升級時 installer 的內建行為**（`install.sh` 防呆與檢測）：

1. 拒絕安裝比已裝版本更舊的 bundle（DB schema 遷移只能前進）。確有需要時
   以 `sudo ./install.sh --allow-downgrade` 覆寫。
2. 服務運行中會自動停止（安裝完成、檢視輸出後由你重啟）。
3. 還原 pristine 的 bundle 內建 Python runtime 並全量重裝 bundle 內的
   wheel——升級後機器上的相依版本必定與 bundle 一致，新版已移除的檔案
   也會被清掉。
4. 完成前自動驗證：所有正式相依必須可 import
   （`scripts/verify_deps.py --offline-bundle`），且 app 能回應
   `illumio-ops.py --help`。任一檢查失敗即中止並回傳非零 exit code。

**移除**：未加 `--purge` 時保留 `config/` 與 `data/`（快取 DB），之後重新
安裝會自動沿用。
```

- [ ] **Step 3: 修正 release-process.md 的文實不符**

`docs/contributing/release-process.md` 約 L131-135 把：

```markdown
After the dependency refresh, the installer restarts `illumio-ops.service` only
when `IS_UPGRADE=true` — fresh installs leave the service stopped so the
operator can review settings first.
```

改為：

```markdown
The installer never starts the service itself. On upgrade it stops a running
service before touching files (torn-state guard) and reminds the operator to
restart afterwards; fresh installs leave the service stopped so the operator
can review settings first. Upgrades additionally refuse a version downgrade
unless `--allow-downgrade` is passed, restore a pristine bundled runtime
before reinstalling wheels (deterministic dependency refresh), and abort on a
failed post-install verification (`scripts/verify_deps.py --offline-bundle`
plus an `illumio-ops.py --help` smoke check).
```

同檔案 L120-129 的 pip 內部指令描述若與新註解不一致，一併對齊（指令本身未變，敘述補上「site-packages 已被 python/ rsync 重設」前提）。

- [ ] **Step 4: 文件一致性檢查**

Run: `bash scripts/check_doc_coverage.sh && python3 scripts/docs_check.py`
Expected: 皆通過（中英成對同步、連結有效）

- [ ] **Step 5: Commit**

```bash
git add docs/getting-started.md docs/getting-started_zh.md docs/contributing/release-process.md
git commit -m "docs: align upgrade SOP with installer guards and verification"
```

---

### Task 11: 全套驗證與 CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`（頂部新增本次條目，格式比照既有條目）

**Interfaces:**
- Consumes: Tasks 1-10 全部完成。

- [ ] **Step 1: 跑完整測試套件**

Run: `python3 -m pytest tests/ -q`
Expected: all passed（含新增的 7 個測試檔）。如有既有測試因 Task 2/4 的行為改動而失敗，逐一檢視：預期內的行為變更（例如依賴舊二元組格式的測試）修測試；非預期的回歸修程式。另跑 `bash -n scripts/install.sh scripts/uninstall.sh scripts/preflight.sh` 確認三支腳本語法無誤。

- [ ] **Step 2: Lint**

Run: `python3 -m ruff check src/ tests/ 2>/dev/null || ruff check src/ tests/`
Expected: 新增/修改檔案無新告警（既有 legacy 告警不在本次範圍）。

- [ ] **Step 3: 更新 CHANGELOG.md**

在 `CHANGELOG.md` 頂部（比照既有條目格式與語言）新增條目，內容涵蓋：
- Fail-fast SQLite runtime check (>= 3.35.0) at entry point
- `/usr/local/bin/illumio-ops` CLI wrapper installed by install.sh
- preflight: bundled SQLite floor check + existing cache DB report
- schema: table-qualified `_ADDED_COLUMNS`, frozen-baseline drift guard test, downgrade warning on newer `user_version`
- siem CLI: schema errors no longer masked by the first-run zero-count fallback
- install: deterministic dependency refresh (pristine runtime + full wheel reinstall), stale-file cleanup on upgrade, downgrade guard (`--allow-downgrade`), running-service guard, post-install verification (verify_deps + smoke check)
- uninstall: `data/` preserved alongside `config/` unless `--purge`
- docs: upgrade SOP aligned with actual installer behavior (installer never restarts the service itself)

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): offline bundle db hardening entries"
```

- [ ] **Step 5: 真環境驗證（測試機，選配但建議）**

在測試機（illumio-ops-test）以新 bundle 走一次 preflight + install 升級流程，逐項確認：
1. `bash preflight.sh` 顯示 `Bundled SQLite: 3.x (>= 3.35.0 required)` PASS 與 `Existing cache DB: user_version=1` PASS。
2. 服務運行中直接 `sudo ./install.sh`：installer 自動停止服務並提示重啟（服務運行守衛生效）。
3. 安裝輸出包含 `Verifying installed dependencies` 且 `Dependency and smoke checks passed`（安裝後檢測生效）。
4. `pip list` 對照 bundle wheels 版本一致（決定性套件更新生效）；升級前若曾有孤兒套件（如 plotly），升級後消失。
5. `/usr/local/bin/illumio-ops --help` 可用（wrapper 生效）。
6. 拿一份較舊版本的 bundle 重跑 `sudo ./install.sh`：被 downgrade 守衛擋下並提示 `--allow-downgrade`。
7. `sudo systemctl restart illumio-ops` 後服務健康、journal 無錯誤、GUI 回應正常。
8. （選配）`sudo /opt/illumio-ops/uninstall.sh` 後確認 `config/` 與 `data/` 保留，再重裝確認 DB 被沿用。

---

## Self-Review 紀錄

- 問題清單 10 項皆有對應任務（見「背景」一節對照表）；out-of-scope 4 項已明列。
- 無 TBD/placeholder；每個程式碼步驟均含完整程式碼。
- 型別/名稱一致性：`_is_first_run_db_error`（Task 4 定義與測試 import 一致）、`MIN_SQLITE_VERSION = (3, 35, 0)`（Task 1 定義，Task 6 bash 側複製並互相註解指向）、`_ADDED_COLUMNS` 三元組格式（Task 2 定義，Task 3 漂移測試訊息引用）、`tests/test_install_lifecycle_contract.py` 由 Task 7 建立、Task 8/9 擴充（執行順序即任務順序）。
- 已知風險：Task 4 Step 3 中 `ctx.exit()` 於 except 區塊內的行為以測試把關（Step 4 驗證 exit code）；Task 3 baseline fixture 凍結政策已寫入 fixture 檔頭註解與測試 docstring 雙處；Task 7 的 `rsync --delete` 排除清單若遺漏 operator 檔案會誤刪——排除項已逐一對照 install.sh 實際寫入 INSTALL_ROOT 的內容（config/、data/、logs/、reports/、python/、MIGRATED_FROM、uninstall.sh），真環境驗證（Task 11 Step 5）再次把關。
- 文件影響：Task 5 與 Task 10 都動 `getting-started*.md`——Task 10 的內容錨定在 Upgrade 章節、Task 5 在 Install 章節，不衝突；兩任務各自跑 doc 檢查。
