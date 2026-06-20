"""App Summary report — single-app view for app owners and auditors.

Mirrors the PolicyDiffReport facade shape: __init__(cm, api_client, ...),
build() returns module_results, run() exports HTML. Reuses ReportGenerator's
traffic fetch, then scopes the DataFrame to one App Label (post-filter) and
re-runs a module subset (mod01/02/03 + RulesEngine findings) plus the
app-baseline tables.
"""
from __future__ import annotations

import re

from src.report.analysis.mod_app_baseline import app_baseline, filter_app_flows


def _app_workload_hrefs(workloads, app: str, env: str | None) -> list[str]:
    """Hrefs of managed workloads carrying app (and env) — used to scope the
    cache read to this app's flows. Same label-match as enforcement_summary."""
    from src.report.analysis.mod_app_baseline import _workload_has_label
    return [
        w.get("href") for w in (workloads or [])
        if w.get("href") and _workload_has_label(w, "app", app)
        and (not env or _workload_has_label(w, "env", env))
    ]


def _safe_filename_token(value: str) -> str:
    token = re.sub(r"[^\w.-]+", "_", value.strip())
    return token.strip("_") or "app"


class AppSummaryReport:
    def __init__(self, cm, api_client=None, config_dir: str = "config", cache_reader=None):
        self.cm = cm
        self.api = api_client
        self._config_dir = config_dir
        self._cache = cache_reader

    def _fetch_estate_df(self, start_date=None, end_date=None, filters=None,
                         use_cache=True, cache_workload_hrefs=None):
        """Fetch the (optionally PCE-scoped) traffic DataFrame via ReportGenerator."""
        from src.report.report_generator import ReportGenerator
        gen = ReportGenerator(config_manager=self.cm, api_client=self.api,
                              config_dir=self._config_dir, cache_reader=self._cache)
        return gen.fetch_traffic_df(start_date=start_date, end_date=end_date,
                                    filters=filters, use_cache=use_cache,
                                    cache_workload_hrefs=cache_workload_hrefs)

    def build(self, app: str, env: str | None = None, lang: str = "en",
              start_date=None, end_date=None, use_cache: bool = True) -> dict:
        from loguru import logger
        import datetime as _dt
        # The PCE traffic query needs full ISO-8601 timestamps; a bare 'YYYY-MM-DD'
        # (which the GUI date pickers send) yields zero flows, which silently
        # produced empty App Summary reports. Normalize date-only inputs here.
        def _iso_window(value, *, end_of_day):
            if not value or not isinstance(value, str) or "T" in value:
                return value
            try:
                parsed = _dt.datetime.strptime(value.strip(), "%Y-%m-%d")
            except ValueError:
                return value
            return parsed.strftime("%Y-%m-%dT" + ("23:59:59Z" if end_of_day else "00:00:00Z"))
        start_date = _iso_window(start_date, end_of_day=False)
        end_date = _iso_window(end_date, end_of_day=True)
        labels = [f"app={app}"] + ([f"env={env}"] if env else [])
        scope_filters = {"src_labels": labels, "dst_labels": labels, "query_operator": "or"}
        # Fetch the app's managed workloads once: their hrefs scope the CACHE read
        # to just this app's flows (fast even when the estate has a traffic burst),
        # and the same list feeds the enforcement section below.
        try:
            workloads = self.api.fetch_managed_workloads() if self.api else None
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[AppSummary] workloads fetch failed: {exc}")
            workloads = None
        cache_hrefs = _app_workload_hrefs(workloads, app, env) if workloads else None
        # Guard the SQLite bind limit: src OR dst IN (...) uses 2 binds per href.
        if cache_hrefs and len(cache_hrefs) > 400:
            logger.info(
                "[AppSummary] {} has {} workloads — skipping cache href filter "
                "(would exceed SQLite bind limit); full read + post-filter",
                app, len(cache_hrefs),
            )
            cache_hrefs = None
        df = self._fetch_estate_df(start_date=start_date, end_date=end_date,
                                   filters=scope_filters, use_cache=use_cache,
                                   cache_workload_hrefs=cache_hrefs)
        scoped = filter_app_flows(df, app, env)
        if scoped.empty:
            return {"app": app, "env": env or "", "empty": True}

        from src.report.analysis.mod01_traffic_overview import traffic_overview
        from src.report.analysis.mod02_policy_decisions import policy_decision_analysis
        from src.report.analysis.mod03_uncovered_flows import uncovered_flows
        from src.report.rules_engine import RulesEngine

        results: dict = {"app": app, "env": env or "", "empty": False}
        results["baseline"] = app_baseline(scoped, app, env)
        results["mod01"] = traffic_overview(scoped)
        results["mod02"] = policy_decision_analysis(scoped, top_n=10)
        results["mod03"] = uncovered_flows(scoped, top_n=10, lang=lang)
        engine = RulesEngine(self._report_cfg(), config_dir=self._config_dir, lang=lang)
        results["findings"] = engine.evaluate(scoped)

        from src.report.analysis.mod_app_baseline import policy_impact, enforcement_summary
        results["policy_impact"] = policy_impact(results["mod02"])
        results["enforcement"] = enforcement_summary(workloads, app, env)
        return results

    def _report_cfg(self) -> dict:
        """Load report_config.yaml (same source ReportGenerator uses for rules)."""
        import os
        from loguru import logger
        path = os.path.join(self._config_dir, "report_config.yaml")
        if not os.path.exists(path):
            logger.warning(f"[AppSummaryReport] report_config.yaml not found at {path}, using defaults")
            return {}
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except ImportError:
            logger.warning("[AppSummaryReport] pyyaml not installed — using default report config")
            return {}
        except Exception as e:
            logger.error(f"[AppSummaryReport] Failed to load report_config.yaml: {e}")
            return {}

    def run(self, app: str, env: str | None = None, output_dir: str = "reports",
            lang: str = "en", start_date=None, end_date=None,
            use_cache: bool = True) -> str:
        results = self.build(app=app, env=env, lang=lang,
                             start_date=start_date, end_date=end_date,
                             use_cache=use_cache)
        from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
        return AppSummaryHtmlExporter(results, lang=lang).export(output_dir)
