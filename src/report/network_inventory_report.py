"""Network Inventory report facade — shared analysis engine + inventory exporter."""
from __future__ import annotations

from src.report.report_generator import ReportGenerator
from src.report.exporters.html_exporter import NetworkInventoryHtmlExporter


class NetworkInventoryReport:
    def __init__(self, cm, api_client=None, config_dir: str = "config", cache_reader=None):
        self.cm = cm
        self._gen = ReportGenerator(cm, api_client=api_client, config_dir=config_dir,
                                    cache_reader=cache_reader)

    def run(self, output_dir: str = "reports", lang: str = "en") -> str:
        result = self._gen.generate_from_api(traffic_report_profile="network_inventory", lang=lang)
        if result.record_count == 0:
            return ""
        return NetworkInventoryHtmlExporter(result.module_results, lang=lang).export(output_dir)
