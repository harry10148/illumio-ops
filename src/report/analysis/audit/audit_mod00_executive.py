"""
src/report/analysis/audit/audit_mod00_executive.py
Module 0: Executive Summary for Audit Report
Combines insights from mod01, mod02, and mod03.

Enhanced KPIs leveraging newly extracted fields:
- Unique Admin Source IPs (insider threat baseline)
- Total Workloads Affected by provisioned policies
"""
import pandas as pd
import datetime


def audit_executive_summary(results: dict, df: pd.DataFrame) -> dict:
    mod01 = results.get('mod01', {})
    mod02 = results.get('mod02', {})
    mod03 = results.get('mod03', {})

    kpis = []

    # KPI 1: Total Events Processed
    kpis.append({'label': '事件總數', 'value': f"{len(df):,}"})

    # KPI 2: System Health Events
    total_health = mod01.get('total_health_events', 0)
    kpis.append({'label': '系統健康事件', 'value': f"{total_health:,}"})

    # KPI 3: Security Concerns (tampering, suspend, clone)
    sec_concerns = mod01.get('security_concern_count', 0)
    kpis.append({'label': '安全疑慮', 'value': str(sec_concerns)})

    # KPI 4: Agent Connectivity Issues
    conn_issues = mod01.get('connectivity_event_count', 0)
    kpis.append({'label': 'Agent 連線問題', 'value': str(conn_issues)})

    # KPI 5: Failed Logins
    failed_logins = mod02.get('failed_logins', 0)
    kpis.append({'label': '登入失敗', 'value': str(failed_logins)})

    # KPI 6: Policy Provisions
    provisions = mod03.get('provision_count', 0)
    kpis.append({'label': 'Provision 次數', 'value': str(provisions)})

    # KPI 7: Rule Changes (Draft)
    rule_changes = mod03.get('rule_change_count', 0)
    kpis.append({'label': '規則變更（Draft）', 'value': str(rule_changes)})

    # KPI 8: High-Risk Events
    kpis.append({'label': '高風險事件', 'value': str(mod03.get('high_risk_count', 0))})

    # KPI 9: Total Workloads Affected (all provisions combined)
    total_wa = mod03.get('total_workloads_affected', 0)
    if total_wa > 0:
        kpis.append({'label': '受影響工作負載', 'value': f"{total_wa:,}"})

    # KPI 10: Unique Admin Source IPs
    unique_ips = 0
    if 'src_ip' in df.columns:
        non_empty = df['src_ip'].astype(str).str.strip().replace('', pd.NA).dropna()
        unique_ips = int(non_empty.nunique())
    if unique_ips > 0:
        kpis.append({'label': '管理來源 IP 數', 'value': str(unique_ips)})

    # Top Event Types overall
    top_events = pd.DataFrame()
    if 'event_type' in df.columns and not df.empty:
        top_events = df['event_type'].value_counts().reset_index().head(15)
        top_events.columns = ['Event Type', 'Count']

    # Severity distribution
    severity_dist = pd.DataFrame()
    if 'severity' in df.columns and not df.empty:
        severity_dist = df['severity'].value_counts().reset_index()
        severity_dist.columns = ['Severity', 'Count']

    # ── Build attention items — MEDIUM+ risk events that need review ──────────
    from src.report.analysis.audit.audit_risk import AUDIT_RISK_MAP, RISK_ORDER, get_risk

    attention_items = []
    if not df.empty and 'event_type' in df.columns:
        for etype, (risk, desc, rec) in AUDIT_RISK_MAP.items():
            if RISK_ORDER.get(risk, 99) > RISK_ORDER.get('MEDIUM', 2):
                continue  # Skip LOW and INFO
            subset = df[df['event_type'] == etype]
            if subset.empty:
                continue
            count = len(subset)
            actors = []
            if 'created_by' in subset.columns:
                actors = subset['created_by'].dropna().unique().tolist()[:3]

            # Enrich with workloads_affected for sec_policy.create
            extra = ''
            if etype == 'sec_policy.create' and 'workloads_affected' in subset.columns:
                total = subset['workloads_affected'].sum()
                if total:
                    extra = f"（受影響工作負載 {int(total)} 台）"

            # Enrich with source IPs for admin-initiated events
            src_ips = []
            if 'src_ip' in subset.columns:
                src_ips = (
                    subset['src_ip'].astype(str).str.strip()
                    .replace('', pd.NA).dropna()
                    .unique().tolist()[:3]
                )

            attention_items.append({
                'risk': risk,
                'event_type': etype,
                'count': count,
                'summary': desc + extra,
                'actors': [str(a) for a in actors],
                'src_ips': [str(ip) for ip in src_ips],
                'recommendation': rec,
            })

    # Sort by risk level
    attention_items.sort(key=lambda x: RISK_ORDER.get(x['risk'], 99))

    return {
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'kpis': kpis,
        'top_events_overall': top_events,
        'severity_distribution': severity_dist,
        'attention_items': attention_items,
    }
