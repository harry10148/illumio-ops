# Track B — CLI Output Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Phase 1 quick wins 建立的 CLI helper modules (_global_flags, _errors, isatty/NO_COLOR Console) 全面套用到 24 個命令；新增結構化 warning/notice 分層、統一 exit code map (sysexits.h-style)、stderr/stdout 嚴格分流；把 §3.2.4 CLI rule 2★/3★/4★/12 全 推到 ≥2。

**Architecture:** 不重寫命令樹（那是 Track C 的範圍），只在每個現有 command function 內部加 `--json/--quiet/--verbose` 處理 + 統一 exit code + structured error/warning 分流。新增 `src/cli/_output.py` 集中所有輸出 helper (echo_info / echo_warning / echo_error)，取代散落的 `click.echo` / `print` / `console.print`。

**Tech Stack:** Click + Rich (現有)；Python 3.12 stdlib (sys, json, os)。

**Reference docs:**
- 評估報告 §3.2.4 CLI rubric (UX 8/21, CLI 11/36, P1: composability=0, error actionability=0)
- §4.7-§4.11 CLI pain cards (b3/b4/b6/b7)
- §5.2 Track B 定義
- Phase 1 plan helpers: `src/cli/_global_flags.py`, `src/cli/_errors.py`, `src/cli/_render.py:_get_console`

**Touch radius:** 中。涉及檔案 (per A.4 inventory):
- `src/cli/cache.py` (4 commands)
- `src/cli/config.py` (3 commands)
- `src/cli/gui_cmd.py` (1 command)
- `src/cli/monitor.py` (1 command)
- `src/cli/report.py` (4 commands)
- `src/cli/rule.py` (3 commands)
- `src/cli/siem.py` (4 commands)
- `src/cli/status.py` (1 command)
- `src/cli/workload.py` (3 commands)
- 加 3 standalone CLI: `src/pce_cache_cli.py`, `src/rule_scheduler_cli.py`, `src/siem_cli.py`
- 新增: `src/cli/_output.py`, `src/cli/_exit_codes.py`

**Hard constraints:**
- 命令外在介面（command name / args / 行為）不變 — Track C 才動入口結構
- 既有 pytest 100% pass (regression)
- Backwards compat: 沒有 `--json` flag 的舊 user 行為 (rich table) 維持預設

**驗收 (整 plan):**
- §3.2.4 rule 2★ capability 1→≥2 (NO_COLOR/TERM 在所有命令生效，已 Phase 1 達成)
- rule 3★ composability 0→≥2 (所有 24 命令支援 --json + stderr/stdout 分流)
- rule 4★ exit codes 1→≥2 (統一 exit code map, SIGINT/SIGTERM 標準化)
- rule 12 actionability 0→≥2 (所有命令的 error 經 _errors 結構化, did-you-mean for top-level)
- Phase 1 + Track B 共用 helper modules 無重複實作

**Commit / branch 策略:** 全 plan 在 `plan/track-b-cli-output-layer-2026-05-06` 分支進行。Tasks 1-2 是 helper module，Tasks 3-7 是 per-file migration，Task 8 是 standalone CLI。每 task 1 commit。

---

## Task 1: 新增 src/cli/_exit_codes.py — 統一 exit code map

**Goal:** 集中定義 sysexits.h-style exit code，命令依失敗類型回傳對應 code，shell pipeline 可依 exit code 路由處理。

**Files:**
- Create: `src/cli/_exit_codes.py`
- Create: `tests/test_cli_exit_codes.py`

- [ ] **Step 1: 寫測試**

