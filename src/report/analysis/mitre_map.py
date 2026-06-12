"""Static MITRE ATT&CK technique mapping for built-in findings rules.

Pure data. Governance / coverage / draft-policy-hygiene rules intentionally
map to () — forcing a technique onto them would mislead SOC readers.
Update alongside rules_engine when rules change.

Grounded against the actual rule semantics in src/report/rules_engine.py
(B-series, L-series) and src/report/rules/ (R-series), not the plan's guess.
Unmapped (governance): B005 Low Policy Coverage, B009 Cross-Env Flow Volume
(INFO/Policy), L008 Lateral Ports in Test Mode (enforcement-gap), and all
R01-R05 DraftPolicy rules.
"""
from __future__ import annotations

RULE_TECHNIQUES: dict[str, tuple[tuple[str, str], ...]] = {
    # B-series — ransomware / unmanaged / behavioral
    # B001/B002/B003 flag ransomware-risk ports (impact + the remote-access
    # tooling attackers use to deploy it).
    "B001": (("T1486", "Data Encrypted for Impact"), ("T1021.002", "SMB/Windows Admin Shares")),
    "B002": (("T1486", "Data Encrypted for Impact"), ("T1219", "Remote Access Software")),
    "B003": (("T1486", "Data Encrypted for Impact"),),
    # B004 Unmanaged Source High Activity — one unmanaged host fanning out to
    # many destinations = network/service scanning.
    "B004": (("T1046", "Network Service Discovery"),),
    # B005 Low Policy Coverage — governance, unmapped.
    # B006 High Lateral Movement — fan-out on SMB/RDP/WinRM/RPC lateral ports.
    "B006": (("T1021", "Remote Services"),),
    # B007 Single User High Destinations — one account reaching abnormally many
    # hosts = valid-account abuse.
    "B007": (("T1078", "Valid Accounts"),),
    # B008 High Bandwidth Anomaly — outsized data volume on flows.
    "B008": (("T1048", "Exfiltration Over Alternative Protocol"),),
    # B009 Cross-Env Flow Volume — INFO/Policy informational metric, unmapped.

    # L-series — lateral movement family
    # L001 Cleartext Protocol (Telnet/FTP) — credential capture via MITM/sniffing.
    "L001": (("T1040", "Network Sniffing"),),
    # L002 Network Discovery Protocol Exposure — NetBIOS/mDNS/LLMNR/SSDP
    # Responder-style name-resolution poisoning to harvest NTLMv2 hashes.
    "L002": (("T1557.001", "LLMNR/NBT-NS Poisoning and SMB Relay"),),
    # L003 Database Port Wide Exposure — broad DB reachability enables remote-service exploitation.
    "L003": (("T1210", "Exploitation of Remote Services"),),
    # L004 Cross-Environment Database Access — Dev→Prod DB pivot (NOT identity;
    # the plan mislabeled this as Kerberos).
    "L004": (("T1210", "Exploitation of Remote Services"),),
    # L005 Identity Infrastructure Wide Exposure — Kerberos/LDAP/GC exposure =
    # Golden/Silver ticket / AD attack surface.
    "L005": (("T1558", "Steal or Forge Kerberos Tickets"),),
    # L006 High Blast-Radius Lateral Movement Path — graph reachability on lateral ports.
    "L006": (("T1021", "Remote Services"),),
    # L007 Unmanaged Host Accessing Critical Services — unmanaged → DB/identity/WinRM.
    "L007": (("T1210", "Exploitation of Remote Services"),),
    # L008 Lateral Ports in Test Mode (PB) — enforcement-gap governance, unmapped.
    # L009 Data Exfiltration Pattern (Outbound to Unmanaged) — managed → external bulk transfer.
    "L009": (("T1048", "Exfiltration Over Alternative Protocol"),),
    # L010 Cross-Environment Lateral Port Access — SMB/RDP/WinRM/RPC across env boundary.
    "L010": (("T1021", "Remote Services"), ("T1570", "Lateral Tool Transfer")),

    # R-series (R01-R05) — DraftPolicy hygiene/governance, all intentionally unmapped.
}


def techniques_for(rule_id: str) -> tuple[tuple[str, str], ...]:
    return RULE_TECHNIQUES.get(rule_id, ())
