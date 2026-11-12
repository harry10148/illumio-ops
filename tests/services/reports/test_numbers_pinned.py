"""Stage 3a rearranges how a report reads; it does not change one number. The key numbers of every report type —
{Kpi.key: (value, previous)} — are written here as they were before the first builder was touched, for the two
sample installs the report tests already have: the one with every setting and analysis (test_report_i18n) and the one
with none of the optional ones (test_reads_without_optional_settings). The order of the numbers is not pinned (the
lead three move to the front); which numbers there are, their values and their types are.

No task of stage 3a may edit an expected value in this file."""
import pytest

from illumio_ops.domain.values import Language, ReportType
from illumio_ops.services.reports.finish import finish
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from tests.services.reports import test_reads_without_optional_settings as plain
from tests.services.reports import test_report_i18n as rich

Numbers = dict[str, tuple[int | float | None, int | float | None]]

PINNED: dict[str, dict[str, Numbers]] = {
    "full": {
        "lateral_posture": {
            "assets_reachable": (1, None), "pivots": (1, None), "new_detections": (2, None),
            "cross_env": (3, None),
        },
        "new_connections": {
            "new": (39, None), "admin": (13, None), "critical": (0, None), "unmanaged_source": (3, None),
        },
        "unmanaged_endpoints": {
            "total": (2, None), "private": (1, None), "admin_sources": (1, None), "public": (1, None),
        },
        "traffic": {
            "flows": (37, None), "connections": (37, None), "sources": (36, None), "destinations": (25, None),
        },
        "security_risk": {
            "maturity": (66, None), "enforced_hosts_pct": (100.0, None), "allowed_pct": (94.6, None),
            "pb_flows": (1, None), "blocked_flows": (1, None), "unmanaged_connections": (2, None),
            "admin_open_connections": (5, None), "critical_high_findings": (12, None),
            "ransomware_protected_pct": (50.0, None), "lateral_detections": (2, None),
        },
        "network_inventory": {
            "managed_hosts": (3, None), "hosts_missing_labels": (3, None), "apps": (1, None),
            "cross_env_connections": (2, None),
        },
        "app_summary": {
            "inbound_connections": (36, None), "outbound_connections": (0, None), "intra_connections": (0, None),
            "allowed_pct": (94.4, None), "pb_flows": (1, None), "hosts": (0, None),
        },
        "ven_status": {
            "managed": (3, None), "online": (2, None), "lost_24h": (1, None), "lost_48h": (0, None),
            "long_offline": (0, None), "status_unknown": (0, None), "sync_problems": (2, None),
            "unexplained_tamper": (1, None),
        },
        "audit": {
            "total": (9, None), "high_risk": (1, None), "auth_failed": (5, None), "authz_denied": (0, None),
            "policy_provisions": (1, None), "draft_changes": (1, None), "agent_security": (1, None),
            "actors": (2, None), "source_ips": (1, None),
        },
        "ransomware": {
            "rated_hosts": (2, None), "org_percent": (12.5, None), "priority": (1, None),
            "safe_to_block": (1, None), "suspicious": (1, None), "contradictions": (1, None),
        },
        "readiness": {
            "apps": (2, None), "ready": (1, None), "held_back": (0, None), "overall": (71, None),
            "predicted_blocked": (7, None),
        },
        "policy_usage": {
            "rules": (None, None), "used": (None, None), "unused": (None, None), "disabled": (None, None),
            "deny_hit": (None, None), "no_rule": (None, None),
        },
        "rule_hit_count": {
            "rules": (4, None), "hit": (2, None), "zero": (1, None), "no_record": (2, None),
        },
        "policy_diff": {
            "total": (21, None), "high": (10, None), "rule_sets": (2, None), "rules": (1, None),
            "objects": (3, None), "other_pending": (1, None),
        },
        "policy_resolver": {
            "rulesets": (1, None), "rules": (1, None), "rows": (-2, None), "capped": (1, None),
            "omitted": (3, None), "not_expanded": (2, None), "no_address": (1, None),
        },
        "custom": {},
    },
    "bare": {
        "lateral_posture": {
            "new_detections": (0, None),
        },
        "new_connections": {
            "new": (39, None), "admin": (13, None), "critical": (0, None), "unmanaged_source": (3, None),
        },
        "unmanaged_endpoints": {
            "total": (2, None), "private": (1, None), "admin_sources": (1, None), "public": (1, None),
        },
        "traffic": {
            "flows": (37, None), "connections": (37, None), "sources": (36, None), "destinations": (25, None),
        },
        "security_risk": {
            "maturity": (68, None), "enforced_hosts_pct": (100.0, None), "allowed_pct": (94.6, None),
            "pb_flows": (1, None), "blocked_flows": (1, None), "unmanaged_connections": (2, None),
            "admin_open_connections": (5, None), "critical_high_findings": (11, None),
            "lateral_detections": (0, None),
        },
        "network_inventory": {
            "managed_hosts": (3, None), "hosts_missing_labels": (3, None), "apps": (1, None),
            "cross_env_connections": (2, None),
        },
        "app_summary": {
            "inbound_connections": (36, None), "outbound_connections": (0, None), "intra_connections": (0, None),
            "allowed_pct": (94.4, None), "pb_flows": (1, None), "hosts": (0, None),
        },
        "ven_status": {
            "managed": (3, None), "online": (2, None), "lost_24h": (1, None), "lost_48h": (0, None),
            "long_offline": (0, None), "status_unknown": (0, None), "sync_problems": (2, None),
        },
        "audit": {
            "total": (9, None), "high_risk": (1, None), "auth_failed": (5, None), "authz_denied": (0, None),
            "policy_provisions": (1, None), "draft_changes": (1, None), "agent_security": (1, None),
            "actors": (2, None), "source_ips": (1, None),
        },
        "ransomware": {
            "org_percent": (12.5, None),
        },
        "readiness": {
            "apps": (2, None), "ready": (1, None), "held_back": (0, None), "overall": (71, None),
            "predicted_blocked": (0, None),
        },
        "policy_usage": {
            "rules": (3, None), "used": (1, None), "unused": (1, None), "disabled": (1, None),
            "deny_hit": (1, None), "no_rule": (9, None),
        },
        "rule_hit_count": {
            "rules": (4, None), "hit": (2, None), "zero": (1, None), "no_record": (2, None),
        },
        "policy_diff": {
            "total": (21, None), "high": (10, None), "rule_sets": (2, None), "rules": (1, None),
            "objects": (3, None), "other_pending": (1, None),
        },
        "policy_resolver": {
            "rulesets": (1, None), "rules": (1, None), "rows": (1, None), "capped": (0, None),
            "omitted": (0, None), "not_expanded": (0, None), "no_address": (0, None),
        },
        "custom": {},
    },
}


