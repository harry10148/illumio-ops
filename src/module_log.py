"""
Per-module execution log.
Each module gets: a RotatingFileHandler log file + in-memory ring buffer.
Call ModuleLog.init(log_dir) once at startup, then ModuleLog.get("name") anywhere.
"""
import os
import re
import threading
import datetime
import logging
from logging.handlers import RotatingFileHandler

_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# Module labels resolved via i18n at display time; keep EN as authoritative
# fallback so log viewers still read correctly without translations loaded.
MODULES: dict[str, str] = {
    "monitor":          "Monitor & Analysis",
    "rule_scheduler":   "Rule Scheduler",
    "report_scheduler": "Report Scheduler",
    "reports":          "Report Generation",
    "actions":          "Manual Actions",
}

# i18n key for each module; the GUI resolves via `t()` / `_translations[...]`.
MODULE_I18N_KEYS: dict[str, str] = {
    "monitor":          "gui_ml_mod_monitor",
    "rule_scheduler":   "gui_ml_mod_rule_scheduler",
    "report_scheduler": "gui_ml_mod_report_scheduler",
    "reports":          "gui_ml_mod_reports",
    "actions":          "gui_ml_mod_actions",
}


class ModuleLog:
    """Thread-safe per-module log with rotating file + in-memory ring buffer."""

    _registry: dict = {}
    _reg_lock = threading.Lock()
    _log_dir: str = ""

    MAX_BUFFER: int = 500
    MAX_BYTES: int = 5 * 1024 * 1024   # 5 MB per file
    BACKUP_COUNT: int = 3              # 3 rotations → max 20 MB per module

    def __init__(self, name: str):
        self.name = name
        self._buffer: list = []
        self._lock = threading.Lock()
        self._file_logger: logging.Logger | None = None

    def _ensure_file_logger(self) -> None:
        if self._file_logger is not None or not self._log_dir:
            return
        log_path = os.path.join(self._log_dir, "modules", f"{self.name}.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        lg = logging.getLogger(f"modlog.{self.name}")
        if not lg.handlers:
            h = RotatingFileHandler(
                log_path, maxBytes=self.MAX_BYTES,
                backupCount=self.BACKUP_COUNT, encoding="utf-8",
            )
            h.setFormatter(logging.Formatter("%(message)s"))
            lg.addHandler(h)
            lg.setLevel(logging.DEBUG)
            lg.propagate = False
        self._file_logger = lg

    def _append(self, level: str, message: str) -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        clean = _ANSI_RE.sub("", str(message))
        entry = {"ts": ts, "level": level, "msg": clean}
        line = f"{ts} [{level:5s}] {clean}"
        with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) > self.MAX_BUFFER:
                del self._buffer[: -self.MAX_BUFFER]
        self._ensure_file_logger()
        if self._file_logger:
            self._file_logger.info(line)

    def info(self, msg: str) -> None:    self._append("INFO",  msg)
    def warning(self, msg: str) -> None: self._append("WARN",  msg)
    def error(self, msg: str) -> None:   self._append("ERROR", msg)
    def debug(self, msg: str) -> None:   self._append("DEBUG", msg)

    def separator(self, label: str = "") -> None:
        line = ("─" * 20 + f" {label} " + "─" * 20) if label else "─" * 50
        self._append("INFO", line)

    def get_recent(self, n: int = 200) -> list:
        with self._lock:
            return list(self._buffer[-n:])

    @classmethod
    def init(cls, log_dir: str) -> None:
        """Call once at startup with the logs/ directory path."""
        cls._log_dir = log_dir

    @classmethod
    def get(cls, name: str) -> "ModuleLog":
        with cls._reg_lock:
            if name not in cls._registry:
                cls._registry[name] = cls(name)
            return cls._registry[name]

    @classmethod
    def list_modules(cls) -> list:
        with cls._reg_lock:
            return [
                {
                    "name": k,
                    "label": MODULES.get(k, k),
                    "i18n_key": MODULE_I18N_KEYS.get(k, ""),
                    "count": len(cls._registry[k]._buffer),
                }
                for k in cls._registry
            ]
