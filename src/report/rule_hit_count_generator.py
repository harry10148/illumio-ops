"""
src/report/rule_hit_count_generator.py
Rule Hit Count Report generator — enhancer over the PCE-NATIVE report.

Hit counts in this report are always VEN-measured native data:
  native — auto-pull via api.pull_rule_hit_count_report() (Task 5)
  csv    — import the PCE UI's native Rule Hit Count CSV export
Both paths feed the same parser; rows are then enriched with live rule
details (consumers/providers/services) joined by rule href.

This report does NOT compute traffic-derived approximations — that is the
existing Policy Usage report's job.
"""
from __future__ import annotations

import datetime
import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from src.i18n import t
from src.report.rule_hit_count_enablement import RuleHitCountNotEnabled, check_enablement

CLEANUP_DAYS_THRESHOLD = 90   # vendor: counts are retained 90 days


@dataclass
class RuleHitCountResult:
    generated_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    record_count: int = 0
    date_range: tuple = ('', '')
    source: str = 'native'
    module_results: dict = field(default_factory=dict)
    dataframe: object = None


# PCE-native CSV header → canonical column. Headers are normalized first
# (lowercase, non-alnum → '_'), so "Rule HREF" → "rule_href".
_CSV_ALIASES = {
    'rule_href': 'rule_href',
    'rule_hit_count': 'hit_count',
    'hit_count': 'hit_count',
    'rule_name': 'description',
    'rule_description': 'description',
    'rule_set_name': 'ruleset_name',
    'ruleset_name': 'ruleset_name',
    'rule_set_href': 'ruleset_href',
    'ruleset_href': 'ruleset_href',
    'days_since_last_hit': 'days_since_last_hit',
    'timestamp_of_last_hit': 'last_hit_at',
    # last_updated_by / last_updated_at：治理欄位，僅 CSV 匯出 pass-through
    # （CsvExporter dump 全欄；rule_href/rule_id 同先例）。HTML 刻意不顯示——
    # 值班判讀價值低，exporter _COLS 白名單濾掉（spec §B, 2026-07-11）。
    'last_updated_by': 'last_updated_by',
    'timestamp_last_updated': 'last_updated_at',
    'start_date': 'start_date',
    'end_date': 'end_date',
}


def _norm_header(header) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(header).strip().lower()).strip('_')


