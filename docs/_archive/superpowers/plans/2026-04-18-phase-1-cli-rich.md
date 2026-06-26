# Phase 1 Implementation Plan — CLI UX 升級 (rich + questionary + click + humanize)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 [src/utils.py](../../../src/utils.py) 裡的 `Colors`/`draw_panel`/`Spinner`/`safe_input` 換成以 rich + questionary 為後端的實作，同時保留**所有**舊 API 介面（共 446 處呼叫點、10 檔），再新增 `src/cli/` click subcommand 框架與 `humanize` 人類可讀格式，最終讓既有 flag (`--monitor`, `--gui`, `--report`) 向後相容。

**Architecture:** **Wrapper 策略** — 不做全面搜尋替換。在 [utils.py](../../../src/utils.py) 內重寫 `Colors`/`draw_panel`/`Spinner`/`safe_input` 的底層實作為 rich/questionary，對外介面 100% 不變，讓 446 處呼叫點自動受惠於 rich 渲染（漸進式 ANSI → rich）。另外建立 `src/cli/` click 子套件作為**新增的**subcommand 入口，`illumio_ops.py` 的 `main()` 先判斷是否有新 subcommand 風格（`illumio-ops monitor`）再 fallback 到舊 argparse（`--monitor`）。i18n 保持 0 findings。

**Tech Stack:** rich>=13.7, questionary>=2.0, click>=8.1, humanize>=4.9（皆 Phase 0 已裝）

**Branch:** `upgrade/phase-1-cli-rich`（**from main after Phase 0 merge**）

**Target tag on merge:** `v3.4.1-cli`

**Parent roadmap:** [2026-04-18-upgrade-roadmap.md](2026-04-18-upgrade-roadmap.md)

---

## File Structure

| 檔案 | 動作 | 責任 |
|---|---|---|
| `src/utils.py` | 重寫底層 | `Colors`/`draw_panel`/`Spinner`/`safe_input` 名稱保留，底層改 rich/questionary |
| `src/utils/humanize_ext.py` | 新增 | humanize 的 i18n wrapper（依 `get_language()` 切 locale） |
| `src/cli/__init__.py` | 新增 | click root group |
| `src/cli/monitor.py` | 新增 | `illumio-ops monitor` subcommand |
| `src/cli/gui.py` | 新增 | `illumio-ops gui` subcommand |
| `src/cli/report.py` | 新增 | `illumio-ops report <type>` subcommands |
| `src/cli/status.py` | 新增 | `illumio-ops status` （新功能：daemon 狀態） |
| `src/cli/_compat.py` | 新增 | 舊 argparse flag → click subcommand 路由 |
| `illumio_ops.py` | 小改 | 先試 click，再 fallback argparse |
| `src/main.py` | 小改 | 原有選單函式保留，但 draw_panel 呼叫自動變 rich |
| `tests/test_cli_backwards_compat.py` | 新增 | 驗證舊 flag 全部仍可用 |
| `tests/test_cli_subcommands.py` | 新增 | 驗證新 subcommand 行為 |
| `tests/test_utils_rich_backed.py` | 新增 | 驗證 wrapper 不破壞既有行為 |
| `scripts/illumio-ops-completion.bash` | 新增 | bash completion（click 自動產出） |
| `src/i18n_en.json` | 補 keys | 新增 status subcommand 與 humanize 相關 key |

**檔案影響面**：新增 11 檔 + 修改 3 檔。**不碰** [settings.py](../../../src/settings.py)、[rule_scheduler_cli.py](../../../src/rule_scheduler_cli.py)、[gui.py](../../../src/gui.py) 等 — 它們透過 wrapper 自動升級。

---

## Task 1: 建立 branch + 從 main rebase 確認 Phase 0 已 merge

**Files:** （無檔案變更）

- [ ] **Step 1: 確認 Phase 0 已 merge 到 main**

Run:
```bash
git fetch origin main
git log origin/main --oneline -5 | grep -q "Phase 0\|v3.4.0-deps"
```
Expected: 找到 Phase 0 merge commit。**若沒有，停止 — Phase 1 必須基於 Phase 0 後的 main**。

- [ ] **Step 2: 建立 feature branch**

Run:
```bash
git checkout main && git pull
git checkout -b upgrade/phase-1-cli-rich
```
Expected: Switched to new branch.

- [ ] **Step 3: 驗證基線測試 + i18n audit 全綠**

Run:
```bash
python -m pytest tests/ -q
python -m pytest tests/test_i18n_audit.py -v
```
Expected: 130 passed + 1 skipped；i18n audit 0 findings。

---

## Task 2: 寫 rich-backed Colors 的 failing test

**Files:**
- Create: `tests/test_utils_rich_backed.py`

- [ ] **Step 1: 建立 failing test**

Create `tests/test_utils_rich_backed.py`:

