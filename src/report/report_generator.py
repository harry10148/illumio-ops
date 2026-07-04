"""
src/report/report_generator.py
Unified Report Generation Entry Point (ModeA — no DB).

Usage:
    from src.report.report_generator import ReportGenerator

    gen = ReportGenerator(config_manager, api_client)

    # From PCE API:
    result = gen.generate_from_api()
    paths = gen.export(result, fmt='excel', output_dir='reports/')

    # From CSV:
    result = gen.generate_from_csv('/path/to/traffic.csv')
    paths = gen.export(result, fmt='all', output_dir='reports/')
"""
from __future__ import annotations

import datetime
from loguru import logger
import os
from dataclasses import dataclass, field
from typing import Optional

from src.i18n import t
from src.report.rules_engine import ruleset_needs_draft_pd, DRAFT_PD_RULES
from src.report.report_metadata import (
    attack_summary_counts,
    build_attack_summary_brief,
    extract_attack_summary,
)
from src.report.tz_utils import parse_tz as _parse_tz, fmt_tz_now as _fmt_tz_now


def _fmt_iso(dt) -> str:
    return dt.isoformat().replace("+00:00", "Z") if hasattr(dt, "isoformat") else str(dt)


_REPORT_DETAIL_LEVEL = "full"


# ─── Snapshot helper (module-level) ──────────────────────────────────────────

def _build_snapshot(module_results: dict) -> dict:
    """Serialize module results into a JSON-safe snapshot for the Web UI dashboard."""
    import math
    try:
        import numpy as np
        _has_np = True
    except ImportError:
        _has_np = False

    def _safe_val(v):
        if _has_np:
            if isinstance(v, np.integer):
                return int(v)
            if isinstance(v, np.floating):
                return None if (np.isnan(v) or np.isinf(v)) else float(v)
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        if isinstance(v, (dict, list)):
            return str(v)
        return v

    def _df_records(df, limit=10):
        if df is None or not hasattr(df, 'empty') or df.empty:
            return []
        return [
            {k: _safe_val(v) for k, v in row.items()}
            for row in df.head(limit).to_dict('records')
        ]

    mod01 = module_results.get('mod01', {})
    mod02 = module_results.get('mod02', {})
    mod03 = module_results.get('mod03', {})
    mod04 = module_results.get('mod04', {})
    mod08 = module_results.get('mod08', {})
    mod11 = module_results.get('mod11', {})
    mod12 = module_results.get('mod12', {})

    # Policy summary from mod02
    policy_summary = []
    if isinstance(mod02, dict) and 'summary' in mod02:
        policy_summary = _df_records(mod02['summary'], limit=10)

    # Top blocked/uncovered app flows (mod02 blocked)
    top_blocked_flows = []
    if isinstance(mod02, dict) and 'blocked' in mod02:
        top_blocked_flows = _df_records(mod02['blocked'].get('top_app_flows'), limit=10)

    return {
        'generated_at': mod12.get('generated_at', ''),
        'kpis':         mod12.get('kpis', []),
        'key_findings': mod12.get('key_findings', []),
        'boundary_breaches': mod12.get('boundary_breaches', []),
        'suspicious_pivot_behavior': mod12.get('suspicious_pivot_behavior', []),
        'blast_radius': mod12.get('blast_radius', []),
        'blind_spots': mod12.get('blind_spots', []),
        'action_matrix': mod12.get('action_matrix', []),
        # mod01 scalars
        'total_flows':          _safe_val(mod01.get('total_flows', 0)),
        'total_connections':    _safe_val(mod01.get('total_connections', 0)),
        'policy_coverage_pct':  _safe_val(mod01.get('policy_coverage_pct', 0)),
        'allowed_flows':        _safe_val(mod01.get('allowed_flows', 0)),
        'blocked_flows':        _safe_val(mod01.get('blocked_flows', 0)),
        'potentially_blocked':  _safe_val(mod01.get('potentially_blocked_flows', 0)),
        'total_mb':             _safe_val(mod01.get('total_mb', 0)),
        'date_range':           mod01.get('date_range', ''),
        # mod01 tables
        'top_ports':      _df_records(mod01.get('top_ports'), limit=10),
        'top_protocols':  _df_records(mod01.get('top_protocols'), limit=5),
        # mod02 tables
        'policy_summary':       policy_summary,
        'top_blocked_flows':    top_blocked_flows,
        # mod03
        'total_uncovered':  _safe_val(mod03.get('total_uncovered', 0)),
        'uncovered_pct':    _safe_val(100 - mod03.get('coverage_pct', 100)),
        'top_uncovered':    _df_records(mod03.get('top_flows'), limit=10),
        # mod04
        'ransomware_risk_total': _safe_val(mod04.get('risk_flows_total', 0)),
        # mod08
        'unique_unmanaged_src': _safe_val(mod08.get('unique_unmanaged_src', 0)),
        'top_unmanaged_src':    _df_records(mod08.get('top_unmanaged_src'), limit=10),
        # mod11
        'bw_data_available': bool(mod11.get('bytes_data_available', False)),
        'total_mb_bw':       _safe_val(mod11.get('total_mb', 0)),
        'top_by_bytes':      _df_records(mod11.get('top_by_bytes'), limit=10),
        'top_bandwidth':     _df_records(mod11.get('top_bandwidth'), limit=10),
        # Phase 3.1: client-side Microsegmentation Maturity bar chart
        'maturity_dimensions': mod12.get('maturity_dimensions', {}),
        'maturity_score':      _safe_val(mod12.get('maturity_score', 0)),
        'maturity_grade':      mod12.get('maturity_grade', '?'),
    }

# ─── Result container ─────────────────────────────────────────────────────────

@dataclass
class ReportResult:
    """In-memory report result (replaces DB persistence in Mode A)."""
    generated_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    data_source: str = ''          # 'csv' or 'api'
    record_count: int = 0
    date_range: tuple = ('', '')
    module_results: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    dataframe: object = None       # pd.DataFrame, optional
    query_context: dict = field(default_factory=dict)

# ─── Generator ───────────────────────────────────────────────────────────────