```python
"""Test exit code constants and helper."""
from src.cli._exit_codes import (
    EXIT_OK, EXIT_USAGE, EXIT_DATAERR, EXIT_NOINPUT,
    EXIT_UNAVAILABLE, EXIT_SOFTWARE, EXIT_OSERR, EXIT_CONFIG,
    EXIT_INTERRUPT, EXIT_TERMINATED,
    exit_for_exception,
)


def test_standard_exit_codes():
    # POSIX
    assert EXIT_OK == 0
    assert EXIT_USAGE == 64        # sysexits.h EX_USAGE
    assert EXIT_DATAERR == 65      # EX_DATAERR
    assert EXIT_NOINPUT == 66      # EX_NOINPUT
    assert EXIT_UNAVAILABLE == 69  # EX_UNAVAILABLE (service unavailable)
    assert EXIT_SOFTWARE == 70     # EX_SOFTWARE (internal error)
    assert EXIT_OSERR == 71        # EX_OSERR
    assert EXIT_CONFIG == 78       # EX_CONFIG
    # Signal-induced (POSIX 128 + signum)
    assert EXIT_INTERRUPT == 130   # SIGINT
    assert EXIT_TERMINATED == 143  # SIGTERM


def test_exit_for_exception_connection_error():
    class ConnectionError(Exception): pass
    code = exit_for_exception(ConnectionError("PCE down"))
    assert code == EXIT_UNAVAILABLE


def test_exit_for_exception_file_not_found():
    code = exit_for_exception(FileNotFoundError("no config"))
    assert code == EXIT_NOINPUT


def test_exit_for_exception_permission():
    code = exit_for_exception(PermissionError("denied"))
    assert code == EXIT_OSERR


def test_exit_for_exception_generic():
    code = exit_for_exception(RuntimeError("oops"))
    assert code == EXIT_SOFTWARE
```

- [ ] **Step 2: Run test, expect ImportError**

```bash
cd /home/harry/rd/illumio-ops
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -m pytest tests/test_cli_exit_codes.py -v 2>&1 | tail -10
```

- [ ] **Step 3: 寫 module**

```python
"""Exit code constants and dispatch (sysexits.h style + POSIX signal codes).

Track B Task 1: gives shell pipelines fine-grained failure dispatch
without parsing stderr.

Codes (per BSD sysexits.h, widely supported):
    0   OK
    64  USAGE     bad invocation
    65  DATAERR   input data invalid
    66  NOINPUT   input file missing/unreadable
    69  UNAVAILABLE  service down (PCE, mail server)
    70  SOFTWARE  internal error (bug)
    71  OSERR     OS-level (file perm, mkdir failure)
    78  CONFIG    bad config

Signal codes:
    130 SIGINT   (Ctrl-C)
    143 SIGTERM  (kill)
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 64
EXIT_DATAERR = 65
EXIT_NOINPUT = 66
EXIT_UNAVAILABLE = 69
EXIT_SOFTWARE = 70
EXIT_OSERR = 71
EXIT_CONFIG = 78
EXIT_INTERRUPT = 130
EXIT_TERMINATED = 143


def exit_for_exception(exc: BaseException) -> int:
    """Map an exception type to a sysexits.h exit code.

    Used in the top-level except handler / install_top_level_handler.
    """
    name = type(exc).__name__
    if 'ConnectionError' in name or 'ConnectTimeout' in name or 'ConnectionRefused' in name:
        return EXIT_UNAVAILABLE
    if 'FileNotFoundError' in name or 'NoInput' in name:
        return EXIT_NOINPUT
    if 'PermissionError' in name:
        return EXIT_OSERR
    if 'KeyboardInterrupt' in name:
        return EXIT_INTERRUPT
    if 'SystemExit' in name:
        return getattr(exc, 'code', EXIT_OK) or EXIT_OK
    if 'ValueError' in name or 'TypeError' in name:
        return EXIT_DATAERR
    if 'ConfigError' in name or 'BadConfig' in name:
        return EXIT_CONFIG
    return EXIT_SOFTWARE
```

- [ ] **Step 4: Run test, expect 5 passed**

```bash
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -m pytest tests/test_cli_exit_codes.py -v 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add src/cli/_exit_codes.py tests/test_cli_exit_codes.py
git commit -m "feat(cli): unified exit code map (sysexits.h) + dispatch helper (b7)

New module src/cli/_exit_codes.py:
- 11 constants: EXIT_OK / USAGE / DATAERR / NOINPUT / UNAVAILABLE /
  SOFTWARE / OSERR / CONFIG / INTERRUPT / TERMINATED
- exit_for_exception(exc) → maps exception type to sysexits code

Touches §3.2.4 CLI rule 4★ exit codes 1→≥2."
```

---

## Task 2: 新增 src/cli/_output.py — 集中輸出 helper