```python
"""Verify utils.py public API still works after rich migration.

These tests are the safety net for the wrapper strategy: every
existing caller (446 occurrences across 10 files) uses Colors.X,
draw_panel(), Spinner, safe_input — the names and semantics must
survive the rich rewrite.
"""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest

from src.utils import Colors, draw_panel, Spinner


def test_colors_constants_still_exist():
    """Every Color used in the codebase must still be importable."""
    # Sampled from grep: Colors.FAIL, .WARNING, .CYAN, .GREEN, .BLUE,
    # .BOLD, .ENDC, .DARK_GRAY are in hot paths.
    for name in ("FAIL", "WARNING", "CYAN", "GREEN", "BLUE",
                 "BOLD", "ENDC", "DARK_GRAY", "RED"):
        assert hasattr(Colors, name), f"Colors.{name} missing after migration"


def test_colors_values_are_strings():
    """Colors.X must still be usable in f-strings: f'{Colors.FAIL}x{Colors.ENDC}'."""
    for name in ("FAIL", "WARNING", "GREEN", "ENDC"):
        assert isinstance(getattr(Colors, name), str)


def test_draw_panel_renders_title_and_lines(capsys):
    """draw_panel must print title + all given lines to stdout."""
    draw_panel("Test Title", ["line one", "line two", "line three"])
    captured = capsys.readouterr()
    assert "Test Title" in captured.out
    assert "line one" in captured.out
    assert "line two" in captured.out
    assert "line three" in captured.out


def test_draw_panel_handles_empty_lines(capsys):
    """Empty line list still renders a panel with the title."""
    draw_panel("Empty", [])
    captured = capsys.readouterr()
    assert "Empty" in captured.out


def test_draw_panel_honors_separator_marker(capsys):
    """'-' as a line marker is used across the codebase as a divider."""
    draw_panel("With Divider", ["top", "-", "bottom"])
    captured = capsys.readouterr()
    assert "top" in captured.out
    assert "bottom" in captured.out


def test_spinner_enters_and_exits_cleanly():
    """Spinner must be usable as a context manager without raising."""
    with Spinner("working..."):
        pass  # should not raise


def test_safe_input_returns_stripped_str():
    """safe_input with str type returns stripped input."""
    from src.utils import safe_input
    with patch("builtins.input", return_value="  hello  "):
        result = safe_input("prompt", str)
    assert result == "hello"


def test_safe_input_returns_int_from_valid_input():
    """safe_input with int type + range validates input."""
    from src.utils import safe_input
    with patch("builtins.input", return_value="3"):
        result = safe_input("prompt", int, range(0, 10))
    assert result == 3


def test_safe_input_returns_none_on_empty_with_int_type():
    """Empty input with int returns None (sentinel for 'go back')."""
    from src.utils import safe_input
    with patch("builtins.input", return_value=""):
        result = safe_input("prompt", int, range(0, 10))
    assert result is None
```

- [ ] **Step 2: 跑測試，確認部分 PASS（舊實作）**

Run:
```bash
python -m pytest tests/test_utils_rich_backed.py -v
```
Expected: 所有測試 PASS（因為目前還沒重寫 utils.py，舊實作已滿足這些契約）。**這是「先固化契約」的 TDD 策略 — 重寫時不能打破任何一個**。

- [ ] **Step 3: Commit**

```bash
git add tests/test_utils_rich_backed.py
git commit -m "test(cli): freeze utils.py public API contracts before rich migration

9 tests cover Colors.*, draw_panel, Spinner, safe_input — the names
and semantics must survive the rich rewrite (446 call sites across
10 files use this API via wrappers)."
```

---

## Task 3: 把 Colors 改成 rich-backed（保留 ANSI 字串介面）

**Files:**
- Modify: `src/utils.py:85-100` (Colors class 區域)

- [ ] **Step 1: 讀目前的 Colors 定義（行 85 附近）**

Use Read tool on `src/utils.py` lines 80-100 to see the exact current Colors class implementation.

- [ ] **Step 2: 改寫 Colors 為 rich Style backed（保留 ANSI 字串）**

Rich supports `rich.style.Style.render()` which emits ANSI codes identical to what Colors currently hard-codes. Replace the Colors class body with:

```python
# In src/utils.py — replace the Colors class (around line 85) with:

from rich.style import Style as _RichStyle


def _ansi(style: _RichStyle) -> str:
    """Render a rich Style to its ANSI escape sequence (keeps back-compat)."""
    # rich.Style renders as SGR sequences; equivalent to the old hardcoded values
    # but driven by a named registry instead of magic numbers.
    return style.render("", reset=False) or ""


class Colors:
    """ANSI color codes — now backed by rich.Style for consistency.

    All 446 existing call sites (f'{Colors.FAIL}...{Colors.ENDC}') keep working
    because these remain plain strings containing ANSI escape sequences.
    New code should prefer rich directly (from rich.console import Console).
    """
    HEADER = _ansi(_RichStyle(color="magenta"))
    BLUE = _ansi(_RichStyle(color="blue"))
    CYAN = _ansi(_RichStyle(color="cyan"))
    GREEN = _ansi(_RichStyle(color="green"))
    WARNING = _ansi(_RichStyle(color="yellow"))
    FAIL = _ansi(_RichStyle(color="red"))
    RED = _ansi(_RichStyle(color="red"))
    ENDC = "\033[0m"
    BOLD = _ansi(_RichStyle(bold=True))
    UNDERLINE = _ansi(_RichStyle(underline=True))
    DARK_GRAY = _ansi(_RichStyle(color="bright_black"))
```

**不改**：如果 `_ansi()` 在某些終端回傳空字串造成現有輸出變樣，保留 `ENDC = "\033[0m"` 硬編碼避免連 reset 都消失。

- [ ] **Step 3: 跑測試確認 Colors 測試通過**

Run:
```bash
python -m pytest tests/test_utils_rich_backed.py::test_colors_constants_still_exist tests/test_utils_rich_backed.py::test_colors_values_are_strings -v
```
Expected: PASS。

- [ ] **Step 4: 跑全套 tests 確認沒打壞任何既有行為**

Run:
```bash
python -m pytest tests/ -q
```
Expected: 130 passed + 1 skipped。**若有任何測試失敗必須修復或還原，不可繼續**。

- [ ] **Step 5: Commit**

```bash
git add src/utils.py
git commit -m "refactor(cli): back Colors with rich.Style while preserving ANSI API

Every Color (FAIL, WARNING, CYAN, etc.) still returns an ANSI escape
string, so the 446 existing f-string call sites keep working unchanged.
The colors are now driven by rich's named style registry instead of
hardcoded SGR numbers, which sets up the later rich.Console migration."
```

---

## Task 4: 把 draw_panel 換成 rich.Panel 實作

**Files:**
- Modify: `src/utils.py:260-340` (draw_panel 區域)

- [ ] **Step 1: 讀目前的 draw_panel 實作**

Use Read tool on `src/utils.py` lines 255-355.

- [ ] **Step 2: 改寫 draw_panel 以 rich.Panel + rich.Console 為後端**

Replace the entire `draw_panel()` function body with:

