"""
src/report/exporters/csv_exporter.py

Generic raw-data CSV exporter — zero external dependencies (stdlib only).

Walks the module_results dict, collects every non-empty DataFrame, and
writes them as individual CSV files packed into a single ZIP archive.

Works for Traffic, Audit, and VEN Status reports without modification.
"""
from __future__ import annotations

import csv
import datetime
import io
import logging
import os
import zipfile

import pandas as pd

logger = logging.getLogger(__name__)

# Module keys whose values should not be walked for DataFrames
_SKIP_KEYS = {'findings', 'error', 'note'}


def _iter_dataframes(data, prefix: str):
    """
    Recursively yield (csv_filename, DataFrame) pairs from a nested
    dict / DataFrame structure.
    """
    if isinstance(data, pd.DataFrame):
        if not data.empty:
            yield f'{prefix}.csv', data
    elif isinstance(data, dict):
        for key, value in data.items():
            if key in _SKIP_KEYS:
                continue
            child_prefix = f'{prefix}_{key}' if prefix else key
            yield from _iter_dataframes(value, child_prefix)
    elif isinstance(data, list):
        # list of dicts → try to make a DataFrame
        if data and isinstance(data[0], dict):
            try:
                df = pd.DataFrame(data)
                if not df.empty:
                    yield f'{prefix}.csv', df
            except Exception:
                pass


class CsvExporter:
    """
    Export report module_results as a ZIP of CSV files.

    Usage:
        exporter = CsvExporter(module_results)
        path = exporter.export('reports/')
    """

    def __init__(self, results: dict, report_label: str = 'Traffic'):
        self._r = results
        self._label = report_label

    def export(self, output_dir: str = 'reports') -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y-%m-%d_%H%M')
        label = self._label.replace(' ', '_')
        zip_name = f'Illumio_{label}_Report_{ts}_raw.zip'
        zip_path = os.path.join(output_dir, zip_name)

        written = 0
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for mod_key, mod_data in self._r.items():
                if mod_key in _SKIP_KEYS:
                    continue
                for csv_name, df in _iter_dataframes(mod_data, mod_key):
                    buf = io.StringIO()
                    df.to_csv(buf, index=False)
                    zf.writestr(csv_name, buf.getvalue())
                    written += 1

        logger.info(f'[CsvExporter] Wrote {written} CSV files → {zip_path}')
        return zip_path