**Goal:** 取代散落的 `click.echo` / `print` / `console.print`。提供 echo_info (stdout, normal), echo_warning (stderr, dimmed), echo_error (stderr, bold), echo_json (stdout 純 JSON), echo_quiet (僅 ID/最少資訊)。所有 helper 自動讀 `_global_flags`。

**Files:**
- Create: `src/cli/_output.py`
- Create: `tests/test_cli_output.py`

- [ ] **Step 1: 寫測試**

```python
"""Test centralized CLI output helpers."""
import json
import sys
import pytest
import click
from click.testing import CliRunner

from src.cli._global_flags import inject_global_flags
from src.cli._output import echo_info, echo_warning, echo_error, echo_json


@pytest.fixture
def runner():
    return CliRunner()


def test_echo_json_emits_to_stdout_only(runner):
    @click.group()
    @inject_global_flags
    def cli(): pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        echo_json(ctx, [{"id": "x", "n": 1}])

    result = runner.invoke(cli, ['--json', 'cmd'])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed == [{"id": "x", "n": 1}]


def test_echo_info_suppressed_in_quiet(runner):
    @click.group()
    @inject_global_flags
    def cli(): pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        echo_info(ctx, "informational message")
        click.echo("always-printed marker")

    result = runner.invoke(cli, ['--quiet', 'cmd'])
    assert "informational message" not in result.output
    assert "always-printed marker" in result.output


def test_echo_warning_goes_to_stderr(runner):
    @click.group()
    @inject_global_flags
    def cli(): pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        echo_warning(ctx, "deprecated flag")

    result = runner.invoke(cli, ['cmd'], mix_stderr=False)
    assert "deprecated flag" in result.stderr
    assert "deprecated flag" not in result.stdout


def test_echo_error_goes_to_stderr(runner):
    @click.group()
    @inject_global_flags
    def cli(): pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        echo_error(ctx, "fatal: bad config")

    result = runner.invoke(cli, ['cmd'], mix_stderr=False)
    assert "fatal: bad config" in result.stderr
```

- [ ] **Step 2: Run, expect ImportError**

```bash
cd /home/harry/rd/illumio-ops
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -m pytest tests/test_cli_output.py -v 2>&1 | tail -10
```

- [ ] **Step 3: 寫 module**

```python
"""Centralized CLI output helpers.

Track B Task 2: replaces ad-hoc click.echo / print / console.print
with semantic functions that:
- Honor --json / --quiet / --verbose from _global_flags
- Route info to stdout, warning/error to stderr (composability)
- Provide structured JSON emission

Migration target: all 24 commands across src/cli/ + 3 standalone CLIs.
"""
from __future__ import annotations

import json as _json
import sys
from typing import Any

import click

from src.cli._global_flags import get_global_flags


def echo_info(ctx: click.Context, message: str) -> None:
    """Print informational message to stdout. Suppressed in --quiet."""
    flags = get_global_flags(ctx)
    if flags.get('quiet'):
        return
    click.echo(message, err=False)


def echo_verbose(ctx: click.Context, message: str) -> None:
    """Print debug-level message to stderr. Only shown with --verbose."""
    flags = get_global_flags(ctx)
    if not flags.get('verbose'):
        return
    click.echo(message, err=True)


def echo_warning(ctx: click.Context, message: str) -> None:
    """Print warning to stderr. Always shown (even in --quiet)."""
    click.echo(f"warning: {message}", err=True)


def echo_error(ctx: click.Context, message: str) -> None:
    """Print error to stderr. Always shown."""
    click.echo(f"error: {message}", err=True)


def echo_json(ctx: click.Context, data: Any, *, indent: int | None = None) -> None:
    """Emit data as JSON to stdout. Use only when --json is set, but no
    explicit gate here — caller decides path: rich-table vs json.

    Always uses ensure_ascii=False (safe for terminal UTF-8).
    """
    click.echo(_json.dumps(data, ensure_ascii=False, indent=indent))


def is_json(ctx: click.Context) -> bool:
    """Convenience: True if caller asked for --json output."""
    return get_global_flags(ctx).get('json', False)


def is_quiet(ctx: click.Context) -> bool:
    return get_global_flags(ctx).get('quiet', False)


def is_verbose(ctx: click.Context) -> bool:
    return get_global_flags(ctx).get('verbose', False)
```

