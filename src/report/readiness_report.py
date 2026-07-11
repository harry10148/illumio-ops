"""Enforcement Readiness standalone report — generator facade.

Thin wrapper over the SHARED mod13 analysis (single source of truth with the
Security report's readiness chapter): fetch the estate traffic DataFrame
(cache-aware, via ReportGenerator.fetch_traffic_df) plus managed workloads,
run enforcement_readiness(), and synthesize the advancement queue that answers
"which app (env) can we safely move to enforcement next".
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import os

import pandas as pd
from loguru import logger

from src.i18n import t
# _score_to_grade is module-private in mod13 but intentionally imported here:
# grade thresholds must stay a single source of truth with the Security chapter.
from src.report.analysis.mod13_readiness import _score_to_grade, enforcement_readiness

_QUEUE_FACTORS = [
    ("policy_coverage", "policy_coverage_ratio"),
    ("ringfence_maturity", "ringfence_maturity_ratio"),
    ("enforcement_mode", "enforcement_mode_ratio"),
    ("staged_readiness", "staged_readiness_ratio"),
    ("remote_app_coverage", "remote_app_coverage_ratio"),
]
_QUEUE_COLS = ["app_display", "app_env_key", "readiness_score", "grade",
               "current_mode", "blocking_factor", "blocking_factor_key",
               "recommended_action", "flow_count", "pb_uncovered_count"]
# mod13 truncates app_env_scores with .head(top_n) (default 20); the standalone
# queue must rank the WHOLE estate, so pass an effectively unbounded top_n.
_ALL_APPS = 100_000
_MODE_ORDER = {"full": 0, "selective": 1, "visibility_only": 2, "idle": 3}


def _iso_window(value, *, end_of_day):
    """Normalize bare 'YYYY-MM-DD' (GUI date pickers) to full ISO-8601 —
    a date-only value makes the PCE traffic query return zero flows
    (same guard as AppSummaryReport.build)."""
    if not value or not isinstance(value, str) or "T" in value:
        return value
    try:
        parsed = datetime.datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%dT" + ("23:59:59Z" if end_of_day else "00:00:00Z"))


def _workload_app_env_key(w: dict) -> str:
    """app|env key for a workload, normalized EXACTLY like mod13's
    _normalize_key_series (lower/strip, empty -> 'unlabeled')."""
    app = env = ""
    for lbl in (w.get("labels") or []):
        if lbl.get("key") == "app":
            app = str(lbl.get("value") or "")
        elif lbl.get("key") == "env":
            env = str(lbl.get("value") or "")
    app = app.strip().lower() or "unlabeled"
    env = env.strip().lower() or "unlabeled"
    return f"{app}|{env}"


def _mode_summary(modes: dict[str, int]) -> str:
    if not modes:
        return "-"
    parts = sorted(modes.items(), key=lambda kv: (_MODE_ORDER.get(kv[0], 9), kv[0]))
    return ", ".join(f"{mode}×{count}" for mode, count in parts)


@dataclasses.dataclass
class ReadinessResult:
    record_count: int
    module_results: dict
    dataframe: pd.DataFrame | None = None
    generated_at: datetime.datetime = dataclasses.field(
        default_factory=datetime.datetime.now)
    date_range: tuple = ("", "")


class ReadinessReportGenerator:
    def __init__(self, config_manager, api_client=None, config_dir: str = "config",
                 cache_reader=None):
        self.cm = config_manager
        self.api = api_client
        self._config_dir = config_dir
        self._cache = cache_reader
        self._lang = "en"

    # ── Fetch ────────────────────────────────────────────────────────────
    def _fetch_estate_df(self, start_date, end_date, *, use_cache: bool = True):
        from src.report.report_generator import ReportGenerator
        gen = ReportGenerator(config_manager=self.cm, api_client=self.api,
                              config_dir=self._config_dir, cache_reader=self._cache)
        return gen.fetch_traffic_df(
            start_date=_iso_window(start_date, end_of_day=False),
            end_date=_iso_window(end_date, end_of_day=True),
            use_cache=use_cache)

    def _fetch_workloads(self) -> list | None:
        if not self.api:
            return None
        try:
            return self.api.fetch_managed_workloads()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Readiness] workloads fetch failed: {} — "
                           "enforcement-mode factor falls back to flow inference", exc)
            return None

    # ── Generate ─────────────────────────────────────────────────────────
    def generate_from_api(self, start_date=None, end_date=None, lang: str = "en",
                          use_cache: bool = True,
                          output_dir: str = "reports") -> ReadinessResult:
        self._lang = lang
        date_range = (start_date or "", end_date or "")
        df = self._fetch_estate_df(start_date, end_date, use_cache=use_cache)
        if df is None or df.empty:
            return ReadinessResult(record_count=0, module_results={},
                                   date_range=date_range)
        workloads = self._fetch_workloads()
        readiness = enforcement_readiness(df, workloads=workloads,
                                          top_n=_ALL_APPS, lang=lang)
        module_results: dict = {"readiness": readiness}
        result = ReadinessResult(record_count=len(df), module_results=module_results,
                                 dataframe=df, date_range=date_range)
        if "error" in readiness:
            return result
        queue_df = self._build_queue(readiness, workloads)
        module_results["queue_df"] = queue_df
        module_results["kpis"] = self._build_kpis(readiness, queue_df, lang)
        self._attach_trend(result, output_dir)
        return result

    # ── Queue synthesis (generator-side; NOT in mod13) ───────────────────
    def _build_queue(self, readiness: dict, workloads: list | None) -> pd.DataFrame:
        scores = readiness.get("app_env_scores")
        if scores is None or scores.empty:
            return pd.DataFrame(columns=_QUEUE_COLS)
        modes_by_key: dict[str, dict[str, int]] = {}
        for w in (workloads or []):
            key = _workload_app_env_key(w)
            mode = str(w.get("enforcement_mode", "unknown")).lower().strip() or "unknown"
            bucket = modes_by_key.setdefault(key, {})
            bucket[mode] = bucket.get(mode, 0) + 1
        action_by_key: dict[str, str] = {}
        recs = readiness.get("recommendations")
        if recs is not None and not recs.empty and "App Env Key" in recs.columns:
            # recommendations are pre-ranked P1..P5 — keep the FIRST per app.
            for _, r in recs.iterrows():
                action_by_key.setdefault(str(r["App Env Key"]), str(r["Action"]))
        rows = []
        for _, s in scores.iterrows():
            ratios = {name: float(s.get(col, 0.0)) for name, col in _QUEUE_FACTORS}
            blocking = min(ratios, key=ratios.get)
            key = str(s["app_env_key"])
            score = float(s["readiness_score"])
            rows.append({
                "app_display": s.get("app_display", key),
                "app_env_key": key,
                "readiness_score": score,
                "grade": _score_to_grade(score),
                "current_mode": _mode_summary(modes_by_key.get(key, {})),
                "blocking_factor": t(f"rpt_factor_{blocking}", lang=self._lang),
                "blocking_factor_key": blocking,
                "recommended_action": action_by_key.get(key, "-"),
                "flow_count": int(s.get("flow_count", 0)),
                "pb_uncovered_count": int(s.get("pb_uncovered_count", 0)),
            })
        # Ready-first: the next app to enforce sits on top.
        return pd.DataFrame(rows, columns=_QUEUE_COLS).sort_values(
            by=["readiness_score", "app_env_key"], ascending=[False, True]
        ).reset_index(drop=True)

    @staticmethod
    def _build_kpis(readiness: dict, queue_df: pd.DataFrame, lang: str) -> list[dict]:
        ready = int(queue_df["grade"].isin(["A", "B"]).sum()) if not queue_df.empty else 0
        blocked = int(queue_df["grade"].isin(["D", "F"]).sum()) if not queue_df.empty else 0
        def _kpi(key: str, value):
            return {"i18n_key": key, "label": t(key, lang=lang), "value": value}
        return [
            _kpi("rpt_readiness_kpi_score", readiness.get("total_score", 0)),
            _kpi("rpt_readiness_kpi_grade", readiness.get("grade", "?")),
            _kpi("rpt_readiness_kpi_ready", ready),
            _kpi("rpt_readiness_kpi_blocked", blocked),
            _kpi("rpt_readiness_kpi_pb_uncovered", readiness.get("pb_uncovered_count", 0)),
        ]

    # ── Trend snapshot (load BEFORE save — trend_store contract) ─────────
    def _attach_trend(self, result: ReadinessResult, output_dir: str) -> None:
        from src.report.trend_store import (
            build_kpi_dict_from_metadata, canonicalize_legacy_keys, compute_deltas,
            load_previous, save_snapshot, snapshot_mismatch,
        )
        try:
            kpi_dict = build_kpi_dict_from_metadata(result.module_results.get("kpis", []))
            prev = load_previous(output_dir, "readiness")
            prev = canonicalize_legacy_keys(prev, candidate_keys=list(kpi_dict.keys()))
            # window as {"start", "end"} — matches ReportGenerator's
            # _snapshot_meta shape, which snapshot_mismatch()/_window_span_days()
            # require (a bare [start, end] list has no .get() and would raise).
            meta = {"profile": "readiness",
                    "window": {"start": result.date_range[0],
                               "end": result.date_range[1]}}
            save_snapshot(output_dir, "readiness", kpi_dict,
                          generated_at=result.generated_at.isoformat(timespec="seconds"),
                          meta=meta)
            result.module_results["_trend_deltas"] = compute_deltas(kpi_dict, prev) if prev else []
            result.module_results["_trend_mismatch"] = snapshot_mismatch(meta, prev) if prev else []
        except Exception as e:  # noqa: BLE001
            logger.warning("Readiness trend delta skipped: {}", e)
            result.module_results["_trend_deltas"] = []

    # ── Export ───────────────────────────────────────────────────────────
    def export(self, result: ReadinessResult, fmt: str = 'html',
               output_dir: str = 'reports', lang: str | None = None) -> list[str]:
        from src.report.exporters.readiness_html_exporter import ReadinessHtmlExporter
        from src.report.exporters.csv_exporter import CsvExporter
        lang = lang or self._lang
        os.makedirs(output_dir, exist_ok=True)
        paths: list[str] = []
        mr = result.module_results or {}
        if fmt in ('html', 'all'):
            path = ReadinessHtmlExporter(result, lang=lang).export(output_dir)
            paths.append(path)
            self._write_report_metadata(path, result, file_format='html')
            print(t("rpt_readiness_html_saved", path=path, lang=lang))
        if fmt in ('csv', 'all'):
            readiness = mr.get("readiness", {})
            # CSV carries FULL untruncated values (recovery path for the
            # HTML _CELL_MAX truncation).
            export_data = {}
            if mr.get("queue_df") is not None:
                export_data["queue"] = mr["queue_df"]
            for key in ("factor_table", "recommendations"):
                df = readiness.get(key)
                if df is not None and not getattr(df, "empty", True):
                    export_data[key] = df
            if export_data:
                path = CsvExporter(export_data, report_label='Readiness').export(output_dir)
                paths.append(path)
                self._write_report_metadata(path, result, file_format='csv')
                print(t("rpt_readiness_csv_saved", path=path, lang=lang))
        return paths

    def _write_report_metadata(self, report_path: str, result: ReadinessResult,
                               file_format: str) -> None:
        payload = {
            "report_type": "readiness",
            "file_format": file_format,
            "generated_at": result.generated_at.isoformat(),
            "record_count": int(result.record_count or 0),
            "date_range": list(result.date_range or ("", "")),
            "kpis": (result.module_results or {}).get("kpis", []),
        }
        with open(report_path + ".metadata.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
