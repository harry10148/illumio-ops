"""How endpoints, processes and accounts are named consistently across PCE records."""
from __future__ import annotations

import re

_PATH_SEP = re.compile(r"[\\/]")

# Accounts that run services rather than people; matched on the lower-cased full name.
SYSTEM_ACCOUNTS: frozenset[str] = frozenset({
    "nt authority\\system",
    "nt authority\\local service",
    "nt authority\\network service",
    "system",
    "root",
    "daemon",
    "nobody",
})
_SYSTEM_PREFIXES: tuple[str, ...] = ("systemd-", "_")  # systemd-timesync, macOS _trustd / _apt


def endpoint_key(href: str | None, ip: str) -> str:
    """A workload (managed or not) by its href, a bare address as ip:<address>."""
    return href if href else f"ip:{ip}"


def normalize_process(name: str | None) -> str | None:
    """Drop the directory part; Windows names (.exe, or given with a backslash path) are
    case-insensitive and lower-cased, Linux names keep their case."""
    if not name:
        return None
    base = _PATH_SEP.split(name)[-1]
    if not base:
        return None
    if base.lower().endswith(".exe") or "\\" in name:
        return base.lower()
    return base


def split_user(name: str | None) -> tuple[str | None, str | None]:
    """(domain, account): DOMAIN\\acct, acct@domain, or a bare local account."""
    if not name:
        return None, None
    if "\\" in name:
        domain, _, account = name.rpartition("\\")
        return domain or None, account or None
    if "@" in name:
        account, _, domain = name.partition("@")
        return domain or None, account or None
    return None, name


def is_system_account(user: str | None) -> bool:
    if not user:
        return False
    low = user.lower()
    if low in SYSTEM_ACCOUNTS:
        return True
    account = split_user(low)[1] or ""
    return any(account.startswith(p) for p in _SYSTEM_PREFIXES)
