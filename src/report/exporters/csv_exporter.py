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
from loguru import logger
import os
import zipfile

import pandas as pd

from src.report.exporters._output_paths import discard_reserved, reserve_unique_path

# Module keys whose values should not be walked for DataFrames
_SKIP_KEYS = {'findings', 'error', 'note'}

# Rows serialised per to_csv() call. Streaming into the ZIP entry keeps peak
# memory at one chunk instead of three full copies of the whole CSV text
# (StringIO buffer + getvalue() str + writestr()'s encoded bytes).
_CHUNK_ROWS = 5000

# 與 xlsx_exporter._neutralize 同契約：Excel/LibreOffice 會把開頭為 = + - @ 的
# 儲存格當公式執行（DDE/HYPERLINK），而這些值可能來自 PCE 上的 process/host/
# label 名稱。前綴單引號使其一律以文字讀入；不截斷、不改動其餘內容。
_FORMULA_PREFIXES = ('=', '+', '-', '@')

def _neutralize(val):
    if isinstance(val, str) and val[:1] in _FORMULA_PREFIXES:
        return "'" + val
    return val

def _is_text_column(series: pd.Series) -> bool:
    """文字欄判定（pandas 3 的字串欄不再是 object dtype，不能只比 == object）。"""
    from pandas.api import types as _pt
    return not (_pt.is_numeric_dtype(series) or _pt.is_bool_dtype(series)
                or _pt.is_datetime64_any_dtype(series)
                or _pt.is_timedelta64_dtype(series))

def _neutralize_frame(chunk: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with formula-leading strings (headers + text cells) defused."""
    text_cols = [c for c in chunk.columns if _is_text_column(chunk[c])]
    out = chunk.copy() if text_cols else chunk
    for col in text_cols:
        out[col] = out[col].map(_neutralize)
    renames = {c: _neutralize(c) for c in out.columns if _neutralize(c) != c}
    return out.rename(columns=renames) if renames else out

def _write_df_entry(zf: zipfile.ZipFile, csv_name: str, df: pd.DataFrame) -> None:
    """Stream one DataFrame into the archive as a UTF-8-with-BOM CSV entry.

    BOM: Excel 在 Windows 用系統 ANSI code page（正體中文為 cp950）讀無 BOM 的
    檔案，繁中報表內容會整片變亂碼；本專案讀入 CSV 一律用 utf-8-sig，輸出端跟齊。
    """
    with zf.open(csv_name, 'w') as raw:
        with io.TextIOWrapper(raw, encoding='utf-8-sig', newline='') as text:
            header = True
            for start in range(0, len(df), _CHUNK_ROWS):
                chunk = _neutralize_frame(df.iloc[start:start + _CHUNK_ROWS])
                chunk.to_csv(text, index=False, header=header)
                header = False

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
                pass  # intentional fallback: skip data sections that cannot be converted to a DataFrame

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
        # 同一分鐘內的併發產出（GUI 臨時報表 thread + 排程）會撞同一個檔名；
        # 先以 O_EXCL 搶下唯一路徑，再由暫存檔 os.replace 進去。
        zip_path = reserve_unique_path(os.path.join(output_dir, zip_name))
        tmp_path = f'{zip_path}.{os.getpid()}.tmp'

        written = 0
        try:
            with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for mod_key, mod_data in self._r.items():
                    if mod_key in _SKIP_KEYS:
                        continue
                    for csv_name, df in _iter_dataframes(mod_data, mod_key):
                        _write_df_entry(zf, csv_name, df)
                        written += 1
            os.replace(tmp_path, zip_path)
        except BaseException:
            discard_reserved(tmp_path)
            discard_reserved(zip_path)
            raise

        logger.info(f'[CsvExporter] Wrote {written} CSV files → {zip_path}')
        return zip_path
