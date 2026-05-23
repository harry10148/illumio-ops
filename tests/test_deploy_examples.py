from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def test_filebeat_has_tls():
    content = (DEPLOY / "filebeat.illumio_ops.yml").read_text()
    assert "ssl.enabled: true" in content or "ssl:\n    enabled: true" in content, \
        "filebeat example must include ssl.enabled: true"
    assert "ssl.verification_mode" in content, \
        "filebeat example must set ssl.verification_mode"
    assert "changeme" not in content.lower(), "filebeat example must not contain literal 'changeme'"


def test_logstash_has_tls():
    content = (DEPLOY / "logstash.illumio_ops.conf").read_text()
    # Logstash output uses `ssl => true` (Ruby-style)
    assert "ssl => true" in content, "logstash example must include ssl => true"
    assert "ssl_certificate_verification => true" in content, \
        "logstash example must enable cert verification"
    assert "changeme" not in content.lower(), "logstash example must not contain literal 'changeme'"


def test_rsyslog_has_tls():
    content = (DEPLOY / "rsyslog.illumio_ops.conf").read_text()
    # rsyslog uses StreamDriver gtls
    assert "gtls" in content.lower(), "rsyslog example must reference gtls (TLS stream driver)"
    assert "changeme" not in content.lower()


def test_no_placeholder_password_literals():
    """Any password-related placeholder must be the obvious <REPLACE_ME> form, not 'changeme'."""
    for f in DEPLOY.glob("*"):
        if f.is_file() and f.suffix in (".yml", ".yaml", ".conf"):
            content = f.read_text().lower()
            assert "changeme" not in content, f"{f.name} still contains 'changeme'"
