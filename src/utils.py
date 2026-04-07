import os
import sys
import logging
import unicodedata
import re
import threading
import itertools
from logging.handlers import RotatingFileHandler
from src.i18n import t, get_language

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_LAST_INPUT_ACTION = "value"


def get_last_input_action() -> str:
    return _LAST_INPUT_ACTION


def _set_last_input_action(action: str):
    global _LAST_INPUT_ACTION
    _LAST_INPUT_ACTION = action


class Colors:
    """ANSI color codes. Auto-disabled when stdout is not a TTY (daemon/service mode)."""

    _enabled = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    # Illumio Brand Colors (True Color RGB)
    HEADER = "\033[38;2;255;85;0m" if _enabled else ""  # Illumio Orange
    BLUE = "\033[94m" if _enabled else ""
    CYAN = "\033[38;2;148;206;229m" if _enabled else "" # Cloud Cerulean 120
    GREEN = "\033[38;2;41;155;101m" if _enabled else "" # Safeguard Green 80
    WARNING = "\033[38;2;255;162;47m" if _enabled else "" # Circuit Gold 100
    FAIL = "\033[38;2;244;63;81m" if _enabled else ""    # Risk Red 80
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
        print(f"{Colors.DARK_GRAY}{help_text}{Colors.ENDC}")

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

    shortcuts = ""
    lang = get_language()
    if allow_cancel:
        if lang == "zh_TW":
            shortcuts = "Enter預設, 0返回, -1取消, h說明"
        else:
            shortcuts = t(
                "cli_shortcuts_full",
                default="Enter=default, 0=back, -1=cancel, h=help",
            )
    else:
        if lang == "zh_TW":
            shortcuts = "Enter預設, h說明"
        else:
            shortcuts = t("cli_shortcuts_no_cancel", default="Enter=default, h=help")

    # Print shortcuts on a separate line to keep the prompt short
    print(f"{prefix}{Colors.DARK_GRAY}  {shortcuts.strip()}{Colors.ENDC}", end="")

    full_prompt = f"\n{Colors.CYAN}[?]{Colors.ENDC} {prompt}{range_hint}"
    if hint:
        def_text = t("def_val_prefix", default="Default")
        full_prompt += f" {Colors.DARK_GRAY}({def_text}: {hint}){Colors.ENDC}"
    full_prompt += f" {Colors.GREEN}❯{Colors.ENDC} "

    while True:
        try:
            raw = input(full_prompt).strip()

            if raw.lower() in ["h", "?"]:
                _set_last_input_action("help")
                if help_text:
                    print(f"{Colors.DARK_GRAY}{help_text}{Colors.ENDC}")
                else:
                    help_text_fallback = (
                        "此欄位沒有額外說明。"
                        if lang == "zh_TW"
                        else "No extra help for this field."
                    )
                    print(
                        f"{Colors.DARK_GRAY}{t('cli_no_field_help', default=help_text_fallback)}{Colors.ENDC}"
                    )
                continue

            if not raw:
                # User hit Enter without typing anything
                _set_last_input_action("empty")
                return ""

            # Standardize 0 and -1 for cancel/back ONLY if explicitly typed
            if allow_cancel and raw == "0":
                _set_last_input_action("back")
                return None

            if allow_cancel and raw == "-1":
                _set_last_input_action("cancel")
                return None

            val = value_type(raw)
            if valid_range and val not in valid_range:
                _set_last_input_action("invalid")
                print(
                    f"{Colors.FAIL}'{raw}' — {t('error_out_of_range', default='Value out of range.')}{range_hint}{Colors.ENDC}"
                )
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
            print(
                f"{Colors.FAIL}'{raw}' — {t('error_format', default='Invalid format.')} ({expected}){Colors.ENDC}"
            )


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

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count
    )
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
    elif unit_type == "bandwidth":
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
        # In Traditional Chinese (cp950) Windows environments, Ambiguous (A) chars usually take 2 spaces.
        width += 2 if status in ("W", "F", "A") else 1
    return width


def pad_string(s: str, total_width: int, fillchar: str = " ") -> str:
    """Pad string to a specific display width considering CJK characters."""
    current_width = get_visible_width(s)
    if current_width >= total_width:
        return s
    return s + fillchar * (total_width - current_width)


