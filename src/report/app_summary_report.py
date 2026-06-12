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


def _safe_filename_token(value: str) -> str:
    token = re.sub(r"[^\w.-]+", "_", value.strip())
    return token.strip("_") or "app"


class AppSummaryReport:
    def __init__(self, cm, api_client=None, config_dir: str = "config", cache_reader=None):
        self.cm = cm
        self.api = api_client
        self._config_dir = config_dir
        self._cache = cache_reader

    def _fetch_estate_df(self, start_date=None, end_date=None):
        """Fetch the estate traffic DataFrame via ReportGenerator's API path."""
        from src.report.report_generator import ReportGenerator
        gen = ReportGenerator(config_manager=self.cm, api_client=self.api,
                              config_dir=self._config_dir, cache_reader=self._cache)
        return gen.fetch_traffic_df(start_date=start_date, end_date=end_date)

    def build(self, app: str, env: str | None = None, lang: str = "en",
              start_date=None, end_date=None) -> dict:
        df = self._fetch_estate_df(start_date=start_date, end_date=end_date)
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
            lang: str = "en", start_date=None, end_date=None) -> str:
        results = self.build(app=app, env=env, lang=lang,
                             start_date=start_date, end_date=end_date)
        from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
        return AppSummaryHtmlExporter(results, lang=lang).export(output_dir)
