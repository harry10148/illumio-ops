import itertools
import logging
import os
import re
import sys
import threading
import unicodedata
from logging.handlers import RotatingFileHandler

from src.i18n import get_language, t

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_LAST_INPUT_ACTION = "value"


def get_last_input_action() -> str:
    return _LAST_INPUT_ACTION


def _set_last_input_action(action: str):
    global _LAST_INPUT_ACTION
    _LAST_INPUT_ACTION = action


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


class Colors:
    """ANSI color codes. Auto-disabled when stdout is not a TTY (daemon/service mode)."""

    _enabled = _stdout_is_tty()

    HEADER = "\033[38;2;255;85;0m" if _enabled else ""
    BLUE = "\033[94m" if _enabled else ""
    CYAN = "\033[38;2;148;206;229m" if _enabled else ""
    GREEN = "\033[38;2;41;155;101m" if _enabled else ""
    WARNING = "\033[38;2;255;162;47m" if _enabled else ""
    FAIL = "\033[38;2;244;63;81m" if _enabled else ""
    DARK_GRAY = "\033[90m" if _enabled else ""
    ENDC = "\033[0m" if _enabled else ""
    BOLD = "\033[1m" if _enabled else ""
    UNDERLINE = "\033[4m" if _enabled else ""


def safe_input(
    prompt: str,
    value_type=str,
    valid_range=None,
    allow_cancel=True,
    hint=None,
    help_text=None,
):
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
            range_hint = ""

    lang = get_language()
    shortcuts = t(
        "cli_shortcuts_full" if allow_cancel else "cli_shortcuts_no_cancel",
        default="Enter=default, 0=back, -1=cancel, h=help" if allow_cancel else "Enter=default, h=help",
    )
    if lang == "zh_TW" and not shortcuts:
        shortcuts = "Enter=default, 0=back, -1=cancel, h=help" if allow_cancel else "Enter=default, h=help"

    print(_console_safe_text(f"{prefix}{Colors.DARK_GRAY}  {shortcuts.strip()}{Colors.ENDC}"), end="")

    full_prompt = f"\n{Colors.CYAN}[?]{Colors.ENDC} {prompt}{range_hint}"
    if hint:
        def_text = t("def_val_prefix", default="Default")
        full_prompt += f" {Colors.DARK_GRAY}({def_text}: {hint}){Colors.ENDC}"
    full_prompt += f" {Colors.GREEN}{_console_prompt_symbol()}{Colors.ENDC} "

    while True:
        raw = ""
        try:
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


def setup_logger(
    name: str,
    log_file: str,
    level=logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
    handler.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger


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


def draw_panel(title: str, lines: list, width: int = 0):
    """Draw a simple terminal panel. Falls back to ASCII when Unicode is unsupported."""
    if width <= 0:
        width = max(get_terminal_width() - 4, 60)
    chars = _box_chars()
    h = Colors.HEADER
    e = Colors.ENDC

    top = f"{h}{chars['top_left']}{chars['horizontal'] * width}{chars['top_right']}{e}"
    mid = f"{h}{chars['left_join']}{chars['horizontal'] * width}{chars['right_join']}{e}"
    bottom = f"{h}{chars['bottom_left']}{chars['horizontal'] * width}{chars['bottom_right']}{e}"

    print(top)
    print(f"{h}{chars['vertical']}{e} {Colors.BOLD}{title}{e}")
    if lines:
        print(mid)
    for line in lines:
        if line == "-":
            print(mid)
        else:
            print(f"{h}{chars['vertical']}{e} {line}")
    print(bottom)


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
    """Context manager that shows a terminal spinner during long operations."""

    def __init__(self, label: str = ""):
        self._label = label
        self._stop = threading.Event()
        self._thread = None
        self._is_tty = _stdout_is_tty()
        self._frames = _spinner_frames()

    def __enter__(self):
        if self._is_tty:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        elif self._label:
            print(self._label)
        return self

    def __exit__(self, *_exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        if self._is_tty:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def update(self, label: str):
        self._label = label

    def _spin(self):
        cycle = itertools.cycle(self._frames)
        while not self._stop.is_set():
            frame = next(cycle)
            sys.stdout.write(f"\r{Colors.CYAN}{frame}{Colors.ENDC} {self._label}\033[K")
            sys.stdout.flush()
            self._stop.wait(0.08)


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
