import pytest
from pydantic import ValidationError

from illumio_ops.domain.values import DeploymentType, Language
from illumio_ops.settings.schema import PceSettings, Settings, default_settings
from illumio_ops.settings.secrets import MASK, SECRET_FIELDS, redact

from .conftest import HASH, KEY


def _pce(**kw):
    base = {"url": "https://pce.example.com:8443", "org_id": "1", "api_key": "k", "api_secret": "s",
            "deployment_type": "on_prem", "console_url": None, "verify_tls": True,
            "events_timeout_seconds": None}
    return PceSettings(**(base | kw))


def test_default_settings_values():
    s = default_settings(password_hash=HASH, secret_key=KEY, port=5443)
    assert s.schema_version == 6 and s.revision == 0
    assert s.pce.url == "" and s.pce.deployment_type is DeploymentType.ON_PREM
    assert s.web.port == 5443 and s.web.username == "illumio" and s.web.must_change_password is False
    assert s.web.session_lifetime_seconds == 28800 and s.web.allowed_ips == ()
    assert s.web.tls.validity_days == 397 and s.web.tls.auto_renew_days == 30
    assert s.web.tls.key_algorithm == "ecdsa-p256" and s.web.tls.min_version == "TLSv1.2"
    assert s.display.language is Language.EN and s.display.timezone == "local"
    assert s.logging.level == "INFO"
    c = s.collection
    assert c.enabled is True and c.traffic_interval_seconds == 600 and c.events_interval_seconds == 300
    assert c.inventory_interval_seconds == 3600 and c.rate_limit_per_minute == 400
    assert c.backfill_days == 30 and c.disk_free_warn_gb == 10
    assert (c.retention.flow_days, c.retention.event_days, c.retention.rollup_days, c.retention.baseline_days) == (35, 90, 90, 30)
    assert c.archive.enabled is False and c.archive.retention_days == 0


def test_verify_tls_accepts_ca_bundle_path():
    assert _pce(verify_tls="/etc/pki/ca.pem").verify_tls == "/etc/pki/ca.pem"
    assert _pce(verify_tls=False).verify_tls is False


def test_verify_tls_rejects_relative_path():
    with pytest.raises(ValidationError):
        _pce(verify_tls="ca.pem")


def test_url_trailing_slash_stripped_and_scheme_required():
    assert _pce(url="https://pce.example.com:8443/").url == "https://pce.example.com:8443"
    assert _pce(url="").url == ""
    with pytest.raises(ValidationError):
        _pce(url="pce.example.com")


def test_org_id_must_be_digits_or_empty():
    assert _pce(org_id="").org_id == ""
    with pytest.raises(ValidationError):
        _pce(org_id="org1")


def test_password_hash_must_be_argon2():
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["web"]["password_hash"] = "plaintext"
    with pytest.raises(ValidationError):
        Settings.model_validate(d)


def test_secret_key_must_be_64_hex():
    with pytest.raises(ValidationError):
        default_settings(password_hash=HASH, secret_key="short")


def test_models_are_frozen(initial):
    with pytest.raises(ValidationError):
        initial.web.port = 1


def test_redact_masks_nonempty_secrets_only(initial):
    r = redact(initial)
    assert r["web"]["password_hash"] == MASK and r["web"]["secret_key"] == MASK
    assert r["pce"]["api_key"] == "" and r["pce"]["api_secret"] == ""  # empty stays empty: "not set"
    assert SECRET_FIELDS == {"pce.api_key", "pce.api_secret", "web.password_hash", "web.secret_key",
                             "alerts.channels.smtp.password", "alerts.channels.line.access_token",
                             "alerts.channels.telegram.bot_token", "alerts.channels.teams.webhook_url",
                             "alerts.channels.webhook.url"}


def _with_alerts(initial, **channels):
    d = initial.model_dump(mode="json")
    for name, values in channels.items():
        d["alerts"]["channels"][name].update(values)
    return d


def test_default_alerts(initial):
    a = initial.alerts
    assert a.retention_days == 90 and not any(getattr(a.channels, c).enabled for c in
                                              ("smtp", "line", "telegram", "teams", "webhook"))
    assert len(a.rules) == 30 and all(r.notify for r in a.rules)


def test_redact_masks_channel_secrets(initial):
    d = _with_alerts(initial, line={"access_token": "tok", "target_id": "U1"}, teams={"webhook_url": "https://t/x?sig=1"})
    r = redact(Settings.model_validate(d))
    assert r["alerts"]["channels"]["line"]["access_token"] == MASK and r["alerts"]["channels"]["line"]["target_id"] == "U1"
    assert r["alerts"]["channels"]["teams"]["webhook_url"] == MASK and r["alerts"]["channels"]["webhook"]["url"] == ""


