"""Passwords created via PBKDF2 must still verify, and should silently
upgrade to argon2id on first successful verify."""
import pytest


def test_argon2_hash_starts_with_prefix():
    from src.config import hash_password_argon2
    h = hash_password_argon2("password123")
    assert h.startswith("argon2:"), f"expected argon2: prefix, got {h[:20]}"


def test_argon2_verify_round_trip():
    from src.config import hash_password_argon2, verify_password
    h = hash_password_argon2("password123")
    # argon2 hash has no separate salt column (embedded)
    assert verify_password(h, salt="", password="password123")
    assert not verify_password(h, salt="", password="wrong")


def test_pbkdf2_hash_still_verifies():
    """Legacy PBKDF2 hashes keep working."""
    from src.config import hash_password, verify_password
    salt = "abc123"
    h = hash_password(salt, "legacy_pw")
    assert verify_password(h, salt=salt, password="legacy_pw")


def test_verify_password_returns_needs_upgrade_flag_for_pbkdf2():
    """After a successful PBKDF2 verify, the caller can request a rehash."""
    from src.config import hash_password, verify_and_upgrade_password
    salt = "abc123"
    h = hash_password(salt, "legacy_pw")
    ok, new_hash = verify_and_upgrade_password(h, salt=salt, password="legacy_pw")
    assert ok is True
    assert new_hash is not None    # upgrade emitted
    assert new_hash.startswith("argon2:")


def test_verify_and_upgrade_password_on_argon2_returns_none_upgrade():
    """Already-argon2 hashes don't emit a new one."""
    from src.config import hash_password_argon2, verify_and_upgrade_password
    h = hash_password_argon2("pw")
    ok, new_hash = verify_and_upgrade_password(h, salt="", password="pw")
    assert ok is True
    assert new_hash is None    # no upgrade needed
