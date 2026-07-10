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
import os
import re
from dataclasses import dataclass, field

from loguru import logger

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

    def generate_from_csv(self, csv_path: str, lang: str = "en") -> RuleHitCountResult:
        """Parse the PCE-native Rule Hit Count CSV (needs Rule HREF + Rule Hit Count)."""
        import pandas as pd
        self._lang = lang
        if not os.path.isfile(csv_path):
            raise FileNotFoundError(f"CSV not found: {csv_path}")

        df = pd.read_csv(csv_path, encoding='utf-8-sig')
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
            rows.append({
                'rule_href': href,
                'ruleset': str(row.get('ruleset_name', '') or ''),
                'rule_no': '',
                'rule_id': href.rstrip('/').rsplit('/', 1)[-1],
                'rule_type': '',
                'description': str(row.get('description', '') or ''),
                'consumers': '',
                'providers': '',
                'services': '',
                'enabled': '',
                'hit_count': hits,
                'days_since_last_hit': '' if pd.isna(days) else str(days),
            })

        # Native export carries the report window as Start/End Date columns.
        date_range = ('', '')
        if len(df) and 'start_date' in df.columns and 'end_date' in df.columns:
            date_range = (str(df.iloc[0]['start_date'])[:10], str(df.iloc[0]['end_date'])[:10])

        enrich_failed = self._enrich_rows(rows)
        return self._finalize(rows, source='csv', date_range=date_range,
                              enrich_failed=enrich_failed)

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
        try:
            from src.report.policy_usage_generator import build_rule_baseline
            rulesets = self.api.get_all_rulesets(force_refresh=True)
            flat_rules, _ = build_rule_baseline(rulesets or [])
        except Exception as exc:
            logger.warning("Rule detail enrichment skipped: {}", exc)
            return True
        by_href = {r.get('href', ''): r for r in flat_rules}
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
