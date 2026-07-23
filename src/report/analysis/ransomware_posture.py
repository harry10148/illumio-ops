"""Pure analysis: ransomware exposure & high-risk open ports from PCE-native data.

Joins per-workload ``risk_details.ransomware.details[]`` (which risky service
port is listening + its protection state) with ``services.open_service_ports[]``
(which process is listening) on ``(port, proto)``. No I/O — all data is supplied
by the caller (see ``ransomware_posture_enrichment``).
"""
from __future__ import annotations

import os

_PROTO_NAMES: dict[int, str] = {6: "TCP", 17: "UDP"}
_SEVERITY_RANK: dict[str, int] = {
    "critical": 0, "high": 1, "medium": 2, "low": 3, "fully_protected": 4,
}
_EXPOSURE_LEVELS = ("critical", "high", "medium", "low", "fully_protected")


def _proto_name(proto) -> str:
    try:
        return _PROTO_NAMES.get(int(proto), str(proto))
    except (TypeError, ValueError):
        return str(proto)


def _process_label(osp_entry: dict) -> tuple[str, str]:
    """Return (short_label, full_path). Windows -> win_service_name; else basename."""
    win = (osp_entry.get("win_service_name") or "").strip()
    full = (osp_entry.get("process_name") or "").strip()
    if win:
        return win, full
    if full:
        return os.path.basename(full.replace("\\", "/")), full
    return "", ""


def _ransomware(workload: dict) -> "dict | None":
    rs = workload.get("risk_summary")
    if not isinstance(rs, dict):
        return None
    rw = rs.get("ransomware")
    return rw if isinstance(rw, dict) else None


def ransomware_posture(workloads: list[dict], enrichment: dict) -> dict:
    """Build KPI, per-VEN rows, and high-risk open-port rows.

    Args:
        workloads: managed-workload dicts; each may carry
            ``risk_summary.ransomware`` {workload_exposure_severity,
            ransomware_protection_percent}.
        enrichment: ``{href: {"open_service_ports": [...], "details": [...]}}``
            where ``details`` is ``risk_details.ransomware.details``.

    Returns:
        ``{"kpi": {...}, "per_ven": [...], "ports": [...]}``; well-formed even
        when no workload has computed ransomware data.
    """
    by_exposure = {lvl: 0 for lvl in _EXPOSURE_LEVELS}
    computed = pending = 0
    cov_sum = 0.0
    per_ven: list[dict] = []
    ports: list[dict] = []

    for wl in workloads:
        rw = _ransomware(wl)
        if rw is None:
            pending += 1
            continue
        computed += 1
        sev = rw.get("workload_exposure_severity") or ""
        if sev in by_exposure:
            by_exposure[sev] += 1
        try:
            pct = float(rw.get("ransomware_protection_percent") or 0.0)
        except (TypeError, ValueError):
            pct = 0.0
        cov_sum += pct

        href = wl.get("href", "")
        host = str(wl.get("hostname") or href)
        enr = enrichment.get(href) or {}

        osp_idx: dict[tuple, dict] = {}
        for e in (enr.get("open_service_ports") or []):
            if not isinstance(e, dict):
                continue
            try:
                osp_idx.setdefault((int(e["port"]), int(e["protocol"])), e)
            except (KeyError, TypeError, ValueError):
                continue

        open_risky = 0
        for d in (enr.get("details") or []):
            if not isinstance(d, dict) or d.get("port_status") != "listening":
                continue
            open_risky += 1
            try:
                key = (int(d.get("port")), int(d.get("proto")))
            except (TypeError, ValueError):
                key = (d.get("port"), d.get("proto"))
            match = osp_idx.get(key, {})
            label, full = _process_label(match)
            ports.append({
                "hostname": host,
                "port": d.get("port"),
                "proto": _proto_name(d.get("proto")),
                "service": d.get("name") or "",
                "severity": d.get("severity") or "",
                "protection_state": d.get("protection_state") or "",
                "process": label,
                "process_full": full,
                "user": (match.get("user") or "") if isinstance(match, dict) else "",
            })

        per_ven.append({
            "hostname": host,
            "severity": sev,
            "protection_percent": round(pct, 1),
            "open_risky_count": open_risky,
            # enrichment 失敗時 open_risky_count=0 是「不知道」不是「乾淨」，
            # 由 exporter 顯示為資料不可得
            "enrichment_error": bool(enr.get("enrichment_error")),
        })

    per_ven.sort(key=lambda r: (_SEVERITY_RANK.get(r["severity"], 9), -r["open_risky_count"]))
    ports.sort(key=lambda r: (r["hostname"], _SEVERITY_RANK.get(r["severity"], 9)))

    return {
        "kpi": {
            "by_exposure": by_exposure,
            "computed": computed,
            "pending": pending,
            "avg_protection_percent": round(cov_sum / computed, 1) if computed else 0.0,
        },
        "per_ven": per_ven,
        "ports": ports,
    }
