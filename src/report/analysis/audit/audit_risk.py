"""
src/report/analysis/audit/audit_risk.py
Audit event risk classification — maps event_type to risk level and metadata.
"""

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
RISK_COLOR = {
    RISK_CRITICAL: '#BE122F',
    RISK_HIGH:     '#F97607',
    RISK_MEDIUM:   '#D4A017',
    RISK_LOW:      '#325158',
    RISK_INFO:     '#989A9B',
}
RISK_BG = {
    RISK_CRITICAL: '#FEF2F2',
    RISK_HIGH:     '#FFF7ED',
    RISK_MEDIUM:   '#FEFCE8',
    RISK_LOW:      '#F0F9FF',
    RISK_INFO:     '#F9FAFB',
}

def get_risk(event_type: str):
    """Return (risk_level, description, recommendation) for an event_type."""
    # Exact match first
    if event_type in AUDIT_RISK_MAP:
        return AUDIT_RISK_MAP[event_type]
    # Prefix match (e.g. 'rule_set.*' not explicitly listed)
    for key, val in AUDIT_RISK_MAP.items():
        if event_type.startswith(key.rstrip('*')):
            return val
    return (RISK_INFO, '', '')

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
