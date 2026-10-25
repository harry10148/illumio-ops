import pytest

from illumio_ops.domain.identity import (
    endpoint_key,
    is_system_account,
    normalize_process,
    split_user,
)
from illumio_ops.domain.values import visibility_sees_allowed


def test_endpoint_key_prefers_href():
    assert endpoint_key("/orgs/1/workloads/abc", "10.0.0.1") == "/orgs/1/workloads/abc"
    assert endpoint_key(None, "10.0.0.1") == "ip:10.0.0.1"


@pytest.mark.parametrize("raw,expected", [
    (r"C:\Windows\System32\svchost.exe", "svchost.exe"),
    ("SvcHost.EXE", "svchost.exe"),
    ("/usr/sbin/sshd", "sshd"),
    ("MySQLd", "MySQLd"),          # Linux names are case-sensitive
    ("", None),
    (None, None),
])
def test_normalize_process_strips_path_and_lowercases_windows(raw, expected):
    assert normalize_process(raw) == expected


def test_split_user_three_forms():
    assert split_user("LAB\\Administrator") == ("LAB", "Administrator")
    assert split_user("alice@corp.example") == ("corp.example", "alice")
    assert split_user("root") == (None, "root")
    assert split_user(None) == (None, None)
    assert split_user("") == (None, None)


@pytest.mark.parametrize("user,expected", [
    ("NT AUTHORITY\\SYSTEM", True), ("nt authority\\network service", True), ("root", True),
    ("systemd-timesync", True), ("LAB\\Administrator", False), ("alice", False), (None, False),
])
def test_is_system_account(user, expected):
    assert is_system_account(user) is expected


@pytest.mark.parametrize("level,expected", [
    ("flow_summary", True), ("enhanced_data_collection", True), ("flow_drops", False), ("flow_off", False),
    ("something_new", None), (None, None),
])
def test_visibility_sees_allowed_table(level, expected):
    assert visibility_sees_allowed(level) is expected


@pytest.mark.parametrize("user", ["CORP\\_svc-backup", "CORP\\systemd-admin", "_svc@corp.example", "CORP\\root"])
def test_a_domain_account_is_never_taken_for_a_system_one(user):
    # The local-account heuristics (a leading "_", "systemd-", "root") must not exempt domain accounts: anyone
    # able to name a domain account would otherwise hide it from the account fan-out detector.
    assert is_system_account(user) is False
