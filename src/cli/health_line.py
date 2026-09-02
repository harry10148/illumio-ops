"""CLI 全域健康列（5 燈）。資料來源與 GUI dashboard overview 同源。

同源是重點：CLI 與 web UI 不該對「這台機器健不健康」給出不同答案，所以這裡
不自己算，只包裝 dashboard 已經在算的那幾個函式。

任何來源失敗 → 該燈 neutral，本模組**絕不**向呼叫端拋錯。健康列是輔助訊號；
一個因為健康探測失敗而畫不出來的選單，比一盞灰燈糟得多。四個 `_load_*` 薄
包裝獨立成模組級函式，測試以 monkeypatch 替換。
"""
from __future__ import annotations

import datetime

from src.i18n import t
from src.cli._render import Colors

_TONE_COLOR = {
    "ok": Colors.GREEN,
    "warn": Colors.WARNING,
    "crit": Colors.FAIL,
    "neutral": Colors.DARK_GRAY,
}
_TONE_RANK = {"neutral": 0, "ok": 1, "warn": 2, "crit": 3}
_LEVEL_TO_TONE = {"ok": "ok", "warning": "warn", "warn": "warn", "error": "crit"}


def _worst(tones) -> str:
    """The lamp shows the worst thing it covers — an ok among errors is a lie."""
    worst = "neutral"
    for tone in tones:
        if _TONE_RANK.get(tone, 0) > _TONE_RANK.get(worst, 0):
            worst = tone
    return worst


def _dur(seconds) -> str:
    """Transcribed from design/v2/mockup/js/core/fmt.mjs dur()."""
    try:
        s = float(seconds or 0)
    except (TypeError, ValueError):
        return "-"
    if s < 60:
        return f"{int(s)}s"
    if s < 3600:
        return f"{round(s / 60)}m"
    return f"{round(s / 3600)}h"


def _load_job_health_rows() -> list[dict]:
    from src.gui.routes.dashboard import _overview_job_health
    return _overview_job_health()


def _load_pipeline(cm) -> dict:
    from src.gui.routes.dashboard import _overview_pipeline
    return _overview_pipeline(cm)


def _load_pce_stats() -> dict:
    import json
    import os
    from src.gui._helpers import _resolve_state_file
    p = _resolve_state_file()
    if not os.path.exists(p):
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return (json.load(f) or {}).get("pce_stats", {}) or {}


def _load_alert_channels(cm) -> list[dict]:
    import json
    import os
    from src.gui._helpers import _resolve_state_file, _summarize_alert_channels
    hist: list = []
    p = _resolve_state_file()
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            hist = (json.load(f) or {}).get("dispatch_history", []) or []
    return _summarize_alert_channels(cm.config, hist, lang="en")


def _lamp(tone: str, text: str) -> dict:
    return {"tone": tone, "text": text}


def _neutral(label_key: str) -> dict:
    return _lamp("neutral", f"{t(label_key)} -")


def _jobs_lamp() -> dict:
    rows = _load_job_health_rows() or []
    if not rows:
        return _neutral("cli_health_jobs")
    tones = [_LEVEL_TO_TONE.get(str(r.get("level", "")), "neutral") for r in rows]
    ok_count = sum(1 for tone in tones if tone == "ok")
    return _lamp(_worst(tones), f"{t('cli_health_jobs')} {ok_count}/{len(rows)}")


def _pce_lamp() -> dict:
    stats = _load_pce_stats() or {}
    if not stats:
        return _neutral("cli_health_pce")
    tone = _LEVEL_TO_TONE.get(str(stats.get("event_poll_status", "")), "neutral")
    failures = int(stats.get("consecutive_failures", 0) or 0)
    # A run of failures outranks whatever the last poll reported: the poll can
    # read "ok" from a cycle that predates the outage.
    if failures > 0:
        tone = "crit"
    label = t("cli_health_pce")
    if tone == "ok":
        text = f"{label} OK"
    elif failures:
        # "PCE 410" reads as a status code; "PCE x410" reads as a count.
        text = f"{label} x{failures}"
    else:
        text = f"{label} -"
    return _lamp(tone, text)