- [ ] **Step 4: Run, expect 4 passed**

```bash
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -m pytest tests/test_cli_output.py -v 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add src/cli/_output.py tests/test_cli_output.py
git commit -m "feat(cli): centralized output helpers (echo_info/warning/error/json) (b3)

New module src/cli/_output.py wrapping click.echo with semantic
intent (info → stdout / warning+error → stderr) and --json/--quiet/
--verbose awareness. is_json/is_quiet/is_verbose convenience getters.

Migration target: all 24 commands + 3 standalone CLIs (Tasks 3-8).

Touches §3.2.4 CLI rule 3★ composability 0→≥1 (foundation)."
```

---

## Task 3: 套用 _output + _exit_codes 到 cache.py (4 commands)

**Goal:** 第一個示範 migration. 把 cache.py 4 個命令全部套用 _output helpers，--json/--quiet 完整支援，errors 經 _errors，exit code 用 EXIT_*.

**Files:**
- Modify: `src/cli/cache.py`

- [ ] **Step 1: Read current cache.py**

```bash
cd /home/harry/rd/illumio-ops
wc -l src/cli/cache.py
grep -nE '@cache\.command|def [a-z]' src/cli/cache.py | head -20
```

- [ ] **Step 2: Migrate each command**

對 4 個命令 (cache list / cache status / cache backfill / cache retention 等實際命令名)，每個改成：

```python
from src.cli._output import is_json, is_quiet, echo_info, echo_warning, echo_error, echo_json
from src.cli._exit_codes import EXIT_OK, EXIT_DATAERR, EXIT_UNAVAILABLE, EXIT_NOINPUT
from src.cli._errors import format_error
import click

@cache.command(name='list')
# ... existing options ...
@click.pass_context
def cache_list(ctx, ...):
    try:
        rows = _fetch_rows(...)
    except FileNotFoundError as e:
        echo_error(ctx, format_error("Cache database missing", recovery="Run 'illumio-ops cache init'."))
        ctx.exit(EXIT_NOINPUT)
    except ConnectionError as e:
        echo_error(ctx, format_error("Cannot connect to PCE", recovery="Check PCE_HOST and credentials."))
        ctx.exit(EXIT_UNAVAILABLE)

    if is_json(ctx):
        echo_json(ctx, [r.to_dict() for r in rows])
        return

    if is_quiet(ctx):
        for r in rows:
            click.echo(r.id)
        return

    # default: rich table (existing behavior, preserved)
    _render_rich_table(rows)
```

對其他 cache.* commands 同樣改造。Phase 1 Task 2.2 已 demo 過 cache status — 把它擴展為完整 _output / _exit_codes 套用。

- [ ] **Step 3: Run cache tests**

```bash
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -m pytest tests/test_cache_cli.py -v 2>&1 | tail -10
```

預期: 既有測試應仍 pass (因為 default behavior 維持). 若有新行為，加新 test。

- [ ] **Step 4: Commit**

```bash
git add src/cli/cache.py tests/test_cache_cli.py
git commit -m "feat(cli): migrate cache.py commands to _output + _exit_codes (Track B)

4 commands all support:
- --json (JSON list output)
- --quiet (IDs only)
- default (rich table, unchanged)
- structured errors via _errors.format_error
- typed exit codes (EXIT_NOINPUT for missing cache, EXIT_UNAVAILABLE
  for PCE down, EXIT_DATAERR for malformed input)

Touches §3.2.4 CLI rule 3★/4★/12 +1 each on cache surface."
```

---

## Task 4: 套用到 rule.py + workload.py + status.py (7 commands)

**Files:**
- Modify: `src/cli/rule.py` (3 commands)
- Modify: `src/cli/workload.py` (3 commands)
- Modify: `src/cli/status.py` (1 command)

- [ ] **Step 1: 對每個檔案執行同 Task 3 的 migration pattern**

每個命令確保:
- pass `ctx` (加 `@click.pass_context` if missing)
- import `_output`, `_errors`, `_exit_codes`
- branch on `is_json(ctx)` / `is_quiet(ctx)` for output mode
- top-level try/except wrap with typed exit codes
- 用 `echo_warning / echo_error` 取代 stderr print