class ReportGenerator:
    """
    Orchestrates the full report pipeline:
        DataSource → Parser → Validator → RulesEngine → 12 Modules → Export
    """

    def __init__(self, config_manager=None, api_client=None, config_dir: str = 'config',
                 cache_reader=None, api=None):
        self.cm = config_manager
        # Allow `api` as a keyword alias for `api_client` (used by tests and cache path)
        self.api = api_client if api_client is not None else api
        self._config_dir = config_dir
        self._cache = cache_reader
        self._report_cfg = self._load_report_config()

    # ── cache-aware traffic fetch ────────────────────────────────────────────

    def _fetch_traffic(self, start: datetime.datetime, end: datetime.datetime,
                       filters: Optional[dict] = None,
                       use_cache: bool = True,
                       cache_workload_hrefs: Optional[list] = None) -> dict:
        """Return traffic flows with metadata. Uses cache when fully covered.
        On partial coverage where cache_start > request start, merges API gap
        with cached data; tags source as 'mixed' when the gap is non-empty,
        or 'cache' when the API returns zero rows for the gap.

        use_cache=False forces a pure live PCE query for the whole window
        (freshest data, no local cache), ignoring any wired cache reader.
        """
        if use_cache and self._cache is not None:
            state = self._cache.cover_state("traffic", start, end)
            if state == "full":
                logger.info("Traffic report: flows from cache ({} → {})", start, end)
                return {
                    "raw": self._cache.read_flows_raw(start, end, workload_hrefs=cache_workload_hrefs),
                    "agg": self._cache.read_flows_agg(start, end),
                    "source": "cache",
                }
            if state == "partial":
                cache_start = self._cache.earliest_data_timestamp("traffic")
                if cache_start is not None and cache_start > start:
                    # 半開的 gap 視窗：cache.read_flows_raw 兩端皆含端點
                    # （'last_detected >= start AND <= end'，見
                    # src/pce_cache/reader.py），且此處呼叫的 PCE traffic
                    # API 與 analyzer._fetch_query_flows 走同一個
                    # start_date/end_date payload（inclusive，秒解析度，
                    # 見 src/analyzer.py C6 修法與其假設風險註解）。若 API
                    # gap 直接以 cache_start 結束，落在 cache_start 精確
                    # 時間戳上的 flow 會被兩側各算一次。將 API gap 的結束
                    # 時間回退 1 秒，使 gap 覆蓋 [start, cache_start)、
                    # cache 覆蓋 [cache_start, end] —— 每筆 flow 恰好計
                    # 一次。與 analyzer 相同的殘餘風險：若 API end 實為
                    # exclusive，則 cache_start-1s 那一整秒的 flow 會被
                    # 漏掉，屬已知取捨，嚴格優於先前的雙算。
                    gap_end_dt = cache_start - datetime.timedelta(seconds=1)
                    logger.info(
                        "Traffic report: hybrid fetch — API gap [{} → {}], cache [{} → {}]",
                        start, gap_end_dt, cache_start, end,
                    )
                    if gap_end_dt >= start:
                        gap = self.api.fetch_traffic_for_report(
                            start_time_str=_fmt_iso(start),
                            end_time_str=_fmt_iso(gap_end_dt),
                            filters=filters,
                        ) or []
                    else:
                        # 次秒級 gap：回退 1 秒後已無有意義的窗口可查詢。
                        gap = []
                    cached = self._cache.read_flows_raw(cache_start, end, workload_hrefs=cache_workload_hrefs)
                    # agg data not available for hybrid results
                    source = "mixed" if gap else "cache"
                    return {"raw": gap + cached, "agg": None, "source": source}
        flows = self.api.fetch_traffic_for_report(
            start_time_str=_fmt_iso(start),
            end_time_str=_fmt_iso(end),
            filters=filters,
        )
        return {"raw": flows or [], "agg": None, "source": "api"}

    def _fetch_traffic_df(self, start: datetime.datetime, end: datetime.datetime,
                          filters: Optional[dict] = None, use_cache: bool = True,
                          cache_workload_hrefs: Optional[list] = None,
                          compute_draft: bool = False):
        """Return (DataFrame, source). Same cover-state logic as _fetch_traffic
        but the cache portion is built via the vectorized read_flows_df (no
        per-row re-flatten); API portions go through _parse_api. The cache and
        API frames are assembled identically so output matches either source."""
        import pandas as pd
        from src.report.df_filter import apply_df_traffic_filters
        # Push the report's policy-decision filter into the cache read — the live
        # API applies it server-side, so the cache must too (correctness) and it
        # reads far fewer rows (perf). The remaining filters (labels/ip/port) the
        # API applies server-side too, so re-apply them on the cache df.
        pds = (filters or {}).get("policy_decisions") or None
        # iplist/workload 物件條件展開成 CIDR（df 無 href 欄位；spec §4.2）。
        # 只在確實含物件 filter key 時才呼叫，避免對不相干的 filters（例如
        # 純 label 條件）也觸發 API 呼叫（測試中 api 為泛用 mock 時尤其重要）。
        _obj_filter_keys = (
            "src_iplist", "src_iplists", "dst_iplist", "dst_iplists",
            "src_workload", "src_workloads", "dst_workload", "dst_workloads",
            "ex_src_iplist", "ex_src_iplists", "ex_dst_iplist", "ex_dst_iplists",
            "ex_src_workload", "ex_src_workloads", "ex_dst_workload", "ex_dst_workloads",
            "any_iplist", "any_workload",
            "ex_any_iplist", "ex_any_workload",
        )
        if filters and self.api is not None and any(filters.get(k) for k in _obj_filter_keys):
            filters = self.api.expand_object_filters_for_df(filters)
        if use_cache and self._cache is not None:
            state = self._cache.cover_state("traffic", start, end)
            if state == "full":
                df = self._cache.read_flows_df(start, end, workload_hrefs=cache_workload_hrefs,
                                               policy_decisions=pds)
                df = apply_df_traffic_filters(df, filters)
                logger.info("Traffic report: flows from cache ({} → {}) [vectorized]", start, end)
                return df, "cache"
            if state == "partial":
                cache_start = self._cache.earliest_data_timestamp("traffic")
                if cache_start is not None and cache_start > start:
                    # 半開的 gap 視窗：語意與假設同 _fetch_traffic 的
                    # 同型註解（cache 兩端皆含端點、PCE API 亦為
                    # inclusive）。將 gap 結束時間回退 1 秒，避免
                    # cache_start 精確時間戳上的 flow 被兩側各算一次。
                    gap_end_dt = cache_start - datetime.timedelta(seconds=1)
                    logger.info(
                        "Traffic report: hybrid fetch — API gap [{} → {}], cache [{} → {}]",
                        start, gap_end_dt, cache_start, end,
                    )
                    if gap_end_dt >= start:
                        gap = self.api.fetch_traffic_for_report(
                            start_time_str=_fmt_iso(start),
                            end_time_str=_fmt_iso(gap_end_dt),
                            filters=filters,
                            compute_draft=compute_draft,
                        ) or []
                    else:
                        # 次秒級 gap：回退 1 秒後已無有意義的窗口可查詢。
                        gap = []
                    df_gap = self._parse_api(gap)
                    df_cache = self._cache.read_flows_df(cache_start, end,
                                                         workload_hrefs=cache_workload_hrefs,
                                                         policy_decisions=pds)
                    df_cache = apply_df_traffic_filters(df_cache, filters)
                    parts = [d for d in (df_gap, df_cache) if not d.empty]
                    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
                    return df, ("mixed" if not df_gap.empty else "cache")
        flows = self.api.fetch_traffic_for_report(
            start_time_str=_fmt_iso(start),
            end_time_str=_fmt_iso(end),
            filters=filters,
            compute_draft=compute_draft,
        )
        return self._parse_api(flows or []), "api"

    def fetch_traffic_df(self, start_date: Optional[str] = None,
                         end_date: Optional[str] = None,
                         filters: Optional[dict] = None,
                         use_cache: bool = True,
                         cache_workload_hrefs: Optional[list] = None):
        """Query the PCE (cache-aware) and return the parsed estate traffic df.

        Thin reuse of the same fetch primitives generate_from_api uses
        (_fetch_traffic + _parse_api). Returns an empty DataFrame when no
        records are returned. Used by single-app facades that scope the estate
        df post-fetch rather than re-querying per app.
        """
        import pandas as pd
        if self.api is None:
            raise RuntimeError("api_client is required for fetch_traffic_df()")
        if not end_date:
            end_date = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        if not start_date:
            start_date = (
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
            ).isoformat().replace("+00:00", "Z")
        start_dt = datetime.datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        end_dt = datetime.datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        if ruleset_needs_draft_pd(DRAFT_PD_RULES):
            filters = dict(filters or {})
            filters.setdefault("requires_draft_pd", True)
        df, _ = self._fetch_traffic_df(start_dt, end_dt, filters, use_cache=use_cache,
                                       cache_workload_hrefs=cache_workload_hrefs)
        return df

    @staticmethod
    def _cap_records(df, max_results, draft_policy: bool = False):
        """Cap df to max_results rows so analysis/render stays tractable on busy
        PCEs. For draft-policy reports, move the draft-divergent (subtype) flows —
        the R01-R05 subjects — ahead of the cap so they survive the truncation."""
        if not max_results or df.empty or len(df) <= max_results:
            return df
        import pandas as pd
        if draft_policy and "draft_policy_decision" in df.columns:
            sub = df["draft_policy_decision"].astype(str).str.contains(
                "_by_boundary|_override_deny|_across_boundary", regex=True, na=False)
            df = pd.concat([df[sub], df[~sub]], ignore_index=True)
        return df.head(max_results)

    # ── public ───────────────────────────────────────────────────────────────

    def generate_from_api(self, start_date: Optional[str] = None,
                          end_date: Optional[str] = None,
                          max_results: int | None = None,
                          filters: Optional[dict] = None,
                          traffic_report_profile: str = "security_risk",
                          detail_level: str = _REPORT_DETAIL_LEVEL,
                          lang: str = "en",
                          clip_to_cache: bool = False,
                          use_cache: bool = True,
                          draft_policy: bool = False,
                          vuln_csv_path: str | None = None) -> ReportResult:
        """Fetch traffic from PCE API and run the full analysis pipeline.

        filters: optional dict with traffic filter keys (src_labels, dst_labels,
                 src_ip, dst_ip, port, proto, ex_src_labels, ex_dst_labels,
                 ex_src_ip, ex_dst_ip, ex_port, policy_decisions).
        """
        from src.report.analysis import PROFILES
        if traffic_report_profile not in PROFILES:
            raise ValueError(f"invalid traffic_report_profile: {traffic_report_profile!r}")
        if self.api is None:
            raise RuntimeError("api_client is required for generate_from_api()")

        # Default to last 7 days if not provided
        if not end_date:
            end_date = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        if not start_date:
            start_date = (
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
            ).isoformat().replace("+00:00", "Z")

        logger.info("[ReportGenerator] Starting API-source report generation")
        print(t("rpt_querying_traffic", start=start_date, end=end_date, lang=lang))
        policy_decisions = list((filters or {}).get("policy_decisions") or ["blocked", "potentially_blocked", "allowed"])

        start_dt = datetime.datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        end_dt = datetime.datetime.fromisoformat(end_date.replace("Z", "+00:00"))

        # Clip the request window to actual cache data range when requested.
        # Lets the user opt out of the leading-gap API call when PCE has
        # nothing older than what the cache already holds.
        if clip_to_cache and self._cache is not None:
            cache_earliest = self._cache.earliest_data_timestamp("traffic")
            if cache_earliest is not None and cache_earliest > start_dt and cache_earliest <= end_dt:
                logger.info(
                    "ReportGenerator: clip_to_cache clipping start {} → {}",
                    start_dt, cache_earliest,
                )
                start_dt = cache_earliest
                start_date = start_dt.isoformat().replace("+00:00", "Z")
            elif cache_earliest is not None and cache_earliest > end_dt:
                logger.info(
                    "ReportGenerator: clip_to_cache requested but cache earliest ({}) is after request end ({}); skipping clip",
                    cache_earliest, end_dt,
                )
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if end_dt > now_utc:
                end_dt = now_utc
                end_date = end_dt.isoformat().replace("+00:00", "Z")

        if draft_policy:
            use_cache = False  # cache has no draft_policy_decision column — force a live fetch
            filters = dict(filters or {})
            filters["requires_draft_pd"] = True
        df, _source = self._fetch_traffic_df(start_dt, end_dt, filters, use_cache=use_cache,
                                             compute_draft=draft_policy)
        if max_results and not df.empty and len(df) > max_results:
            logger.info("[ReportGenerator] capping {} rows to max_results={}", len(df), max_results)
            df = self._cap_records(df, max_results, draft_policy)

        if df.empty:
            logger.warning("[ReportGenerator] No records returned from API")
            print(t("rpt_no_traffic_data", lang=lang))
            return ReportResult(
                data_source=_source,
                record_count=0,
                query_context={
                    "start_date": start_date,
                    "end_date": end_date,
                    "filters": dict(filters or {}),
                    "policy_decisions": policy_decisions,
                    "query_diagnostics": self.api.get_last_traffic_query_diagnostics() if self.api else {},
                },
            )

        print(t("rpt_records_received", count=f"{len(df):,}", lang=lang))
        self._detail_level = _REPORT_DETAIL_LEVEL
        self._lang = lang
        self._vuln_csv_path = vuln_csv_path
        return self._run_pipeline(
            df,
            source=_source,
            query_context={
                "start_date": start_date,
                "end_date": end_date,
                "filters": dict(filters or {}),
                "policy_decisions": policy_decisions,
                "query_diagnostics": self.api.get_last_traffic_query_diagnostics() if self.api else {},
            },
            traffic_report_profile=traffic_report_profile,
        )

    def generate_from_csv(self, csv_path: str,
                          traffic_report_profile: str = "security_risk",
                          detail_level: str = _REPORT_DETAIL_LEVEL,
                          lang: str = "en",
                          vuln_csv_path: str | None = None) -> ReportResult:
        """Parse a CSV file from the PCE UI export and run the analysis pipeline."""
        from src.report.analysis import PROFILES
        if traffic_report_profile not in PROFILES:
            raise ValueError(f"invalid traffic_report_profile: {traffic_report_profile!r}")
        self._detail_level = _REPORT_DETAIL_LEVEL
        self._lang = lang
        self._vuln_csv_path = vuln_csv_path
        logger.info(f"[ReportGenerator] Starting CSV-source report from: {csv_path}")
        print(t("rpt_parsing_csv", path=csv_path, lang=lang))
        df = self._parse_csv(csv_path)
        return self._run_pipeline(df, source='csv', traffic_report_profile=traffic_report_profile)

    def export(self, result: ReportResult, fmt: str = 'html',
               output_dir: str = 'reports',
               send_email: bool = False,
               reporter=None,
               traffic_report_profile: str = "security_risk",
               detail_level: str = _REPORT_DETAIL_LEVEL,
               lang: str | None = None) -> list[str]:
        """
        Export a ReportResult to one or more files.

        Args:
            result:                output of generate_from_*()
            fmt:                   'html' | 'csv' | 'all'
            output_dir:            directory to write files into
            send_email:            if True, send via reporter.send_report_email()
            reporter:              Reporter instance (required if send_email=True)
            traffic_report_profile: 'security_risk' | 'network_inventory'

        Returns:
            list of file paths written
        """
        from src.report.exporters.html_exporter import (
            SecurityRiskHtmlExporter, NetworkInventoryHtmlExporter,
        )
        from src.report.exporters.csv_exporter import CsvExporter

        # When the caller (CLI / scheduler) omits lang, inherit the language the
        # report was generated and analysed in. Exec-summary KPI labels are
        # resolved at analysis time while section/nav text resolves at export
        # time — if the two stages disagree the report comes out half-Chinese,
        # half-English. Defaulting to self._lang keeps a single source of truth.
        lang = lang or getattr(self, '_lang', 'en')

        paths = []
        # Per-format errors surface to the GUI so the user can see why a format
        # produced no file (previously swallowed by silent except → empty paths).
        self.last_export_errors: dict[str, str] = {}

        # Trend analysis + baseline drift: compute and inject into
        # result.module_results BEFORE any exporter consumes it — exporters
        # below render whatever is in module_results at construction time.
        # Loads read the PREVIOUS run's files; saves archive this run's data.
        try:
            from src.report.trend_store import save_snapshot, load_previous, compute_deltas, build_kpi_dict_from_metadata, canonicalize_legacy_keys, snapshot_mismatch
            _trend_key = f"traffic_{traffic_report_profile}"
            meta = self._build_report_metadata(result, file_format="snapshot")
            kpi_dict = build_kpi_dict_from_metadata(meta.get("kpis", []))
            ts = meta.get("generated_at", "")
            prev = load_previous(output_dir, _trend_key)
            prev = canonicalize_legacy_keys(prev, candidate_keys=list(kpi_dict.keys()))
            _snapshot_meta = {
                "window": {
                    "start": result.date_range[0] if result.date_range else "",
                    "end": result.date_range[1] if len(result.date_range) > 1 else "",
                },
                "data_source": result.data_source,
                "profile": traffic_report_profile,
            }
            save_snapshot(output_dir, _trend_key, kpi_dict, generated_at=ts, meta=_snapshot_meta)
            if prev:
                result.module_results["_trend_deltas"] = compute_deltas(kpi_dict, prev)
                result.module_results["_trend_mismatch"] = snapshot_mismatch(_snapshot_meta, prev)
            # Baseline drift is a security_risk-only section; other profiles
            # neither render nor archive flow signatures.
            if traffic_report_profile == "security_risk":
                from src.report.flow_history import build_signatures, load_previous_baseline, save_signatures
                from src.report.analysis.mod_drift import baseline_drift
                if result.dataframe is not None and not result.dataframe.empty:
                    _prev_sigs, _prev_ts, _prev_meta = load_previous_baseline(output_dir, _trend_key)
                    result.module_results["mod_drift"] = baseline_drift(
                        result.dataframe, prev_signatures=_prev_sigs, prev_generated_at=_prev_ts,
                        prev_meta=_prev_meta, current_meta=_snapshot_meta)
                    save_signatures(output_dir, _trend_key, build_signatures(result.dataframe),
                                    generated_at=ts, meta=_snapshot_meta)
        except Exception as e:
            logger.warning(f"[ReportGenerator] Trend snapshot failed: {e}")

        if fmt in ('html', 'all', 'all_raw'):
            from src.report.exporters.html_exporter import TrafficFlowsHtmlExporter
            _exporter_cls = {
                "network_inventory": NetworkInventoryHtmlExporter,
                "traffic": TrafficFlowsHtmlExporter,
            }.get(traffic_report_profile, SecurityRiskHtmlExporter)
            path = _exporter_cls(
                result.module_results,
                data_source=result.data_source,
                profile=traffic_report_profile,
                detail_level=_REPORT_DETAIL_LEVEL,
                compute_draft=ruleset_needs_draft_pd(DRAFT_PD_RULES),
                lang=lang,
            ).export(output_dir)
            paths.append(path)
            self._write_report_metadata(path, self._build_report_metadata(result, file_format="html"))
            print(t("rpt_html_saved", path=path, lang=lang))

        if fmt in ('xlsx', 'all'):
            try:
                import datetime as _dt
                ts_str = _dt.datetime.now().strftime('%Y-%m-%d_%H%M')
                xlsx_path = os.path.join(output_dir, f'Illumio_Traffic_Report_{ts_str}.xlsx')
                meta = self._build_report_metadata(result, file_format="xlsx")
                xlsx_metadata = {
                    'title': 'Traffic Flow Report',
                    'generated_at': meta.get('generated_at', ''),
                    'start_date': result.date_range[0] if result.date_range else '',
                    'end_date': result.date_range[1] if len(result.date_range) > 1 else '',
                }
                build_traffic_xlsx(
                    result.module_results or {}, xlsx_path,
                    profile=traffic_report_profile, lang=lang,
                    record_count=result.record_count, metadata=xlsx_metadata,
                )
                paths.append(xlsx_path)
                print(t("rpt_xlsx_saved", path=xlsx_path, lang=lang, default=f"XLSX saved: {xlsx_path}"))
            except Exception as exc:
                logger.exception('XLSX export failed: {}', exc)
                self.last_export_errors['xlsx'] = str(exc) or exc.__class__.__name__

        if fmt in ('csv', 'all', 'all_raw'):
            export_data = dict(result.module_results)
            if result.dataframe is not None and not result.dataframe.empty:
                export_data['raw_traffic'] = result.dataframe
            path = CsvExporter(export_data, report_label='Traffic').export(output_dir)
            paths.append(path)
            self._write_report_metadata(path, self._build_report_metadata(result, file_format="csv"))
            print(t("rpt_csv_saved", path=path, lang=lang))

        if fmt in ('raw_csv', 'all_raw'):
            if result.data_source != 'api' or not result.query_context:
                raise ValueError("Raw Explorer CSV export is only supported for API-sourced traffic reports")
            if self.api is None:
                raise RuntimeError("api_client is required for raw Explorer CSV export")
            raw_export = self.api.export_traffic_query_csv(
                start_time_str=result.query_context.get("start_date"),
                end_time_str=result.query_context.get("end_date"),
                policy_decisions=result.query_context.get("policy_decisions"),
                filters=result.query_context.get("filters"),
                output_dir=output_dir,
            )
            paths.append(raw_export["path"])
            self._write_report_metadata(
                raw_export["path"],
                {
                    "report_type": "traffic_raw_csv",
                    "file_format": "raw_csv",
                    "generated_at": result.generated_at.isoformat(),
                    "record_count": int(raw_export.get("row_count", 0) or 0),
                    "date_range": list(result.date_range),
                    "summary": "Raw Explorer CSV export",
                    "query_diagnostics": raw_export.get("query_diagnostics", {}),
                    "policy_decisions": raw_export.get("policy_decisions", []),
                    "filters": raw_export.get("filters", {}),
                    "job_href": raw_export.get("job_href", ""),
                    "compute_draft": raw_export.get("compute_draft", False),
                },
            )
            print(t("rpt_raw_csv_saved", path=raw_export['path'], lang=lang))

        # Save snapshot for Web UI Dashboard directly
        try:
            import json
            snapshot_path = os.path.join(output_dir, 'latest_snapshot.json')
            with open(snapshot_path, 'w', encoding='utf-8') as f:
                json.dump(_build_snapshot(result.module_results), f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[ReportGenerator] Failed to write KPI snapshot: {e}")

        # Snapshot store for Change Impact (snapshot_store, separate from trend_store)
        try:
            from datetime import datetime, timezone
            from src.report.snapshot_store import write_snapshot, cleanup_old
            # Posture/maturity KPIs live as top-level keys in mod12 (the display
            # 'kpis' is a list). collect_current_kpis 是快照寫入端與章節渲染端的
            # 單一事實來源，兩端 key 集合由此保持一致。
            from src.report.analysis.mod_change_impact import collect_current_kpis
            kpis_dict = collect_current_kpis(result.module_results)
            if isinstance(kpis_dict, dict) and kpis_dict:
                retention = self.cm.models.report.snapshot_retention_days
                snap = {
                    "report_type": "traffic",
                    "profile": traffic_report_profile,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "query_window": {
                        "start": result.date_range[0] if result.date_range else None,
                        "end": result.date_range[1] if len(result.date_range) > 1 else None,
                    },
                    "kpis": kpis_dict,
                    "policy_changes_since_previous": [],
                }
                write_snapshot("traffic", snap)
                cleanup_old("traffic", retention_days=retention)
        except Exception as e:
            logger.warning(f"[ReportGenerator] Change Impact snapshot write failed: {e}")

        # Refresh the dashboard posture summary now that a fresh KPI snapshot
        # exists, so the overview hero updates immediately after a report run
        # instead of waiting for the next scheduled posture tick.
        try:
            from src.scheduler.jobs import run_posture_summary
            run_posture_summary(self.cm)
        except Exception as e:
            logger.warning(f"[ReportGenerator] posture refresh after report failed: {e}")

        if send_email and reporter is not None:
            html_path = next((p for p in paths if p.endswith('.html')), None)
            mod12 = result.module_results.get('mod12', {})
            subject = t("rpt_email_traffic_subject", lang=lang) + f" — {datetime.date.today()}"
            html_body = self._build_email_body(mod12, lang=lang)
            try:
                reporter.send_report_email(subject, html_body, attachment_path=html_path)
                print(t("rpt_email_sent", lang=lang))
            except Exception as e:
                logger.error(f"[ReportGenerator] Email send failed: {e}")
                print(t("rpt_email_failed", error=str(e), lang=lang))

        return paths

    # ── private — pipeline ───────────────────────────────────────────────────

    def _run_pipeline(self, df, source: str, query_context: Optional[dict] = None,
                      traffic_report_profile: str = "security_risk") -> ReportResult:
        """Validate → Rules → 12 modules → wrap result."""
        import pandas as pd
        from src.report.parsers.validators import validate, coerce
        from src.report.rules_engine import RulesEngine

        if df is None or (hasattr(df, 'empty') and df.empty):
            logger.warning("[ReportGenerator] Empty DataFrame, skipping analysis")
            return ReportResult(data_source=source, record_count=0)

        lang = getattr(self, '_lang', 'en')

        issues = validate(df)
        if issues:
            print(t("rpt_schema_warnings", count=len(issues), lang=lang))
            df = coerce(df)

        record_count = len(df)
        print(t("rpt_running_analysis", count=f"{record_count:,}", lang=lang))

        # Rules engine
        if traffic_report_profile == "traffic":
            findings = []
        else:
            engine = RulesEngine(self._report_cfg, config_dir=self._config_dir, lang=lang)
            findings = engine.evaluate(df)
            print(t("rpt_rules_findings", count=len(findings), lang=lang))

        # 15 modules
        results = self._run_modules(df, findings, traffic_report_profile=traffic_report_profile,
                                    lang=lang)

        # Label hygiene (Inventory profile section): workloads fetch is best-effort.
        # CSV-sourced reports have no inventory — flow-derived metrics only.
        if traffic_report_profile != "traffic":
            try:
                from src.report.analysis.mod_labels import label_hygiene
                _workloads = None
                if source != 'csv' and self.api is not None:
                    _workloads = self.api.fetch_managed_workloads()
                results["mod_labels"] = label_hygiene(df, _workloads, lang=lang)
            except Exception as exc:  # noqa: BLE001 — hygiene must not break the report
                logger.warning(f"[Report] label hygiene skipped: {exc}")
                results["mod_labels"] = {"workload_data_available": False,
                                         "managed_unlabeled_flow_count": 0}
        else:
            results["mod_labels"] = {"workload_data_available": False,
                                     "managed_unlabeled_flow_count": 0}

        # V-E lite: only when the operator supplies a vulnerability-scan CSV.
        if getattr(self, "_vuln_csv_path", None) and traffic_report_profile != "traffic":
            try:
                from src.report.parsers.vuln_csv import load_vulns
                from src.report.analysis.mod_vuln import vuln_exposure
                results["mod_vuln"] = vuln_exposure(df, load_vulns(self._vuln_csv_path), lang=lang)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[Report] vuln exposure skipped: {exc}")
                results["mod_vuln"] = {"available": False}

        # Override generated_at with configured timezone
        tz_str = self.cm.config.get('settings', {}).get('timezone', 'local')
        try:
            tz = _parse_tz(tz_str)
            results['mod12']['generated_at'] = _fmt_tz_now(tz)
        except Exception:
            pass  # intentional fallback: keep mod12's default generated_at if timezone parsing fails

        # Date range
        first = df['first_detected'].min() if 'first_detected' in df.columns else pd.NaT
        last = df['last_detected'].max() if 'last_detected' in df.columns else pd.NaT
        date_range = (str(first.date()) if pd.notna(first) else '',
                      str(last.date()) if pd.notna(last) else '')

        return ReportResult(
            data_source=source,
            record_count=record_count,
            date_range=date_range,
            module_results=results,
            findings=findings,
            dataframe=df,
            query_context=dict(query_context or {}),
        )

    @staticmethod
    def _write_report_metadata(report_path: str, payload: dict):
        import json

        with open(report_path + ".metadata.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

    def _build_report_metadata(self, result: ReportResult, file_format: str) -> dict:
        mod12 = result.module_results.get("mod12", {}) if isinstance(result.module_results, dict) else {}
        attack_summary = extract_attack_summary(result.module_results, top_n=5)
        counts = attack_summary_counts(attack_summary)
        summary = build_attack_summary_brief(counts)
        if not summary:
            summary = f"traffic records {int(getattr(result, 'record_count', 0) or 0)}"
        return {
            "report_type": "traffic",
            "file_format": file_format,
            "generated_at": getattr(result, "generated_at", datetime.datetime.now()).isoformat(),
            "record_count": int(getattr(result, "record_count", 0) or 0),
            "date_range": list(getattr(result, "date_range", ("", "")) or ("", "")),
            "kpis": mod12.get("kpis", []),
            "summary": summary,
            "attack_summary": attack_summary,
            "attack_summary_counts": counts,
        }

    def _run_modules(self, df, findings: list,
                     traffic_report_profile: str = "security_risk",
                     lang: str = "en") -> dict:
        """Execute all registered analysis modules via the module registry."""
        from src.report.analysis import get_traffic_modules, get_summary_module

        top_n = self._report_cfg.get('output', {}).get('top_n', 20)
        results: dict = {'findings': findings}
        module_errors: list = []

        for mod_id, fn, adapter in get_traffic_modules(traffic_report_profile):
            try:
                results[mod_id] = adapter(fn, df, self._report_cfg, top_n, lang)
                print(f"[Report]   {mod_id} ✓", end='  \r', flush=True)
            except Exception as e:
                logger.warning(f"[ReportGenerator] {mod_id} failed: {e}")
                results[mod_id] = {'error': str(e)}
                module_errors.append({'module': mod_id, 'error': str(e)})

        # Summary module runs last (depends on all other results)
        try:
            summary_id, summary_fn = get_summary_module()
            results[summary_id] = summary_fn(results, profile=traffic_report_profile, lang=lang)
        except Exception as e:
            logger.error(f"[ReportGenerator] summary module failed: {e}")
            results['mod12'] = {'error': str(e)}
            module_errors.append({'module': 'mod12', 'error': str(e)})

        results['_module_errors'] = module_errors
        print(t("rpt_modules_complete", lang=lang) + "             ")

        return results

    # ── private — parsers ────────────────────────────────────────────────────

    def _parse_csv(self, csv_path: str):
        from src.report.parsers.csv_parser import CSVParser
        return CSVParser().parse(csv_path)

    def _parse_api(self, records: list):
        from src.report.parsers.api_parser import APIParser
        return APIParser().parse(records)

    # ── private — config ─────────────────────────────────────────────────────

    def _load_report_config(self) -> dict:
        path = os.path.join(self._config_dir, 'report_config.yaml')
        if not os.path.exists(path):
            logger.warning(f"[ReportGenerator] report_config.yaml not found at {path}, using defaults")
            return {}
        try:
            import yaml
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except ImportError:
            logger.warning("[ReportGenerator] pyyaml not installed — using default report config")
            return {}
        except Exception as e:
            logger.error(f"[ReportGenerator] Failed to load report_config.yaml: {e}")
            return {}

    # ── private — email body ─────────────────────────────────────────────────

    def _build_email_body(self, mod12: dict, lang: str = "en") -> str:
        """Build a compact HTML email body from the executive summary."""
        kpis = mod12.get('kpis', [])
        findings = mod12.get('key_findings', [])
        boundary_breaches = mod12.get('boundary_breaches', [])
        suspicious_pivot = mod12.get('suspicious_pivot_behavior', [])
        blast_radius = mod12.get('blast_radius', [])
        blind_spots = mod12.get('blind_spots', [])
        action_matrix = mod12.get('action_matrix', [])

        def _sev_bg(sev):
            if sev == 'CRITICAL': return '#BE122F'
            if sev == 'HIGH':     return '#F43F51'
            return '#F97607'

        kpi_rows = ''.join(
            f'<tr>'
            f'<td style="font-weight:600;padding:5px 12px;color:#989A9B;font-size:11px;text-transform:uppercase;letter-spacing:.04em">{k["label"]}</td>'
            f'<td style="padding:5px 12px;font-weight:700;font-size:16px;color:#1A2C32">{k["value"]}</td>'
            f'</tr>'
            for k in kpis
        )
        finding_rows = ''.join(
            f'<tr>'
            f'<td style="color:white;background:{_sev_bg(f.get("severity",""))};padding:4px 10px;font-weight:700;border-radius:4px;white-space:nowrap">'
            f'{f.get("severity","")}</td>'
            f'<td style="padding:4px 10px;color:#313638">{f.get("finding","")}</td>'
            f'<td style="padding:4px 10px;color:#989A9B"><em>{f.get("action","")}</em></td>'
            f'</tr>'
            for f in findings
        )
        attack_rows = []
        for title, items in [
            (t("rpt_email_boundary_breaches", lang=lang), boundary_breaches),
            (t("rpt_email_suspicious_pivot_behavior", lang=lang), suspicious_pivot),
            (t("rpt_email_blast_radius", lang=lang), blast_radius),
            (t("rpt_email_blind_spots", lang=lang), blind_spots),
        ]:
            if items:
                sample = items[0]
                attack_rows.append(
                    f'<tr>'
                    f'<td style="padding:4px 10px;font-weight:700;color:#1A2C32">{title}</td>'
                    f'<td style="padding:4px 10px;color:#313638">{sample.get("finding","")}</td>'
                    f'<td style="padding:4px 10px;color:#989A9B"><em>{sample.get("action","")}</em></td>'
                    f'</tr>'
                )
        if action_matrix:
            top_action = action_matrix[0]
            attack_rows.append(
                f'<tr>'
                f'<td style="padding:4px 10px;font-weight:700;color:#1A2C32">{t("rpt_email_action_matrix", lang=lang)}</td>'
                f'<td style="padding:4px 10px;color:#313638">{top_action.get("action","")}</td>'
                f'<td style="padding:4px 10px;color:#989A9B"></td>'
                f'</tr>'
            )
        attack_rows_html = "".join(attack_rows)

        return f"""
<html><body style="margin:0;padding:0;background:#F4F4F4;font-family:'Montserrat',Arial,sans-serif;color:#313638;line-height:1.5">
<div style="max-width:700px;margin:0 auto;padding:16px">
  <div style="border-radius:10px;overflow:hidden;border:1px solid #325158">
    <div style="background:#1A2C32;border-left:4px solid #FF5500;padding:18px 20px;color:#fff">
      <div style="font-size:20px;font-weight:700;margin-bottom:4px">{t("rpt_email_traffic_subject", lang=lang)}</div>
      <div style="font-size:12px;color:#989A9B">{t("rpt_email_generated_label", lang=lang)} {mod12.get('generated_at','')}</div>
    </div>
    <div style="background:#fff;padding:20px">
      <h3 style="color:#1A2C32;font-size:13px;font-weight:600;margin:0 0 8px;border-bottom:2px solid #FF5500;padding-bottom:5px">{t("rpt_email_key_metrics", lang=lang)}</h3>
      <table border="0" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;margin-bottom:20px">
        {kpi_rows}
      </table>
      <h3 style="color:#1A2C32;font-size:13px;font-weight:600;margin:0 0 8px;border-bottom:2px solid #FF5500;padding-bottom:5px">{t("rpt_email_key_findings", lang=lang)}</h3>
      <table border="0" cellpadding="0" cellspacing="3" style="border-collapse:separate;border-spacing:0 3px;width:100%">
        {finding_rows or f'<tr><td colspan="3" style="padding:8px;color:#989A9B">{t("rpt_email_no_findings", lang=lang)}</td></tr>'}
      </table>
      <h3 style="color:#1A2C32;font-size:13px;font-weight:600;margin:16px 0 8px;border-bottom:2px solid #FF5500;padding-bottom:5px">{t("rpt_email_attack_summary", lang=lang)}</h3>
      <table border="0" cellpadding="0" cellspacing="3" style="border-collapse:separate;border-spacing:0 3px;width:100%">
        {attack_rows_html or f'<tr><td colspan="3" style="padding:8px;color:#989A9B">{t("rpt_email_no_attack_findings", lang=lang)}</td></tr>'}
      </table>
    </div>
    <div style="background:#F4F4F4;padding:12px 20px;border-top:1px solid #E5E5E5;text-align:center;color:#989A9B;font-size:11px">
      {t("rpt_email_footer", lang=lang)}
    </div>
  </div>
</div>
</body></html>"""


def build_traffic_xlsx(module_results: dict, out_path: str, *, profile: str,
                       lang: str = "en", record_count: int = 0,
                       metadata: dict | None = None) -> str:
    """依 _run_pipeline 產出的 module_results 組裝 Traffic curated workbook，只讀不重算。

    分頁對應（key 缺，即該 profile 未跑該模組 → 整張 sheet 略過，不寫空 sheet）：
      mod12.kpis → Executive Summary（KPI/Value 兩欄表，chart_spec 附掛）、
      mod02 summary+port_coverage+audit_flags → Policy Decisions（堆疊）、
      mod03 top_flows+uncovered_port_services+uncovered_ports+uncovered_services+
        by_recommendation → Uncovered Flows（堆疊）、
      mod15 service_summary+fan_out_sources+allowed_lateral_flows+attack_paths+
        六下放表（ip_top_talkers/ip_top_pairs/source_risk_scores/bridge_nodes/
        top_reachable_nodes/app_chains）→ Lateral Movement（堆疊；全空→no_lateral note）、
      mod07.matrices 四維度 top_cross_pairs → Cross-Label Matrix（堆疊；全空→no_matrix note）、
      mod08 top_unmanaged_src+per_dst_app+exposed_ports_merged+三下放表
        （src_port_detail/managed_hosts_targeted_by_unmanaged/top_unmanaged_dst）
        → Unmanaged Hosts（堆疊）。

    同源鐵律：只讀 module_results，禁止 analysis import 或 raw df 重算。堆疊 sheet 無法附掛
    chart_spec（helper 不支援），故僅 Executive Summary 附掛圖表，其餘 chart 省略。
    舊 Top Talkers（原自 raw flows groupby 重算）已廢棄——同源約束下無重算空間，主機層
    資訊改由 Lateral Movement 的 ip_top_talkers 提供。
    """
    import pandas as pd
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from src.report.exporters.xlsx_exporter import add_df_sheet, add_stacked_tables_sheet

    _ = profile  # profile 僅語意標記，sheet 取捨純看 key 是否存在
    wb = Workbook()
    summary_ws = wb.active
    summary_ws.title = "Summary"
    meta = metadata or {}
    summary_ws["A1"] = meta.get("title", "Traffic Flow Report")
    summary_ws["A1"].font = Font(size=18, bold=True)
    summary_ws["A2"] = f"Generated: {meta.get('generated_at', '')}"
    if meta.get("start_date"):
        summary_ws["A3"] = f"Period: {meta.get('start_date')} → {meta.get('end_date', '')}"
    summary_ws["A4"] = f"Records: {record_count}"
    summary_ws.freeze_panes = "A2"

    kpi_col = t("rpt_xlsx_col_kpi", lang=lang)
    val_col = t("rpt_xlsx_col_value", lang=lang)

    # --- Executive Summary（mod12）---
    mod12 = module_results.get("mod12")
    if mod12:
        kpis = mod12.get("kpis") or []
        kpi_df = (
            pd.DataFrame([{kpi_col: k.get("label", ""), val_col: k.get("value", "")} for k in kpis])
            if kpis else None
        )
        add_df_sheet(
            wb, t("rpt_xlsx_sheet_exec_summary", lang=lang), kpi_df,
            chart_spec=mod12.get("chart_spec"), lang=lang,
        )

    # --- Policy Decisions（mod02）---
    mod02 = module_results.get("mod02")
    if mod02:
        add_stacked_tables_sheet(
            wb, t("rpt_xlsx_sheet_policy_decisions", lang=lang),
            [
                (t("rpt_pd_chart_title", lang=lang), mod02.get("summary")),
                (t("rpt_tr_port_coverage", lang=lang), mod02.get("port_coverage")),
                (t("rpt_tr_audit_flags", lang=lang), mod02.get("audit_flags")),
            ],
            lang=lang,
        )

    # --- Uncovered Flows（mod03）---
    mod03 = module_results.get("mod03")
    if mod03:
        add_stacked_tables_sheet(
            wb, t("rpt_xlsx_sheet_uncovered_flows", lang=lang),
            [
                (t("rpt_tr_top_uncovered", lang=lang), mod03.get("top_flows")),
                (t("rpt_tr_port_service_gaps", lang=lang), mod03.get("uncovered_port_services")),
                (t("rpt_tr_uncovered_ports", lang=lang), mod03.get("uncovered_ports")),
                (t("rpt_tr_uncovered_services", lang=lang), mod03.get("uncovered_services")),
                (t("rpt_tr_by_rec", lang=lang), mod03.get("by_recommendation")),
            ],
            lang=lang,
        )

    # --- Lateral Movement（mod15；含六下放表，全空落回 no_lateral note）---
    mod15 = module_results.get("mod15")
    if mod15:
        add_stacked_tables_sheet(
            wb, t("rpt_xlsx_sheet_lateral_movement", lang=lang),
            [
                (t("rpt_tr_lateral_by_service", lang=lang), mod15.get("service_summary")),
                (t("rpt_tr_fan_out", lang=lang), mod15.get("fan_out_sources")),
                (t("rpt_tr_allowed_lateral", lang=lang), mod15.get("allowed_lateral_flows")),
                (t("rpt_mod15_attack_paths", lang=lang), mod15.get("attack_paths")),
                (t("rpt_tr_ip_top_talkers", lang=lang), mod15.get("ip_top_talkers")),
                (t("rpt_tr_ip_top_pairs", lang=lang), mod15.get("ip_top_pairs")),
                (t("rpt_tr_top_risk_sources", lang=lang), mod15.get("source_risk_scores")),
                (t("rpt_mod15_bridge_nodes", lang=lang), mod15.get("bridge_nodes")),
                (t("rpt_mod15_top_reachable", lang=lang), mod15.get("top_reachable_nodes")),
                (t("rpt_tr_app_chains", lang=lang), mod15.get("app_chains")),
            ],
            empty_note=t("rpt_xlsx_no_lateral", lang=lang),
            lang=lang,
        )

    # --- Cross-Label Matrix（mod07；四維度 top_cross_pairs，全空落回 no_matrix note）---
    mod07 = module_results.get("mod07")
    if mod07:
        matrices = mod07.get("matrices") or {}
        cross_tables = [
            (f"{t('rpt_tr_label_key', lang=lang)} {dim.upper()}",
             (matrices.get(dim) or {}).get("top_cross_pairs"))
            for dim in ("env", "app", "role", "loc")
        ]
        add_stacked_tables_sheet(
            wb, t("rpt_xlsx_sheet_cross_label", lang=lang), cross_tables,
            empty_note=t("rpt_no_matrix", lang=lang), lang=lang,
        )

    # --- Unmanaged Hosts（mod08；含三下放表）---
    mod08 = module_results.get("mod08")
    if mod08:
        add_stacked_tables_sheet(
            wb, t("rpt_xlsx_sheet_unmanaged", lang=lang),
            [
                (t("rpt_tr_top_unmanaged", lang=lang), mod08.get("top_unmanaged_src")),
                (t("rpt_tr_managed_apps_unmanaged", lang=lang), mod08.get("per_dst_app")),
                (t("rpt_tr_exposed_ports_merged", lang=lang), mod08.get("exposed_ports_merged")),
                (t("rpt_tr_src_port_detail", lang=lang), mod08.get("src_port_detail")),
                (t("rpt_tr_managed_targeted", lang=lang), mod08.get("managed_hosts_targeted_by_unmanaged")),
                (t("rpt_tr_top_unmanaged_dst", lang=lang), mod08.get("top_unmanaged_dst")),
            ],
            lang=lang,
        )

    wb.save(out_path)
    return out_path
