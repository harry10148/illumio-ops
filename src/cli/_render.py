"""Terminal/TUI rendering helpers used by CLI menus and reports.

Moved from src/utils.py per L8 (code-review-fixes plan). Provides:
- Colors (ANSI color constants backed by rich.Style)
- safe_input / get_last_input_action (input prompt helpers)
- format_unit, get_terminal_width, get_visible_width, pad_string
- draw_panel, draw_table (rich-backed terminal rendering)
- Spinner (context-manager spinner)
- progress_bar (inline progress meter)

Tests reach into this module's privates (_stdout_is_tty, _ansi) — they
remain importable here. src/utils.py re-exports the public names for
backwards compatibility with existing `from src.utils import X`.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import unicodedata

from rich.style import Style as _RichStyle
from rich.color import ColorSystem as _ColorSystem
from rich.console import Console as _RichConsole
from rich.panel import Panel as _RichPanel
from rich.text import Text as _RichText
from rich import box as _rich_box
import questionary as _q
from questionary import Style as _QStyle

from src.i18n import get_language, t

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class _InputState:
    """Thread-safe singleton wrapping the last input action string."""

    def __init__(self, initial: str = "value") -> None:
        self._lock = threading.Lock()
        self._value = initial

    def get(self) -> str:
        with self._lock:
            return self._value

    def set(self, action: str) -> None:
        with self._lock:
            self._value = action


_INPUT_STATE = _InputState("value")


def get_last_input_action() -> str:
    """Return the most recent input action (thread-safe)."""
    return _INPUT_STATE.get()


def _set_last_input_action(action: str) -> None:
    """Record the most recent input action (thread-safe)."""
    _INPUT_STATE.set(action)


def _stdout_is_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _stream_encoding(stream=None) -> str:
    target = stream or sys.stdout
    return getattr(target, "encoding", None) or sys.getdefaultencoding() or "utf-8"


def _stream_supports_text(text: str, stream=None) -> bool:
    try:
        text.encode(_stream_encoding(stream))
        return True
    except UnicodeEncodeError:
        return False


def _console_safe_text(text: str) -> str:
    encoding = _stream_encoding()
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        return text.encode(encoding, errors="replace").decode(encoding)


def _console_prompt_symbol() -> str:
    return "❯" if _stream_supports_text("❯") else ">"


def _box_chars() -> dict[str, str]:
    if _stream_supports_text("┌─│└┘┼"):
        return {
            "top_left": "┌",
            "top_right": "┐",
            "bottom_left": "└",
            "bottom_right": "┘",
            "horizontal": "─",
            "vertical": "│",
            "cross": "┼",
            "left_join": "├",
            "right_join": "┤",
        }
    return {
        "top_left": "+",
        "top_right": "+",
        "bottom_left": "+",
        "bottom_right": "+",
        "horizontal": "-",
        "vertical": "|",
        "cross": "+",
        "left_join": "+",
        "right_join": "+",
    }


def _spinner_frames() -> list[str]:
    return ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"] if _stream_supports_text("⠋") else ["|", "/", "-", "\\"]


# NOTE: _make_ansi_codes() is a private rich API (underscore prefix).
# rich.Style.render("", reset=False) was the original plan target but the
# reset= kwarg was removed in rich 13.x, so we fell back to this private call.
# If this breaks on a rich upgrade, replace with a lookup table of hardcoded
# SGR codes (FAIL=31, GREEN=32, CYAN=36, etc.) mapping rich named colors to
# ANSI numbers. See: https://en.wikipedia.org/wiki/ANSI_escape_code#SGR_parameters
def _ansi(style: _RichStyle) -> str:
    """Render a rich Style to its ANSI escape sequence.

    Uses rich.Style._make_ansi_codes (private API) because the public
    render() method no longer supports reset=False. Isolated here so a
    future rich API change is a one-function fix.
    """
    if not _stdout_is_tty():
        return ""
    codes = style._make_ansi_codes(_ColorSystem.TRUECOLOR)
    return f"\033[{codes}m" if codes else ""


class Colors:
    """ANSI color codes — now backed by rich.Style for consistency.

    All 446 existing call sites (f'{Colors.FAIL}...{Colors.ENDC}') keep working
    because these remain plain strings containing ANSI escape sequences.
    New code should prefer rich directly (from rich.console import Console).
    Auto-disabled when stdout is not a TTY (daemon/service mode).
    """

    HEADER = _ansi(_RichStyle(color="magenta"))
    BLUE = _ansi(_RichStyle(color="blue"))
    CYAN = _ansi(_RichStyle(color="cyan"))
    GREEN = _ansi(_RichStyle(color="green"))
    WARNING = _ansi(_RichStyle(color="yellow"))
    FAIL = _ansi(_RichStyle(color="red"))
    RED = _ansi(_RichStyle(color="red"))
    DARK_GRAY = _ansi(_RichStyle(color="bright_black"))
    ENDC = "\033[0m"
    BOLD = _ansi(_RichStyle(bold=True))
    UNDERLINE = _ansi(_RichStyle(underline=True))


_QUESTIONARY_STYLE = _QStyle([
    ("qmark", "fg:#00afff bold"),
    ("question", "bold"),
    ("answer", "fg:#00ff7f bold"),
    ("pointer", "fg:#00afff bold"),
    ("highlighted", "fg:#00afff bold"),
    ("selected", "fg:#00ff7f"),
    ("instruction", "fg:#808080"),
])


def safe_input(
    prompt: str,
    value_type=str,
    valid_range=None,
    allow_cancel=True,
    hint=None,
    help_text=None,
):
    """Prompt for input with type + range validation.

    Backend uses questionary on interactive TTY for nicer prompts and
    ctrl-c handling. Non-TTY path (piped input, tests, CI) falls back
    to input() so unit tests with patch('builtins.input') continue to work.

    Return semantics:
      - str: returns stripped string, or "" if empty (go-back from str context)
      - int/float: returns typed value, or None if empty (go-back sentinel)
      - None returned on 0/"0" (back), -1/"-1" (cancel), EOF, KeyboardInterrupt
    """
    if help_text:
        print(_console_safe_text(f"{Colors.DARK_GRAY}{help_text}{Colors.ENDC}"))

    if prompt.startswith("\n"):
        prefix = "\n"
        prompt = prompt[1:]
    else:
        prefix = ""

    range_hint = ""
    if valid_range:
        try:
            vals = sorted(list(valid_range))
            if vals and all(isinstance(v, int) for v in vals):
                if vals == list(range(vals[0], vals[-1] + 1)):
                    range_hint = f" [{vals[0]}-{vals[-1]}]"
                else:
                    range_hint = " [" + ",".join(str(v) for v in vals) + "]"
            else:
                range_hint = " [" + ",".join(str(v) for v in vals) + "]"
        except Exception:
            range_hint = ""  # intentional fallback: skip range hint display if values are not iterable/numeric

    lang = get_language()
    shortcuts = t(
        "cli_shortcuts_full" if allow_cancel else "cli_shortcuts_no_cancel",
        default="Enter=default, 0=back, -1=cancel, h=help" if allow_cancel else "Enter=default, h=help",
    )
    if lang == "zh_TW" and not shortcuts:
        shortcuts = "Enter=default, 0=back, -1=cancel, h=help" if allow_cancel else "Enter=default, h=help"

    print(_console_safe_text(f"{prefix}{Colors.DARK_GRAY}  {shortcuts.strip()}{Colors.ENDC}"))

    full_prompt = f"\n{Colors.CYAN}[?]{Colors.ENDC} {prompt}{range_hint}"
    if hint:
        def_text = t("def_val_prefix", default="Default")
        full_prompt += f" {Colors.DARK_GRAY}({def_text}: {hint}){Colors.ENDC}"
    full_prompt += f" {Colors.GREEN}{_console_prompt_symbol()}{Colors.ENDC} "

    # Use questionary on interactive TTY for nicer prompts; fall back to input() otherwise
    use_questionary = (
        hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        and hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    )

    while True:
        raw = ""
        try:
            if use_questionary:
                try:
                    answer = _q.text(
                        prompt + range_hint,
                        style=_QUESTIONARY_STYLE,
                        **({} if hint is None else {"instruction": f"(Default: {hint})"}),
                    ).unsafe_ask()
                    if answer is None:
                        _set_last_input_action("back")
                        return None
                    raw = answer.strip()
                except KeyboardInterrupt:
                    _set_last_input_action("back")
                    return None
            else:
                try:
                    raw = input(full_prompt).strip()
                except UnicodeEncodeError:
                    raw = input(_console_safe_text(full_prompt)).strip()

            if raw.lower() in ["h", "?"]:
                _set_last_input_action("help")
                message = help_text or t("cli_no_field_help", default="No extra help for this field.")
                print(_console_safe_text(f"{Colors.DARK_GRAY}{message}{Colors.ENDC}"))
                continue

            if not raw:
                # Empty input: for numeric types return None with action="empty"
                # so callers can distinguish "user pressed Enter (use default)"
                # from "user pressed 0 (go back)".  str prompts keep returning "".
                if value_type in (int, float):
                    _set_last_input_action("empty")
                    return None
                _set_last_input_action("empty")
                return ""

            if allow_cancel and raw == "0":
                _set_last_input_action("back")
                return None

            if allow_cancel and raw == "-1":
                _set_last_input_action("cancel")
                return None

            val = value_type(raw)
            if valid_range and val not in valid_range:
                _set_last_input_action("invalid")
                message = t("error_out_of_range", default="Value out of range.")
                print(_console_safe_text(f"{Colors.FAIL}'{raw}' - {message}{range_hint}{Colors.ENDC}"))
                continue
            _set_last_input_action("value")
            return val
        except EOFError:
            _set_last_input_action("cancel")
            print()
            return None
        except ValueError:
            _set_last_input_action("invalid")
            expected = "number" if value_type in (int, float) else str(value_type.__name__)
            message = t("error_format", default="Invalid format.")
            print(_console_safe_text(f"{Colors.FAIL}'{raw}' - {message} ({expected}){Colors.ENDC}"))


def get_terminal_width(default: int = 80) -> int:
    """Return current terminal width, capped at 120. Falls back to *default* in non-TTY."""
    try:
        return min(os.get_terminal_size().columns, 120)
    except (AttributeError, ValueError, OSError):
        return default


def format_unit(value, unit_type="volume") -> str:
    try:
        val = float(value)
    except (ValueError, TypeError):
        return str(value)

    if unit_type == "volume":
        if val >= 1024 * 1024:
            return f"{val / (1024 * 1024):.2f} TB"
        if val >= 1024:
            return f"{val / 1024:.2f} GB"
        return f"{val:.2f} MB"
    if unit_type == "bandwidth":
        if val >= 1000:
            return f"{val / 1000:.2f} Gbps"
        return f"{val:.2f} Mbps"
    return str(val)


def get_visible_width(s: str) -> int:
    """Calculate the exact visible width of a string on screen, ignoring ANSI codes."""
    clean_s = ANSI_ESCAPE.sub("", str(s))
    width = 0
    for char in clean_s:
        status = unicodedata.east_asian_width(char)
        width += 2 if status in ("W", "F", "A") else 1
    return width


def pad_string(s: str, total_width: int, fillchar: str = " ") -> str:
    """Pad string to a specific display width considering CJK characters."""
    current_width = get_visible_width(s)
    if current_width >= total_width:
        return s
    return s + fillchar * (total_width - current_width)


_CONSOLE_SINGLETON: "_RichConsole | None" = None


def _get_console() -> _RichConsole:
    """Lazily build a shared Console so encoding / color detection runs once."""
    global _CONSOLE_SINGLETON
    if _CONSOLE_SINGLETON is None:
        _CONSOLE_SINGLETON = _RichConsole(
            force_terminal=None,  # auto-detect
            safe_box=True,        # degrades to ASCII when terminal can't render unicode
            highlight=False,      # don't auto-colorize numbers/URLs (keeps existing look)
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

    panel_kwargs: dict = {
        "title": title,
        "title_align": "left",
        "border_style": "cyan",
        "box": _rich_box.ROUNDED,
        "padding": (0, 1),
    }
    if width and width > 0:
        panel_kwargs["width"] = width

    console.print(_RichPanel(body, **panel_kwargs))


def draw_table(headers: list, rows: list):
    """Draw a terminal table and fall back to ASCII when Unicode is unsupported."""
    if not headers and not rows:
        return

    cols_width = [get_visible_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(cols_width):
                cols_width[i] = max(cols_width[i], get_visible_width(cell))

    cols_width = [w + 2 for w in cols_width]

    term_w = get_terminal_width()
    overhead = len(cols_width) * 3 + 2
    total = sum(cols_width) + overhead
    if total > term_w and len(cols_width) > 1:
        excess = total - term_w
        while excess > 0:
            max_i = max(range(len(cols_width)), key=lambda i: cols_width[i])
            if cols_width[max_i] <= 6:
                break
            shrink = min(excess, cols_width[max_i] - 6)
            cols_width[max_i] -= shrink
            excess -= shrink

    chars = _box_chars()
    h = Colors.HEADER
    e = Colors.ENDC

    def _truncate(text: str, max_w: int) -> str:
        clean = ANSI_ESCAPE.sub("", text)
        if get_visible_width(clean) <= max_w:
            return text
        result = []
        width = 0
        ellipsis = "…" if _stream_supports_text("…") else "."
        reserve = get_visible_width(ellipsis)
        for ch in clean:
            cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1
            if width + cw > max_w - reserve:
                break
            result.append(ch)
            width += cw
        return "".join(result) + ellipsis

    def draw_sep():
        segments = [chars["horizontal"] * w for w in cols_width]
        return f"{h}{chars['cross'].join(segments)}{e}"

    def draw_row(row_data, is_header=False):
        cells = []
        for i, cell in enumerate(row_data):
            if i >= len(cols_width):
                continue
            cell_str = _truncate(str(cell), cols_width[i] - 1)
            pad = max(cols_width[i] - get_visible_width(cell_str) - 1, 0)
            content = f"{Colors.CYAN}{cell_str}{e}" if is_header else cell_str
            cells.append(f" {content}{' ' * pad}")
        divider = f" {chars['vertical']} "
        return divider.join(cells)

    print(draw_sep())
    print(draw_row(headers, is_header=True))
    print(draw_sep())
    for row in rows:
        print(draw_row(row))
    print(draw_sep())


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

    def update(self, label: str):
        """Update spinner message (back-compat)."""
        self._message = label
        if self._status is not None:
            self._status.update(f"[{self._color}]{label}[/{self._color}]")


def progress_bar(current: int, total: int, label: str = "", width: int = 30):
    """Print an inline text progress bar. Call repeatedly to update in place."""
    if total <= 0:
        return
    ratio = min(current / total, 1.0)
    filled = int(width * ratio)
    fill = "█" if _stream_supports_text("█") else "#"
    empty = "░" if _stream_supports_text("░") else "-"
    bar = fill * filled + empty * (width - filled)
    pct = f"{ratio * 100:.0f}%"
    line = f"\r{Colors.CYAN}{bar}{Colors.ENDC} {pct} {current}/{total}"
    if label:
        line += f" {Colors.DARK_GRAY}{label}{Colors.ENDC}"
    sys.stdout.write(_console_safe_text(line) + "\033[K")
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")