def test_enabled_smtp_requires_host_sender_recipients(initial):
    with pytest.raises(ValidationError):
        Settings.model_validate(_with_alerts(initial, smtp={"enabled": True}))
    ok = _with_alerts(initial, smtp={"enabled": True, "host": "mail", "sender": "a@b", "recipients": ["c@d"]})
    assert Settings.model_validate(ok).alerts.channels.smtp.enabled
    with pytest.raises(ValidationError):
        Settings.model_validate(_with_alerts(initial, smtp={"recipients": ["not-an-address"]}))


def test_enabled_line_requires_token_and_target(initial):
    with pytest.raises(ValidationError):
        Settings.model_validate(_with_alerts(initial, line={"enabled": True, "access_token": "t"}))


def test_channel_urls_must_be_https(initial):
    for name, field in (("teams", "webhook_url"), ("webhook", "url")):
        with pytest.raises(ValidationError):
            Settings.model_validate(_with_alerts(initial, **{name: {field: "http://hook.example/x"}}))


def test_duplicate_rule_ids_rejected(initial):
    d = initial.model_dump(mode="json")
    d["alerts"]["rules"].append(d["alerts"]["rules"][0])
    with pytest.raises(ValidationError):
        Settings.model_validate(d)


def test_timezone_accepts_the_5x_formats():
    from illumio_ops.settings.schema import DisplaySettings

    for tz in ("local", "UTC", "UTC+8", "UTC-5", "UTC+5.5", "Asia/Taipei"):
        assert DisplaySettings(language="en", timezone=tz).timezone == tz
    for bad in ("UTC+24", "Mars/Base", "../etc/passwd", "GMT+8x", ""):
        with pytest.raises(ValidationError):
            DisplaySettings(language="en", timezone=bad)


def test_display_zone_resolves_every_accepted_format():
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    from illumio_ops.settings.schema import DisplaySettings

    def zone(tz):
        return DisplaySettings(language="en", timezone=tz).zone()

    at = datetime(2026, 10, 24, 19, 0, tzinfo=UTC)
    assert zone("local") is None  # the server's own clock
    assert zone("UTC") is UTC
    assert at.astimezone(zone("UTC+8")).hour == 3 and at.astimezone(zone("UTC-5")).hour == 14
    assert at.astimezone(zone("UTC+5.5")).utcoffset() == timedelta(hours=5, minutes=30)
    assert zone("Asia/Taipei") == ZoneInfo("Asia/Taipei")


# ── final review fixes ─────────────────────────────────────────────────────

def _with_web(**web):
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["web"].update(web)
    return d


def test_allowed_ips_entries_must_be_addresses():
    from illumio_ops.settings.store import SettingsInvalid, validate_settings

    validate_settings(_with_web(allowed_ips=["10.0.0.0/8", "::1", "192.168.1.7"]))
    with pytest.raises(SettingsInvalid) as e:
        validate_settings(_with_web(allowed_ips=["10.0.0.0/8", "10.0.0.0/33", "server.example"]))
    assert [loc for loc, _ in e.value.errors] == ["web.allowed_ips.1", "web.allowed_ips.2"]


def test_certificate_paths_must_be_absolute():
    from illumio_ops.settings.store import SettingsInvalid, validate_settings

    d = _with_web()
    d["web"]["tls"].update(cert_file="certs/c.pem", key_file="/etc/k.pem")
    with pytest.raises(SettingsInvalid) as e:
        validate_settings(d)
    assert [loc for loc, _ in e.value.errors] == ["web.tls.cert_file"]


def _with_collection(**changes):
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    for dotted, value in changes.items():
        node = d["collection"]
        *parents, leaf = dotted.split("__")
        for part in parents:
            node = node[part]
        node[leaf] = value
    return d


def test_retention_flow_days_below_baseline_is_invalid():
    from illumio_ops.settings.store import SettingsInvalid, validate_settings
    with pytest.raises(SettingsInvalid) as e:
        validate_settings(_with_collection(retention__flow_days=20))
    [(loc, msg)] = e.value.errors
    assert loc == "collection.retention" and "flow_days" in msg and "20" not in msg


def test_retention_rollup_below_flow_is_invalid():
    with pytest.raises(ValidationError):
        Settings.model_validate(_with_collection(retention__rollup_days=31))


def test_collection_unknown_key_is_invalid():
    d = _with_collection()
    d["collection"]["traffic_filter"] = {"actions": ["allowed"]}
    with pytest.raises(ValidationError):
        Settings.model_validate(d)


def test_collection_interval_bounds():
    with pytest.raises(ValidationError):
        Settings.model_validate(_with_collection(traffic_interval_seconds=60))



def _with_lateral(**changes):
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["lateral"] |= changes
    return d


def _invalid_paths(d):
    with pytest.raises(ValidationError) as e:
        Settings.model_validate(d)
    return [".".join(str(p) for p in err["loc"]) for err in e.value.errors()]


