"""
src/report/rules_engine.py
Rules Engine for Traffic Flow Security Analysis.

Built-in structural rules (B001–B009, L001–L010) — always executed, no label
semantics assumed.

All findings are returned as a list[Finding] for direct use by Module 12
(executive_summary) and the Excel/HTML exporters.
"""
from __future__ import annotations

from loguru import logger
from typing import Optional

import pandas as pd

from src.i18n import t

# Backwards-compat re-exports — see src/report/rules/ for new homes
from src.report.rules import (  # noqa: F401
    Finding,
    _DraftPdRuleMixin,
    R01DraftDenyDetected,
    R02OverrideDenyDetected,
    R03VisibilityBoundaryBreach,
    R04AllowedAcrossBoundary,
    R05DraftReportedMismatch,
)


def _fmt_bytes(n: float) -> str:
    """Return human-readable byte string (B / KB / MB / GB / TB)."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def annotate_techniques(findings: list) -> list:
    """Attach MITRE technique tuples to findings (pure, in-place safe)."""
    from src.report.analysis.mitre_map import techniques_for
    for f in findings:
        f.technique_ids = techniques_for(f.rule_id)
    return findings


# Registry of standalone draft-PD rules (R01–R05)
DRAFT_PD_RULES: list = [
    R01DraftDenyDetected,
    R02OverrideDenyDetected,
    R03VisibilityBoundaryBreach,
    R04AllowedAcrossBoundary,
    R05DraftReportedMismatch,
]


def ruleset_needs_draft_pd(ruleset) -> bool:
    """Return True if any rule in ruleset requires draft_policy_decision data."""
    for r in ruleset:
        obj = r() if isinstance(r, type) else r
        if getattr(obj, "needs_draft_pd", lambda: False)():
            return True
    return False


# ─── Rules Engine ────────────────────────────────────────────────────────────

class RulesEngine:
    """
    Evaluates all structural and semantic rules against a Unified DataFrame.

    Usage:
        engine = RulesEngine(report_config, config_dir='config/')
        findings = engine.evaluate(df)
    """

    def __init__(self, report_config: dict, config_dir: str = 'config', lang: str = 'en'):
        self._cfg = report_config
        self._thresholds = report_config.get('thresholds', {})
        self._risk_ports = self._build_risk_port_map(report_config)
        self._lateral_ports = set(report_config.get('lateral_movement_ports', []))
        self._lang = lang

    # ── public ───────────────────────────────────────────────────────────────

    def evaluate(self, df: pd.DataFrame) -> list[Finding]:
        """Run all rules and return sorted findings list."""
        findings: list[Finding] = []
        findings.extend(self._eval_builtin(df))
        findings.extend(self._eval_draft_pd(df))
        findings.sort(key=lambda f: f.severity_rank)
        logger.info(f"[RulesEngine] {len(findings)} findings generated")
        return annotate_techniques(findings)

    # ── draft-policy rules (R01–R05) ─────────────────────────────────────────

    def _eval_draft_pd(self, df: pd.DataFrame) -> list[Finding]:
        """Evaluate the standalone draft-PD rules (R01–R05).

        These only fire when the unified df carries a 'draft_policy_decision'
        column (populated by flatten_flow_record when the PCE async query ran
        with compute_draft). When the column is absent — the common case for
        reports whose fetch layer did not request draft computation — every
        rule's _has_draft() guard returns empty and this is a no-op.
        """
        if "draft_policy_decision" not in df.columns:
            return []
        findings: list[Finding] = []
        ctx: dict = {}
        for rule_cls in DRAFT_PD_RULES:
            try:
                findings.extend(rule_cls().evaluate(df, ctx, self._lang) or [])
            except Exception as e:
                logger.warning(f"[RulesEngine] Draft rule {rule_cls.__name__} failed: {e}")
        return findings

    # ── built-in rules ───────────────────────────────────────────────────────

    def _eval_builtin(self, df: pd.DataFrame) -> list[Finding]:
        findings = []
        for rule in [
            # ── Ransomware exposure (B001–B003) ──────────────────────────────
            self._b001_ransomware_critical,
            self._b002_ransomware_high,
            self._b003_ransomware_medium_uncovered,
            # ── Policy & coverage gaps (B004–B005, B009) ─────────────────────
            self._b004_unmanaged_high_activity,
            self._b005_low_policy_coverage,
            self._b009_cross_env_volume,
            # ── Anomalous behaviour (B006–B008) ──────────────────────────────
            self._b006_lateral_movement,
            self._b007_user_high_destinations,
            self._b008_bandwidth_anomaly,
            # ── Lateral movement — cleartext & legacy protocols (L001–L002) ──
            self._l001_cleartext_protocols,
            self._l002_legacy_discovery_protocols,
            # ── Lateral movement — database exposure (L003–L004) ─────────────
            self._l003_database_port_wide_exposure,
            self._l004_cross_env_database_access,
            # ── Lateral movement — identity infrastructure (L005) ─────────────
            self._l005_identity_infrastructure_exposure,
            # ── Lateral movement — graph-based blast radius (L006) ────────────
            self._l006_high_reachability_lateral_path,
            # ── Lateral movement — unmanaged pivot (L007) ─────────────────────
            self._l007_unmanaged_targeting_critical_services,
            # ── Lateral movement — enforcement gap (L008) ─────────────────────
            self._l008_enforcement_mode_gap,
            # ── Lateral movement — exfiltration pattern (L009) ────────────────
            self._l009_outbound_exfiltration_pattern,
            # ── Lateral movement — cross-env identity abuse (L010) ────────────
            self._l010_cross_env_lateral_port_access,
        ]:
            try:
                result = rule(df)
                if result:
                    findings.append(result)
            except Exception as e:
                logger.warning(f"[RulesEngine] Rule {rule.__name__} failed: {e}")
        return findings

    def _b001_ransomware_critical(self, df: pd.DataFrame) -> Optional[Finding]:
        """B001: Contextual analysis of critical ransomware port exposure.

        Severity is determined by network context, not simply by port presence:
          CRITICAL — cross-environment flows (e.g. Dev → Prod on SMB/RDP)
          HIGH     — cross-subnet allowed flows (not same /24, not cross-env)
          MEDIUM   — all flows within the same /24 subnet (likely admin traffic)
          INFO     — flows only exist as potentially_blocked (test-mode, same subnet)

        Same-subnet RDP/SMB/WinRM is commonplace for Windows administration and
        does not necessarily indicate malicious activity.  The risk escalates when
        these ports cross network or environment boundaries.
        """
        critical_ports = self._risk_ports.get('critical', set())
        if not critical_ports:
            return None

        matched = df[
            df['port'].isin(critical_ports) &
            (df['policy_decision'] != 'blocked')
        ].copy()
        if matched.empty:
            return None

        # ── Classify each flow by network proximity ───────────────────────────
        def _same_24(row) -> bool:
            try:
                s = str(row.get('src_ip', '')).split('.')
                d = str(row.get('dst_ip', '')).split('.')
                return len(s) == 4 and len(d) == 4 and s[:3] == d[:3]
            except Exception:
                return False  # intentional fallback: any error in subnet check means "not same /24"

        matched['_same_subnet'] = matched.apply(_same_24, axis=1)

        if 'src_env' in matched.columns and 'dst_env' in matched.columns:
            matched['_cross_env'] = (
                matched['src_env'].notna() & matched['dst_env'].notna() &
                matched['src_env'].ne('') & matched['dst_env'].ne('') &
                (matched['src_env'] != matched['dst_env'])
            )
        else:
            matched['_cross_env'] = False

        n_total       = len(matched)
        n_cross_env   = int(matched['_cross_env'].sum())
        n_cross_subnet = int((~matched['_same_subnet']).sum())
        n_same_subnet = int(matched['_same_subnet'].sum())
        n_allowed     = int((matched['policy_decision'] == 'allowed').sum())
        n_pb          = int((matched['policy_decision'] == 'potentially_blocked').sum())

        # Cross-subnet-scoped counts. The cross-subnet branches below describe the
        # cross-subnet flows specifically, so severity must be driven by the
        # allowed/PB split WITHIN that subset — not by estate-wide n_allowed/n_pb
        # (which also count same-subnet admin traffic and mislabel severity).
        cross_subnet_rows = matched[~matched['_same_subnet']]
        n_cross_subnet_allowed = int((cross_subnet_rows['policy_decision'] == 'allowed').sum())
        n_cross_subnet_pb      = int((cross_subnet_rows['policy_decision'] == 'potentially_blocked').sum())

        _port_names = {135: 'RPC', 445: 'SMB', 3389: 'RDP', 5985: 'WinRM', 5986: 'WinRM-SSL'}
        port_counts = matched['port'].value_counts().head(5).to_dict()
        named_ports = {_port_names.get(p, str(p)): c for p, c in port_counts.items()}

        # ── Contextual severity determination ─────────────────────────────────
        if n_cross_env > 0:
            severity = 'CRITICAL'
            cross_env_rows = matched[matched['_cross_env']]
            n_cross_env_allowed = int((cross_env_rows['policy_decision'] == 'allowed').sum())
            n_cross_env_pb = n_cross_env - n_cross_env_allowed
            risk_summary = t(
                "rpt_rule_B001_risk_cross_env", lang=self._lang,
                n_cross_env=n_cross_env,
                n_cross_env_allowed=n_cross_env_allowed,
                n_cross_env_pb=n_cross_env_pb,
            )
            if n_cross_env_allowed > 0:
                recommendation = t("rule_b001_rec_critical_cross_env", named_ports=list(named_ports.keys()), lang=self._lang)
            else:
                recommendation = t("rule_b001_rec_pb_cross_env", named_ports=list(named_ports.keys()), lang=self._lang)
        elif n_cross_subnet > 0 and n_cross_subnet_allowed > 0:
            severity = 'HIGH'
            risk_summary = t(
                "rpt_rule_B001_risk_cross_subnet_allowed", lang=self._lang,
                n_cross_subnet=n_cross_subnet,
                n_allowed=n_cross_subnet_allowed,
                n_same_subnet=n_same_subnet,
            )
            recommendation = t("rule_b001_rec_cross_subnet_allowed",
                               named_ports=list(named_ports.keys()), n_same_subnet=n_same_subnet, lang=self._lang)
        elif n_cross_subnet > 0 and n_cross_subnet_pb == n_cross_subnet:
            severity = 'MEDIUM'
            risk_summary = t(
                "rpt_rule_B001_risk_cross_subnet_pb", lang=self._lang,
                n_cross_subnet=n_cross_subnet,
            )
            recommendation = t("rule_b001_rec_cross_subnet_pb", lang=self._lang)
        elif n_same_subnet == n_total and n_pb == n_total:
            severity = 'INFO'
            risk_summary = t(
                "rpt_rule_B001_risk_same_subnet_pb", lang=self._lang,
                n_total=n_total,
            )
            recommendation = t("rule_b001_rec_same_subnet_pb", lang=self._lang)
        else:
            # Same-subnet, allowed — MEDIUM (legitimate admin but worth documenting)
            severity = 'MEDIUM'
            risk_summary = t(
                "rpt_rule_B001_risk_same_subnet_allowed", lang=self._lang,
                n_total=n_total,
                n_allowed=n_allowed,
                n_pb=n_pb,
            )
            recommendation = t("rule_b001_rec_same_subnet_allowed", lang=self._lang)

        # Top suspicious flows (cross-subnet or cross-env, allowed)
        suspicious = matched[
            (matched['_cross_env'] | ~matched['_same_subnet']) &
            (matched['policy_decision'] == 'allowed')
        ]
        top_pairs = (suspicious[['src_ip', 'dst_ip', 'port', 'policy_decision']]
                     .head(5).to_dict('records')) if not suspicious.empty else []

        description = t(
            "rpt_rule_B001_desc", lang=self._lang,
            n_total=n_total,
            named_ports=named_ports,
            risk_summary=risk_summary,
            n_same_subnet=n_same_subnet,
            n_cross_subnet=n_cross_subnet,
            n_cross_env=n_cross_env,
            n_allowed=n_allowed,
            n_pb=n_pb,
        )

        return Finding(
            rule_id='B001', rule_name='Ransomware Risk Port — Contextual Analysis',
            severity=severity, category='Ransomware',
            description=description,
            recommendation=recommendation,
            evidence={
                'total_flows': n_total,
                'same_subnet_flows': n_same_subnet,
                'cross_subnet_flows': n_cross_subnet,
                'cross_env_flows': n_cross_env,
                'explicitly_allowed': n_allowed,
                'test_mode_only': n_pb,
                'top_ports': str(named_ports),
                'top_suspicious_pairs': str(top_pairs[:3]) if top_pairs else 'None',
            },
        )

    def _b002_ransomware_high(self, df: pd.DataFrame) -> Optional[Finding]:
        high_ports = self._risk_ports.get('high', set())
        if not high_ports:
            return None
        mask = (df['port'].isin(high_ports)) & (df['policy_decision'] == 'allowed')
        matched = df[mask]
        if not matched.empty:
            top_ports = matched['port'].value_counts().head(5).to_dict()
            _port_names = {5938: 'TeamViewer', 5900: 'VNC', 5901: 'VNC-alt', 137: 'NetBIOS-NS',
                           138: 'NetBIOS-DGM', 139: 'NetBIOS-SSN', 4899: 'Radmin'}
            named = {_port_names.get(p, str(p)): c for p, c in top_ports.items()}
            unique_src = matched['src_ip'].nunique()
            unique_dst = matched['dst_ip'].nunique()
            return Finding(
                rule_id='B002', rule_name='Ransomware Risk Port (High)',
                severity='HIGH', category='Ransomware',
                description=t(
                    "rpt_rule_B002_desc", lang=self._lang,
                    n_flows=len(matched),
                    named=named,
                    unique_src=unique_src,
                    unique_dst=unique_dst,
                ),
                recommendation=t("rule_b002_rec", lang=self._lang),
                evidence={'matched_flows': len(matched), 'top_ports': str(top_ports),
                          'unique_sources': unique_src, 'unique_destinations': unique_dst},
            )
        return None

    def _b003_ransomware_medium_uncovered(self, df: pd.DataFrame) -> Optional[Finding]:
        medium_ports = self._risk_ports.get('medium', set())
        if not medium_ports:
            return None
        mask = (df['port'].isin(medium_ports)) & (df['policy_decision'] == 'potentially_blocked')
        matched = df[mask]
        if not matched.empty:
            top_ports = matched['port'].value_counts().head(5).to_dict()
            _port_names = {22: 'SSH', 2049: 'NFS', 20: 'FTP-data', 21: 'FTP', 80: 'HTTP',
                           8080: 'HTTP-alt', 8443: 'HTTPS-alt'}
            named = {_port_names.get(p, str(p)): c for p, c in top_ports.items()}
            # Distinct hosts across both ends: summing the two nunique() counts
            # double-counts any IP that appears as both source and destination.
            unique_wl = pd.concat([matched['src_ip'], matched['dst_ip']]).nunique()
            return Finding(
                rule_id='B003', rule_name='Ransomware Risk Port (Medium) — Uncovered',
                severity='MEDIUM', category='Ransomware',
                description=t(
                    "rpt_rule_B003_desc", lang=self._lang,
                    n_flows=len(matched),
                    named=named,
                    unique_wl=unique_wl,
                ),
                recommendation=t("rule_b003_rec", lang=self._lang),
                evidence={'matched_flows': len(matched), 'top_ports': str(top_ports)},
            )
        return None

    def _b004_unmanaged_high_activity(self, df: pd.DataFrame) -> Optional[Finding]:
        threshold = self._thresholds.get('unmanaged_connection_threshold', 50)
        unmanaged_src = df[df['src_managed'] == False]
        total = len(unmanaged_src)
        if total > threshold:
            top_ips = unmanaged_src['src_ip'].value_counts().head(5).to_dict()
            unique_dst = unmanaged_src['dst_ip'].nunique()
            top_dst_ports = unmanaged_src['port'].value_counts().head(5).to_dict()
            return Finding(
                rule_id='B004', rule_name='Unmanaged Source High Activity',
                severity='MEDIUM', category='UnmanagedHost',
                description=t(
                    "rpt_rule_B004_desc", lang=self._lang,
                    total=total,
                    threshold=threshold,
                    unique_dst=unique_dst,
                    top_ports_list=list(top_dst_ports.keys()),
                    top_src_ips_list=list(top_ips.keys())[:3],
                ),
                recommendation=t("rule_b004_rec", lang=self._lang),
                evidence={'total_flows': total, 'top_src_ips': str(top_ips),
                          'unique_managed_destinations': unique_dst, 'top_ports': str(top_dst_ports)},
            )
        return None

    def _b005_low_policy_coverage(self, df: pd.DataFrame) -> Optional[Finding]:
        threshold = self._thresholds.get('min_policy_coverage_pct', 30)
        if df.empty:
            return None
        allowed = (df['policy_decision'] == 'allowed').sum()
        total = len(df)
        coverage_pct = (allowed / total * 100) if total > 0 else 0
        if coverage_pct < threshold:
            blocked = (df['policy_decision'] == 'blocked').sum()
            pb = (df['policy_decision'] == 'potentially_blocked').sum()
            return Finding(
                rule_id='B005', rule_name='Low Policy Coverage',
                severity='MEDIUM', category='Policy',
                description=t(
                    "rpt_rule_B005_desc", lang=self._lang,
                    coverage_pct=f"{coverage_pct:.1f}",
                    total=f"{total:,}",
                    allowed=f"{allowed:,}",
                    blocked=f"{blocked:,}",
                    pb=f"{pb:,}",
                ),
                recommendation=t("rule_b005_rec", threshold=threshold, lang=self._lang),
                evidence={'coverage_pct': f'{coverage_pct:.1f}', 'allowed': allowed,
                          'blocked': blocked, 'potentially_blocked': pb, 'total': total},
            )
        return None

    def _b006_lateral_movement(self, df: pd.DataFrame) -> Optional[Finding]:
        threshold = self._thresholds.get('lateral_movement_outbound_dst', 10)
        lateral = df[df['port'].isin(self._lateral_ports) & (df['policy_decision'] != 'blocked')]
        if lateral.empty:
            return None
        per_src_all = lateral.groupby('src_ip')['dst_ip'].nunique()
        high_src = per_src_all[per_src_all > threshold]
        if high_src.empty:
            return None

        lateral_allowed = lateral[lateral['policy_decision'] == 'allowed']
        per_src_allowed = lateral_allowed.groupby('src_ip')['dst_ip'].nunique() if not lateral_allowed.empty else {}
        high_src_allowed = {ip: c for ip, c in per_src_allowed.items() if c > threshold} if per_src_allowed is not None and len(per_src_allowed) else {}

        # Severity: HIGH if any source exceeds threshold via explicitly allowed flows;
        # MEDIUM if fan-out is driven only by potentially_blocked (no allow rule — will be blocked when enforced)
        severity = 'HIGH' if high_src_allowed else 'MEDIUM'

        top = high_src.nlargest(3).to_dict()
        total_lateral = len(lateral)
        n_allowed_flows = len(lateral_allowed)
        n_pb_flows = total_lateral - n_allowed_flows
        top_ports = lateral['port'].value_counts().head(5).to_dict()

        return Finding(
            rule_id='B006', rule_name='High Lateral Movement',
            severity=severity, category='LateralMovement',
            description=t(
                "rpt_rule_B006_desc", lang=self._lang,
                n_high_src=len(high_src),
                threshold=threshold,
                total_lateral=f"{total_lateral:,}",
                n_allowed_flows=n_allowed_flows,
                n_pb_flows=n_pb_flows,
                top_offenders=list(top.keys())[:3],
            ),
            recommendation=t("rule_b006_rec_allowed" if high_src_allowed else "rule_b006_rec_pb", lang=self._lang),
            evidence={'high_src_count': len(high_src), 'top_sources': str(top),
                      'total_lateral_flows': total_lateral, 'allowed_flows': n_allowed_flows,
                      'pb_flows': n_pb_flows, 'top_ports': str(top_ports)},
        )

    def _b007_user_high_destinations(self, df: pd.DataFrame) -> Optional[Finding]:
        threshold = self._thresholds.get('user_destination_threshold', 20)
        has_user = df[df['user_name'].str.strip() != '']
        if has_user.empty:
            return None
        per_user = has_user.groupby('user_name')['dst_ip'].nunique()
        high_users = per_user[per_user > threshold]
        if not high_users.empty:
            top = high_users.nlargest(3).to_dict()
            top_ports = has_user[has_user['user_name'].isin(high_users.index)]['port'].value_counts().head(5).to_dict()
            return Finding(
                rule_id='B007', rule_name='Single User High Destinations',
                severity='HIGH', category='UserActivity',
                description=t(
                    "rpt_rule_B007_desc", lang=self._lang,
                    n_users=len(high_users),
                    threshold=threshold,
                    top_accounts=list(top.keys())[:3],
                    top_counts=list(top.values())[:3],
                    top_ports_list=list(top_ports.keys()),
                ),
                recommendation=t("rule_b007_rec", lang=self._lang),
                evidence={'high_user_count': len(high_users), 'top_users': str(top),
                          'top_ports': str(top_ports)},
            )
        return None

    def _b008_bandwidth_anomaly(self, df: pd.DataFrame) -> Optional[Finding]:
        percentile = self._thresholds.get('high_bytes_percentile', 95)
        if df['bytes_total'].sum() == 0:
            return None
        threshold_bytes = df['bytes_total'].quantile(percentile / 100.0)
        if threshold_bytes == 0:
            return None
        anomalies = df[df['bytes_total'] > threshold_bytes]
        if not anomalies.empty:
            top = anomalies.nlargest(3, 'bytes_total')[['src_ip', 'dst_ip', 'bytes_total']].to_dict('records')
            total_anomaly_bytes = anomalies['bytes_total'].sum()
            top_ports = anomalies['port'].value_counts().head(5).to_dict()
            return Finding(
                rule_id='B008', rule_name='High Bandwidth Anomaly',
                severity='MEDIUM', category='Bandwidth',
                description=t(
                    "rpt_rule_B008_desc", lang=self._lang,
                    n_anomalies=len(anomalies),
                    percentile=percentile,
                    threshold_bytes=_fmt_bytes(threshold_bytes),
                    total_anomaly_bytes=_fmt_bytes(total_anomaly_bytes),
                    top_src=top[0]['src_ip'],
                    top_dst=top[0]['dst_ip'],
                    top_bytes=_fmt_bytes(top[0]['bytes_total']),
                    top_ports_list=list(top_ports.keys()),
                ),
                recommendation=t("rule_b008_rec", lang=self._lang),
                evidence={'anomaly_count': len(anomalies), 'percentile_threshold': _fmt_bytes(threshold_bytes),
                          'total_anomaly_bytes': _fmt_bytes(total_anomaly_bytes), 'top_flows': str(top),
                          'top_ports': str(top_ports)},
            )
        return None

    def _b009_cross_env_volume(self, df: pd.DataFrame) -> Optional[Finding]:
        threshold = self._thresholds.get('cross_env_connection_threshold', 100)
        cross = df[(df['src_env'] != '') & (df['dst_env'] != '') & (df['src_env'] != df['dst_env'])]
        if len(cross) > threshold:
            top_pairs = cross.groupby(['src_env', 'dst_env']).size().nlargest(5).to_dict()
            top_ports = cross['port'].value_counts().head(5).to_dict()
            unique_envs = set(cross['src_env'].unique()) | set(cross['dst_env'].unique())
            top_pairs_str = ', '.join(f"{k[0]}→{k[1]} ({v})" for k, v in list(top_pairs.items())[:3])
            return Finding(
                rule_id='B009', rule_name='Cross-Env Flow Volume',
                severity='INFO', category='Policy',
                description=t(
                    "rpt_rule_B009_desc", lang=self._lang,
                    n_cross=f"{len(cross):,}",
                    n_envs=len(unique_envs),
                    threshold=threshold,
                    top_pairs_str=top_pairs_str,
                    top_ports_list=list(top_ports.keys()),
                ),
                recommendation=t("rule_b009_rec", lang=self._lang),
                evidence={'cross_env_flows': len(cross), 'top_pairs': str(top_pairs),
                          'environments': str(sorted(unique_envs)), 'top_ports': str(top_ports)},
            )
        return None

    # ── Lateral movement rules (L001–L010) ───────────────────────────────────
    # These rules are focused specifically on detecting attacker pivoting,
    # credential abuse, and blast-radius expansion inside the network.
    # Methodology inspired by Illumio MCP server security analysis functions:
    #   compliance-check, detect-lateral-movement-paths, enforcement-readiness,
    #   find-unmanaged-traffic, identify-infrastructure-services.

    # Port groups used across lateral movement rules
    _DB_PORTS    = {1433, 3306, 5432, 1521, 27017, 6379, 9200, 5984, 50000}
    _IDENTITY_PORTS = {88, 389, 636, 3268, 3269, 464}   # Kerberos, LDAP, GC
    _CLEARTEXT_PORTS = {23, 20, 21}                       # Telnet, FTP
    _DISCOVERY_PORTS = {137, 138, 5353, 5355, 1900, 3702} # NetBIOS, mDNS, LLMNR, SSDP, WSD
    _WINDOWS_MGMT_PORTS = {135, 445, 5985, 5986, 47001}   # RPC, SMB, WinRM
    _REMOTE_ACCESS_PORTS = {22, 3389, 5900, 5901, 5938, 23}

    def _l001_cleartext_protocols(self, df: pd.DataFrame) -> Optional[Finding]:
        """L001: Cleartext / legacy protocols (Telnet 23, FTP 20/21) that transmit credentials
        in plaintext. Any flow on these ports is a credential-harvesting risk — attackers
        running MITM or ARP poisoning can capture passwords directly."""
        matched = df[df['port'].isin(self._CLEARTEXT_PORTS)].copy()
        if matched.empty:
            return None
        allowed = matched[matched['policy_decision'] == 'allowed']
        top_ports = matched['port'].value_counts().head(5).to_dict()
        top_apps = matched['src_app'].fillna('unknown').value_counts().head(5).to_dict()
        severity = 'HIGH' if not allowed.empty else 'MEDIUM'
        return Finding(
            rule_id='L001', rule_name='Cleartext Protocol in Use',
            severity=severity, category='LateralMovement',
            description=t(
                "rpt_rule_L001_desc", lang=self._lang,
                n_flows=len(matched),
                telnet_count=top_ports.get(23, 0),
                ftp_count=top_ports.get(21, 0) + top_ports.get(20, 0),
                n_allowed=len(allowed),
            ),
            recommendation=t("rule_l001_rec", lang=self._lang),
            evidence={'total_flows': len(matched), 'allowed_flows': len(allowed),
                      'top_ports': str(top_ports), 'top_source_apps': str(top_apps)},
        )

    def _l002_legacy_discovery_protocols(self, df: pd.DataFrame) -> Optional[Finding]:
        """L002: Network discovery / broadcast protocols (NetBIOS 137-138, mDNS 5353,
        LLMNR 5355, SSDP 1900, WSD 3702) that enable attackers to perform hostname
        resolution poisoning (Responder attacks) and harvest NTLMv2 hashes without
        any authentication required."""
        matched = df[df['port'].isin(self._DISCOVERY_PORTS)].copy()
        if matched.empty:
            return None
        unblocked = matched[matched['policy_decision'] != 'blocked']
        if len(unblocked) == 0:
            return None  # All blocked — fine
        threshold = self._thresholds.get('discovery_protocol_threshold', 10)
        if len(unblocked) < threshold:
            return None
        top_ports = unblocked['port'].value_counts().head(5).to_dict()
        _port_names = {137: 'NetBIOS-NS', 138: 'NetBIOS-DGM', 5353: 'mDNS',
                       5355: 'LLMNR', 1900: 'SSDP', 3702: 'WSD'}
        named = {_port_names.get(p, str(p)): c for p, c in top_ports.items()}
        return Finding(
            rule_id='L002', rule_name='Network Discovery Protocol Exposure',
            severity='MEDIUM', category='LateralMovement',
            description=t(
                "rpt_rule_L002_desc", lang=self._lang,
                n_flows=len(unblocked),
                named=named,
            ),
            recommendation=t("rule_l002_rec", lang=self._lang),
            evidence={'unblocked_flows': len(unblocked), 'top_protocols': str(named)},
        )

    def _l003_database_port_wide_exposure(self, df: pd.DataFrame) -> Optional[Finding]:
        """L003: Database ports (MSSQL 1433, MySQL 3306, PostgreSQL 5432, Oracle 1521,
        MongoDB 27017, Redis 6379, Elasticsearch 9200) allowed from many distinct source
        apps. Databases should only be reachable from their direct application tier.
        Wide exposure enables SQL injection pivoting and direct data exfiltration."""
        db_flows = df[df['port'].isin(self._DB_PORTS) &
                      (df['policy_decision'] == 'allowed')].copy()
        if db_flows.empty:
            return None
        threshold = self._thresholds.get('db_unique_src_app_threshold', 5)
        per_db = (db_flows.groupby(['dst_ip', 'port'])
                  .agg(unique_src_apps=('src_app', 'nunique'),
                       unique_src_ips=('src_ip', 'nunique'),
                       connections=('num_connections', 'sum'))
                  .reset_index())
        wide = per_db[per_db['unique_src_apps'] > threshold]
        if wide.empty:
            # Also flag if total unique src apps across all DBs is high
            total_unique = db_flows['src_app'].nunique()
            if total_unique <= threshold:
                return None
        top_db = per_db.nlargest(5, 'unique_src_apps')[['dst_ip', 'port', 'unique_src_apps']].to_dict('records')
        top_ports = db_flows['port'].value_counts().head(5).to_dict()
        _db_names = {1433: 'MSSQL', 3306: 'MySQL', 5432: 'PostgreSQL', 1521: 'Oracle',
                     27017: 'MongoDB', 6379: 'Redis', 9200: 'Elasticsearch'}
        named_ports = {_db_names.get(p, str(p)): c for p, c in top_ports.items()}
        return Finding(
            rule_id='L003', rule_name='Database Port Wide Exposure',
            severity='HIGH', category='LateralMovement',
            description=t(
                "rpt_rule_L003_desc", lang=self._lang,
                n_src_apps=db_flows['src_app'].nunique(),
                named_ports=named_ports,
                n_wide=len(wide),
                threshold=threshold,
            ),
            recommendation=t("rule_l003_rec", lang=self._lang),
            evidence={'total_db_flows': len(db_flows),
                      'unique_src_apps': db_flows['src_app'].nunique(),
                      'top_databases': str(top_db), 'ports': str(named_ports)},
        )

    def _l004_cross_env_database_access(self, df: pd.DataFrame) -> Optional[Finding]:
        """L004: Database traffic that crosses environment boundaries
        (e.g., Development app → Production database). Cross-environment database
        access violates the principle of environment isolation and is a common
        path for attackers who compromise a lower-security environment to pivot
        into production data stores."""
        if 'src_env' not in df.columns or 'dst_env' not in df.columns:
            return None
        cross = df[
            df['port'].isin(self._DB_PORTS) &
            df['src_env'].notna() & df['dst_env'].notna() &
            df['src_env'].ne('') & df['dst_env'].ne('') &
            (df['src_env'] != df['dst_env']) &
            (df['policy_decision'] == 'allowed')
        ].copy()
        if cross.empty:
            return None
        top_pairs = (cross.groupby(['src_env', 'dst_env', 'port'])
                     .size().nlargest(5).reset_index(name='flows').to_dict('records'))
        top_pairs_str = ', '.join(
            f"{r['src_env']}→{r['dst_env']}:{r['port']}({r['flows']})" for r in top_pairs[:3]
        )
        return Finding(
            rule_id='L004', rule_name='Cross-Environment Database Access',
            severity='HIGH', category='LateralMovement',
            description=t(
                "rpt_rule_L004_desc", lang=self._lang,
                n_flows=len(cross),
                top_pairs_str=top_pairs_str,
            ),
            recommendation=t("rule_l004_rec", lang=self._lang),
            evidence={'cross_env_db_flows': len(cross), 'top_env_pairs': str(top_pairs)},
        )

    def _l005_identity_infrastructure_exposure(self, df: pd.DataFrame) -> Optional[Finding]:
        """L005: Kerberos (88), LDAP (389/636), Global Catalog (3268/3269) flows from
        non-infrastructure / non-DC source applications. Active Directory is the
        master authentication authority — if an attacker can directly query LDAP or
        forge Kerberos tickets (Golden/Silver ticket attacks), they own the domain.
        Lateral access to these ports is a critical escalation risk."""
        id_flows = df[df['port'].isin(self._IDENTITY_PORTS) &
                      (df['policy_decision'] != 'blocked')].copy()
        if id_flows.empty:
            return None
        threshold = self._thresholds.get('identity_unique_src_threshold', 3)
        unique_src_apps = id_flows['src_app'].fillna('').nunique()
        if unique_src_apps <= threshold:
            return None

        id_allowed = id_flows[id_flows['policy_decision'] == 'allowed']
        unique_src_apps_allowed = id_allowed['src_app'].fillna('').nunique()

        # HIGH if explicit allow rules expose identity ports broadly;
        # MEDIUM if only potentially_blocked (no allow rule — default-deny blocks when enforced)
        severity = 'HIGH' if unique_src_apps_allowed > threshold else 'MEDIUM'

        top_ports = id_flows['port'].value_counts().head(5).to_dict()
        top_srcs = id_flows['src_app'].fillna('unknown').value_counts().head(5).to_dict()
        _port_names = {88: 'Kerberos', 389: 'LDAP', 636: 'LDAPS', 3268: 'GC', 3269: 'GC-SSL', 464: 'Kpasswd'}
        named = {_port_names.get(p, str(p)): c for p, c in top_ports.items()}
        return Finding(
            rule_id='L005', rule_name='Identity Infrastructure Wide Exposure',
            severity=severity, category='LateralMovement',
            description=t(
                "rpt_rule_L005_desc", lang=self._lang,
                unique_src_apps=unique_src_apps,
                unique_src_apps_allowed=unique_src_apps_allowed,
                unique_src_apps_pb=unique_src_apps - unique_src_apps_allowed,
                named=named,
            ),
            recommendation=t("rule_l005_rec_allowed" if unique_src_apps_allowed > threshold else "rule_l005_rec_pb", lang=self._lang),
            evidence={'unblocked_flows': len(id_flows), 'allowed_flows': len(id_allowed),
                      'unique_src_apps': unique_src_apps, 'unique_src_apps_allowed': unique_src_apps_allowed,
                      'top_ports': str(named), 'top_sources': str(top_srcs)},
        )

    def _l006_high_reachability_lateral_path(self, df: pd.DataFrame) -> Optional[Finding]:
        """L006: Graph-based lateral movement path analysis (inspired by MCP
        detect-lateral-movement-paths BFS). Builds app→app graph on lateral ports,
        computes BFS reachability for each app node. Apps that can reach many others
        via a chain of lateral-port connections represent the highest blast-radius
        compromise scenarios — an attacker starting at any of these pivot points
        can reach the most downstream systems."""
        from collections import defaultdict, deque
        lateral = df[
            df['port'].isin(self._lateral_ports) &
            (df['policy_decision'] == 'allowed') &
            df['src_app'].notna() & df['src_app'].ne('') &
            df['dst_app'].notna() & df['dst_app'].ne('')
        ]
        if lateral.empty:
            return None

        # Build directed adjacency list: src_app|src_env → dst_app|dst_env
        adj: dict[str, set[str]] = defaultdict(set)
        for _, row in lateral.iterrows():
            src = f"{row['src_app']}|{row.get('src_env','')}"
            dst = f"{row['dst_app']}|{row.get('dst_env','')}"
            if src != dst:
                adj[src].add(dst)

        if not adj:
            return None

        all_nodes = set(adj.keys()) | {d for dsts in adj.values() for d in dsts}
        threshold = self._thresholds.get('blast_radius_threshold', 5)

        # BFS reachability per node
        high_risk = []
        for start in all_nodes:
            visited: set[str] = {start}
            queue: deque[str] = deque([start])
            while queue:
                node = queue.popleft()
                for nb in adj.get(node, set()):
                    if nb not in visited:
                        visited.add(nb)
                        queue.append(nb)
            reach = len(visited) - 1
            if reach >= threshold:
                app, env = start.split('|', 1) if '|' in start else (start, '')
                high_risk.append({'app': app, 'env': env, 'reachable': reach})

        if not high_risk:
            return None

        high_risk.sort(key=lambda x: -x['reachable'])
        top5 = high_risk[:5]
        top_pivots_str = ', '.join(f"{r['app']}({r['reachable']} reachable)" for r in top5)
        return Finding(
            rule_id='L006', rule_name='High Blast-Radius Lateral Movement Path',
            severity='HIGH', category='LateralMovement',
            description=t(
                "rpt_rule_L006_desc", lang=self._lang,
                n_high_risk=len(high_risk),
                threshold=threshold,
                top_pivots_str=top_pivots_str,
            ),
            recommendation=t("rule_l006_rec", lang=self._lang),
            evidence={'high_risk_nodes': len(high_risk),
                      'blast_radius_threshold': threshold,
                      'top_pivot_apps': str(top5[:3])},
        )

    def _l007_unmanaged_targeting_critical_services(self, df: pd.DataFrame) -> Optional[Finding]:
        """L007: Unmanaged (non-PCE) hosts communicating on database, identity, or
        Windows management ports to managed workloads. Unmanaged hosts have no VEN
        and therefore no Illumio enforcement — they are effectively outside the
        zero-trust boundary. If they can reach critical services, they represent
        uncontrolled attack surface from potentially compromised or shadow IT assets."""
        critical_ports = self._DB_PORTS | self._IDENTITY_PORTS | self._WINDOWS_MGMT_PORTS
        matched = df[
            (df['src_managed'] == False) &
            df['port'].isin(critical_ports) &
            (df['policy_decision'] != 'blocked')
        ].copy()
        if matched.empty:
            return None
        threshold = self._thresholds.get('unmanaged_critical_threshold', 5)
        if len(matched) < threshold:
            return None
        top_ips = matched['src_ip'].value_counts().head(5).to_dict()
        top_ports = matched['port'].value_counts().head(5).to_dict()
        top_dst = matched['dst_app'].fillna('unknown').value_counts().head(5).to_dict()
        # Numeric fallbacks FIRST so the explicit friendly names win the merge —
        # otherwise the spread clobbers MSSQL/MySQL/PgSQL (1433/3306/5432 are in
        # _DB_PORTS) back to bare numbers.
        _all_names = {**{p: str(p) for p in self._DB_PORTS},
                      1433: 'MSSQL', 3306: 'MySQL', 5432: 'PgSQL', 88: 'Kerberos',
                      389: 'LDAP', 445: 'SMB', 135: 'RPC', 5985: 'WinRM'}
        named_ports = {_all_names.get(p, str(p)): c for p, c in top_ports.items()}
        return Finding(
            rule_id='L007', rule_name='Unmanaged Host Accessing Critical Services',
            severity='HIGH', category='LateralMovement',
            description=t(
                "rpt_rule_L007_desc", lang=self._lang,
                n_flows=len(matched),
                unique_src=matched['src_ip'].nunique(),
                named_ports=named_ports,
                top_dst=top_dst,
            ),
            recommendation=t("rule_l007_rec", lang=self._lang),
            evidence={'total_flows': len(matched),
                      'unique_unmanaged_src': matched['src_ip'].nunique(),
                      'top_src_ips': str(top_ips), 'top_ports': str(named_ports)},
        )

    def _l008_enforcement_mode_gap(self, df: pd.DataFrame) -> Optional[Finding]:
        """L008: Detects workloads operating in visibility/test mode by identifying
        'potentially_blocked' flows — traffic that would be blocked if the workload
        were in enforced mode. High PB volume on lateral movement ports means
        attackers CAN traverse these paths right now even though policies say they
        should be blocked. This is the most common cause of 'we had rules but got
        breached' incidents."""
        pb = df[
            (df['policy_decision'] == 'potentially_blocked') &
            df['port'].isin(self._lateral_ports | self._WINDOWS_MGMT_PORTS |
                            self._DB_PORTS | self._IDENTITY_PORTS)
        ].copy()
        if pb.empty:
            return None
        threshold = self._thresholds.get('pb_lateral_threshold', 10)
        if len(pb) < threshold:
            return None
        top_ports = pb['port'].value_counts().head(5).to_dict()
        top_apps = pb['dst_app'].fillna('unknown').value_counts().head(5).to_dict()
        unique_src = pb['src_ip'].nunique()
        unique_dst = pb['dst_ip'].nunique()
        return Finding(
            rule_id='L008', rule_name='Lateral Ports in Test Mode (PB)',
            severity='HIGH', category='LateralMovement',
            description=t(
                "rpt_rule_L008_desc", lang=self._lang,
                n_flows=len(pb),
                unique_src=unique_src,
                unique_dst=unique_dst,
                top_ports=top_ports,
            ),
            recommendation=t("rule_l008_rec", top_apps=top_apps, lang=self._lang),
            evidence={'pb_lateral_flows': len(pb), 'unique_src': unique_src,
                      'unique_dst': unique_dst, 'top_ports': str(top_ports),
                      'top_dst_apps': str(top_apps)},
        )

    def _l009_outbound_exfiltration_pattern(self, df: pd.DataFrame) -> Optional[Finding]:
        """L009: Managed application workloads sending significant data volume to
        unmanaged (external/unknown) destination IPs. This is the classic data
        exfiltration pattern — attacker has already achieved lateral movement,
        established a beachhead, and is now exfiltrating data to an external C2
        or staging host outside the PCE-managed environment."""
        exfil = df[
            (df['dst_managed'] == False) &
            (df['src_managed'] == True) &
            (df['policy_decision'] == 'allowed') &
            (df['bytes_total'] > 0)
        ].copy()
        if exfil.empty:
            return None
        total_bytes = exfil['bytes_total'].sum()
        threshold_mb = self._thresholds.get('exfil_bytes_threshold_mb', 100)
        if total_bytes < threshold_mb * 1024 * 1024:
            return None
        top_dst = exfil.groupby('dst_ip')['bytes_total'].sum().nlargest(5).to_dict()
        top_apps = exfil.groupby('src_app')['bytes_total'].sum().nlargest(5).to_dict()
        top_dst_fmt = {ip: _fmt_bytes(b) for ip, b in top_dst.items()}
        top_apps_fmt = {app: _fmt_bytes(b) for app, b in top_apps.items()}
        return Finding(
            rule_id='L009', rule_name='Data Exfiltration Pattern (Outbound to Unmanaged)',
            severity='HIGH', category='LateralMovement',
            description=t(
                "rpt_rule_L009_desc", lang=self._lang,
                total_bytes=_fmt_bytes(total_bytes),
                unique_dst=exfil['dst_ip'].nunique(),
                top_apps_fmt=top_apps_fmt,
            ),
            recommendation=t("rule_l009_rec", top_dst_fmt=top_dst_fmt, lang=self._lang),
            evidence={'total_transferred': _fmt_bytes(total_bytes),
                      'unique_unmanaged_dst': exfil['dst_ip'].nunique(),
                      'top_dst_ips': str(top_dst_fmt), 'top_src_apps': str(top_apps_fmt)},
        )

    def _l010_cross_env_lateral_port_access(self, df: pd.DataFrame) -> Optional[Finding]:
        """L010: Lateral movement ports (SMB, RDP, WinRM, RPC) allowed between
        workloads in DIFFERENT environments (Production, Development, Staging, etc.).
        Environment boundaries are your macro-segmentation layer — if lateral ports
        cross these boundaries, an attacker who compromises a Dev system can directly
        pivot into Production via the same techniques used for intra-network movement."""
        if 'src_env' not in df.columns or 'dst_env' not in df.columns:
            return None
        cross = df[
            df['port'].isin(self._lateral_ports | self._WINDOWS_MGMT_PORTS) &
            df['src_env'].notna() & df['dst_env'].notna() &
            df['src_env'].ne('') & df['dst_env'].ne('') &
            (df['src_env'] != df['dst_env']) &
            (df['policy_decision'] == 'allowed')
        ].copy()
        if cross.empty:
            return None
        threshold = self._thresholds.get('cross_env_lateral_threshold', 5)
        if len(cross) < threshold:
            return None
        top_pairs = (cross.groupby(['src_env', 'dst_env'])
                     .agg(flows=('num_connections', 'sum'),
                          ports=('port', lambda x: str(sorted(set(x))[:5])))
                     .reset_index().nlargest(5, 'flows').to_dict('records'))
        top_ports = cross['port'].value_counts().head(5).to_dict()
        top_pairs_str = ', '.join(
            f"{r['src_env']}→{r['dst_env']}({r['flows']} flows)" for r in top_pairs[:3]
        )
        return Finding(
            rule_id='L010', rule_name='Cross-Environment Lateral Port Access',
            severity='CRITICAL', category='LateralMovement',
            description=t(
                "rpt_rule_L010_desc", lang=self._lang,
                n_flows=len(cross),
                top_pairs_str=top_pairs_str,
            ),
            recommendation=t("rule_l010_rec", lang=self._lang),
            evidence={'cross_env_lateral_flows': len(cross), 'top_env_pairs': str(top_pairs[:3]),
                      'top_ports': str(top_ports)},
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _build_risk_port_map(self, report_config: dict) -> dict[str, set[int]]:
        """Flatten risk port config into level → set[port]."""
        result = {}
        for level, entries in report_config.get('ransomware_risk_ports', {}).items():
            ports = set()
            for entry in entries:
                p = entry.get('ports', [])
                if isinstance(p, list):
                    ports.update(p)
                else:
                    ports.add(p)
            result[level] = ports
        return result
