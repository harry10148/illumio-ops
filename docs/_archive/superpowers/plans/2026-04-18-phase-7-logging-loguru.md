# Phase 7 Implementation Plan — Logging 完整替換 (loguru)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以 loguru 完整取代所有 `import logging` / `logger = logging.getLogger(__name__)` 的用法（主程式側 33 檔，實際匯入約 77 檔）。保留 [src/module_log.py](../../../src/module_log.py) — 它是 GUI 即時 log 視圖的業務邏輯，不屬於 logging infra。loguru 作為 sink 與 formatter 的統一底層，同時提供結構化 JSON 選項供 SIEM 收集。

**Architecture:** **Codemod-driven mechanical replacement**。寫一支 `scripts/migrate_to_loguru.py`，自動化：
1. `import logging` → `from loguru import logger`（移除 module-level `logger = logging.getLogger(__name__)`）
2. `logger.info("x %s", v)` → `logger.info("x {}", v)`（%s → {}, %d → {} 等格式字串轉換）
3. `logger.exception(...)` / `logger.error(..., exc_info=True)` 保留 — loguru 支援
4. `logger.debug/info/warning/error/critical` 介面全相容無需改

[src/utils.py](../../../src/utils.py) 的 `setup_logger()` 改為配置 loguru sink（保留簽章、內部委派）。JSON sink 可透過 `settings.logging.json_sink=true` 開關。既有 `logs/illumio_ops.log` 檔名與輪轉策略維持。

**Tech Stack:** loguru>=0.7 (Phase 0 已裝)

**Branch:** `upgrade/phase-7-logging-loguru`（from main；獨立 phase、可在 Phase 9 之前完成）

**Target tag on merge:** `v3.6.0-loguru`

**Parent roadmap:** [2026-04-18-upgrade-roadmap.md](2026-04-18-upgrade-roadmap.md)

---

## File Structure

