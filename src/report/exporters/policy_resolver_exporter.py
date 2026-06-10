"""Policy Resolver exporter — JSON + CSV.

JSON: one document with a per-ruleset map of resolved rows.
CSV : reuses the generic CsvExporter (writes one CSV per ruleset into a ZIP).
"""
from __future__ import annotations

import datetime
import json
import os

from loguru import logger

from src.report.exporters.csv_exporter import CsvExporter


class PolicyResolverExporter:
    def __init__(self, results: dict, lang: str = "en"):
        self._r = results
        # Kept for signature parity with sibling exporters and the facade's
        # run(lang=...) contract; JSON+CSV output itself is language-neutral.
        self._lang = lang

    def export_json(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        path = os.path.join(output_dir, f"Illumio_Policy_Resolver_{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._r, f, ensure_ascii=False, indent=2)
        logger.info(f"[PolicyResolverExporter] Wrote JSON -> {path}")
        return path

    def export_csv(self, output_dir: str = "reports") -> str:
        # Pass the {name: [rows]} rulesets dict directly; CsvExporter's
        # _iter_dataframes handles list-of-dicts and writes one CSV per key
        # into a ZIP.
        rulesets = self._r.get("rulesets") or {}
        return CsvExporter(rulesets, report_label="Policy_Resolver").export(output_dir)

    def export(self, output_dir: str = "reports", fmt: str = "all") -> list[str]:
        """Write outputs selected by fmt; return the list of written paths.

        fmt: "json" -> JSON only; "csv" -> CSV zip only; "all" -> both.
        """
        paths: list[str] = []
        if fmt in ("json", "all"):
            paths.append(self.export_json(output_dir))
        if fmt in ("csv", "all"):
            paths.append(self.export_csv(output_dir))
        return paths
