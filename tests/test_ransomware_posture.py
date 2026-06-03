"""Tests for ransomware_posture pure analysis."""
from src.report.analysis.ransomware_posture import ransomware_posture


def _wl(href, host, sev, pct):
    return {"href": href, "hostname": host,
            "risk_summary": {"ransomware": {"workload_exposure_severity": sev,
                                            "ransomware_protection_percent": pct}}}


WORKLOADS = [
    _wl("/w/dc", "dc", "critical", 0.0),
    _wl("/w/web", "web", "high", 50.0),
    # pending: no risk_summary.ransomware
    {"href": "/w/new", "hostname": "new", "risk_summary": {"ransomware": None}},
]

ENRICH = {
    "/w/dc": {
        "open_service_ports": [
            {"port": 3389, "protocol": 6, "process_name": r"C:\Windows\System32\svchost.exe",
             "win_service_name": "TermService", "user": "SYSTEM"},
            {"port": 22, "protocol": 6, "process_name": "/usr/sbin/sshd", "user": "root"},
        ],
        "details": [
            {"port": 3389, "proto": 6, "name": "S-RDP", "severity": "critical",
             "port_status": "listening", "protection_state": "unprotected"},
            {"port": 23, "proto": 6, "name": "S-TELNET", "severity": "medium",
             "port_status": "inactive", "protection_state": "unprotected"},
        ],
    },
    "/w/web": {
        "open_service_ports": [
            {"port": 22, "protocol": 6, "process_name": "/usr/sbin/sshd", "user": "root"},
        ],
        "details": [
            {"port": 22, "proto": 6, "name": "S-SSH", "severity": "high",
             "port_status": "listening", "protection_state": "protected_open"},
        ],
    },
}


def test_kpi_counts_and_pending():
    out = ransomware_posture(WORKLOADS, ENRICH)
    assert out["kpi"]["by_exposure"]["critical"] == 1
    assert out["kpi"]["by_exposure"]["high"] == 1
    assert out["kpi"]["computed"] == 2
    assert out["kpi"]["pending"] == 1
    assert out["kpi"]["avg_protection_percent"] == 25.0


def test_listening_filter_counts_open_ports():
    out = ransomware_posture(WORKLOADS, ENRICH)
    by_host = {r["hostname"]: r for r in out["per_ven"]}
    assert by_host["dc"]["open_risky_count"] == 1
    assert by_host["web"]["open_risky_count"] == 1


def test_process_label_windows_uses_service_name():
    out = ransomware_posture(WORKLOADS, ENRICH)
    rdp = next(p for p in out["ports"] if p["hostname"] == "dc" and p["port"] == 3389)
    assert rdp["process"] == "TermService"
    assert rdp["process_full"] == r"C:\Windows\System32\svchost.exe"
    assert rdp["user"] == "SYSTEM"
    assert rdp["proto"] == "TCP"


def test_process_label_linux_uses_basename():
    out = ransomware_posture(WORKLOADS, ENRICH)
    ssh = next(p for p in out["ports"] if p["hostname"] == "web" and p["port"] == 22)
    assert ssh["process"] == "sshd"
    assert ssh["protection_state"] == "protected_open"


def test_inactive_ports_excluded_from_detail():
    out = ransomware_posture(WORKLOADS, ENRICH)
    assert not any(p["service"] == "S-TELNET" for p in out["ports"])


def test_per_ven_sorted_by_severity_then_count():
    out = ransomware_posture(WORKLOADS, ENRICH)
    assert [r["hostname"] for r in out["per_ven"]] == ["dc", "web"]


def test_join_miss_yields_dash_process():
    wl = [_wl("/w/x", "x", "critical", 0.0)]
    enr = {"/w/x": {"open_service_ports": [],
                    "details": [{"port": 445, "proto": 6, "name": "S-SMB",
                                 "severity": "critical", "port_status": "listening",
                                 "protection_state": "unprotected"}]}}
    out = ransomware_posture(wl, enr)
    smb = out["ports"][0]
    assert smb["process"] == ""
    assert smb["user"] == ""


def test_empty_inputs_well_formed():
    out = ransomware_posture([], {})
    assert out["per_ven"] == [] and out["ports"] == []
    assert out["kpi"]["computed"] == 0 and out["kpi"]["pending"] == 0