def _numbers(ctx) -> tuple[dict[str, Numbers], dict[str, int]]:
    out: dict[str, Numbers] = {}
    counts: dict[str, int] = {}
    for rt in ReportType:
        cond = rich.APP_DB if specs()[rt].requires_app else None
        custom_id = rich._custom(ctx) if rt is ReportType.CUSTOM else None
        doc = finish(specs()[rt].build(BuildInput(
            ctx=ctx, params=ReportParams(report_type=rt, filter=cond, custom_id=custom_id), start=rich.START,
            end=rich.END, lang=Language.EN, tz=rich.UTC, now=rich.NOW, pce_label="pce")))
        out[rt.value] = {k.key: (k.value, k.previous) for k in doc.kpis}
        counts[rt.value] = len(doc.kpis)
    return out, counts


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Both installs, one after the other: each patches the same PCE-facing functions, so the first is torn down
    (its patches undone) before the second is set up."""
    got = {}
    for name, fixture in (("full", rich.ctx), ("bare", plain.bare)):
        gen = fixture.__wrapped__(tmp_path_factory)
        got[name] = _numbers(next(gen))
        assert next(gen, None) is None
    return got


def _typed(numbers: Numbers) -> dict[str, tuple[str, str]]:
    """1 and 1.0 are equal and print differently ('1' and '1.0'): the type is part of the number."""
    return {key: (repr(value), repr(previous)) for key, (value, previous) in numbers.items()}


@pytest.mark.parametrize("install", ["full", "bare"])
@pytest.mark.parametrize("rt", [t.value for t in ReportType])
def test_key_numbers_are_what_they_were(built, install, rt):
    numbers, counts = built[install]
    assert _typed(numbers[rt]) == _typed(PINNED[install][rt])
    assert counts[rt] == len(PINNED[install][rt]), "a key number is listed twice"
