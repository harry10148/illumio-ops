"""Policy Diff report facade — DRAFT-vs-ACTIVE diff + audit attribution.

Mirrors the SecurityRiskReport shape: run(output_dir, lang) -> path. Fetches
both draft and active rulesets (both already exposed by ApiClient), runs the
pure diff engine, attributes rows from the existing audit-events pipeline, and
exports HTML (+ CSV via the shared CsvExporter when fmt requires it).
"""
from __future__ import annotations

import datetime

from loguru import logger

from src.report.analysis.policy_diff.diff_engine import diff_rulesets
from src.report.analysis.policy_diff.attribution import attribute_changes
from src.report.analysis.policy_diff.risk import grade_changes
from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter

_DEFAULT_WINDOW_DAYS = 30


class PolicyDiffReport:
    def __init__(self, cm, api_client=None, config_dir: str = "config", cache_reader=None,
                 attribution_days: int = _DEFAULT_WINDOW_DAYS):
        self.cm = cm
        self.api = api_client
        self._config_dir = config_dir
        self._cache = cache_reader
        self._attribution_days = int(attribution_days)

    def _fetch_policy_events(self, lang: str = "en") -> dict:
        """Reuse the audit pipeline to get policy-change events for attribution."""
        if not self.api:
            return {"draft_events": None}
        from src.report.audit_generator import AuditGenerator
        from src.report.analysis.audit.audit_mod03_policy import audit_policy_changes
        try:
            end = datetime.datetime.now(datetime.timezone.utc)
            start = end - datetime.timedelta(days=self._attribution_days)
            gen = AuditGenerator(config_manager=self.cm, api_client=self.api,
                                 config_dir=self._config_dir, cache_reader=self._cache)
            gen._lang = lang
            events, _src = gen._fetch_events(start, end)
            if not events:
                return {"draft_events": None}
            df = AuditGenerator._build_dataframe(events)
            return audit_policy_changes(df)
        except Exception as exc:
            logger.warning(f"PolicyDiffReport: attribution events unavailable ({exc})")
            return {"draft_events": None}

    def _build_name_map(self) -> dict[str, str]:
        """href -> display name, from ACTIVE object inventories (best-effort)."""
        names: dict[str, str] = {}
        if not self.api:
            return names
        try:
            for obj in (self.api.get_ip_lists() or []):
                if obj.get("href") and obj.get("name"):
                    names[obj["href"]] = obj["name"]
            for obj in (self.api.get_services() or []):
                if obj.get("href") and obj.get("name"):
                    names[obj["href"]] = obj["name"]
            for obj in (self.api.get_label_groups() or []):
                if obj.get("href") and obj.get("name"):
                    names[obj["href"]] = obj["name"]
        except Exception as exc:
            logger.warning(f"PolicyDiffReport: name map unavailable ({exc})")
        # ACTIVE inventories carry /active/ hrefs; draft-side rules reference
        # the same objects via /draft/ hrefs — cover both.
        names.update({h.replace("/active/", "/draft/"): n
                      for h, n in names.items() if "/active/" in h})
        return names

    def build(self, lang: str = "en") -> dict:
        """Return the attributed diff module_results (no export)."""
        draft = self.api.get_all_rulesets(force_refresh=True) if self.api else []
        active = self.api.get_active_rulesets() if self.api else []
        diff = diff_rulesets(draft, active, names=self._build_name_map())
        diff = attribute_changes(diff, self._fetch_policy_events(lang))
        diff = grade_changes(diff)
        return diff

    def run(self, output_dir: str = "reports", lang: str = "en", fmt: str = "html") -> str:
        diff = self.build(lang)
        if fmt == "csv":
            from src.report.exporters.csv_exporter import CsvExporter
            return CsvExporter(diff, report_label="Policy_Diff").export(output_dir)
        return PolicyDiffHtmlExporter(diff, lang=lang).export(output_dir)