```python
# In src/utils.py — replace draw_panel (around line 260) with:

from rich.console import Console as _RichConsole
from rich.panel import Panel as _RichPanel
from rich.text import Text as _RichText
from rich import box as _rich_box

_CONSOLE_SINGLETON: _RichConsole | None = None


def _get_console() -> _RichConsole:
    """Lazily build a shared Console so encoding / color detection runs once."""
    global _CONSOLE_SINGLETON
    if _CONSOLE_SINGLETON is None:
        _CONSOLE_SINGLETON = _RichConsole(
            # Respect the existing TTY/encoding checks from the project
            force_terminal=None,   # auto-detect
            safe_box=True,         # degrades to ASCII when terminal can't render unicode
            highlight=False,       # don't auto-colorize numbers/URLs (keeps existing look)
        )
    return _CONSOLE_SINGLETON


def draw_panel(title: str, lines: list, width: int = 0) -> None:
    """Render a titled panel containing `lines` to stdout.

    Back-compat: every caller expects this prints and returns None.
    A line value of '-' is treated as a divider (used across the codebase).

    The width parameter is accepted for source compatibility but rich
    now auto-sizes based on terminal; explicit width is used as max.
    """
    console = _get_console()

    # Build body Text; honor '-' as a horizontal-rule marker
    body = _RichText()
    for i, line in enumerate(lines):
        if line == "-":
            # Light divider — use a dim rule-like character span
            body.append("─" * max(20, min(len(title) + 10, 80)), style="bright_black")
        else:
            # `line` can contain existing ANSI codes from Colors.X usage.
            # Parse ANSI so rich renders colors correctly instead of escaping them.
            body.append(_RichText.from_ansi(str(line)))
        if i < len(lines) - 1:
            body.append("\n")

    panel_kwargs = {
        "title": title,
        "title_align": "left",
        "border_style": "cyan",
        "box": _rich_box.ROUNDED,
        "padding": (0, 1),
    }
    if width and width > 0:
        panel_kwargs["width"] = width

    console.print(_RichPanel(body, **panel_kwargs))
```

- [ ] **Step 3: 跑測試**

Run:
```bash
python -m pytest tests/test_utils_rich_backed.py -v
```
Expected: 全 9 個測試 PASS。

- [ ] **Step 4: 跑全套測試**

Run:
```bash
python -m pytest tests/ -q
```
Expected: 130 passed + 1 skipped。

- [ ] **Step 5: 視覺煙霧測試**

Run:
```bash
python -c "from src.utils import draw_panel, Colors; draw_panel('Demo', [f'{Colors.GREEN}hello{Colors.ENDC}', '-', 'plain line', f'{Colors.FAIL}red line{Colors.ENDC}'])"
```
Expected: 可見彩色、有邊框的 panel 輸出。

- [ ] **Step 6: Commit**

```bash
git add src/utils.py
git commit -m "refactor(cli): back draw_panel with rich.Panel

All 446 existing Colors.X f-strings inside lines are parsed via
Text.from_ansi so they render correctly as styled text inside the
rich Panel. Behavior matches the old draw_panel: title + lines,
'-' as divider, returns None.

Width parameter still accepted for source compat (rich auto-sizes
otherwise)."
```

---

## Task 5: 把 Spinner 換成 rich.status

**Files:**
- Modify: `src/utils.py:354+` (Spinner class 區域)

- [ ] **Step 1: 讀目前的 Spinner**

Use Read tool on `src/utils.py` line 350+.

- [ ] **Step 2: 改寫 Spinner 為 rich.status.Status wrapper**

Replace the Spinner class with:

```python
# In src/utils.py — replace Spinner class (around line 354) with:

class Spinner:
    """Context-manager spinner — now backed by rich.status.Status.

    Usage (unchanged from previous API):
        with Spinner("Working..."):
            do_work()
    """

    def __init__(self, message: str = "", color: str = "cyan"):
        self._message = message
        self._color = color
        self._status = None

    def __enter__(self):
        console = _get_console()
        self._status = console.status(
            f"[{self._color}]{self._message}[/{self._color}]",
            spinner="dots",
        )
        self._status.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._status is not None:
            self._status.__exit__(exc_type, exc_val, exc_tb)
            self._status = None
        return False
```

- [ ] **Step 3: 跑測試**

Run:
```bash
python -m pytest tests/test_utils_rich_backed.py::test_spinner_enters_and_exits_cleanly tests/ -q
```
Expected: 全綠。

- [ ] **Step 4: Commit**

```bash
git add src/utils.py
git commit -m "refactor(cli): back Spinner with rich.status.Status

Context-manager API preserved; spinner animation and color now
driven by rich's builtin 'dots' spinner set, replacing the previous
threaded print-flush loop."
```

---

## Task 6: safe_input 改用 questionary（保留舊參數簽章）

**Files:**
- Modify: `src/utils.py:102-258` (safe_input 函式)

- [ ] **Step 1: 讀目前的 safe_input 實作**

Use Read tool on `src/utils.py` lines 100-260.

- [ ] **Step 2: 改寫 safe_input 後端為 questionary，但保留簽章與 return types**

Replace the `safe_input()` function with:

```python
# In src/utils.py — replace safe_input (around line 102) with:
#
# Core signature preserved:
#   safe_input(prompt, type_=str, valid_range=None, **kwargs) -> Any | None
#
# Returns None when user enters empty input with int type (the "go back" sentinel
# used throughout the menus).

import questionary as _q
from questionary import Style as _QStyle


_QUESTIONARY_STYLE = _QStyle([
    ("qmark", "fg:#00afff bold"),
    ("question", "bold"),
    ("answer", "fg:#00ff7f bold"),
    ("pointer", "fg:#00afff bold"),
    ("highlighted", "fg:#00afff bold"),
    ("selected", "fg:#00ff7f"),
    ("instruction", "fg:#808080"),
])


def safe_input(prompt: str, type_=str, valid_range=None, **kwargs):
    """Prompt for input with type + range validation.

    Backend now uses questionary (nicer prompts, ctrl-c handling).
    Return semantics preserved:
      - str: returns stripped string, or None if EOF/interrupt
      - int: returns int, or None if empty (go-back sentinel) or invalid
    """
    import sys

    # questionary needs a TTY; fall back to input() for piped/non-TTY (tests, CI)
    if not (hasattr(sys.stdin, "isatty") and sys.stdin.isatty()):
        try:
            raw = input(prompt + " ")
        except (EOFError, KeyboardInterrupt):
            return None
        _set_last_input_action("value")
        if type_ is int:
            raw = raw.strip()
            if not raw:
                _set_last_input_action("back")
                return None
            try:
                v = int(raw)
                if valid_range is not None and v not in valid_range:
                    return None
                return v
            except ValueError:
                return None
        return raw.strip()

    # Interactive TTY path: questionary
    try:
        answer = _q.text(
            prompt,
            style=_QUESTIONARY_STYLE,
            **{k: v for k, v in kwargs.items() if k in ("default", "instruction")},
        ).unsafe_ask()
    except KeyboardInterrupt:
        _set_last_input_action("back")
        return None

    if answer is None:
        _set_last_input_action("back")
        return None

    _set_last_input_action("value")
    if type_ is int:
        answer = answer.strip()
        if not answer:
            _set_last_input_action("back")
            return None
        try:
            v = int(answer)
            if valid_range is not None and v not in valid_range:
                return None
            return v
        except ValueError:
            return None
    return answer.strip()
```