def draw_panel(title: str, lines: list, width: int = 0):
    """Draws a modern UI panel using Unicode box-drawing characters (╭/│/╰ style).
    *width* defaults to terminal width − 4 (min 60)."""
    if width <= 0:
        width = max(get_terminal_width() - 4, 60)
    h = Colors.HEADER
    e = Colors.ENDC
    content = []

    # Title row
    content.append(f"{h}╭── {Colors.BOLD}{title}{e}")

    # Separator after title if there are lines
    if lines:
        content.append(f"{h}├{'─' * width}{e}")

    # Lines
    for line in lines:
        if line == "-":
            content.append(f"{h}├{'─' * width}{e}")
        else:
            content.append(f"{h}│{e} {line}")

    # Footer
    content.append(f"{h}╰{'─' * width}{e}")

    print("\n".join(content))


def draw_table(headers: list, rows: list):
    """Draws a modern UI table using Unicode box-drawing characters.
    Automatically truncates columns when the total width exceeds the terminal."""
    if not headers and not rows:
        return

    cols_width = [get_visible_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(cols_width):
                w = get_visible_width(cell)
                if w > cols_width[i]:
                    cols_width[i] = w

    # Add padding
    cols_width = [w + 2 for w in cols_width]

    # Shrink columns if total exceeds terminal width
    term_w = get_terminal_width()
    overhead = len(cols_width) * 3 + 2  # separators + margins
    total = sum(cols_width) + overhead
    if total > term_w and len(cols_width) > 1:
        excess = total - term_w
        # Shrink widest columns first
        while excess > 0:
            max_i = max(range(len(cols_width)), key=lambda i: cols_width[i])
            if cols_width[max_i] <= 6:
                break
            shrink = min(excess, cols_width[max_i] - 6)
            cols_width[max_i] -= shrink
            excess -= shrink

    h = Colors.HEADER
    e = Colors.ENDC

    def _truncate(text: str, max_w: int) -> str:
        """Truncate *text* to *max_w* visible width, adding … if needed."""
        clean = ANSI_ESCAPE.sub("", text)
        if get_visible_width(clean) <= max_w:
            return text
        result = []
        w = 0
        for ch in clean:
            cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1
            if w + cw > max_w - 1:
                break
            result.append(ch)
            w += cw
        return "".join(result) + "…"

    def draw_sep():
        seps = [f"{'─' * w}" for w in cols_width]
        return f"{h}{'─┼─'.join(seps)}{e}"

    def draw_row(row_data, is_header=False):
        cells = []
        for i, cell in enumerate(row_data):
            if i >= len(cols_width):
                continue
            cell_str = _truncate(str(cell), cols_width[i] - 1)
            w = get_visible_width(cell_str)
            pad = max(cols_width[i] - w - 1, 0)
            content = f"{Colors.CYAN}{cell_str}{e}" if is_header else f"{cell_str}"
            cells.append(f" {content}{' ' * pad}")
        return f" {'│'.join(cells)}"

    print(draw_sep())
    print(draw_row(headers, is_header=True))
    print(draw_sep())

    for row in rows:
        print(draw_row(row))

    print(draw_sep())


class Spinner:
    """Context manager that shows a terminal spinner during long operations.

    Usage::

        with Spinner("Analyzing..."):
            do_long_work()
    """

    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str = ""):
        self._label = label
        self._stop = threading.Event()
        self._thread = None
        self._is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def __enter__(self):
        if self._is_tty:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            if self._label:
                print(self._label)
        return self

    def __exit__(self, *_exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        if self._is_tty:
            # Clear spinner line
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def update(self, label: str):
        """Update the spinner label while running."""
        self._label = label

    def _spin(self):
        cycle = itertools.cycle(self._FRAMES)
        while not self._stop.is_set():
            frame = next(cycle)
            sys.stdout.write(
                f"\r{Colors.CYAN}{frame}{Colors.ENDC} {self._label}\033[K"
            )
            sys.stdout.flush()
            self._stop.wait(0.08)


def progress_bar(current: int, total: int, label: str = "", width: int = 30):
    """Print an inline text progress bar. Call repeatedly to update in place."""
    if total <= 0:
        return
    ratio = min(current / total, 1.0)
    filled = int(width * ratio)
    bar = "█" * filled + "░" * (width - filled)
    pct = f"{ratio * 100:.0f}%"
    line = f"\r{Colors.CYAN}{bar}{Colors.ENDC} {pct} {current}/{total}"
    if label:
        line += f" {Colors.DARK_GRAY}{label}{Colors.ENDC}"
    sys.stdout.write(line + "\033[K")
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")