- [ ] **Step 2: Verify no regressions**

```bash
cd /home/harry/rd/illumio-ops
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -m pytest tests/ -x 2>&1 | tail -10
```

- [ ] **Step 3: Commit**

```bash
git add src/cli/rule.py src/cli/workload.py src/cli/status.py
git commit -m "feat(cli): migrate rule/workload/status to _output + _exit_codes (Track B)

7 commands across 3 files:
- rule list / rule create / rule delete
- workload list / workload show / workload tag
- status

All support --json/--quiet/default; structured errors; typed exit codes.

Touches §3.2.4 CLI rule 3★/4★/12 +1 each on rule/workload/status surface."
```

---

## Task 5: 套用到 report.py + monitor.py + gui_cmd.py (6 commands)

**Files:**
- Modify: `src/cli/report.py` (4 commands: traffic / audit / ven-status / policy-usage)
- Modify: `src/cli/monitor.py` (1 command)
- Modify: `src/cli/gui_cmd.py` (1 command)

- [ ] **Step 1: 同 Task 4 pattern 套用**

`report.*` 命令較特別 — 主要輸出是檔案 (.html / .pdf)，stdout 多為 progress / 結果路徑。改成：
- 預設: rich progress + 結果路徑
- `--json`: `{"output_path": "...", "type": "html", "size": N}` JSON
- `--quiet`: 只印 path

`monitor` 命令長任務 — 用 `echo_verbose(ctx, "...")` 取代 debug print。

`gui_cmd` (`gui` / `gui start`) — 啟動 server, exit code 應是 0 (正常結束) / EXIT_UNAVAILABLE (port busy).

- [ ] **Step 2: Verify**

```bash
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -m pytest tests/ -x 2>&1 | tail -10
```

- [ ] **Step 3: Commit**

```bash
git add src/cli/report.py src/cli/monitor.py src/cli/gui_cmd.py
git commit -m "feat(cli): migrate report/monitor/gui to _output + _exit_codes (Track B)

6 commands. report.* emits {output_path, type, size} JSON when --json;
monitor uses echo_verbose for debug; gui_cmd exits with EXIT_UNAVAILABLE
on port-busy.

Touches §3.2.4 CLI rule 3★/4★/12 +1 each on report/monitor/gui surface."
```

---

## Task 6: 套用到 siem.py + config.py (7 commands)

**Files:**
- Modify: `src/cli/siem.py` (4 commands)
- Modify: `src/cli/config.py` (3 commands)

- [ ] **Step 1: Migrate**

`siem.*` 命令 (per A.5 finding) 用 `raise SystemExit(1)` × 7 — 改成 `ctx.exit(EXIT_*)` 對應失敗類型。

`config.*` (set/get/show) — `--json` 對 show 很自然 (整個 config 即一個 JSON 物件).

- [ ] **Step 2: Verify**

```bash
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 -m pytest tests/ -x 2>&1 | tail -10
```

- [ ] **Step 3: Commit**

```bash
git add src/cli/siem.py src/cli/config.py
git commit -m "feat(cli): migrate siem/config to _output + _exit_codes (Track B)

7 commands. siem.* SystemExit raises replaced with ctx.exit(EXIT_*)
mapping. config.show outputs full config as JSON when --json.

Touches §3.2.4 CLI rule 3★/4★/12 +1 each on siem/config surface."
```

---

## Task 7: 全 root.py group 安裝 SIGINT/SIGTERM handler

**Files:**
- Modify: `illumio-ops.py` (entry) 或 `src/cli/root.py`

**Goal:** Phase 1 Task 2.3 已加 install_top_level_handler 處理 KeyboardInterrupt (exit 130). 本 task 加 SIGTERM (exit 143)，並把 _exit_codes.exit_for_exception 串接.

- [ ] **Step 1: Update install_top_level_handler in src/cli/_errors.py**