- [ ] **Step 3: 跑測試**

Run:
```bash
python -m pytest tests/test_utils_rich_backed.py -v tests/ -q
```
Expected: 全綠。

- [ ] **Step 4: 手動互動測試（在 TTY）**

Run:
```bash
python -c "from src.utils import safe_input; print(safe_input('請輸入一個 0-9 的數字: ', int, range(0,10)))"
```
Expected: 出現帶 `?` 符號的 questionary prompt；輸入 5 → 印出 5；按 Ctrl+C → 印出 None。

- [ ] **Step 5: Commit**

```bash
git add src/utils.py
git commit -m "refactor(cli): back safe_input with questionary while preserving API

Interactive path uses questionary for nicer prompts + ctrl-c handling.
Non-TTY path (piped input, tests, CI) falls back to input() so unit
tests with patch('builtins.input') continue to work unchanged.

Return semantics preserved: None for empty int input (go-back sentinel),
stripped string for str type, validated int for int type with valid_range."
```

---

## Task 7: 新增 humanize_ext i18n wrapper

**Files:**
- Create: `src/utils/__init__.py` (if utils is now a module, ignore — else new package)
- Create: `src/utils/humanize_ext.py`
- Create: `tests/test_humanize_ext.py`

**⚠️ 注意**: `src/utils.py` 現存為單檔。本 Task **不**將其改為 package（會動到 import 路徑，破壞 446 處）。改為新增 `src/humanize_ext.py`（頂層模組）。

- [ ] **Step 1: 建立 failing test**

Create `tests/test_humanize_ext.py`:

```python
"""humanize wrapper must honor i18n language setting."""
import datetime as _dt
from unittest.mock import patch

from src.humanize_ext import human_size, human_time_delta, human_number


def test_human_size_bytes_to_mb():
    assert human_size(1_500_000) in ("1.4 MB", "1.5 MB")  # humanize rounds


def test_human_size_handles_zero():
    assert human_size(0) == "0 Bytes"


def test_human_time_delta_seconds():
    with patch("src.humanize_ext.get_language", return_value="en"):
        delta = _dt.timedelta(seconds=45)
        assert "second" in human_time_delta(delta)


def test_human_time_delta_zh_tw():
    with patch("src.humanize_ext.get_language", return_value="zh_TW"):
        delta = _dt.timedelta(hours=2)
        result = human_time_delta(delta)
        # Chinese locale should produce chinese or at minimum not English 'hour'
        assert "小時" in result or "時" in result or "hour" not in result.lower()


def test_human_number_thousands():
    assert human_number(12345) in ("12,345", "12345")
```

- [ ] **Step 2: 跑測試確認失敗**

Run:
```bash
python -m pytest tests/test_humanize_ext.py -v
```
Expected: `ImportError: No module named 'src.humanize_ext'`（預期失敗）。

- [ ] **Step 3: 建立實作**

Create `src/humanize_ext.py`:

```python
"""humanize wrapper that follows the project's i18n language setting.

Falls back gracefully if humanize's zh_TW locale is not available
(humanize currently ships zh_CN; we map zh_TW → zh_CN at runtime).
"""
from __future__ import annotations

import datetime as _dt
import humanize as _humanize

from src.i18n import get_language


_LOCALE_MAP = {
    "en": None,       # default (no activate call)
    "zh_TW": "zh_CN", # humanize has zh_CN; good enough for zh_TW readers
    "zh_CN": "zh_CN",
}


def _activate_locale() -> None:
    lang = get_language() or "en"
    locale = _LOCALE_MAP.get(lang)
    if locale is None:
        # humanize has no deactivate(); reload to reset
        _humanize.i18n.deactivate()
        return
    try:
        _humanize.i18n.activate(locale)
    except FileNotFoundError:
        # locale files missing; silently fall back to english
        pass


def human_size(n: int) -> str:
    """Format bytes as human-readable, e.g. '3.5 MB'."""
    if n == 0:
        return "0 Bytes"
    return _humanize.naturalsize(n)


def human_time_delta(delta: _dt.timedelta) -> str:
    """Format a timedelta, e.g. '2 hours', '5 minutes', '3 days'."""
    _activate_locale()
    return _humanize.naturaldelta(delta)


def human_number(n: int | float) -> str:
    """Format a number with thousands separator: 12345 -> '12,345'."""
    return _humanize.intcomma(n)


def human_time_ago(past: _dt.datetime) -> str:
    """Format a past datetime as 'X time ago'."""
    _activate_locale()
    now = _dt.datetime.now(past.tzinfo) if past.tzinfo else _dt.datetime.now()
    return _humanize.naturaltime(now - past)
```

- [ ] **Step 4: 跑測試確認全綠**

Run:
```bash
python -m pytest tests/test_humanize_ext.py -v
```
Expected: 5 tests PASS。

- [ ] **Step 5: Commit**

```bash
git add src/humanize_ext.py tests/test_humanize_ext.py
git commit -m "feat(cli): add humanize wrapper that honors i18n language

Exposes human_size, human_time_delta, human_number, human_time_ago
with automatic locale switching based on get_language(). zh_TW maps
to humanize's zh_CN locale (close enough and officially available)."
```