def test_default_lateral_pins_values():
    lat = default_settings(password_hash=HASH, secret_key=KEY).lateral
    assert lat.extra_admin_ports == () and lat.removed_admin_ports == ()
    assert lat.include_pce_admin_services is True
    assert lat.critical_assets == () and lat.admin_groups == ()
    assert lat.environment_label_key == "env" and lat.graph_hops == 3 and lat.observation_days == 30
    d = lat.detectors
    assert (d.fanout_targets, d.fanout_window_minutes, d.account_fanout_targets, d.account_fanout_window_minutes) == (10, 60, 10, 60)
    assert (d.chain_window_minutes, d.blocked_targets, d.blocked_window_minutes, d.blocked_surge_factor) == (30, 5, 60, 3.0)
    assert d.exclude_system_accounts is True and d.precursor_hours == 24
    expected = {(e.port, e.proto): e.processes for e in lat.expected_initiators}
    assert set(expected) == {(445, 6), (3389, 6), (22, 6), (5985, 6), (5986, 6), (135, 6)}
    assert expected[(445, 6)] == ("system", "svchost.exe", "lsass.exe", "explorer.exe", "services.exe", "mount.cifs", "smbclient")
    assert expected[(3389, 6)] == ("mstsc.exe", "msrdc.exe", "rdcman.exe", "xfreerdp", "remmina")
    assert expected[(22, 6)] == ("ssh", "scp", "sftp", "rsync", "git", "ssh.exe", "putty.exe", "plink.exe", "winscp.exe")
    assert expected[(5985, 6)] == expected[(5986, 6)] == ("powershell.exe", "pwsh.exe", "pwsh", "wsmprovhost.exe", "svchost.exe")
    assert expected[(135, 6)] == ("lsass.exe", "svchost.exe", "services.exe", "backgroundtaskhost.exe", "wmiprvse.exe",
                                  "dsregcmd.exe", "mmc.exe")


def test_lateral_unknown_key_invalid():
    assert "lateral.bogus" in _invalid_paths(_with_lateral(bogus=1))


def test_observation_days_may_exceed_baseline():
    # Lowering the baseline retention on the data-collection page must not fail on a lateral field;
    # the exposure graph uses the smaller of the two (Task 5).
    d = _with_lateral(observation_days=60)
    assert Settings.model_validate(d).lateral.observation_days == 60
    d["collection"]["retention"]["baseline_days"] = 7
    assert Settings.model_validate(d).collection.retention.baseline_days == 7


def test_port_both_added_and_removed_invalid():
    entry = {"port": 8080, "proto": 6}
    assert any(p.startswith("lateral") for p in _invalid_paths(
        _with_lateral(extra_admin_ports=[entry], removed_admin_ports=[entry])))


def test_duplicate_expected_initiator_port_invalid():
    rows = [{"port": 22, "proto": 6, "processes": ["ssh"]}, {"port": 22, "proto": 6, "processes": ["scp"]}]
    assert any(p.startswith("lateral") for p in _invalid_paths(_with_lateral(expected_initiators=rows)))


def test_expected_initiator_processes_normalized():
    d = _with_lateral(expected_initiators=[{"port": 3389, "proto": 6, "processes": ["C:\\Windows\\System32\\MSTSC.EXE"]}])
    assert Settings.model_validate(d).lateral.expected_initiators[0].processes == ("mstsc.exe",)
    blank = _with_lateral(expected_initiators=[{"port": 3389, "proto": 6, "processes": [""]}])
    assert any(p.startswith("lateral") for p in _invalid_paths(blank))


def test_invalid_lateral_messages_do_not_echo_values():
    with pytest.raises(ValidationError) as e:
        Settings.model_validate(_with_lateral(environment_label_key="", graph_hops=99))
    assert "99" not in " ".join(err["msg"] for err in e.value.errors())


def _lateral(**kw):
    from illumio_ops.settings.schema import LateralSettings, default_lateral
    return LateralSettings.model_validate(default_lateral().model_dump(mode="json") | kw)


def test_peer_group_keys_rejects_empty_and_duplicates():
    for bad in ([], ["app", "app"], ["a", "b", "c", "d", "e"], [""]):
        with pytest.raises(ValidationError):
            _lateral(peer_group_keys=bad)
    assert _lateral(peer_group_keys=["app"]).peer_group_keys == ("app",)


def test_directory_server_ips_rejects_networks():
    with pytest.raises(ValidationError):
        _lateral(directory_server_ips=["10.0.0.0/24"])
    with pytest.raises(ValidationError):
        _lateral(directory_server_ips=["dc-1"])
    assert _lateral(directory_server_ips=[" 10.0.0.5 "]).directory_server_ips == ("10.0.0.5",)


def test_suspicious_tools_are_normalized():
    assert _lateral(suspicious_tools=["C:\\Tools\\PsExec.EXE", "/usr/bin/nc"]).suspicious_tools == ("psexec.exe", "nc")
    assert _lateral(suspicious_tools=[]).suspicious_tools == ()


def test_added_port_category():
    lat = _lateral(extra_admin_ports=[{"port": 1521, "proto": 6, "category": "database"}])
    assert lat.extra_admin_ports[0].category == "database"
    with pytest.raises(ValidationError):
        _lateral(extra_admin_ports=[{"port": 1521, "proto": 6, "category": "other"}])