class RuleHitCountGenerator:
    def __init__(self, config_manager, api_client=None, config_dir: str = 'config'):
        self.cm = config_manager
        self.api = api_client
        self._config_dir = config_dir
        self._lang = "en"

    # ── Public interface ──────────────────────────────────────────────────

    def generate_from_native(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        lang: str = "en",
    ) -> RuleHitCountResult:
        """Pull the PCE-native report and parse it. Raises RuleHitCountNotEnabled
        when the feature is not fully enabled — callers decide whether to run
        the enablement wizard (interactive) or skip (scheduler)."""
        if not self.api:
            raise RuntimeError("api_client required for native rule hit count generation")
        self._lang = lang

        status = check_enablement(self.api)
        if status.state != "enabled":
            raise RuleHitCountNotEnabled(status)

        print(t("rpt_rhc_pulling", lang=lang))
        kwargs = {}
        if start_date and end_date:
            kwargs = {"start_date": start_date, "end_date": end_date}
        else:
            kwargs = {"last_num_days": 30}
        csv_path = self.api.pull_rule_hit_count_report(**kwargs)
        try:
            result = self.generate_from_csv(csv_path, lang=lang)
        finally:
            try:
                os.unlink(csv_path)
            except OSError:
                pass
        result.source = 'native'
        return result

    def generate_from_csv(self, csv_path: str, lang: str = "en") -> RuleHitCountResult:
        """Parse the PCE-native Rule Hit Count CSV (needs Rule HREF + Rule Hit Count)."""
        import pandas as pd
        self._lang = lang
        if not os.path.isfile(csv_path):
            raise FileNotFoundError(f"CSV not found: {csv_path}")

        try:
            df = pd.read_csv(csv_path, encoding='utf-8-sig')
        except pd.errors.EmptyDataError:
            raise ValueError(f"rule hit count CSV is empty: {csv_path}") from None
        df.columns = [_norm_header(c) for c in df.columns]
        df = df.rename(columns={c: _CSV_ALIASES[c] for c in df.columns if c in _CSV_ALIASES})
        logger.info(f"Loaded rule hit count CSV: {len(df)} rows, columns={list(df.columns)}")
        if 'rule_href' not in df.columns or 'hit_count' not in df.columns:
            raise ValueError(
                f"unrecognized rule hit count CSV (columns={list(df.columns)}); "
                "need at least 'Rule HREF' and 'Rule Hit Count'")

        rows = []
        for _, row in df.iterrows():
            href = str(row.get('rule_href', '') or '').strip()
            if not href or href == 'nan':
                continue
            try:
                hits = int(float(row.get('hit_count', 0) or 0))
            except (TypeError, ValueError):
                hits = 0
            days = row.get('days_since_last_hit', '')

            def _s(col: str) -> str:
                v = row.get(col, '')
                return '' if pd.isna(v) else str(v)

            rows.append({
                'rule_href': href,
                # ruleset/description 走 _s：pandas 缺值是 float NaN（truthy），
                # str(NaN)='nan' 會把字面 nan 印進報表
                'ruleset': _s('ruleset_name'),
                'rule_no': '',
                'rule_id': href.rstrip('/').rsplit('/', 1)[-1],
                'rule_type': '',
                'description': _s('description'),
                'consumers': '',
                'providers': '',
                'services': '',
                'enabled': '',
                'hit_count': hits,
                'days_since_last_hit': '' if pd.isna(days) else str(days),
                'last_hit_at': _s('last_hit_at'),
                'last_updated_by': _s('last_updated_by'),
                'last_updated_at': _s('last_updated_at'),
            })

        # Native export carries the report window as Start/End Date columns.
        date_range = ('', '')
        if len(df) and 'start_date' in df.columns and 'end_date' in df.columns:
            date_range = (str(df.iloc[0]['start_date'])[:10], str(df.iloc[0]['end_date'])[:10])

        enrich_failed = self._enrich_rows(rows)
        return self._finalize(rows, source='csv', date_range=date_range,
                              enrich_failed=enrich_failed)

    def export(
        self,
        result: RuleHitCountResult,
        fmt: str = 'html',
        output_dir: str = 'reports',
        lang: str | None = None,
    ) -> list[str]:
        from src.report.exporters.rule_hit_count_html_exporter import RuleHitCountHtmlExporter
        from src.report.exporters.csv_exporter import CsvExporter

        lang = lang or getattr(self, '_lang', 'en')
        os.makedirs(output_dir, exist_ok=True)
        paths = []

        if fmt in ('html', 'all'):
            path = RuleHitCountHtmlExporter(result, lang=lang).export(output_dir)
            paths.append(path)
            self._write_report_metadata(path, result, file_format='html')
            print(t("rpt_rhc_html_saved", path=path, lang=lang))

        if fmt in ('csv', 'all'):
            mr = result.module_results or {}
            export_data = {}
            # CSV carries the FULL untruncated cell values (HTML truncates at
            # _CELL_MAX with title= hover; this is the recovery path).
            for key in ('hit_df', 'unused_df', 'cleanup_df'):
                df = mr.get(key)
                if df is not None and not df.empty:
                    export_data[key.replace('_df', '_rules')] = df
            if result.dataframe is not None and not result.dataframe.empty:
                export_data['all_rules'] = result.dataframe
            if export_data:
                path = CsvExporter(export_data, report_label='Rule_Hit_Count').export(output_dir)
                paths.append(path)
                self._write_report_metadata(path, result, file_format='csv')
                print(t("rpt_rhc_csv_saved", path=path, lang=lang))

        return paths

    def _write_report_metadata(self, report_path: str, result: RuleHitCountResult,
                               file_format: str) -> None:
        payload = {
            "report_type": "rule_hit_count",
            "file_format": file_format,
            "generated_at": result.generated_at.isoformat(),
            "record_count": int(result.record_count or 0),
            "date_range": list(result.date_range or ("", "")),
            "source": result.source,
            "kpis": (result.module_results or {}).get('kpis', {}),
        }
        with open(report_path + ".metadata.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _actor_str(self, actors) -> str:
        if not actors:
            return 'Any'
        try:
            return self.api.resolve_actor_str(actors)
        except Exception:
            logger.opt(exception=True).debug("resolve_actor_str failed")
            return ''

    def _service_str(self, services) -> str:
        if not services:
            return 'All Services'
        try:
            return self.api.resolve_service_str(services)
        except Exception:
            logger.opt(exception=True).debug("resolve_service_str failed")
            return ''

    def _enrich_rows(self, rows: list) -> bool:
        """Best-effort join of live rule details by href. Returns True on FAILURE
        (so the exporter can flag it); enrichment failure never kills the report."""
        if not self.api or not rows:
            return False
        # 先預熱 href→名稱快取（labels/label_groups/ip_lists/services），否則
        # resolve_actor_str/_service_str 冷快取時只回型別字樣（Label/IPList/
        # Service(id)）。best-effort：預熱失敗名稱降級即可，不擋報表、不標
        # enrich_failed。force_refresh=False＝只補快取、不失效 query-lookup 快取。
        try:
            self.api.update_label_cache(silent=True, force_refresh=False)
        except Exception:
            logger.opt(exception=True).debug("label cache warm failed; actor names degrade to types")
        try:
            from src.report.policy_usage_generator import build_rule_baseline
            rulesets = self.api.get_all_rulesets(force_refresh=True, raise_on_error=True)
            flat_rules, _ = build_rule_baseline(rulesets or [])
        except Exception as exc:
            logger.warning("Rule detail enrichment skipped: {}", exc)
            return True
        # get_all_rulesets() always hits the DRAFT sec_policy endpoint, so rule
        # hrefs here are draft-form. The native Rule Hit Count CSV export always
        # carries ACTIVE-form Rule HREFs (hit counts only cover Active rules).
        # Key both forms so the join below matches regardless of which shape
        # the CSV or a future native-API path supplies (cf. label_cache /
        # service_ports_cache double-keying in src/api/labels.py).
        by_href = {}
        for r in flat_rules:
            href = r.get('href', '')
            if not href:
                continue
            by_href[href] = r
            by_href[href.replace('/draft/', '/active/')] = r
        for row in rows:
            rule = by_href.get(row['rule_href'])
            if not rule:
                continue
            row['ruleset'] = row['ruleset'] or rule.get('_ruleset_name', '')
            row['rule_no'] = rule.get('_rule_no', '')
            row['rule_type'] = rule.get('_rule_type', '')
            row['description'] = row['description'] or rule.get('description', '')
            row['consumers'] = self._actor_str(rule.get('consumers'))
            row['providers'] = self._actor_str(rule.get('providers'))
            row['services'] = self._service_str(rule.get('ingress_services'))
            row['enabled'] = bool(rule.get('enabled', True))
        return False

    def _finalize(self, rows: list, source: str, date_range: tuple,
                  enrich_failed: bool = False) -> RuleHitCountResult:
        import pandas as pd
        df = pd.DataFrame(rows)
        total = len(rows)
        hit = sum(1 for r in rows if r['hit_count'] > 0)
        kpis = {
            'total_rules': total,
            'hit_rules': hit,
            'unused_rules': total - hit,
            'hit_rate_pct': round(hit * 100.0 / total, 1) if total else 0.0,
            'total_hits': sum(r['hit_count'] for r in rows),
        }
        if total:
            hit_df = df[df['hit_count'] > 0].sort_values('hit_count', ascending=False)
            unused_df = df[df['hit_count'] == 0]
            days = pd.to_numeric(df['days_since_last_hit'], errors='coerce')
            cleanup_df = df[df['enabled'].astype(bool) &
                            ((df['hit_count'] == 0) | (days >= CLEANUP_DAYS_THRESHOLD))]
            cleanup_df = cleanup_df.assign(_days=days[cleanup_df.index]) \
                                   .sort_values('_days', ascending=False, na_position='last') \
                                   .drop(columns=['_days'])
        else:
            hit_df = unused_df = cleanup_df = df
        return RuleHitCountResult(
            record_count=total,
            date_range=date_range,
            source=source,
            module_results={'kpis': kpis, 'hit_df': hit_df, 'unused_df': unused_df,
                            'cleanup_df': cleanup_df, 'enrich_failed': enrich_failed},
            dataframe=df,
        )
