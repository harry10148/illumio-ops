from __future__ import annotations

import json
import re
import threading
from functools import lru_cache
from pathlib import Path

# engine.py lives at src/i18n/, but i18n_en.json / i18n_zh_TW.json sit at src/.
_ROOT = Path(__file__).resolve().parent.parent
_EN_MESSAGES_PATH = _ROOT / "i18n_en.json"
_ZH_MESSAGES_PATH = _ROOT / "i18n_zh_TW.json"


class _I18nState:
    """Thread-safe singleton for the active language code."""

    _VALID = frozenset({"en", "zh_TW"})

    def __init__(self, initial: str = "en") -> None:
        self._lock = threading.Lock()
        self._lang = initial

    def get_language(self) -> str:
        with self._lock:
            return self._lang

    def set_language(self, lang: str) -> None:
        if lang in self._VALID:
            with self._lock:
                self._lang = lang


_I18N_STATE = _I18nState("en")


def set_language(lang: str) -> None:
    """Set the active UI language (thread-safe). Public API."""
    _I18N_STATE.set_language(lang)


def get_language() -> str:
    """Return the active UI language code (thread-safe). Public API."""
    return _I18N_STATE.get_language()

def _load_en_messages() -> dict[str, str]:
    try:
        return json.loads(_EN_MESSAGES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_zh_messages() -> dict[str, str]:
    try:
        return json.loads(_ZH_MESSAGES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

EN_MESSAGES = _load_en_messages()
ZH_MESSAGES = _load_zh_messages()
_PLACEHOLDER_VALUE_RE = re.compile(r"^(?:Rpt|GUI|Gui|Sched)\b")
_STRICT_PREFIXES = (
    "gui_", "sched_", "rs_", "wgs_", "login_", "cli_", "main_",
    "settings_", "rpt_", "menu_", "ven_", "pu_", "report_",
    "error_", "alert_", "daemon_", "line_", "mail_", "webhook_",
    "event_", "confirm_", "select_", "step_", "metric_", "pd_",
    "filter_", "ex_", "rule_", "trigger_", "pill_",
)


def _is_strict_surface_key(key: str) -> bool:
    # Event catalog labels/categories are generated from vendor event ids and
    # rely on humanized fallback when explicit dictionary keys are absent.
    if key.startswith("event_label_") or key.startswith("cat_"):
        return False
    return key.startswith(_STRICT_PREFIXES)


def _missing_marker(key: str) -> str:
    return f"[MISSING:{key}]"


def _load_json_data(filename: str) -> dict[str, str]:
    """Load a JSON-encoded dict from src/i18n/data/<filename>."""
    path = Path(__file__).parent / "data" / filename
    return json.loads(path.read_text(encoding="utf-8"))


_ZH_EXPLICIT: dict[str, str] = _load_json_data("zh_explicit.json")

_SKIP_TOKENS = {
    "gui", "cli", "lbl", "opt", "th", "nav", "wiz", "menu", "main",
    "msg", "col", "tab", "sec", "event",
}

_TOKEN_MAP_EN: dict[str, str] = _load_json_data("token_map_en.json")

_TOKEN_MAP_ZH: dict[str, str] = _load_json_data("token_map_zh.json")

_PHRASE_OVERRIDES: dict[str, str] = _load_json_data("phrase_overrides.json")

def _humanize_key_en(key: str) -> str:
    if key.startswith("event_label_"):
        key = key[len("event_label_"):]
    elif key.startswith("cat_"):
        key = key[len("cat_"):]
    parts = [p for p in key.split("_") if p and p not in _SKIP_TOKENS and not p.isdigit()]
    if not parts:
        return key
    words = []
    for part in parts:
        words.append(_TOKEN_MAP_EN.get(part.lower(), part.replace("-", " ").title()))
    return " ".join(words).strip()

@lru_cache(maxsize=1)
def _normalized_en_messages() -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in dict(EN_MESSAGES).items():
        if not isinstance(value, str):
            normalized[key] = value
            continue
        stripped = value.strip()
        if not stripped:
            normalized[key] = _humanize_key_en(key)
            continue
        if _PLACEHOLDER_VALUE_RE.match(stripped):
            normalized[key] = _humanize_key_en(key)
            continue
        normalized[key] = value
    return normalized


@lru_cache(maxsize=1)
def _normalized_zh_messages() -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in dict(ZH_MESSAGES).items():
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if not stripped:
            continue
        normalized[key] = value
    return normalized

def _needs_space(prev: str, curr: str) -> bool:
    return (
        (prev.isascii() and (prev.isalnum() or prev in "/+%")) and
        (curr.isascii() and (curr.isalnum() or curr in "/+%"))
    )

def _smart_join_zh(parts: list[str]) -> str:
    result = ""
    for part in parts:
        if not part:
            continue
        if not result:
            result = part
            continue
        if _needs_space(result[-1], part[0]):
            result += " " + part
        else:
            result += part
    return result

def _humanize_key_zh(key: str) -> str:
    if key.startswith("event_label_"):
        key = key[len("event_label_"):]
    elif key.startswith("cat_"):
        key = key[len("cat_"):]
    parts = [p for p in key.split("_") if p and p not in _SKIP_TOKENS and not p.isdigit()]
    if not parts:
        return key
    words: list[str] = []
    for part in parts:
        word = _TOKEN_MAP_ZH.get(part.lower(), part.replace("-", " ").title())
        if words and words[-1] == word:
            continue
        words.append(word)
    return _smart_join_zh(words).strip() or key

def _translate_text(text: str) -> str:
    if not text:
        return text
    if text in _PHRASE_OVERRIDES:
        return _PHRASE_OVERRIDES[text]
    result = text
    for src, dst in sorted(_PHRASE_OVERRIDES.items(), key=lambda item: len(item[0]), reverse=True):
        result = result.replace(src, dst)

    replacements = [
        (r"\bTraffic Flow Report\b", "流量分析報表"),
        (r"\bAudit Log Report\b", "稽核報表"),
        (r"\bAudit & System Events Report\b", "稽核與系統事件報表"),
        (r"\bVEN Status Report\b", "VEN 狀態報表"),
        (r"\bPolicy Usage Report\b", "Policy 使用報表"),
        (r"\bReport Generation\b", "報表產生"),
        (r"\bRule Scheduler\b", "規則排程"),
        (r"\bSystem Settings\b", "系統設定"),
        (r"\bView System Logs\b", "查看系統日誌"),
        (r"\bLaunch Web GUI\b", "啟動 Web GUI"),
        (r"\bRule Management & Alerts\b", "規則管理與告警"),
        (r"\bGenerate\b", "產生"),
        (r"\bDelete\b", "刪除"),
        (r"\bDownload\b", "下載"),
        (r"\bView\b", "檢視"),
        (r"\bSave\b", "儲存"),
        (r"\bLoading\b", "載入中"),
        (r"\bSearch\b", "搜尋"),
        (r"\bRulesets\b", "規則集"),
        (r"\bRuleset\b", "Ruleset"),
        (r"\bRules\b", "規則"),
        (r"\bRule\b", "規則"),
        (r"\bSchedule\b", "排程"),
        (r"\bTraffic\b", "流量"),
        (r"\bAudit\b", "稽核"),
        (r"\bReport\b", "報表"),
        (r"\bStatus\b", "狀態"),
        (r"\bSettings\b", "設定"),
        (r"\bSystem\b", "系統"),
        (r"\bStart Date\b", "開始日期"),
        (r"\bEnd Date\b", "結束日期"),
        (r"\bTime Window\b", "時間視窗"),
        # Glossary whitelist: keep English — Port, Service(s), Workload(s),
        # Policy, Enforcement, Allow, Deny, Blocked, Potentially Blocked,
        # PCE, VEN are handled elsewhere in the chain but NO regex here
        # substitutes them with Chinese.
        (r"\bSource\b", "來源端"),
        (r"\bDestination\b", "目的端"),
        (r"\bProtocol\b", "Protocol"),
        (r"\bConnections\b", "連線數"),
        (r"\bDecision\b", "判定"),
        (r"\bEnabled\b", "啟用"),
        (r"\bDisabled\b", "停用"),
        (r"\bSuccess\b", "成功"),
        (r"\bFailed\b", "失敗"),
        (r"\bUpdated\b", "已更新"),
        (r"\bSaved\b", "已儲存"),
        (r"\bDeleted\b", "已刪除"),
        (r"\bNever run\b", "尚未執行"),
        (r"\bOnline\b", "Online"),
        (r"\bOffline\b", "Offline"),
        (r"\bmanaged\b", "managed"),
        (r"\bunmanaged\b", "unmanaged"),
        (r"\bYes\b", "是"),
        (r"\bNo\b", "否"),
    ]
    for pattern, repl in replacements:
        result = re.sub(pattern, repl, result)

    result = result.replace(" : ", "：").replace(": ", "：")
    result = result.replace(" ?", "？").replace(" .", "。")
    result = re.sub(r"\s{2,}", " ", result).strip()
    return result

@lru_cache(maxsize=1)
def _discover_keys() -> set[str]:
    patterns = [
        re.compile(r"""_?t\(\s*['"]([^'"]+)['"]"""),
        re.compile(r"""data-i18n=["']([A-Za-z0-9_&]+)["']"""),
        re.compile(r"""_translations\[['"]([A-Za-z0-9_&]+)['"]\]"""),
    ]
    keys: set[str] = set()
    for path in list(_ROOT.rglob("*.py")) + list(_ROOT.rglob("*.html")) + list(_ROOT.rglob("*.js")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in patterns:
            for key in pattern.findall(text):
                if re.fullmatch(r"[A-Za-z0-9_&]+", key):
                    keys.add(key)
    return keys

@lru_cache(maxsize=2)
def _build_messages(lang: str) -> dict[str, str]:
    en_messages = _normalized_en_messages()
    all_keys = set(en_messages) | _discover_keys()
    if lang == "en":
        base = dict(en_messages)
        for key in all_keys:
            if key in base and isinstance(base[key], str) and base[key].strip():
                continue
            if _is_strict_surface_key(key):
                base[key] = _missing_marker(key)
            else:
                base[key] = _humanize_key_en(key)
        return base

    zh_messages = _normalized_zh_messages()
    base: dict[str, str] = {}
    for key in all_keys:
        zh_text = zh_messages.get(key)
        if isinstance(zh_text, str) and zh_text.strip():
            base[key] = zh_text
            continue
        if _is_strict_surface_key(key):
            base[key] = _missing_marker(key)
            continue
        if key in _ZH_EXPLICIT:
            base[key] = _ZH_EXPLICIT[key]
            continue
        en_text = en_messages.get(key)
        if en_text:
            translated = _translate_text(en_text)
            if translated and translated != en_text:
                base[key] = translated
                continue
        base[key] = _humanize_key_zh(key)
    return base

def get_messages(lang: str | None = None) -> dict[str, str]:
    lang = lang or get_language()
    if lang not in {"en", "zh_TW"}:
        lang = "en"
    return dict(_build_messages(lang))

def t(key: str, **kwargs) -> str:
    default_val = kwargs.pop("default", None)
    _lang = get_language()
    text = get_messages(_lang).get(key)
    if text is None:
        text = _normalized_en_messages().get(key)
    if text is None and _is_strict_surface_key(key):
        text = _missing_marker(key)
    if text is None:
        if default_val is not None:
            text = default_val
        else:
            text = _humanize_key_zh(key) if _lang == "zh_TW" else _humanize_key_en(key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
