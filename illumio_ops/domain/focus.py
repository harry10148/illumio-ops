"""The focus list (spec §6.5.4 現在該關注什麼): what the home page and every report e-mail open with.

Items are derived from the stored analysis results, never a mailbox: each says why it matters and where to
go next, and is ranked by severity x whether it touches a critical asset x whether it is new this week x
how much the data behind it can be trusted. The weights are the builder's (spec §10).

Builders take the results as stored (JSON-shaped mappings) and are pure.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from illumio_ops.domain.values import (
    Confidence,
    DetectorKind,
    FocusKind,
    Severity,
    raise_severity,
)

SEVERITY_POINTS: Mapping[Severity, int] = {Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 4, Severity.CRITICAL: 8}
CONFIDENCE_FACTOR: Mapping[Confidence, float] = {Confidence.HIGH: 1.0, Confidence.MEDIUM: 0.8, Confidence.LOW: 0.6}
CRITICAL_FACTOR = 1.5
NEW_FACTOR = 1.3
WEEK = timedelta(days=7)
LOW_COVERAGE_PERCENT = 20.0

Target = Literal["workbench", "lateral", "host", "settings_lateral", "settings_collection", "alerts", "system_jobs",
                 "system_pce"]


@dataclass(frozen=True)
class FocusAction:
    target: Target
    segment: Mapping[str, Any] | None = None  # a stored analysis segment (JSON) to open the workbench with
    host_key: str | None = None


@dataclass(frozen=True)
class FocusItem:
    kind: FocusKind
    fingerprint: str
    severity: Severity
    critical_asset: bool
    confidence: Confidence
    title_key: str
    why_key: str
    params: Mapping[str, Any]
    action: FocusAction


@dataclass(frozen=True)
class RankedItem:
    item: FocusItem
    score: float
    first_seen: datetime
    new_this_week: bool
    weeks_persisting: int


def score(item: FocusItem, *, new_this_week: bool) -> float:
    return (SEVERITY_POINTS[item.severity] * (CRITICAL_FACTOR if item.critical_asset else 1.0)
            * (NEW_FACTOR if new_this_week else 1.0) * CONFIDENCE_FACTOR[item.confidence])


def rank(items: Sequence[FocusItem], first_seen: Mapping[str, datetime], now: datetime) -> list[RankedItem]:
    out = []
    for it in items:
        seen = first_seen.get(it.fingerprint, now)
        new = now - seen < WEEK
        out.append(RankedItem(item=it, score=score(it, new_this_week=new), first_seen=seen, new_this_week=new,
                              weeks_persisting=int((now - seen) / WEEK)))
    return sorted(out, key=lambda r: (-r.score, r.item.kind.value, r.item.fingerprint))


DETECTION_TITLE_KEYS: Mapping[DetectorKind, str] = {
    DetectorKind.FANOUT: "focus_title_fanout", DetectorKind.NEW_ADMIN_CONNECTION: "focus_title_new_admin_connection",
    DetectorKind.PIVOT_CHAIN: "focus_title_pivot_chain", DetectorKind.BLOCKED_SURGE: "focus_title_blocked_surge",
    DetectorKind.NON_ADMIN_GROUP: "focus_title_non_admin_group", DetectorKind.CROSS_ENV: "focus_title_cross_env",
    DetectorKind.ACCOUNT_FANOUT: "focus_title_account_fanout",
    DetectorKind.UNEXPECTED_INITIATOR: "focus_title_unexpected_initiator",
    DetectorKind.PEER_DEVIATION: "focus_title_peer_deviation", DetectorKind.VOLUME_SURGE: "focus_title_volume_surge",
    DetectorKind.ACCOUNT_NEW_SOURCE: "focus_title_account_new_source",
    DetectorKind.SUSPICIOUS_TOOL: "focus_title_suspicious_tool", DetectorKind.NEW_PROCESS: "focus_title_new_process",
    DetectorKind.AUTH_TO_NON_DC: "focus_title_auth_to_non_dc", DetectorKind.NEW_DC_CLIENT: "focus_title_new_dc_client",
    DetectorKind.DIRECTORY_SURGE: "focus_title_directory_surge",
}
FOCUS_KEYS: Mapping[str, str] = {
    **{f"title_{k.value}": v for k, v in DETECTION_TITLE_KEYS.items()},
    "title_exposure_asset": "focus_title_exposure_asset", "title_pivot_host": "focus_title_pivot_host",
    "title_cross_env_edges": "focus_title_cross_env_edges", "title_tamper": "focus_title_tamper",
    "title_ransomware_priority": "focus_title_ransomware_priority",
    "title_vendor_contradiction": "focus_title_vendor_contradiction", "title_mode_switch": "focus_title_mode_switch",
    "title_data_coverage": "focus_title_data_coverage", "title_visibility": "focus_title_visibility",
    "title_collection_gap": "focus_title_collection_gap", "title_job_failing": "focus_title_job_failing",
    "title_pce_probe": "focus_title_pce_probe", "title_setup_critical": "focus_title_setup_critical",
    "title_setup_admin": "focus_title_setup_admin", "title_stale_selector": "focus_title_stale_selector",
    "title_events_only": "focus_title_events_only",
    "why_detection": "focus_why_detection", "why_exposure_asset": "focus_why_exposure_asset",
    "why_pivot": "focus_why_pivot", "why_cross_env": "focus_why_cross_env", "why_tamper_cycle": "focus_why_tamper_cycle",
    "why_tamper": "focus_why_tamper", "why_ransomware": "focus_why_ransomware",
    "why_contradiction": "focus_why_contradiction", "why_mode_switch": "focus_why_mode_switch",
    "why_coverage": "focus_why_coverage", "why_visibility": "focus_why_visibility", "why_gap": "focus_why_gap",
    "why_health": "focus_why_health", "why_setup": "focus_why_setup", "why_stale": "focus_why_stale",
    "why_events_only": "focus_why_events_only",
}


def _item(kind: FocusKind, fingerprint: str, severity: Severity, title: str, why: str, params: Mapping[str, Any],
          action: FocusAction, *, critical: bool = False, confidence: Confidence = Confidence.HIGH) -> FocusItem:
    return FocusItem(kind=kind, fingerprint=fingerprint, severity=severity, critical_asset=critical,
                     confidence=confidence, title_key=FOCUS_KEYS[title], why_key=FOCUS_KEYS[why], params=dict(params),
                     action=action)


def _confidence(conf: Mapping[str, Any]) -> Confidence:
    total, covered = conf.get("total"), conf.get("covered")
    if total and covered is not None and covered / total * 100 < LOW_COVERAGE_PERCENT:
        return Confidence.LOW
    return Confidence.MEDIUM if conf.get("incomplete_gaps") else Confidence.HIGH


def detection_items(detections: Sequence[Mapping[str, Any]], *, names: Mapping[str, str | None],
                    now: datetime) -> list[FocusItem]:
    """Detections seen in the last 7 days, each as one item opening its evidence in the workbench."""
    out = []
    for d in detections:
        if datetime.fromisoformat(str(d["last_seen"])) < now - WEEK:
            continue
        kind = DetectorKind(d["detector"])
        summary = dict(d.get("summary") or {})
        subject = str(d["subject_key"])
        params = {**summary, "host": names.get(subject) or subject, "account": subject,
                  "minutes": summary.get("window_minutes")}
        out.append(FocusItem(
            kind=FocusKind.DETECTION, fingerprint=f"det|{d['fingerprint']}", severity=Severity(d["severity"]),
            critical_asset=bool(d.get("critical_asset")), confidence=_confidence(d.get("confidence") or {}),
            title_key=DETECTION_TITLE_KEYS[kind], why_key=FOCUS_KEYS["why_detection"], params=params,
            action=FocusAction(target="workbench", segment=d.get("segment"))))
    return out


def exposure_items(exposure: Mapping[str, Any], *, names: Mapping[str, str | None],
                   baseline_full: bool) -> list[FocusItem]:
    confidence = Confidence.HIGH if baseline_full else Confidence.MEDIUM
    hops = exposure.get("hops")
    out = []
    for a in exposure.get("assets") or ():
        n = int(a.get("sources_now") or 0)
        if not n:
            continue
        severity = Severity.HIGH if n >= 20 else Severity.MEDIUM if n >= 5 else Severity.LOW
        out.append(_item(FocusKind.EXPOSURE_ASSET, f"asset|{a['key']}", severity, "title_exposure_asset",
                         "why_exposure_asset", {"asset": names.get(a["key"]) or a["key"], "sources": n, "hops": hops},
                         FocusAction(target="lateral", host_key=a["key"]), critical=True, confidence=confidence))
    pivots = sorted((h for h in exposure.get("hosts") or () if h.get("pivot_now")),
                    key=lambda h: (-int(h.get("reach_now") or 0), str(h["key"])))[:5]
    for h in pivots:
        out.append(_item(FocusKind.PIVOT_HOST, f"pivot|{h['key']}", Severity.MEDIUM, "title_pivot_host", "why_pivot",
                         {"host": names.get(h["key"]) or h["key"]}, FocusAction(target="lateral", host_key=h["key"]),
                         confidence=confidence))
    crossing = list(exposure.get("cross_env") or ())
    if crossing:
        allowed = any(e.get("state") == "allowed" for e in crossing)  # listed first, so the cap never hides one
        out.append(_item(FocusKind.CROSS_ENV, "xenv", Severity.HIGH if allowed else Severity.MEDIUM,
                         "title_cross_env_edges", "why_cross_env",
                         {"count": int(exposure.get("cross_env_total") or len(crossing))},
                         FocusAction(target="lateral"), confidence=confidence))
    return out


def tamper_items(hosts: Sequence[Mapping[str, Any]]) -> list[FocusItem]:
    """Hosts with tampering no known cause explains in the last 7 days."""
    out = []
    for h in hosts:
        if not h.get("unexplained_7d"):
            continue
        pattern = str(h.get("pattern"))
        severity = Severity.HIGH if pattern == "burst" else Severity.MEDIUM
        if h.get("has_signal"):
            severity = raise_severity(severity)
        out.append(_item(FocusKind.TAMPER, f"tamper|{h['href']}", severity, "title_tamper",
                         "why_tamper_cycle" if pattern == "regular_cycle" else "why_tamper",
                         {"host": h.get("hostname") or h["href"], "count": h.get("unexplained_7d"), "pattern": pattern},
                         FocusAction(target="host", host_key=str(h["href"]))))
    return out


def ransomware_items(overlay: Mapping[str, Any]) -> list[FocusItem]:
    """Unprotected high-risk services that are listening and in use (spec §6.5.6, the first class)."""
    out = []
    for s in overlay.get("priority") or ():
        sev = str(s.get("severity") or "").lower()
        severity = Severity(sev) if sev in ("critical", "high") else Severity.MEDIUM
        out.append(_item(FocusKind.RANSOMWARE_PRIORITY, f"rw|{s['host']}|{s['port']}", severity,
                         "title_ransomware_priority", "why_ransomware",
                         {"host": s.get("hostname") or s["host"], "service": s.get("name"), "port": s.get("port")},
                         FocusAction(target="host", host_key=str(s["host"]))))
    return out


def contradiction_item(count: int) -> list[FocusItem]:
    """Low on purpose: it says which numbers not to rank by; it does not reorder anything."""
    if not count:
        return []
    return [_item(FocusKind.VENDOR_CONTRADICTION, "rw-contradiction", Severity.LOW, "title_vendor_contradiction",
                  "why_contradiction", {"count": count}, FocusAction(target="lateral"))]


def mode_switch_item(*, hosts: int, connections: int, truncated: bool) -> list[FocusItem]:
    if not hosts:
        return []
    return [_item(FocusKind.MODE_SWITCH_BLOCKER, "mode-switch", Severity.MEDIUM, "title_mode_switch", "why_mode_switch",
                  {"hosts": hosts, "connections": connections, "truncated": truncated}, FocusAction(target="workbench"))]


def coverage_item(*, total: int, process: int, user: int) -> list[FocusItem]:
    if not total:
        return []
    percent = round(min(process, user) / total * 100, 1)
    if percent >= LOW_COVERAGE_PERCENT:
        return []
    return [_item(FocusKind.DATA_COVERAGE, "coverage", Severity.LOW, "title_data_coverage", "why_coverage",
                  {"percent": percent}, FocusAction(target="settings_collection"))]


def visibility_item(hosts: Sequence[str]) -> list[FocusItem]:
    if not hosts:
        return []
    return [_item(FocusKind.VISIBILITY, "visibility", Severity.MEDIUM, "title_visibility", "why_visibility",
                  {"count": len(hosts)}, FocusAction(target="settings_collection"))]


def gap_item(*, failed: int, truncated: int) -> list[FocusItem]:
    if not failed and not truncated:
        return []
    return [_item(FocusKind.COLLECTION_GAP, "gaps", Severity.HIGH if failed else Severity.MEDIUM,
                  "title_collection_gap", "why_gap", {"count": failed + truncated},
                  FocusAction(target="settings_collection"))]


def health_items(*, failing_jobs: Sequence[str], probe_ok: bool | None) -> list[FocusItem]:
    out = [_item(FocusKind.SYSTEM_HEALTH, f"job|{j}", Severity.HIGH, "title_job_failing", "why_health", {"job": j},
                 FocusAction(target="system_jobs")) for j in failing_jobs]
    if probe_ok is False:
        out.append(_item(FocusKind.SYSTEM_HEALTH, "pce-probe", Severity.HIGH, "title_pce_probe", "why_health", {},
                         FocusAction(target="system_pce")))
    return out


def setup_items(*, critical_set: bool, admin_set: bool, stale: Sequence[tuple[str, str, str]],
                collected: bool) -> list[FocusItem]:
    """What the analysis needs from the operator. Without traffic collection only that is said: nothing else on
    the lateral side can be found."""
    if not collected:
        return [_item(FocusKind.SETUP_REQUIRED, "events-only", Severity.LOW, "title_events_only", "why_events_only", {},
                      FocusAction(target="settings_collection"))]
    out = []
    if not critical_set:
        out.append(_item(FocusKind.SETUP_REQUIRED, "setup|critical", Severity.LOW, "title_setup_critical", "why_setup",
                         {}, FocusAction(target="settings_lateral")))
    if not admin_set:
        out.append(_item(FocusKind.SETUP_REQUIRED, "setup|admin", Severity.LOW, "title_setup_admin", "why_setup", {},
                         FocusAction(target="settings_lateral")))
    out += [_item(FocusKind.STALE_SELECTOR, f"stale|{s}|{k}|{v}", Severity.MEDIUM, "title_stale_selector", "why_stale",
                  {"setting": s, "key": k, "value": v}, FocusAction(target="settings_lateral")) for s, k, v in stale]
    return out


def item_json(r: RankedItem) -> dict[str, Any]:
    it = r.item
    return {"kind": it.kind.value, "fingerprint": it.fingerprint, "severity": it.severity.value,
            "critical_asset": it.critical_asset, "confidence": it.confidence.value, "title_key": it.title_key,
            "why_key": it.why_key, "params": dict(it.params),
            "action": {"target": it.action.target, "segment": it.action.segment, "host_key": it.action.host_key},
            "score": round(r.score, 3), "first_seen": r.first_seen.isoformat(), "new_this_week": r.new_this_week,
            "weeks_persisting": r.weeks_persisting}



