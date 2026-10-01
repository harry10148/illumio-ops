import configparser
from pathlib import Path

UNIT_PATH = Path(__file__).parent.parent / "deploy" / "illumio-ops.service"


def _parse_unit():
    cp = configparser.RawConfigParser(strict=False)
    cp.optionxform = str  # preserve case
    cp.read(UNIT_PATH)
    return cp


def test_unit_runs_as_system_user():
    cp = _parse_unit()
    assert cp["Service"]["User"] == "illumio-ops"
    assert cp["Service"]["Group"] == "illumio-ops"


def test_unit_has_hardening_directives():
    cp = _parse_unit()
    s = cp["Service"]
    assert s["NoNewPrivileges"] == "true"
    assert s["ProtectSystem"] == "strict"
    assert s["ProtectHome"] == "true"
    assert s["PrivateTmp"] == "true"
    assert s["RestrictAddressFamilies"] == "AF_INET AF_INET6 AF_UNIX"
    assert s["SystemCallFilter"] == "@system-service"
    # MemoryDenyWriteExecute is intentionally omitted: CPython 3.12's allocator
    # uses mprotect(PROT_WRITE|PROT_EXEC) during thread init on RHEL/Rocky 9,
    # which this directive would break ("can't start new thread"). See unit file.
    assert "MemoryDenyWriteExecute" not in s
    assert s["LockPersonality"] == "true"
    assert s["ProtectKernelTunables"] == "true"
    assert s["ProtectControlGroups"] == "true"
    assert s["RestrictSUIDSGID"] == "true"
    assert s["RestrictNamespaces"] == "true"
    assert s["CapabilityBoundingSet"] == ""  # drop all caps


def test_unit_restart_policy():
    # always 而非 on-failure：長駐服務任何非預期結束（包含以 0 結束，例如舊版
    # Web GUI 啟動失敗時）都要重啟；systemctl stop 不會觸發重啟。
    cp = _parse_unit()
    assert cp["Service"]["Restart"] == "always"
    assert int(cp["Service"]["RestartSec"]) >= 5