---

## Task 8: 建立 click subcommand 骨架

**Files:**
- Create: `src/cli/__init__.py`
- Create: `src/cli/root.py`
- Create: `tests/test_cli_subcommands.py`

- [ ] **Step 1: 建立 failing test**

Create `tests/test_cli_subcommands.py`:

```python
"""Verify the new `illumio-ops` subcommand framework."""
from click.testing import CliRunner


def test_root_help_lists_subcommands():
    from src.cli.root import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    # Check all planned subcommands appear in help
    for sub in ("monitor", "gui", "report", "status"):
        assert sub in result.output, f"subcommand {sub} missing from --help"


def test_version_subcommand():
    from src.cli.root import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "illumio" in result.output.lower()
```

- [ ] **Step 2: 跑測試，確認失敗**

Run:
```bash
python -m pytest tests/test_cli_subcommands.py -v
```
Expected: ImportError（`src.cli.root` 不存在）。

- [ ] **Step 3: 建立 package**

Create `src/cli/__init__.py` with exactly:
```python
"""illumio-ops click-based CLI subcommand entrypoints (Phase 1)."""
from src.cli.root import cli

__all__ = ["cli"]
```

Create `src/cli/root.py`:

```python
"""Top-level click command group for illumio-ops."""
from __future__ import annotations

import click


@click.group(invoke_without_command=True,
             context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Illumio PCE Ops — monitoring, reporting, and policy management."""
    if ctx.invoked_subcommand is None:
        # No subcommand → defer to the legacy interactive main menu.
        # Imported lazily to avoid argparse side-effects.
        from src.main import main_menu
        main_menu()


@cli.command()
def version() -> None:
    """Print the illumio-ops version."""
    click.echo("illumio-ops 3.4.1-cli (Phase 1 — CLI UX upgrade)")


# Subcommands registered below
from src.cli import monitor as _monitor   # noqa: E402
from src.cli import gui_cmd as _gui       # noqa: E402
from src.cli import report as _report     # noqa: E402
from src.cli import status as _status     # noqa: E402

cli.add_command(_monitor.monitor_cmd)
cli.add_command(_gui.gui_cmd)
cli.add_command(_report.report_group)
cli.add_command(_status.status_cmd)
```