def _lag_lamp(pipeline: dict) -> dict:
    rows = pipeline.get("cache_lag") or []
    if not rows:
        return _neutral("cli_health_lag")
    tones = [_LEVEL_TO_TONE.get(str(r.get("level", "")), "neutral") for r in rows]
    worst_lag = max((float(r.get("lag_s") or 0) for r in rows), default=0)
    return _lamp(_worst(tones), f"{t('cli_health_lag')} {_dur(worst_lag)}")


def _siem_lamp(pipeline: dict) -> dict:
    if "siem_success_1h" not in pipeline and "verdict" not in pipeline:
        return _neutral("cli_health_siem")
    tone = _LEVEL_TO_TONE.get(str(pipeline.get("verdict", "")), "neutral")
    success = pipeline.get("siem_success_1h")
    dlq = int(pipeline.get("dlq", 0) or 0)
    # Both of these mean deliveries are being lost even while the verdict says
    # the pipeline is up, so they can only raise the lamp, never lower it.
    if dlq > 0 or (success is not None and float(success) < 95):
        tone = _worst([tone, "warn"])
    text = f"{t('cli_health_siem')} {'-' if success is None else f'{float(success):.0f}%'}"
    return _lamp(tone, text)


def _chan_lamp(cm) -> dict:
    rows = _load_alert_channels(cm) or []
    live = [r for r in rows if r.get("enabled") and r.get("configured")]
    label = t("cli_health_chan")
    if not live:
        # Nothing configured is not the same as everything working.
        return _lamp("neutral", f"{label} 0/{len(rows)}")
    failed = any(r.get("last_status") and r.get("last_status") != "success" for r in live)
    return _lamp("crit" if failed else "ok", f"{label} {len(live)}/{len(rows)}")


def _clock(cm) -> str:
    from src.cli.menus._helpers import _tz_offset_info
    label, offset_hours = _tz_offset_info(cm)
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset_hours)
    return f"{now.strftime('%H:%M')} {label}"


def build_health_summary(cm) -> dict:
    """Five lamps plus a clock. Every source is isolated: one failure is one
    grey lamp, not a missing menu."""
    summary: dict = {}

    def _safe(key, fn, label_key):
        try:
            summary[key] = fn()
        except Exception:
            summary[key] = _neutral(label_key)

    _safe("jobs", _jobs_lamp, "cli_health_jobs")
    _safe("pce", _pce_lamp, "cli_health_pce")

    try:
        pipeline = _load_pipeline(cm) or {}
    except Exception:
        pipeline = {}
    _safe("lag", lambda: _lag_lamp(pipeline), "cli_health_lag")
    _safe("siem", lambda: _siem_lamp(pipeline), "cli_health_siem")
    _safe("chan", lambda: _chan_lamp(cm), "cli_health_chan")

    try:
        summary["clock"] = _clock(cm)
    except Exception:
        summary["clock"] = ""
    return summary


def build_health_line(cm) -> str:
    """One line: ``● Jobs 14/14 │ ● PCE OK │ … 06:27 UTC+8``."""
    s = build_health_summary(cm)
    dot = "●" if _supports_unicode() else "*"
    sep = " │ " if _supports_unicode() else " | "
    parts = []
    for key in ("jobs", "pce", "lag", "siem", "chan"):
        lamp = s.get(key) or _lamp("neutral", "-")
        parts.append(f"{_paint(dot, _TONE_COLOR.get(lamp['tone'], ''))} {lamp['text']}")
    line = sep.join(parts)
    clock = s.get("clock") or ""
    return f"{line}   {_paint(clock, Colors.DARK_GRAY)}" if clock else line


def _paint(text: str, color: str) -> str:
    """Colors go empty when stdout is not a TTY, but ENDC is a hardcoded reset —
    pairing them unconditionally leaves a bare escape sequence in piped output."""
    return f"{color}{text}{Colors.ENDC}" if color else text


def _supports_unicode() -> bool:
    """Same fallback shape as _render._console_prompt_symbol."""
    import sys
    enc = getattr(sys.stdout, "encoding", "") or ""
    try:
        "●│".encode(enc or "ascii")
    except (UnicodeEncodeError, LookupError):
        return False
    return True