```python
import signal
from src.cli._exit_codes import (
    EXIT_INTERRUPT, EXIT_TERMINATED, EXIT_SOFTWARE, exit_for_exception
)


def install_top_level_handler(app_name: str = "illumio-ops") -> None:
    """Wrap sys.excepthook + install SIGTERM handler.

    On unhandled exception: structured error to stderr + typed exit code.
    On SIGINT: exit 130. On SIGTERM: exit 143.
    """
    def excepthook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.exit(EXIT_INTERRUPT)
        cause = str(exc) or exc_type.__name__
        recovery = _recovery_for(exc_type)
        print(format_error(cause, recovery), file=sys.stderr)
        sys.exit(exit_for_exception(exc) or EXIT_SOFTWARE)

    def sigterm_handler(signum, frame):
        sys.exit(EXIT_TERMINATED)

    sys.excepthook = excepthook
    signal.signal(signal.SIGTERM, sigterm_handler)


def _recovery_for(exc_type) -> str:
    name = exc_type.__name__
    if 'ConnectionError' in name or 'ConnectTimeout' in name:
        return "Check network reachability and PCE config (PCE_HOST, PCE_PORT)."
    if 'PermissionError' in name:
        return "Check file permissions for the path mentioned above."
    if 'FileNotFoundError' in name:
        return "Verify the file path or run setup if this is the first run."
    return "Re-run with --verbose for more detail."
```

- [ ] **Step 2: Test SIGTERM**

```python
# tests/test_cli_signal.py
import subprocess
import signal
import time
import os

import pytest


def test_sigterm_exit_143():
    """Verify illumio-ops cli exits 143 on SIGTERM."""
    proc = subprocess.Popen(
        ['python3', 'illumio-ops.py', 'monitor', '--noop-loop'],  # if such flag exists
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    time.sleep(0.5)
    proc.terminate()
    proc.wait(timeout=5)
    assert proc.returncode == 143
```

(若沒有合適的 long-running noop command, skip this test 或 skip-if-no-monitor-noop. 可先以 unit test 確認 sigterm_handler logic.)

- [ ] **Step 3: Commit**

```bash
git add src/cli/_errors.py tests/test_cli_signal.py
git commit -m "feat(cli): SIGTERM → exit 143; structured exit_for_exception (b7)

Extends Phase 1 install_top_level_handler:
- SIGTERM signal handler → sys.exit(EXIT_TERMINATED=143)
- excepthook now uses _exit_codes.exit_for_exception (typed) instead
  of always exit(1)
- Recovery hints abstracted to _recovery_for() helper

Touches §3.2.4 CLI rule 4★ exit codes 1→≥2."
```

---

## Task 8: 套用到 3 standalone CLIs (pce_cache_cli, rule_scheduler_cli, siem_cli)

**Goal:** 3 個獨立入口 (per A.4) 完全無 exit code 語義. 套用 _output + _exit_codes + install_top_level_handler.

**Files:**
- Modify: `src/pce_cache_cli.py`
- Modify: `src/rule_scheduler_cli.py`
- Modify: `src/siem_cli.py`

- [ ] **Step 1: 對每個 CLI 加 install_top_level_handler 在 main entry**

```python
# Top of each *_cli.py main:
from src.cli._errors import install_top_level_handler
from src.cli._exit_codes import EXIT_OK, EXIT_USAGE, EXIT_UNAVAILABLE

if __name__ == '__main__':
    install_top_level_handler('illumio-ops')
    cli()
```

- [ ] **Step 2: 各 CLI 內部命令同 Task 3-6 pattern 套用**

(If standalone CLI 不用 Click 而用 argparse, parallel logic — 用 _output helpers 即可，但 ctx 概念可能無對應. 在這種情況 _output helpers 也應該支援 None context (degraded: just stdout/stderr direct, no flag-aware suppression).)

如果 _output helpers 假設 click.Context, 寫一個 `class _NullCtx` shim:
```python
class _NullCtx:
    obj = None
    parent = None
```

讓 standalone CLI 可呼叫 `echo_info(_NullCtx(), msg)` 不爆。

- [ ] **Step 3: Verify each CLI starts + --help works**

```bash
cd /home/harry/rd/illumio-ops
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 src/pce_cache_cli.py --help 2>&1 | head -5
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 src/rule_scheduler_cli.py --help 2>&1 | head -5
PYTHONPATH=$(pwd)/venv/lib/python3.12/site-packages python3 src/siem_cli.py --help 2>&1 | head -5
```