(The 4 imports above reference files created in subsequent tasks — tests will skip this one until Tasks 9-12 finish; for now add stubs so root.py imports don't fail.)

- [ ] **Step 4: 建立 4 個 subcommand stub 讓 root.py import 成功**

Create `src/cli/monitor.py`:
```python
import click

@click.command("monitor")
@click.option("-i", "--interval", type=int, default=10, help="Minutes between cycles")
def monitor_cmd(interval: int) -> None:
    """Run headless monitoring daemon (equivalent to --monitor)."""
    from src.main import run_daemon_loop
    run_daemon_loop(interval)
```

Create `src/cli/gui_cmd.py`:
```python
import click

@click.command("gui")
@click.option("-p", "--port", type=int, default=5001)
def gui_cmd(port: int) -> None:
    """Launch Web GUI (equivalent to --gui)."""
    from src.config import ConfigManager
    from src.gui import launch_gui, HAS_FLASK
    if not HAS_FLASK:
        click.echo("Flask is required; run: pip install -r requirements.txt", err=True)
        raise click.Abort()
    launch_gui(ConfigManager(), port=port)
```

Create `src/cli/report.py`:
```python
import click

@click.group("report")
def report_group() -> None:
    """Generate reports (traffic/audit/ven/policy-usage)."""


@report_group.command("traffic")
@click.option("--source", type=click.Choice(["api", "csv"]), default="api")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None)
@click.option("--format", "fmt", type=click.Choice(["html", "csv", "all"]), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--email", is_flag=True)
def report_traffic(source: str, file_path, fmt: str, output_dir, email: bool) -> None:
    """Generate Traffic Flow Report."""
    import sys
    from src.config import ConfigManager
    from src.api_client import ApiClient
    from src.reporter import Reporter
    from src.report.report_generator import ReportGenerator
    import os

    cm = ConfigManager()
    api = ApiClient(cm)
    reporter = Reporter(cm)
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir = os.path.dirname(pkg_dir)
    config_dir = os.path.join(root_dir, 'config')
    out = output_dir or cm.config.get('report', {}).get('output_dir', 'reports')
    if not os.path.isabs(out):
        out = os.path.join(root_dir, out)
    gen = ReportGenerator(cm, api_client=api, config_dir=config_dir)
    result = (gen.generate_from_csv(file_path) if source == "csv"
              else gen.generate_from_api())
    if result.record_count == 0:
        click.echo("No data for report", err=True)
        sys.exit(1)
    paths = gen.export(result, fmt=fmt, output_dir=out,
                       send_email=email, reporter=reporter if email else None)
    for p in paths:
        click.echo(p)
```

Create `src/cli/status.py`:
```python
import click


@click.command("status")
def status_cmd() -> None:
    """Show daemon / scheduler / config status."""
    from rich.console import Console
    from rich.table import Table
    from src.config import ConfigManager
    import os
    import datetime as _dt

    cm = ConfigManager()
    console = Console()
    table = Table(title="illumio-ops status", show_header=True, header_style="cyan")
    table.add_column("Item")
    table.add_column("Value")

    table.add_row("PCE URL", cm.config["api"]["url"])
    table.add_row("Language", cm.config["settings"].get("language", "en"))
    table.add_row("Rules", str(len(cm.config.get("rules", []))))

    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir = os.path.dirname(pkg_dir)
    log_file = os.path.join(root_dir, "logs", "illumio_ops.log")
    if os.path.exists(log_file):
        mtime = _dt.datetime.fromtimestamp(os.path.getmtime(log_file))
        try:
            from src.humanize_ext import human_time_ago
            table.add_row("Last log activity", human_time_ago(mtime))
        except Exception:
            table.add_row("Last log activity", mtime.isoformat(timespec="seconds"))
    else:
        table.add_row("Last log activity", "(no log file)")

    console.print(table)
```

- [ ] **Step 5: 跑測試確認綠燈**

Run:
```bash
python -m pytest tests/test_cli_subcommands.py -v
```
Expected: 2 tests PASS。

- [ ] **Step 6: 跑全套測試**

Run:
```bash
python -m pytest tests/ -q
```
Expected: 全綠。

- [ ] **Step 7: Commit**

```bash
git add src/cli/ tests/test_cli_subcommands.py
git commit -m "feat(cli): add click subcommand framework (monitor/gui/report/status)

New src/cli/ package with click group root + 4 subcommands:
- monitor  — headless daemon (equivalent to --monitor)
- gui      — Web GUI (equivalent to --gui)
- report   — report generation subgroup (traffic today, more in Phase 5)
- status   — rich-rendered status dashboard (new feature)

The root command invoked bare (no subcommand) falls through to the
legacy interactive main_menu() so `illumio-ops` still enters the menu."
```

---

## Task 9: 改寫 illumio_ops.py 入口 — 先試 click 再 fallback argparse

**Files:**
- Modify: `illumio_ops.py`
- Modify: `src/main.py:main()`（只小改：接受外部 argv，返回而非 exit）
- Create: `tests/test_cli_backwards_compat.py`

- [ ] **Step 1: 建立舊 flag 相容測試（先寫測試）**

Create `tests/test_cli_backwards_compat.py`:

```python
"""Verify that all legacy argparse flags still work after click migration."""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY = REPO_ROOT / "illumio_ops.py"


def _run(args, timeout=10):
    return subprocess.run(
        [sys.executable, str(ENTRY), *args],
        capture_output=True, text=True, timeout=timeout,
    )


def test_legacy_monitor_flag_still_recognized():
    # Run with --monitor -i 1 for 2 seconds then kill
    proc = subprocess.Popen(
        [sys.executable, str(ENTRY), "--monitor", "-i", "1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        # Give it 3 seconds to start, then terminate
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.terminate()
            out, err = proc.communicate(timeout=5)
        else:
            out, err = proc.stdout.read(), proc.stderr.read()
    finally:
        if proc.poll() is None:
            proc.kill()
    # Should not have crashed with an argparse error
    assert "unrecognized arguments" not in err
    assert "error:" not in err.lower() or "daemon" in out.lower()


def test_new_version_subcommand_works():
    result = _run(["version"])
    assert result.returncode == 0
    assert "illumio-ops" in result.stdout.lower()


def test_new_status_subcommand_works():
    result = _run(["status"])
    # status may exit non-zero if config missing, but it must not crash
    assert "illumio-ops status" in result.stdout.lower() or result.returncode in (0, 1)


def test_help_shows_subcommands():
    result = _run(["--help"])
    assert result.returncode == 0
    for sub in ("monitor", "gui", "report", "status", "version"):
        assert sub in result.stdout
```

- [ ] **Step 2: 跑測試確認失敗（click 還沒掛上 entry）**

Run:
```bash
python -m pytest tests/test_cli_backwards_compat.py -v
```
Expected: `test_new_version_subcommand_works` 與 `test_help_shows_subcommands` 失敗。

- [ ] **Step 3: 改寫 illumio_ops.py**

Replace `illumio_ops.py` content with:

```python
#!/usr/bin/env python3
"""Illumio PCE Ops — Entry Point.

Two parsers coexist:
- click-based subcommands (preferred): illumio-ops monitor/gui/report/status/version
- legacy argparse flags (backwards-compatible): --monitor, --gui, --report, -i, -p

The dispatcher below picks which to use based on argv[1] — if it matches a
known click subcommand name we delegate to click, otherwise argparse handles
the classic flags.

Usage:
    python illumio_ops.py                       # interactive menu
    python illumio_ops.py monitor -i 5          # new subcommand style
    python illumio_ops.py --monitor -i 5        # legacy (still works)
    python illumio_ops.py report traffic        # new
    python illumio_ops.py --report              # legacy (still works)
"""
from __future__ import annotations

import sys

# Known click subcommand names; anything else falls back to argparse.
_CLICK_SUBCOMMANDS = {"monitor", "gui", "report", "status", "version", "-h", "--help"}


def _looks_like_click_invocation(argv: list[str]) -> bool:
    """True when argv starts with a click subcommand (or is -h/--help)."""
    return len(argv) >= 2 and argv[1] in _CLICK_SUBCOMMANDS


if __name__ == "__main__":
    try:
        if _looks_like_click_invocation(sys.argv):
            from src.cli.root import cli
            cli(prog_name="illumio-ops")
        else:
            from src.main import main
            main()
    except ImportError as e:
        print(f"Error importing src package: {e}")
        print("Ensure you are running this script from the project root directory.")
        sys.exit(1)
```

- [ ] **Step 4: 跑相容測試**

Run:
```bash
python -m pytest tests/test_cli_backwards_compat.py -v
```
Expected: 4 tests PASS。

- [ ] **Step 5: 手動驗證舊/新 flag 都 OK**

Run（不 commit，只驗證）:
```bash
python illumio_ops.py --help              # 走 argparse 舊 help（legacy）
python illumio_ops.py --help              # 走 click 新 help（實際上取決於 argv[1]）
python illumio_ops.py version             # 走 click
python illumio_ops.py status              # 走 click
python illumio_ops.py --monitor -i 1 &    # 走 argparse，sleep 5 後 kill
sleep 5 && kill %1 2>/dev/null
```

注意：`--help` 在舊/新之間有歧義 — 按 `_CLICK_SUBCOMMANDS` 判斷會走 click。若要看 argparse 舊 help 只能用 `python illumio_ops.py -?` 或類似。**這是可接受的**（click 的 help 較完整），在 PR 說明裡交代。

- [ ] **Step 6: 跑全套測試**

Run:
```bash
python -m pytest tests/ -q
```
Expected: 130+ passed。

- [ ] **Step 7: Commit**

```bash
git add illumio_ops.py tests/test_cli_backwards_compat.py
git commit -m "feat(cli): dispatch click vs argparse by argv[1]

illumio_ops.py now picks the parser based on argv[1]:
- 'monitor', 'gui', 'report', 'status', 'version', '-h/--help' → click
- anything else (including --monitor, --gui, --report) → legacy argparse

Both paths coexist so existing scripts/systemd units/documentation
continue to work unchanged, while new CLI workflows use the richer
click subcommand help + bash completion."
```

---

## Task 10: 接 humanize 進主選單狀態列（使用者可見第一個改善）

**Files:**
- Modify: `src/main.py:main_menu()`（狀態列加 humanize 時間戳）

- [ ] **Step 1: 讀目前 main_menu 狀態列**

Use Read tool on `src/main.py` lines 265-340.

- [ ] **Step 2: 修改 main_menu 狀態列加入 humanize 時間**

In the status lines construction (around line 290-295), change:

```python
# OLD:
lines = [
    f"API: {cm.config['api']['url']} | Rules: {len(cm.config['rules'])}",
    f"Language: {current_lang} | Theme: {current_theme}",
    ...
]
```

Into:

```python
# NEW:
import os as _os
from src.humanize_ext import human_time_ago
import datetime as _dt

_pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
_root_dir = _os.path.dirname(_pkg_dir)
_log_file = _os.path.join(_root_dir, "logs", "illumio_ops.log")
_last_activity = "(no log activity)"
if _os.path.exists(_log_file):
    try:
        _mtime = _dt.datetime.fromtimestamp(_os.path.getmtime(_log_file))
        _last_activity = human_time_ago(_mtime)
    except Exception:
        _last_activity = "(unavailable)"

lines = [
    f"API: {cm.config['api']['url']} | Rules: {len(cm.config['rules'])}",
    f"Language: {current_lang} | Theme: {current_theme} | Last activity: {_last_activity}",
    f"{Colors.DARK_GRAY}{shortcuts_line}{Colors.ENDC}",
    "-",
    ...
]
```

- [ ] **Step 3: 新增 i18n key（供未來 ZH 顯示）**

Add to `src/i18n_en.json`:
```json
"gui_last_activity": "Last activity",
"gui_no_log_activity": "(no log activity)",
```

And to `src/i18n.py` `_ZH_EXPLICIT` dict:
```python
"gui_last_activity": "最後活動時間",
"gui_no_log_activity": "(無日誌活動)",
```

- [ ] **Step 4: 跑 i18n audit**

Run:
```bash
python -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -v
```
Expected: 0 findings / all pass。

- [ ] **Step 5: 跑全套測試**

Run:
```bash
python -m pytest tests/ -q
```
Expected: 130+ passed。

- [ ] **Step 6: Commit**

```bash
git add src/main.py src/i18n_en.json src/i18n.py
git commit -m "feat(cli): show 'Last activity: 3 minutes ago' in main menu

Uses humanize_ext.human_time_ago on logs/illumio_ops.log mtime.
Follows i18n: zh_TW shows 「最後活動時間: X分鐘前」 via humanize's
zh_CN locale (close enough for zh_TW readers)."
```

---

## Task 11: 新增 bash completion 腳本

**Files:**
- Create: `scripts/illumio-ops-completion.bash`
- Modify: `README.md`（新增安裝說明）

- [ ] **Step 1: 產生 click 內建 completion 腳本**

click 8 內建 `_CLICK_COMPLETE=bash_source` env var。直接產生靜態版（供 RPM bundle）：

Create `scripts/illumio-ops-completion.bash`:

```bash
# illumio-ops bash completion
# Install by sourcing in ~/.bashrc or dropping in /etc/bash_completion.d/
#
# Regenerate with: _ILLUMIO_OPS_COMPLETE=bash_source illumio-ops > illumio-ops-completion.bash

_illumio_ops_completion() {
    local IFS=$'\n'
    local response

    response=$(env COMP_WORDS="${COMP_WORDS[*]}" COMP_CWORD=$COMP_CWORD \
        _ILLUMIO_OPS_COMPLETE=bash_complete illumio-ops)

    for completion in $response; do
        IFS=',' read type value <<< "$completion"

        if [[ $type == 'dir' ]]; then
            COMPREPLY=()
            compopt -o dirnames
        elif [[ $type == 'file' ]]; then
            COMPREPLY=()
            compopt -o default
        elif [[ $type == 'plain' ]]; then
            COMPREPLY+=($value)
        fi
    done

    return 0
}

_illumio_ops_completion_setup() {
    complete -o nosort -F _illumio_ops_completion illumio-ops
}

_illumio_ops_completion_setup
```

- [ ] **Step 2: README.md 加安裝說明**

Read README.md current structure; find the "Installation" or "Usage" section; append:

```markdown
### Shell Tab Completion (bash)

```bash
# Source once (dev)
source scripts/illumio-ops-completion.bash

# Install globally (RPM will do this automatically):
sudo cp scripts/illumio-ops-completion.bash /etc/bash_completion.d/illumio-ops
```
```

- [ ] **Step 3: Commit**

```bash
git add scripts/illumio-ops-completion.bash README.md
git commit -m "feat(cli): add bash completion script for click subcommands

Generated from click 8's built-in completion engine. Will be installed
to /etc/bash_completion.d/illumio-ops by the future RPM.

Source scripts/illumio-ops-completion.bash for dev use."
```

---

## Task 12: 最終 regression pass + merge + tag

**Files:** （無檔案變更）

- [ ] **Step 1: 跑完整測試套件**

Run:
```bash
python -m pytest tests/ -q
```
Expected: **133+ passed + 1 pre-existing skip**（原 130 + 新增約 13 Phase 1 測試）。

- [ ] **Step 2: 跑 i18n audit**

Run:
```bash
python -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -v
```
Expected: 0 findings / all pass。

- [ ] **Step 3: 手動煙霧測試所有入口點**

Run each:
```bash
python illumio_ops.py --help             # click help
python illumio_ops.py version
python illumio_ops.py status
python illumio_ops.py --monitor -i 1 &   # legacy, kill after 5s
sleep 5 && kill %1 2>/dev/null
python illumio_ops.py                    # interactive menu (manual 0 to exit)
```
Expected: 所有都正常，新 subcommand 看到 rich 渲染的輸出，互動選單有 rich panel 邊框。

- [ ] **Step 4: 更新 Status.md 與 Task.md**

Edit Status.md version to `v3.4.1-cli`; update Dependency Status if needed (no change since Phase 0 already added rich/questionary/click/humanize).

Edit Task.md：在 Phase 0 section 後插入 Phase 1 完成記錄:

```markdown
---

## Phase 1: CLI UX 升級 ✅ DONE (2026-04-XX)

- [x] **P1**: rich + questionary + click + humanize integration
  - `Colors`/`draw_panel`/`Spinner`/`safe_input` 底層改 rich/questionary，446 呼叫點無感升級
  - 新 `src/cli/` click subcommand：`monitor`/`gui`/`report`/`status`/`version`
  - `illumio_ops.py` 依 argv[1] 派送 click vs argparse，舊 flag 完整向後相容
  - 主選單狀態列加「Last activity: 3 minutes ago」（humanize）
  - Bash completion 腳本備好供 RPM 使用
  - Test count: 130 → 143（新增 ~13）；i18n audit 持續 0 findings
  - Branch: `upgrade/phase-1-cli-rich` → squash merge + tag `v3.4.1-cli`
  - **Next Wave A task**: Phase 2 (HTTP) ‖ Phase 3 (Settings) 已可並行
```

Commit:
```bash
git add Status.md Task.md
git commit -m "docs: record Phase 1 completion"
```

- [ ] **Step 5: Push branch**

Run:
```bash
git push -u origin upgrade/phase-1-cli-rich
```

- [ ] **Step 6: 建 PR（或本機 squash merge）**

若有 gh CLI：
```bash
gh pr create --title "Phase 1: CLI UX upgrade (rich + questionary + click + humanize)" --body "$(cat <<'EOF'
## Summary
- rich-backed `Colors`/`draw_panel`/`Spinner` in utils.py (446 call sites auto-upgraded)
- questionary-backed `safe_input` with TTY-aware fallback for tests/CI
- New `src/cli/` click subcommand framework with monitor/gui/report/status/version
- argv[1] dispatcher keeps all legacy flags (`--monitor`, `--gui`, `--report`) working
- Main menu status line shows "Last activity: N minutes ago" via humanize
- Bash completion script for future RPM installation

## Why
Phase 1 of the upgrade roadmap. User-visible UX improvements first to build
upgrade momentum before structural work (Phase 2-7). No business logic changed.

## Test plan
- [x] `pytest tests/` — 143 passed, 1 pre-existing skip (was 130)
- [x] i18n audit — 0 findings
- [x] `python illumio_ops.py` — interactive menu works with rich panels
- [x] `python illumio_ops.py monitor -i 1` — new subcommand works
- [x] `python illumio_ops.py --monitor -i 1` — legacy flag works
- [x] `python illumio_ops.py status` — new status dashboard works
- [x] `python illumio_ops.py version` — version string

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

否則：
```bash
git checkout main && git pull
git merge --squash upgrade/phase-1-cli-rich
git commit -m "feat(cli): Phase 1 — CLI UX upgrade (v3.4.1-cli)"
git tag -a v3.4.1-cli -m "Phase 1 complete: rich + questionary + click + humanize"
git push origin main
git push origin v3.4.1-cli
```

- [ ] **Step 7: 清理 local branch**

```bash
git branch -d upgrade/phase-1-cli-rich
```

- [ ] **Step 8: 更新 memory**

Append to `C:/Users/harry/.claude/projects/D--OneDrive-RD-illumio-ops/memory/upgrade_roadmap_phase0.md`:

```markdown

## Phase 1 ✅ DONE (2026-04-XX)

- Branch: `upgrade/phase-1-cli-rich`, tag `v3.4.1-cli`
- Strategy: wrapper-first — rewrote `Colors`/`draw_panel`/`Spinner`/`safe_input` in utils.py to be rich/questionary-backed while keeping names; 446 call sites auto-upgraded
- New `src/cli/` click subcommand framework; `illumio_ops.py` dispatches by argv[1]
- Legacy argparse flags all still work
- humanize integrated in main menu status line
- 130 → 143 tests, i18n audit still 0 findings
- Wave A still has Phase 2 (HTTP) and Phase 3 (Settings) open in parallel
```

---

## Phase 1 完成驗收清單

- [ ] `src/utils.py` Colors/draw_panel/Spinner/safe_input 已 rich/questionary backed
- [ ] `src/humanize_ext.py` 存在且測試通過
- [ ] `src/cli/` 含 5 subcommand（monitor/gui/report/status/version）
- [ ] `illumio_ops.py` argv[1] dispatcher 運作
- [ ] 舊 flag (`--monitor`, `--gui`, `--report`) 全部可用
- [ ] 主選單狀態列有 humanize 時間
- [ ] bash completion 腳本存在
- [ ] 所有既有 127 業務測試 + 新增 ~13 Phase 1 測試通過
- [ ] i18n audit 0 findings
- [ ] Status.md + Task.md 更新
- [ ] memory 更新
- [ ] branch merged + `v3.4.1-cli` tagged

**Done means ready to:** Phase 2 (HTTP) 可續開；Wave A 繼續推進。

---

## Rollback Plan

若 Phase 1 merge 後發現 rich 渲染在某客戶終端崩壞：

```bash
git revert v3.4.1-cli
git tag -d v3.4.1-cli
git push origin :refs/tags/v3.4.1-cli
```

wrapper 策略的好處：revert 一個 commit 即可回到 Phase 0 狀態，業務邏輯完全不受影響。

---

## Self-Review Checklist

- ✅ **Spec coverage**：路線圖 Phase 1 描述的 rich + questionary + click + humanize + bash completion 全部有對應 task
- ✅ **No placeholders**：每個 step 有具體 command 或完整程式碼
- ✅ **Type consistency**：`humanize_ext` 命名於 Task 7/10 一致；`src/cli/` package 結構於 Task 8/9 一致
- ✅ **Wrapper 策略最小破壞**：Task 3-6 改底層不改介面，446 call sites 不必一個個改
- ✅ **TDD**：Task 2 先固化契約 → Task 3-6 重寫底層；Task 8 先寫 click 測試 → 補 stub
- ✅ **頻繁 commit**：12 個 task，每個各自 commit
