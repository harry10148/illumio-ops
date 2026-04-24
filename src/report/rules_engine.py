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
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

def _fmt_bytes(n: float) -> str:
    """Return human-readable byte string (B / KB / MB / GB / TB)."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

# ─── Finding model ───────────────────────────────────────────────────────────

SEVERITY_RANK = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}

@dataclass
class Finding:
    rule_id: str
    rule_name: str
    severity: str            # CRITICAL | HIGH | MEDIUM | LOW | INFO
    category: str            # e.g. Ransomware, LateralMovement, Policy
    description: str
    recommendation: str
    evidence: dict = field(default_factory=dict)   # supporting data for the finding

    @property
    def severity_rank(self) -> int:
        return SEVERITY_RANK.get(self.severity, 99)

    def to_dict(self) -> dict:
        return {
            'rule_id': self.rule_id,
            'rule_name': self.rule_name,
            'severity': self.severity,
            'category': self.category,
            'description': self.description,
            'recommendation': self.recommendation,
            **{f'evidence_{k}': v for k, v in self.evidence.items()},
        }

# ─── Rules Engine ────────────────────────────────────────────────────────────

class RulesEngine:
    """
    Evaluates all structural and semantic rules against a Unified DataFrame.

    Usage:
        engine = RulesEngine(report_config, config_dir='config/')
        findings = engine.evaluate(df)
    """

    def __init__(self, report_config: dict, config_dir: str = 'config'):
        self._cfg = report_config
        self._thresholds = report_config.get('thresholds', {})
        self._risk_ports = self._build_risk_port_map(report_config)
        self._lateral_ports = set(report_config.get('lateral_movement_ports', []))

    # ── public ───────────────────────────────────────────────────────────────

    def evaluate(self, df: pd.DataFrame) -> list[Finding]:
        """Run all rules and return sorted findings list."""
        findings: list[Finding] = []
        findings.extend(self._eval_builtin(df))
        findings.sort(key=lambda f: f.severity_rank)
        logger.info(f"[RulesEngine] {len(findings)} findings generated")
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

        _port_names = {135: 'RPC', 445: 'SMB', 3389: 'RDP', 5985: 'WinRM', 5986: 'WinRM-SSL'}
        port_counts = matched['port'].value_counts().head(5).to_dict()
        named_ports = {_port_names.get(p, str(p)): c for p, c in port_counts.items()}

        # ── Contextual severity determination ─────────────────────────────────
        if n_cross_env > 0:
            severity = 'CRITICAL'
            cross_env_rows = matched[matched['_cross_env']]
            n_cross_env_allowed = int((cross_env_rows['policy_decision'] == 'allowed').sum())
            n_cross_env_pb = n_cross_env - n_cross_env_allowed
            risk_summary = (
                f"{n_cross_env} flows cross environment boundaries "
                f"({n_cross_env_allowed} explicitly allowed, {n_cross_env_pb} potentially_blocked) — "
                "active lateral movement path between security domains."
            )
            if n_cross_env_allowed > 0:
                recommendation = (
                    "CRITICAL: Explicit allow rules permit lateral movement ports across environment boundaries. "
                    f"Immediately remove or tightly scope these allow rules for: {list(named_ports.keys())}. "
                    "Investigate source IPs in cross-env flows — treat as active incident until proven otherwise."
                )
            else:
                recommendation = (
                    "CRITICAL: Cross-environment flows detected with no allow rule (potentially_blocked). "
                    "No explicit policy permits this traffic — it flows only because workloads are in test mode. "
                    f"Move workloads to enforced mode to activate default-deny and block these paths immediately. "
                    f"Investigate why this cross-env traffic exists on: {list(named_ports.keys())}."
                )
        elif n_cross_subnet > 0 and n_allowed > 0:
            severity = 'HIGH'
            risk_summary = (
                f"{n_cross_subnet} flows are cross-subnet ({n_allowed} explicitly allowed). "
                f"Same-subnet flows: {n_same_subnet} (may be legitimate admin)."
            )
            recommendation = (
                f"Cross-subnet flows on {list(named_ports.keys())} indicate unscoped management access "
                "or potential lateral movement. "
                "Restrict allow rules to: (1) authorised jump-host / bastion IPs only, "
                "(2) specific management VLAN ranges. "
                f"Same-subnet flows ({n_same_subnet}) may be legitimate Windows admin — "
                "verify source IPs and scope rules accordingly. "
                "Apply Illumio rules with explicit source IP / label constraints."
            )
        elif n_cross_subnet > 0 and n_pb == n_cross_subnet:
            severity = 'MEDIUM'
            risk_summary = (
                f"{n_cross_subnet} cross-subnet flows have no allow rule (potentially_blocked) — "
                "traffic flows because VEN is in test mode; enforce to activate default-deny."
            )
            recommendation = (
                "Cross-subnet flows on critical ports have no allow rule (potentially_blocked) — "
                "no policy covers these paths; they flow only because VEN is in test mode. "
                "Move destination workloads to selective or full enforcement to activate default-deny. "
                f"Same-subnet flows ({n_same_subnet}) may be legitimate admin traffic."
            )
        elif n_same_subnet == n_total and n_pb == n_total:
            severity = 'INFO'
            risk_summary = (
                f"All {n_total} flows are within the same /24 subnet and in test mode only. "
                "Traffic is likely routine Windows admin; block is not active but risk is limited."
            )
            recommendation = (
                "Same-subnet traffic on critical ports in test mode only. "
                "Low immediate risk — verify source IPs are authorised admin systems, "
                "then move workloads to enforced mode. "
                "Consider scoping allow rules to specific admin IPs rather than subnet-wide."
            )
        else:
            # Same-subnet, allowed — MEDIUM (legitimate admin but worth documenting)
            severity = 'MEDIUM'
            risk_summary = (
                f"All {n_total} flows are within the same /24 subnet "
                f"({n_allowed} allowed, {n_pb} test-mode). "
                "Likely Windows administration traffic, but source scope should be verified."
            )
            recommendation = (
                "Same-subnet flows on critical ports are typical for Windows server administration "
                "(RDP to nearby servers, SMB file shares, WinRM remote management). "
                "Recommended actions: "
                "(1) Verify each source IP is an authorised admin system or jump host, "
                "(2) Scope Illumio allow rules to specific source IPs rather than allowing all "
                "same-subnet access — this prevents lateral movement if any same-subnet host is compromised, "
                "(3) Confirm SMB 445 and RPC 135 are not used for general file sharing across workloads."
            )

        # Top suspicious flows (cross-subnet or cross-env, allowed)
        suspicious = matched[
            (matched['_cross_env'] | ~matched['_same_subnet']) &
            (matched['policy_decision'] == 'allowed')
        ]
        top_pairs = (suspicious[['src_ip', 'dst_ip', 'port', 'policy_decision']]
                     .head(5).to_dict('records')) if not suspicious.empty else []

        description = (
            f"{n_total} non-blocked flows on critical lateral movement ports: {named_ports}. "
            f"{risk_summary} "
            f"Flow breakdown — same-subnet: {n_same_subnet}, "
            f"cross-subnet: {n_cross_subnet}, cross-env: {n_cross_env}, "
            f"explicitly allowed: {n_allowed}, test-mode only: {n_pb}."
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
                description=(
                    f"{len(matched)} flows on high-risk remote access ports are explicitly allowed: "
                    f"{named}. These flows span {unique_src} unique source IPs → {unique_dst} unique "
                    f"destinations. Remote access tools are the #1 initial access vector for ransomware "
                    f"operators (e.g., Conti, LockBit) who exploit exposed VNC/TeamViewer to gain GUI "
                    f"access without triggering endpoint alerts."
                ),
                recommendation=(
                    "1) Verify each allowed flow has a documented business justification. "
                    "2) Block TeamViewer (5938) and VNC (5900/5901) unless required for specific admin workflows — "
                    "replace with MFA-protected jump servers. "
                    "3) If NetBIOS (137-139) is allowed, migrate to SMBv3 over 445 with encryption. "
                    "4) Create Illumio deny rules for these ports from all non-admin workloads."
                ),
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
            unique_wl = matched['src_ip'].nunique() + matched['dst_ip'].nunique()
            return Finding(
                rule_id='B003', rule_name='Ransomware Risk Port (Medium) — Uncovered',
                severity='MEDIUM', category='Ransomware',
                description=(
                    f"{len(matched)} flows on medium-risk ports are in 'potentially_blocked' state "
                    f"(workloads still in test/visibility mode): {named}. "
                    f"This affects approximately {unique_wl} workload IPs. "
                    f"While these flows would be blocked in enforced mode, they represent real "
                    f"network paths that ransomware could exploit if enforcement is delayed."
                ),
                recommendation=(
                    "1) Prioritize moving workloads with potentially_blocked flows to enforced mode — "
                    "start with the highest-risk ports (SSH, NFS). "
                    "2) Review the 'potentially_blocked' flows to ensure no legitimate traffic "
                    "will break when enforcement is applied. "
                    "3) Create allow rules for verified legitimate traffic before switching to enforced mode. "
                    "4) Set a deadline for enforcement — prolonged test mode leaves the network exposed."
                ),
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
                description=(
                    f"{total} flows originated from unmanaged sources (threshold: {threshold}), "
                    f"targeting {unique_dst} unique managed destinations on ports {list(top_dst_ports.keys())}. "
                    f"Top unmanaged source IPs: {list(top_ips.keys())[:3]}. "
                    f"Unmanaged hosts bypass Illumio policy enforcement — any traffic they send "
                    f"cannot be micro-segmented, creating blind spots in your security posture."
                ),
                recommendation=(
                    "1) Identify each unmanaged source IP — are they network devices, legacy servers, "
                    "or shadow IT? "
                    "2) Deploy VEN agents on servers that should be managed. "
                    "3) For network devices that can't run a VEN, use IP lists and enforcement "
                    "boundaries to control their access. "
                    "4) Create explicit deny rules for any unmanaged-to-managed path that isn't required."
                ),
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
                description=(
                    f"Policy coverage is only {coverage_pct:.1f}% — out of {total:,} total flows, "
                    f"only {allowed:,} are explicitly allowed by rules, while {blocked:,} are blocked "
                    f"and {pb:,} are potentially blocked (test mode). "
                    f"Low coverage means most traffic is flowing without explicit policy authorization, "
                    f"making it impossible to distinguish legitimate traffic from attacker movement."
                ),
                recommendation=(
                    "1) Focus first on critical tiers: databases, identity infrastructure (AD/LDAP), "
                    "and externally-facing workloads. "
                    "2) Use Illumio's Explorer to identify top unruled flows and create allow rules "
                    "for verified traffic. "
                    "3) Set a target coverage of >{threshold}% within 30 days. "
                    "4) Enable enforcement gradually — start with ring-fencing high-value assets, "
                    "then expand to general workloads."
                ),
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
            description=(
                f"{len(high_src)} source IPs each connected to >{threshold} unique destinations "
                f"via lateral movement ports, totalling {total_lateral:,} flows "
                f"({n_allowed_flows} explicitly allowed, {n_pb_flows} potentially_blocked). "
                f"Top offenders: {list(top.keys())[:3]}. "
                f"This fan-out pattern is a strong indicator of host-hopping."
            ),
            recommendation=(
                "1) Investigate the top source IPs — check for exploit tools, unexpected SSH sessions, "
                "or RDP brute-force. "
                + ("2) Remove or tightly scope the allow rules driving the high-fan-out flows. " if high_src_allowed else
                   "2) Move workloads to enforced mode — no allow rules exist for these paths; "
                   "default-deny will block them upon enforcement. ")
                + "3) Ring-fence high-value assets (databases, domain controllers) to limit blast radius."
            ),
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
                description=(
                    f"{len(high_users)} user accounts each reached >{threshold} unique destination IPs. "
                    f"Top accounts: {list(top.keys())[:3]} (reaching {list(top.values())[:3]} destinations). "
                    f"Ports used: {list(top_ports.keys())}. "
                    f"Normal users typically access a small, predictable set of servers. "
                    f"A single account reaching many destinations may indicate credential theft, "
                    f"automated scanning, or data exfiltration via compromised credentials."
                ),
                recommendation=(
                    "1) Cross-reference flagged accounts with HR/IT records — are these admin accounts "
                    "or regular users? "
                    "2) Check authentication logs for failed login attempts or impossible-travel alerts. "
                    "3) For admin accounts, enforce just-in-time access and MFA for lateral sessions. "
                    "4) Create Illumio user-based rules to limit which destinations each role can access. "
                    "5) If compromise is suspected, rotate credentials immediately and isolate the workload."
                ),
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
                description=(
                    f"{len(anomalies)} flows exceed the {percentile}th percentile threshold "
                    f"({_fmt_bytes(threshold_bytes)}), transferring a combined {_fmt_bytes(total_anomaly_bytes)}. "
                    f"Top flow: {top[0]['src_ip']} → {top[0]['dst_ip']} ({_fmt_bytes(top[0]['bytes_total'])}). "
                    f"Ports involved: {list(top_ports.keys())}. "
                    f"Abnormally large data transfers may indicate data exfiltration, "
                    f"unauthorized backups, or misconfigured replication jobs."
                ),
                recommendation=(
                    "1) Verify the top bandwidth consumers — are they backup servers, replication, "
                    "or database sync? Document expected high-volume flows. "
                    "2) For unexplained transfers, check if the source is a compromised workload "
                    "exfiltrating data to an external or lateral destination. "
                    "3) Consider implementing bandwidth-aware rules or QoS policies for known "
                    "high-volume services. "
                    "4) Set up Illumio monitoring alerts for sustained anomalous volume."
                ),
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
            return Finding(
                rule_id='B009', rule_name='Cross-Env Flow Volume',
                severity='INFO', category='Policy',
                description=(
                    f"{len(cross):,} cross-environment flows detected across {len(unique_envs)} "
                    f"environments (threshold: {threshold}). "
                    f"Top environment pairs: " +
                    ', '.join(f"{k[0]}→{k[1]} ({v})" for k, v in list(top_pairs.items())[:3]) +
                    f". Ports: {list(top_ports.keys())}. "
                    f"Cross-environment traffic is expected for some services (monitoring, DNS, NTP) "
                    f"but should be explicitly authorized. Uncontrolled cross-env flows break "
                    f"environment isolation and can enable pivot attacks from lower to higher environments."
                ),
                recommendation=(
                    "1) Audit each cross-env flow pair — document which ones are expected "
                    "(e.g., Production monitoring pulling from Staging). "
                    "2) Create explicit Illumio rules for approved cross-env paths with "
                    "specific port restrictions. "
                    "3) Block all other cross-env flows, especially database ports (see L004) and "
                    "admin protocols (SSH, RDP). "
                    "4) Use Illumio environment labels consistently to enforce isolation boundaries."
                ),
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
            description=(
                f"{len(matched)} flows detected on cleartext protocols "
                f"(Telnet:{top_ports.get(23,0)}, FTP:{top_ports.get(21,0)+top_ports.get(20,0)}). "
                f"{len(allowed)} of these are explicitly allowed."
            ),
            recommendation=(
                "Immediately disable Telnet (port 23) and FTP (ports 20/21). "
                "Replace with SSH (22) or SFTP. Cleartext credentials can be captured "
                "by any attacker with network access, enabling trivial lateral movement."
            ),
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
            description=(
                f"{len(unblocked)} flows on broadcast/discovery protocols are not blocked: "
                f"{named}. These protocols enable Responder-based NTLMv2 hash harvesting."
            ),
            recommendation=(
                "Block NetBIOS (137-138), LLMNR (5355), and SSDP (1900) at the segmentation "
                "layer. These protocols serve no legitimate role in modern micro-segmented "
                "environments and are used almost exclusively for network reconnaissance and "
                "credential poisoning attacks (e.g., Responder / Inveigh)."
            ),
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
            description=(
                f"Database ports are reachable from {db_flows['src_app'].nunique()} "
                f"unique source applications: {named_ports}. "
                f"{len(wide)} database endpoints are reachable from >{threshold} distinct app tiers."
            ),
            recommendation=(
                "Database ports should only be reachable from their direct application tier "
                "(typically 1-2 app labels). Use Illumio rule-sets to restrict db access to "
                "approved app labels only. Wide database exposure is the primary post-exploitation "
                "data exfiltration path after lateral movement succeeds."
            ),
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
        return Finding(
            rule_id='L004', rule_name='Cross-Environment Database Access',
            severity='HIGH', category='LateralMovement',
            description=(
                f"{len(cross)} allowed database flows cross environment boundaries. "
                f"Top pairs: " +
                ', '.join(f"{r['src_env']}→{r['dst_env']}:{r['port']}({r['flows']})" for r in top_pairs[:3])
            ),
            recommendation=(
                "Enforce strict environment isolation for all database ports. "
                "No Dev/Test/Staging application should have direct access to Production databases. "
                "Use read replicas or API gateways as the cross-environment interface, never direct DB ports."
            ),
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
            description=(
                f"Identity infrastructure ports (Kerberos/LDAP) are reachable from "
                f"{unique_src_apps} distinct source apps ({unique_src_apps_allowed} via explicit allow rules, "
                f"{unique_src_apps - unique_src_apps_allowed} potentially_blocked): {named}. "
                f"Excessive LDAP/Kerberos reach enables domain enumeration and ticket attacks."
            ),
            recommendation=(
                ("Restrict Kerberos (88) and LDAP (389/636) to domain-joined workloads only. "
                 "Remove or tightly scope allow rules permitting broad identity-port access. "
                 if unique_src_apps_allowed > threshold else
                 "These flows have no allow rule — move workloads to enforced mode so default-deny blocks them. "
                 "Before enforcing, create allow rules only for legitimate LDAP consumers (domain-joined workloads). ")
                + "No application tier should query LDAP directly — use a service account wrapper."
            ),
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
        return Finding(
            rule_id='L006', rule_name='High Blast-Radius Lateral Movement Path',
            severity='HIGH', category='LateralMovement',
            description=(
                f"{len(high_risk)} application nodes can reach ≥{threshold} other apps "
                f"via allowed lateral-port connections (pivoting chains). "
                f"Top pivot points: " +
                ', '.join(f"{r['app']}({r['reachable']} reachable)" for r in top5)
            ),
            recommendation=(
                "Reduce lateral-port connectivity between application tiers using Illumio "
                "rule-sets. Each application should only be able to reach its direct "
                "dependencies — not transitively reach the entire network. "
                "Prioritise isolating the top pivot apps listed in evidence."
            ),
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
        _all_names = {1433: 'MSSQL', 3306: 'MySQL', 5432: 'PgSQL', 88: 'Kerberos',
                      389: 'LDAP', 445: 'SMB', 135: 'RPC', 5985: 'WinRM', **{p: str(p) for p in self._DB_PORTS}}
        named_ports = {_all_names.get(p, str(p)): c for p, c in top_ports.items()}
        return Finding(
            rule_id='L007', rule_name='Unmanaged Host Accessing Critical Services',
            severity='HIGH', category='LateralMovement',
            description=(
                f"{len(matched)} flows from {matched['src_ip'].nunique()} unmanaged hosts "
                f"targeting database/identity/management ports: {named_ports}. "
                f"Top targets: {top_dst}."
            ),
            recommendation=(
                "Unmanaged hosts should NEVER directly reach database, identity, or Windows "
                "management ports. Options: (1) Onboard the hosts to PCE immediately, "
                "(2) Add explicit deny rules for unmanaged sources on these ports, "
                "(3) Investigate whether these are attacker-controlled hosts or shadow IT. "
                "Priority: verify the top source IPs are known/authorised assets."
            ),
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
            description=(
                f"{len(pb)} flows on lateral/critical ports are 'potentially_blocked' "
                f"({unique_src} sources → {unique_dst} destinations). "
                f"These paths are currently traversable because workloads are not fully enforced. "
                f"Top ports: {top_ports}."
            ),
            recommendation=(
                "Move workloads from visibility/test mode to selective or full enforcement. "
                "Until enforcement is active, 'potentially_blocked' flows are live attack "
                "paths — no allow rule covers them; only enforced mode's default-deny will block them. "
                "Check enforcement mode in PCE for the destination apps: {top_apps}."
            ),
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
            description=(
                f"Managed workloads transferred {_fmt_bytes(total_bytes)} "
                f"to {exfil['dst_ip'].nunique()} unmanaged destinations. "
                f"Top source apps: {top_apps_fmt}."
            ),
            recommendation=(
                "Investigate all managed-to-unmanaged outbound flows above the threshold. "
                "Legitimate outbound traffic (internet APIs, CDN) should be explicitly "
                "allowed and scoped to known destination IPs or ranges. "
                "Apply an outbound allowlist policy and deny all other external destinations. "
                "Top suspicious destinations (by bytes): {top_dst_fmt}."
            ),
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
        return Finding(
            rule_id='L010', rule_name='Cross-Environment Lateral Port Access',
            severity='CRITICAL', category='LateralMovement',
            description=(
                f"{len(cross)} allowed flows use lateral/management ports across environment "
                f"boundaries. Environment isolation is broken. "
                f"Top environment pairs: " +
                ', '.join(f"{r['src_env']}→{r['dst_env']}({r['flows']} flows)" for r in top_pairs[:3])
            ),
            recommendation=(
                "CRITICAL: Lateral movement ports (SMB 445, RDP 3389, WinRM 5985/5986, RPC 135) "
                "must NEVER be allowed across environment boundaries. "
                "Implement deny rules at the environment boundary level immediately. "
                "This represents an active lateral movement path between environments that "
                "an attacker can exploit to escalate from low-security to high-security zones."
            ),
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
