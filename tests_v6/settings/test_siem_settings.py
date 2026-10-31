"""SIEM settings (schema 9, P7 Task 3): destinations, the HEC token as a secret, the upgrade from schema 8."""
import json

import pytest

from illumio_ops.settings.schema import default_settings
from illumio_ops.settings.secrets import (
    MASK,
    CredentialsRequired,
    merge_siem_destinations,
    redact,
)
from illumio_ops.settings.store import SettingsInvalid, SettingsStore, validate_settings

from .conftest import HASH, KEY

ID = "0123456789abcdef0123456789abcdef"


def dest(**kw):
    base = {"id": ID, "name": "graylog", "enabled": True, "transport": "tcp", "format": "cef_pce",
            "host": "siem.example", "port": 5514, "framing": "lf", "verify_tls": True, "hec_token": "",
            "batch_size": 100, "max_retries": 10, "sources": ["audit"], "new_connection_decisions": [], "new_connection_internal_only": True,
            "mask_pii": False}
    base.update(kw)
    return base


def settings_with(*dests, **siem):
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["siem"].update({"destinations": list(dests), **siem})
    return d


def test_a_fresh_install_forwards_nothing():
    s = default_settings(password_hash=HASH, secret_key=KEY).siem
    assert not s.enabled and s.destinations == () and s.dlq_max_per_dest == 10_000
    assert s.tick_seconds == 30 and s.backlog_warn_rows == 50_000


def test_a_schema_8_file_loads_with_siem_off(tmp_path):
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 8
    del d["siem"]
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(d))
    p.chmod(0o600)
    s = SettingsStore(p).load()
    assert s.schema_version == 11 and not s.siem.enabled and s.siem.destinations == ()


def test_a_complete_destination_is_valid():
    s = validate_settings(settings_with(dest()))
    assert s.siem.destinations[0].sources[0].value == "audit"


@pytest.mark.parametrize(("change", "field"), [
    ({"transport": "hec", "hec_token": ""}, "hec_token"),
    ({"host": ""}, "host"),
    ({"host": "https://siem.example"}, "host"),
    ({"sources": []}, "sources"),
    ({"sources": ["audit", "audit"]}, "sources"),
    ({"verify_tls": "relative/ca.pem"}, "verify_tls"),
    ({"max_retries": 0}, "max_retries"),
    ({"new_connection_decisions": ["allowed", "allowed"]}, "new_connection_decisions"),
    ({"hec_token": "a\nb"}, "hec_token"),
])
def test_an_incomplete_or_wrong_destination_is_refused(change, field):
    with pytest.raises(SettingsInvalid) as e:
        validate_settings(settings_with(dest(**change)))
    assert any(field in str(loc) or field in msg for loc, msg in e.value.errors), e.value.errors


def test_a_disabled_destination_may_be_incomplete():
    validate_settings(settings_with(dest(enabled=False, host="", transport="hec", hec_token="")))


def test_names_and_ids_are_unique():
    with pytest.raises(SettingsInvalid):
        validate_settings(settings_with(dest(), dest(id="f" * 32)))  # same name
    with pytest.raises(SettingsInvalid):
        validate_settings(settings_with(dest(), dest(name="other")))  # same id


def test_redact_hides_every_hec_token():
    s = validate_settings(settings_with(dest(transport="hec", hec_token="tok-1"),
                                        dest(id="f" * 32, name="b", transport="udp", hec_token="")))
    r = redact(s)
    assert [d["hec_token"] for d in r["siem"]["destinations"]] == [MASK, ""]
    assert "tok-1" not in json.dumps(r)


def test_a_masked_token_keeps_the_saved_one_while_the_destination_stays():
    saved = validate_settings(settings_with(dest(transport="hec", hec_token="tok-1"))).siem
    out = merge_siem_destinations(saved, [dest(transport="hec", hec_token=MASK, name="renamed")], mask=MASK)
    assert out[0]["hec_token"] == "tok-1" and out[0]["name"] == "renamed"


def test_a_kept_token_may_not_follow_the_destination_elsewhere():
    """Anyone holding a session could otherwise point the saved token at their own server (the SMTP rule)."""
    saved = validate_settings(settings_with(dest(transport="hec", hec_token="tok-1"))).siem
    with pytest.raises(CredentialsRequired):
        merge_siem_destinations(saved, [dest(transport="hec", hec_token=MASK, host="evil.example")], mask=MASK)


def test_a_new_destination_gets_no_saved_token():
    saved = validate_settings(settings_with(dest(transport="hec", hec_token="tok-1"))).siem
    out = merge_siem_destinations(saved, [dest(id="f" * 32, transport="hec", hec_token=MASK)], mask=MASK)
    assert out[0]["hec_token"] == ""


def test_a_kept_token_may_not_lose_tls_verification():
    saved = validate_settings(settings_with(dest(transport="hec", hec_token="tok-1"))).siem
    with pytest.raises(CredentialsRequired):
        merge_siem_destinations(saved, [dest(transport="hec", hec_token=MASK, verify_tls=False)], mask=MASK)