| 檔案 | 動作 | 責任 |
|---|---|---|
| `scripts/migrate_to_loguru.py` | 新增 | 自動化 codemod：改 imports + 格式字串；dry-run 模式先檢視 |
| `src/utils.py` | 改 `setup_logger()` | 內部改配置 loguru sink；公開簽章保留給 33 檔 caller |
| `src/loguru_config.py` | 新增 | loguru 中央配置：rotation/retention/JSON sink/format |
| 33 個 src/*.py | codemod 自動處理 | import + logger assignment + %s 替換 |
| `src/module_log.py` | **不動** | 業務邏輯（ring-buffer for GUI），不是 logging 層 |
| `tests/test_loguru_setup.py` | 新增 | JSON sink / rotation / log level / exception trace 測試 |
| `tests/test_migration_script.py` | 新增 | codemod dry-run 測試（已知 input/output pairs） |
| Status.md / Task.md | 更新 | Phase 7 完成、新增 loguru 到 dependency status |

**檔案影響面**：33 檔 src/ 受 codemod 影響（機械式）+ 2 新檔 + 3 新/改配置檔 + 2 新測試。

---

## Task 1: Branch + baseline + contract tests

**Files:**
- Create: `tests/test_logger_interface_contract.py`

- [ ] Build branch from main:
```bash
git checkout main && git pull
git checkout -b upgrade/phase-7-logging-loguru
```

- [ ] Baseline tests (expect 252 passed, 3 skipped)

- [ ] Write contract test freezing logger interface that 33 files depend on:

```python
"""Freeze the logger interface that all 33 src/ files use.
After migration, these must still work:
  logger.debug/info/warning/error/critical(msg, *args, **kwargs)
  logger.exception(msg)
  logger.error(msg, exc_info=True)
"""
import logging as _std_logging


def test_logger_has_standard_methods():
    from src.utils import logger
    for method in ("debug", "info", "warning", "error", "critical", "exception"):
        assert callable(getattr(logger, method)), f"logger.{method} missing"


def test_logger_error_with_exc_info_true(caplog):
    from src.utils import logger
    try:
        raise ValueError("boom")
    except ValueError:
        # Must not raise; must log the traceback
        logger.error("caught", exc_info=True)


def test_logger_info_handles_format_args(caplog):
    from src.utils import logger
    # loguru uses {} not %s; the codemod converts call sites.
    # After migration, this pattern must work:
    logger.info("value is {}", 42)
```

(Note: the exact assertion may need adjusting once loguru is wired — the point is to freeze the SURFACE, not the exact internal.)

---

## Task 2: Build `src/loguru_config.py` (central config)

**Files:**
- Create: `src/loguru_config.py`
- Create: `tests/test_loguru_setup.py`

- [ ] Write failing tests (rotation exists, JSON sink opt-in, handler count, exception formatting)

- [ ] Implement:

```python
"""Central loguru configuration for illumio_ops.

setup_loguru(log_file, level="INFO", json_sink=False, rotation="10 MB", retention=10)
  - Configures loguru logger.add() sinks
  - Console sink with color if TTY
  - File sink with rotation + retention
  - Optional JSON sink (for SIEM)
  - Replaces standard logging handlers for compatibility with 3rd-party libs
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger


class _StdLibInterceptHandler(logging.Handler):
    """Route stdlib logging calls (from 3rd-party libs) into loguru."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_loguru(log_file: str,
                 level: str = "INFO",
                 json_sink: bool = False,
                 rotation: str = "10 MB",
                 retention: int = 10) -> None:
    """Install loguru sinks. Idempotent — removes prior sinks first."""
    logger.remove()  # clear defaults

    # Console sink (respects TTY color detection)
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
               "<level>{level: <8}</level> "
               "<cyan>{name}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
    )

    # File sink with rotation
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file,
        level=level,
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        enqueue=True,   # thread-safe via queue
        format="{time:YYYY-MM-DD HH:mm:ss} {level: <8} {name}:{line} - {message}",
    )

    # Optional JSON sink (SIEM-friendly)
    if json_sink:
        logger.add(
            str(Path(log_file).with_suffix(".json.log")),
            level=level,
            rotation=rotation,
            retention=retention,
            serialize=True,  # emits JSON per line
            enqueue=True,
        )

    # Intercept stdlib logging so 3rd-party libs go through loguru
    logging.basicConfig(handlers=[_StdLibInterceptHandler()], level=0, force=True)
```

- [ ] Tests pass; commit.

---

## Task 3: Adapt `src/utils.py::setup_logger()`

**Files:**
- Modify: `src/utils.py`

- [ ] Replace setup_logger body:
```python
def setup_logger(name: str, log_file: str,
                 level: str = "INFO", json_sink: bool = False) -> None:
    """Configure logging — delegates to loguru."""
    from src.loguru_config import setup_loguru
    setup_loguru(log_file, level=level, json_sink=json_sink)
```

- [ ] Add `from loguru import logger` at top of utils.py.

- [ ] Full test suite green; commit.

---

## Task 4: Write migration codemod

**Files:**
- Create: `scripts/migrate_to_loguru.py`
- Create: `tests/test_migration_script.py`

- [ ] TDD: known-input fixtures + expected output:
  - Input: `import logging\nlogger = logging.getLogger(__name__)\n...\nlogger.info("x %s", v)`
  - Expected: `from loguru import logger\n...\nlogger.info("x {}", v)`

- [ ] Implement script using Python `ast` + regex for format strings:

```python
#!/usr/bin/env python3
"""Codemod: stdlib logging → loguru across src/."""
import ast
import re
import sys
from pathlib import Path


_LOGGER_ASSIGN_PATTERN = re.compile(
    r"^logger\s*=\s*logging\.getLogger\([^)]*\)\s*$",
    re.MULTILINE,
)
_IMPORT_PATTERN = re.compile(r"^import logging(\s*#[^\n]*)?$", re.MULTILINE)
_FORMAT_SPEC_PATTERN = re.compile(r"%[sdifr]")


def _convert_format_specs_in_logger_calls(src: str) -> str:
    """Find logger.<level>('...%s...', args) and convert %s → {}."""
    # Regex over logger.(debug|info|warning|error|critical|exception)(
    call_re = re.compile(
        r"(logger\.(?:debug|info|warning|error|critical|exception)\()"
        r'(["\'])'
        r"((?:[^"\'\\]|\\.)*?)"
        r"\2"
    )
    def _repl(m):
        prefix, quote, content = m.group(1), m.group(2), m.group(3)
        return prefix + quote + _FORMAT_SPEC_PATTERN.sub("{}", content) + quote
    return call_re.sub(_repl, src)


def migrate_file(path: Path, dry_run: bool = False) -> bool:
    """Return True if file was (or would be) changed."""
    original = path.read_text(encoding="utf-8")
    text = original

    # 1. Replace `import logging` with `from loguru import logger`
    if "logger = logging.getLogger" in text or re.search(_IMPORT_PATTERN, text):
        text = _IMPORT_PATTERN.sub("from loguru import logger", text)
        text = _LOGGER_ASSIGN_PATTERN.sub("", text)

    # 2. Convert %s/%d to {} inside logger call string literals
    text = _convert_format_specs_in_logger_calls(text)

    # 3. Remove residual empty lines where logger assignment used to be
    text = re.sub(r"\n\n\n+", "\n\n", text)

    if text == original:
        return False

    if dry_run:
        print(f"[dry-run] would modify {path}")
    else:
        path.write_text(text, encoding="utf-8")
        print(f"migrated {path}")
    return True


def main() -> int:
    src = Path(__file__).resolve().parent.parent / "src"
    dry = "--dry-run" in sys.argv
    exclude = {"module_log.py", "loguru_config.py", "utils.py"}
    changed = 0
    for py in src.rglob("*.py"):
        if py.name in exclude:
            continue
        if migrate_file(py, dry_run=dry):
            changed += 1
    print(f"\n{'Would migrate' if dry else 'Migrated'} {changed} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] Tests verify dry-run doesn't touch files + conversion correctness. Commit codemod before running.

---

## Task 5: Dry-run + execute codemod

**Files:** all 30 migrated src/*.py

- [ ] Dry-run first:
```bash
python scripts/migrate_to_loguru.py --dry-run
```
Expected: "Would migrate ~30 files".

- [ ] Execute:
```bash
python scripts/migrate_to_loguru.py
```

- [ ] Run full test suite:
```bash
python -m pytest tests/ -q
```

- [ ] **Manually fix** any test failures — likely candidates:
  - Edge cases the regex missed (e.g., multi-line logger calls)
  - Tests that mocked `logging.getLogger` need updates
  - Any `logging.basicConfig(...)` calls in src/main.py — remove (loguru handles via intercept handler)

- [ ] i18n audit stays 0.

- [ ] Commit as single "migrate src to loguru" (atomic) — the codemod is the commit message.

---

## Task 6: Verify daemon logs + JSON sink manual test

**Files:** no code changes

- [ ] Smoke test daemon mode:
```bash
timeout 5 python illumio_ops.py --monitor -i 1 || true
cat logs/illumio_ops.log | tail -20
```
Expected: lines like `2026-XX-XX HH:MM:SS INFO     src.main:59 - Starting scheduler-backed daemon`.

- [ ] Test JSON sink (add to config.json: `"logging": {"json_sink": true}` — plus settings schema update in `src/config_models.py` for `LoggingSettings`):
```bash
timeout 5 python illumio_ops.py --monitor -i 1 || true
jq '.' logs/illumio_ops.json.log | head -20
```
Expected: valid JSON per line.

- [ ] Commit config_models.py + sample config change if schema added.

---

## Task 7: Docs + Merge

**Files:** `Status.md`, `Task.md`, `README.md`

- [ ] Status.md — version `v3.6.0-loguru`; loguru marked "used".
- [ ] Task.md — Phase 7 block with codemod + file count + test delta.
- [ ] README.md — mention JSON sink for SIEM integration.

- [ ] Push + PR + merge + tag:
```bash
git push -u origin upgrade/phase-7-logging-loguru
# Merge via gh / API, then:
git tag v3.6.0-loguru && git push origin v3.6.0-loguru
```

---

## Phase 7 完成驗收清單

- [ ] `src/loguru_config.py` 有 `setup_loguru()`
- [ ] `src/utils.py::setup_logger()` 委派到 loguru
- [ ] `scripts/migrate_to_loguru.py` 可 dry-run / execute
- [ ] 30 files src/*.py migrated（保留 module_log.py, loguru_config.py, utils.py）
- [ ] stdlib logging 透過 InterceptHandler 進 loguru（3rd-party libs 也整併）
- [ ] JSON sink 可開關
- [ ] 252+ tests 通過（baseline 252 + ~5 loguru setup tests + 2 migration script tests）
- [ ] i18n audit 0 findings
- [ ] `v3.6.0-loguru` tag

---

## Rollback

`git revert v3.6.0-loguru` — single atomic codemod commit reverts cleanly. Legacy `import logging` path not removed from Python runtime, so revert is safe.

---

## 已知風險

1. **第三方 library log format**：若有 library 直接呼叫 `logging.getLogger("xxx")` 並 `%s` 格式化，InterceptHandler 會 route 到 loguru 但 `%s` 不會被轉 — loguru 會原樣印出。**這是預期行為**：3rd-party format strings 不需改動。
2. **pytest caplog fixture**：改 loguru 後 caplog 可能抓不到（因為走 loguru sink 而非 stdlib）。如必要，在 conftest.py 加入 loguru ↔ pytest 橋接 fixture。
3. **Multi-line logger calls**：`logger.info(\n    "x %s",\n    v)` 正則表達式可能失誤 — 手動 review codemod diff。
