import os
import sys
import logging
import unicodedata
from logging.handlers import RotatingFileHandler
from src.i18n import t


class Colors:
    """ANSI color codes. Auto-disabled when stdout is not a TTY (daemon/service mode)."""
    _enabled = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

    HEADER = '\033[95m' if _enabled else ''
    BLUE = '\033[94m' if _enabled else ''
    CYAN = '\033[96m' if _enabled else ''
    GREEN = '\033[92m' if _enabled else ''
    WARNING = '\033[93m' if _enabled else ''
    FAIL = '\033[91m' if _enabled else ''
    DARK_GRAY = '\033[90m' if _enabled else ''
    ENDC = '\033[0m' if _enabled else ''


def safe_input(prompt: str, value_type=str, valid_range=None, allow_cancel=True, hint=None, help_text=None):
    nav_hint = f" [{t('nav_back', default='0.Back')}]" if allow_cancel else ""
    help_hint = f" [{t('nav_help', default='?:Help')}]" if help_text else ""
    full_prompt = f"{prompt}{Colors.CYAN}{nav_hint}{help_hint}{Colors.ENDC}"
    if hint:
        full_prompt += f" {Colors.CYAN}({hint}){Colors.ENDC}"
    full_prompt += ": "
    
    while True:
        try:
            raw = input(full_prompt).strip()
            
            if raw == '?' and help_text:
                print(f"{Colors.DARK_GRAY}{help_text}{Colors.ENDC}")
                continue
                
            if not raw:
                # User hit Enter without typing anything
                return ""
            
            # Standardize 0 and -1 for cancel/back ONLY if explicitly typed
            if allow_cancel and raw in ['0', '-1']:
                return None
            
            val = value_type(raw)
            if valid_range and val not in valid_range:
                print(f"{Colors.FAIL}{t('error_out_of_range', default='Value out of range.')}{Colors.ENDC}")
                continue
            return val
        except ValueError:
            print(f"{Colors.FAIL}{t('error_format', default='Invalid format.')}{Colors.ENDC}")


def setup_logger(name: str, log_file: str, level=logging.INFO,
                 max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5) -> logging.Logger:
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
    handler.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger


def format_unit(value, type='volume') -> str:
    try:
        val = float(value)
    except (ValueError, TypeError):
        return str(value)

    if type == 'volume':
        if val >= 1024 * 1024:
            return f"{val / (1024 * 1024):.2f} TB"
        if val >= 1024:
            return f"{val / 1024:.2f} GB"
        return f"{val:.2f} MB"
    elif type == 'bandwidth':
        if val >= 1000:
            return f"{val / 1000:.2f} Gbps"
        return f"{val:.2f} Mbps"
    return str(val)


def get_display_width(s: str) -> int:
    """Calculate the display width of a string (CJK characters count as 2)."""
    width = 0
    for char in s:
        status = unicodedata.east_asian_width(char)
        width += 2 if status in ('W', 'F') else 1
    return width


def pad_string(s: str, total_width: int, fillchar: str = ' ') -> str:
    """Pad string to a specific display width considering CJK characters."""
    current_width = get_display_width(s)
    if current_width >= total_width:
        # Note: Truncation is tricky with mixed widths, returning mostly as-is 
        # but you should truncate before passing to this function if strictly needed.
        return s
    return s + fillchar * (total_width - current_width)
