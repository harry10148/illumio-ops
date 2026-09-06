"""
src/report/analysis/audit/audit_risk.py
Audit event risk classification — maps event_type to risk level and metadata.
"""
from __future__ import annotations

from src.i18n import t
from src.report.exporters.report_shell import (
    SEVERITY_TONE, TONE_FILL_HEX, TONE_HEX)

RISK_CRITICAL = 'CRITICAL'
RISK_HIGH     = 'HIGH'
RISK_MEDIUM   = 'MEDIUM'
RISK_LOW      = 'LOW'
RISK_INFO     = 'INFO'

# Map event_type (or prefix) → (risk_level, short_description, recommendation)
AUDIT_RISK_MAP = {
    # CRITICAL
    'agent.tampering':      (RISK_CRITICAL, 'Firewall rules tampered outside Illumio', 'Investigate workload for compromise; review iptables changes'),
    'agent.clone_detected': (RISK_CRITICAL, 'VEN clone identity detected', 'Identify clone source; revoke and re-pair affected VEN'),
    # HIGH
    'agent.suspend':        (RISK_HIGH, 'VEN protection suspended', 'Verify if suspension was authorized; review PCE audit trail'),
    'workloads.unpair':     (RISK_HIGH, 'Bulk workload unpair operation', 'Verify planned maintenance; check who initiated unpair'),
    'agents.unpair':        (RISK_HIGH, 'Bulk agent unpair operation', 'Verify planned maintenance; check who initiated unpair'),
    'request.authorization_failed': (RISK_HIGH, 'API authorization failure — privilege escalation attempt', 'Review user/key attempting access; check RBAC assignments'),
    # MEDIUM
    'sec_policy.create':    (RISK_MEDIUM, 'Security policy provisioned', 'Review workloads_affected count; verify change was intentional'),
    'rule_set.create':      (RISK_MEDIUM, 'Ruleset created', 'Verify change was authorized; review scope'),
    'rule_set.update':      (RISK_MEDIUM, 'Ruleset modified', 'Verify change was authorized; review scope'),
    'rule_set.delete':      (RISK_MEDIUM, 'Ruleset deleted', 'Verify deletion was authorized'),
    'sec_rule.create':      (RISK_MEDIUM, 'Security rule created', 'Verify change was authorized; check resource_changes'),
    'sec_rule.update':      (RISK_MEDIUM, 'Security rule modified', 'Verify change was authorized; check before/after diff'),
    'sec_rule.delete':      (RISK_MEDIUM, 'Security rule deleted', 'Verify deletion was authorized'),
    'api_key.create':       (RISK_MEDIUM, 'API key created', 'Confirm with admin; revoke if unauthorized'),
    'api_key.delete':       (RISK_MEDIUM, 'API key deleted', 'Confirm with admin if deletion was intended'),
    'authentication_settings.update': (RISK_MEDIUM, 'Authentication settings changed', 'Verify MFA or session settings were not weakened'),
    'firewall_settings.update': (RISK_MEDIUM, 'Global firewall/policy settings changed', 'Review what settings were modified'),
    'enforcement_boundary.create': (RISK_MEDIUM, 'Enforcement boundary created', 'Review scope and intent'),
    'enforcement_boundary.update': (RISK_MEDIUM, 'Enforcement boundary modified', 'Review scope changes'),
    'enforcement_boundary.delete': (RISK_MEDIUM, 'Enforcement boundary deleted', 'Verify deletion was authorized'),
    # LOW
    'system_task.agent_missed_heartbeats_check': (RISK_LOW, 'VEN missed heartbeats', 'Check network to PCE; verify VEN service is running'),
    'system_task.agent_offline_check': (RISK_LOW, 'VENs marked offline', 'Investigate host/network issues; restore connectivity'),
    'lost_agent.found':     (RISK_LOW, 'Lost VEN reconnected — policy gap existed', 'Review what policies were missing during outage'),
    'user.use_expired_password': (RISK_LOW, 'User used expired password', 'Prompt user to reset password immediately'),
}

RISK_ORDER = {RISK_CRITICAL: 0, RISK_HIGH: 1, RISK_MEDIUM: 2, RISK_LOW: 3, RISK_INFO: 4}
# Risk level -> the report shell's tone vocabulary. Same table the HTML badge
# uses (report_shell.SEVERITY_TONE), so a risk level cannot mean one colour in
# a table and another in a chart.
RISK_TONE = {
    RISK_CRITICAL: SEVERITY_TONE["CRITICAL"],
    RISK_HIGH:     SEVERITY_TONE["HIGH"],
    RISK_MEDIUM:   SEVERITY_TONE["MEDIUM"],
    RISK_LOW:      SEVERITY_TONE["LOW"],
    RISK_INFO:     SEVERITY_TONE["INFO"],
}

# Kept as names rather than hex tables. Nothing in src reads these two today —
# the HTML side moved to `data-tone` in Phase 2B Task 6 and lets SHELL_CSS
# resolve the colour (see concern_card.py and audit_html_exporter.py, which both
# say so). They stay because they are the risk model's own statement of "what
# colour is this level", and the next consumer that cannot use CSS (a chart, an
# xlsx fill) should read them instead of inventing a third palette. Resolving
# them from the shell means that consumer gets today's colours, not 2026-04's.
RISK_COLOR = {level: TONE_HEX[tone] for level, tone in RISK_TONE.items()}
RISK_BG = {level: TONE_FILL_HEX[tone] for level, tone in RISK_TONE.items()}

def get_risk(event_type: str, lang: str | None = None):
    """Return (risk_level, description, recommendation) for an event_type.

    English fallback strings live in AUDIT_RISK_MAP; when ``lang`` is provided
    the description/recommendation are looked up in i18n under
    ``rpt_au_event_<event_type_with_dots_to_underscores>_summary`` and
    ``..._rec``. Missing translations fall back to the English literal so we
    never display a raw i18n key.
    """
    if event_type in AUDIT_RISK_MAP:
        entry = AUDIT_RISK_MAP[event_type]
        match_type = event_type
    else:
        entry = None
        match_type = None
        for key, val in AUDIT_RISK_MAP.items():
            if event_type.startswith(key.rstrip('*')):
                entry = val
                match_type = key
                break
    if entry is None:
        return (RISK_INFO, '', '')
    risk, desc, rec = entry
    if lang and match_type:
        safe = match_type.replace('.', '_')
        desc_t = t(f"rpt_au_event_{safe}_summary", lang=lang, default=desc)
        rec_t = t(f"rpt_au_event_{safe}_rec", lang=lang, default=rec)
        return (risk, desc_t, rec_t)
    return (risk, desc, rec)

def classify_df(df):
    """Add 'risk_level' column to a DataFrame that has 'event_type' column.
    Also adds failure-based risk override: user.sign_in with status=='failure' → LOW.
    Returns new DataFrame with 'risk_level' column added."""
    import pandas as pd
    if df.empty or 'event_type' not in df.columns:
        return df
    df = df.copy()
    df['risk_level'] = df['event_type'].apply(lambda et: get_risk(et)[0])
    # Override: user.sign_in / user.login failure → LOW risk
    if 'status' in df.columns:
        fail_auth_mask = (
            df['event_type'].isin(['user.sign_in', 'user.login', 'user.authenticate']) &
            (df['status'] == 'failure')
        )
        df.loc[fail_auth_mask, 'risk_level'] = RISK_LOW
        # request.authentication_failed always HIGH (already in map, but status column confirms)
    return df