- [ ] **Step 4: Commit**

```bash
git add src/pce_cache_cli.py src/rule_scheduler_cli.py src/siem_cli.py src/cli/_output.py
git commit -m "feat(cli): apply _output + _exit_codes to 3 standalone CLIs (Track B)

pce_cache_cli / rule_scheduler_cli / siem_cli now have:
- install_top_level_handler at entry
- typed exit codes via _exit_codes
- _output helpers (with _NullCtx shim if non-Click)
- consistent stderr/stdout split

Touches §3.2.4 — final 3 entries reach parity with main CLI on rules
3★/4★/12."
```

---

## Self-review checklist

執行完所有 Task 後驗證：

### Helpers
- [ ] `tests/test_cli_exit_codes.py`: 5 passed
- [ ] `tests/test_cli_output.py`: 4 passed
- [ ] `tests/test_cli_errors.py` + `test_global_flags.py` + `test_render_tty.py` (Phase 1) 仍 pass

### Migration coverage
- [ ] `grep -rcE 'is_json\(ctx\)|echo_json\(' src/cli/` — 預期 24+ 命中 (each command + helper)
- [ ] `grep -rcE 'EXIT_(OK|USAGE|DATAERR|NOINPUT|UNAVAILABLE|SOFTWARE|OSERR|CONFIG)' src/cli/` — 預期 30+ 命中
- [ ] `grep -rE 'sys\.exit\(1\)|raise SystemExit\(1\)' src/cli/ src/*_cli.py` — 預期顯著減少 (從 A.5 的 ~15 處到 < 5 — 剩下的應有 typed reason)

### Composability
- [ ] `illumio-ops --json cache list` 輸出純 JSON, 可用 jq 解析 (manual smoke test)
- [ ] `illumio-ops --quiet rule list | wc -l` 輸出純 ID 列表
- [ ] `illumio-ops cache list 2>/dev/null | head` stderr 與 stdout 分離正確
- [ ] `NO_COLOR=1 illumio-ops cache list` 無 ANSI escape

### Exit codes
- [ ] PCE down 時 `illumio-ops cache list; echo $?` → 69 (UNAVAILABLE)
- [ ] 不存在 config `illumio-ops --config /tmp/nope.json status; echo $?` → 66 (NOINPUT) 或 78 (CONFIG)
- [ ] Ctrl-C → exit 130

---

## §12 後續

Track B 完成後可解鎖:

- **Track C — CLI Entry Unification** (Phase 3): 統一 illumio-ops 根命令 + 3 standalone deprecate. 必須 Track B 已 ship (Track C 假設所有命令都已用 _output 統一介面)
- **Track D — Email System (MJML)** (Phase 3): 獨立, 可平行 ship 於 Track C
- **Phase 4 Track E**: conditional 視 Phase 1+2+3 完成後重評

---

## Self-review of this plan

- ✅ Goal/Architecture/Tech Stack header 完整
- ✅ Reference docs (assessment §3.2.4 + §4.7-§4.11 + §5.2)
- ✅ 8 tasks: 2 helper modules + 5 migration batches + 1 standalone CLI batch
- ✅ TDD on helper modules (Tasks 1-2 + Task 7)
- ✅ Migration pattern documented in Task 3 (示範), Tasks 4-6 用相同 pattern
- ✅ standalone CLI 特殊處理 (`_NullCtx` shim)
- ✅ 不動命令樹結構 (Track C 才動入口)
- ⚠️ Tasks 3-6 mechanical 但量大, subagent 可能需多輪 (每 task 處理 4-7 個命令)
- ⚠️ Task 8 假設 standalone CLI 用 Click, 若用 argparse 需調整
- ⚠️ Task 7 SIGTERM test 依賴有 long-running noop command, 若無則 skip 不影響 plan 完成

預計執行時間（subagent-driven 模式）:
- Tasks 1-2: ~2 hours (helpers, TDD)
- Task 3: ~1.5 hours (cache.py, demo migration)
- Tasks 4-6: ~3-4 hours (5 files, mechanical migration)
- Task 7: ~1 hour (signal handler)
- Task 8: ~2 hours (3 standalone CLIs)
- 總計: ~9-10 hours subagent time
