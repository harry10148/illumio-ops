"""Policy Resolver exporter — JSON + CSV.

JSON: one document with a per-ruleset map of resolved rows.
CSV : reuses the generic CsvExporter (writes one CSV per ruleset into a ZIP).
"""
from __future__ import annotations

import datetime
import json
import os

from loguru import logger

from src.report.exporters._output_paths import (
    discard_reserved,
    reserve_unique_path,
    write_text_atomic,
)
from src.report.exporters.csv_exporter import CsvExporter
from src.report.report_metadata import write_metadata_sidecar


class PolicyResolverExporter:
    def __init__(self, results: dict, lang: str = "en"):
        self._r = results
        # Kept for signature parity with sibling exporters and the facade's
        # run(lang=...) contract; JSON+CSV output itself is language-neutral.
        self._lang = lang

    def export_json(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        # 先序列化完成再碰檔案系統：舊寫法是 open(...,'w') 之後才 json.dump()，
        # 序列化中途拋錯就留下半截／0-byte 的 JSON（GUI 照樣列出並可下載）。
        # 再以 O_EXCL 搶下唯一檔名（同分鐘併發產出會撞名）＋暫存檔 os.replace。
        body = json.dumps(self._r, ensure_ascii=False, indent=2)
        path = reserve_unique_path(
            os.path.join(output_dir, f"Illumio_Policy_Resolver_{ts}.json"))
        try:
            write_text_atomic(path, body)
        except BaseException:
            discard_reserved(path)
            raise
        self._write_report_metadata(path, file_format="json")
        logger.info(f"[PolicyResolverExporter] Wrote JSON -> {path}")
        return path

    def export_csv(self, output_dir: str = "reports") -> str:
        # Pass the {name: [rows]} rulesets dict directly; CsvExporter's
        # _iter_dataframes handles list-of-dicts and writes one CSV per key
        # into a ZIP.
        rulesets = self._r.get("rulesets") or {}
        path = CsvExporter(rulesets, report_label="Policy_Resolver").export(output_dir)
        self._write_report_metadata(path, file_format="csv")
        return path

    def _write_report_metadata(self, report_path: str, file_format: str) -> None:
        """Sidecar for /api/reports (report_type / summary). Merges — see
        write_metadata_sidecar; the scheduler owns schedule_id in the same file."""
        record_count = int(self._r.get("record_count", 0) or 0)
        rulesets = self._r.get("rulesets") or {}
        # Language-neutral, like the audit/traffic sidecars ("audit events N").
        summary = f"resolved rows {record_count} across {len(rulesets)} ruleset(s)"
        payload = {
            "report_type": "policy_resolver",
            "file_format": file_format,
            "generated_at": datetime.datetime.now().isoformat(),
            "record_count": record_count,
            "summary": summary,
        }
        if self._r.get("truncated"):
            # Row-cap truncation must never be silent (see resolve()'s row cap).
            omitted = int(self._r.get("rows_omitted", 0) or 0)
            payload["truncated"] = True
            payload["rows_omitted"] = omitted
            payload["row_cap"] = self._r.get("row_cap")
            payload["truncated_rulesets"] = list(self._r.get("truncated_rulesets") or [])
            payload["summary"] = f"{summary} (truncated: {omitted} rows omitted)"
        write_metadata_sidecar(report_path, payload)

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
