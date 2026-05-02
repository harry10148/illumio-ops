"""
src/gui/_helpers.py — Shared utilities for the GUI Blueprint modules.

All symbols that are used by two or more Blueprint modules (or by external
callers via src.gui re-exports) live here.  Import with:

    from src.gui._helpers import _ok, _err, _err_with_log, ...
"""
from __future__ import annotations

import os
import re
import json
import struct
import datetime
import ipaddress
import socket as _socket
import traceback as _traceback
import uuid as _uuid
from collections import deque
import threading

from loguru import logger

from src.config import ConfigManager
from src.i18n import t, get_messages
from src.alerts import PLUGIN_METADATA, plugin_config_path, plugin_config_value
from src.report.dashboard_summaries import (
    build_audit_dashboard_summary,
    build_policy_usage_dashboard_summary,
    write_audit_dashboard_summary,
    write_policy_usage_dashboard_summary,
)

try:
    from flask import jsonify, request
except ImportError:
    jsonify = None  # type: ignore[assignment]
    request = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# ANSI / text helpers
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


# ---------------------------------------------------------------------------
# IP helpers
# ---------------------------------------------------------------------------

def _normalize_ip_token(value: str):
    token = str(value or "").strip()
    if not token:
        raise ValueError("empty ip token")
    if "/" in token:
        network = ipaddress.ip_network(token, strict=False)
        if isinstance(network, ipaddress.IPv6Network) and network.network_address.ipv4_mapped:
            mapped = network.network_address.ipv4_mapped
            prefix = max(0, network.prefixlen - 96)
            return ipaddress.ip_network(f"{mapped}/{prefix}", strict=False)
        return network
    addr = ipaddress.ip_address(token)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        return addr.ipv4_mapped
    return addr


def _loopback_equivalent(left, right) -> bool:
    return (
        isinstance(left, (ipaddress.IPv4Address, ipaddress.IPv6Address))
        and isinstance(right, (ipaddress.IPv4Address, ipaddress.IPv6Address))
        and left.is_loopback
        and right.is_loopback
    )


def _check_ip_allowed(allowed_ips: list, remote_addr: str) -> bool:
    if not allowed_ips:
        return True
    try:
        remote = _normalize_ip_token(remote_addr)
    except ValueError:
        return False
    for allowed in allowed_ips:
        try:
            normalized = _normalize_ip_token(allowed)
            if isinstance(normalized, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
                net = normalized
                if remote in net:
                    return True
            else:
                ip = normalized
                if remote == ip or _loopback_equivalent(remote, ip):
                    return True
        except ValueError:
            continue
    return False

def _validate_allowed_ips(values) -> tuple[list, list]:
    normalized = []
    invalid = []
    for raw in values or []:
        item = str(raw or "").strip()
        if not item:
            continue
        try:
            canonical = _normalize_ip_token(item)
            normalized.append(str(canonical))
        except ValueError:
            invalid.append(item)
    return normalized, invalid


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

_SECRET_PATTERN = re.compile(
    r'(?:^|_)(?:password|secret|key|token|webhook_url|line_channel_access_token|smtp_password)$'
)

def _redact_secrets(obj):
    """Recursively redact secret fields for API responses."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _SECRET_PATTERN.search(k.lower()):
                out[k] = "*" * min(len(str(v)), 8) if v else ""
                out[f"{k}__set"] = bool(v)
                out[f"{k}__length"] = len(str(v)) if v else 0
            else:
                out[k] = _redact_secrets(v)
        return out
    elif isinstance(obj, list):
        return [_redact_secrets(item) for item in obj]
    return obj


def _strip_redaction_placeholders(obj):
    """Drop masked secret values from an incoming settings payload.

    GET /api/settings replaces secret fields with up-to-8 asterisks via
    _redact_secrets. If the GUI POSTs the unchanged response back, the
    masked value would overwrite the real secret. This helper strips
    secret-named keys whose value is purely asterisks (1-8 chars) so the
    existing stored value is preserved.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if (_SECRET_PATTERN.search(k.lower())
                    and isinstance(v, str)
                    and 1 <= len(v) <= 8
                    and v == "*" * len(v)):
                continue
            out[k] = _strip_redaction_placeholders(v)
        return out
    elif isinstance(obj, list):
        return [_strip_redaction_placeholders(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Settings / config helpers
# ---------------------------------------------------------------------------

_SETTINGS_ALLOWLISTS = {
    "smtp": {"host", "port", "user", "password", "enable_auth", "enable_tls"},
    "alerts": {"active", "line_channel_access_token", "line_target_id", "webhook_url"},
    "settings": {
        "language", "theme", "timezone", "enable_health_check", "dashboard_queries",
    },
    "api": {"url", "org_id", "key", "secret", "verify_ssl"},
    "email": {"sender", "recipients"},
    "report": {"output_dir", "retention_days"},
}

def _normalize_rule_throttle(raw_value):
    value = str(raw_value or "").strip()
    if not value:
        return ""
    try:
        from src.events import parse_throttle
    except Exception:
        parse_throttle = None
    if parse_throttle and not parse_throttle(value):
        raise ValueError("Invalid throttle format. Use values like 2/10m or 5/1h.")
    return value

def _normalize_match_fields(raw_value):
    if not raw_value:
        return {}
    if isinstance(raw_value, dict):
        normalized = {}
        for key, value in raw_value.items():
            key_str = str(key or "").strip()
            value_str = str(value or "").strip()
            if key_str and value_str:
                normalized[key_str] = value_str
        return normalized
    raise ValueError("match_fields must be an object of field-path to pattern.")

def _is_workload_href(href: str) -> bool:
    normalized = str(href or "").strip()
    return bool(normalized) and "/workloads/" in normalized

def _normalize_quarantine_hrefs(raw_hrefs) -> list[str]:
    normalized: list[str] = []
    for raw_href in raw_hrefs or []:
        href = str(raw_href or "").strip()
        if href and _is_workload_href(href) and href not in normalized:
            normalized.append(href)
    return normalized


# ---------------------------------------------------------------------------
# TCP RST drop helpers
# ---------------------------------------------------------------------------

def _rst_drop():
    """Close the underlying TCP socket with RST (SO_LINGER 0) and raise to
    prevent Flask from sending any HTTP response.  To a port scanner the
    connection appears reset — identical to 'connection refused' — so the
    port does not register as an open HTTP service.
    """
    try:
        environ = request.environ
        # Werkzeug exposes the raw socket in several possible locations
        sock = environ.get('werkzeug.socket')
        if sock is None:
            wsgi_in = environ.get('wsgi.input')
            for attr in ('raw', '_sock', 'raw._sock'):
                obj = wsgi_in
                for part in attr.split('.'):
                    obj = getattr(obj, part, None)
                    if obj is None:
                        break
                if isinstance(obj, _socket.socket):
                    sock = obj
                    break
        if sock is not None:
            # l_onoff=1, l_linger=0 — kernel sends RST on close, not FIN
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER,
                            struct.pack('ii', 1, 0))
            try:
                sock.shutdown(_socket.SHUT_RDWR)
            except OSError:
                pass  # intentional fallback: socket may already be closed; RST linger is best-effort
    except Exception:
        pass  # intentional fallback: TCP RST socket introspection is best-effort; always raise _RstDrop regardless
    # Raise — Flask will attempt to write the 500 but the socket is gone
    raise _RstDrop()

class _RstDrop(Exception):
    """Sentinel: request was silently dropped via TCP RST."""


# ---------------------------------------------------------------------------
# Path constants (same directory as __init__.py — src/gui/)
# ---------------------------------------------------------------------------

_GUI_DIR = os.path.dirname(os.path.abspath(__file__))  # src/gui/
_PKG_DIR = os.path.dirname(_GUI_DIR)                   # src/
_ROOT_DIR = os.path.dirname(_PKG_DIR)                  # project root


# ---------------------------------------------------------------------------
# Report / config / state path helpers
# ---------------------------------------------------------------------------

_ALLOWED_REPORT_FORMATS = frozenset({'html', 'csv', 'pdf', 'xlsx', 'all'})

def _resolve_reports_dir(cm_ref: ConfigManager) -> str:
    """Return absolute path to the report output directory."""
    d = cm_ref.config.get('report', {}).get('output_dir', 'reports')
    return d if os.path.isabs(d) else os.path.join(_ROOT_DIR, d)

def _resolve_config_dir() -> str:
    return os.path.join(_ROOT_DIR, 'config')

def _resolve_state_file() -> str:
    return os.path.join(_ROOT_DIR, 'logs', 'state.json')


# ---------------------------------------------------------------------------
# UI / i18n helpers
# ---------------------------------------------------------------------------

_UI_EXTRA_KEYS = frozenset({"rule_pce_health"})

def _ui_translation_dict(lang: str) -> dict:
    return {
        k: v
        for k, v in get_messages(lang).items()
        if k.startswith(("gui_", "sched_", "status_", "error_"))
        or k in _UI_EXTRA_KEYS
    }


# ---------------------------------------------------------------------------
# Plugin / alert channel helpers
# ---------------------------------------------------------------------------

def _plugin_config_roots() -> set[str]:
    roots: set[str] = set()
    for plugin_name, meta in PLUGIN_METADATA.items():
        for field_key in meta.fields:
            path = plugin_config_path(plugin_name, field_key)
            if path:
                roots.add(path[0])
    return roots

def _summarize_alert_channels(config: dict, dispatch_history: list) -> list[dict]:
    active = set(config.get("alerts", {}).get("active", []) or [])
    summaries = []
    for name, meta in PLUGIN_METADATA.items():
        required_missing = []
        for key, field in meta.fields.items():
            if not field.required:
                continue
            value = plugin_config_value(config, name, key)
            if isinstance(value, list):
                present = any(str(item or "").strip() for item in value)
            elif isinstance(value, (int, float)):
                present = True
            else:
                present = bool(str(value or "").strip()) if not isinstance(value, bool) else value
            if not present:
                required_missing.append(key)

        latest = next((item for item in reversed(dispatch_history or []) if item.get("channel") == name), None)
        summaries.append({
            "name": name,
            "display_name": meta.display_name,
            "description": meta.description,
            "enabled": name in active,
            "configured": len(required_missing) == 0,
            "missing_required": required_missing,
            "last_status": latest.get("status", "") if latest else "",
            "last_target": latest.get("target", "") if latest else "",
            "last_timestamp": latest.get("timestamp", "") if latest else "",
            "last_error": latest.get("error", "") if latest else "",
        })
    return summaries


# ---------------------------------------------------------------------------
# Standard API response helpers
# ---------------------------------------------------------------------------

def _ok(data=None, **kw):
    """Standard success response: {"ok": true, ...}"""
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    body.update(kw)
    return jsonify(body)

def _err(msg, status=400):
    """Standard error response: {"ok": false, "error": "..."}"""
    return jsonify({"ok": False, "error": msg}), status

def _safe_log(s: str, max_len: int = 200) -> str:
    """Strip CRLF and truncate for safe log output."""
    return str(s).replace('\r', '').replace('\n', '').replace('\t', ' ')[:max_len]

def _err_with_log(category: str, exc: Exception, status: int = 500):
    """H3: log full exception detail server-side, return generic error to client.

    Logs ``[GUI:{category}] req={req_id}: <traceback>`` via ``loguru.error`` and
    returns ``(jsonify({"ok": False, "error": "<i18n>", "request_id": req_id}), status)``.
    The 8-char request_id is for log correlation only — not a security token.

    ``category`` is a short label like 'pce_profile' or 'dashboard_summary' used
    only in the log line, never in the response.
    """
    req_id = str(_uuid.uuid4())[:8]
    logger.error(f"[GUI:{category}] req={req_id}: {_traceback.format_exc()}")
    return jsonify({
        "ok": False,
        "error": t("gui_err_internal", default="Internal server error"),
        "request_id": req_id,
    }), status


# ---------------------------------------------------------------------------
# PCE URL helpers
# ---------------------------------------------------------------------------

def _get_active_pce_url(cm: 'ConfigManager') -> str:
    """Return the active PCE profile URL, falling back to config['api']['url']."""
    active_id = cm.config.get('active_pce_id')
    if active_id is not None:
        for p in cm.config.get('pce_profiles', []):
            if p.get('id') == active_id:
                return p.get('url', '') or cm.config.get('api', {}).get('url', '')
    return cm.config.get('api', {}).get('url', '')


# ---------------------------------------------------------------------------
# Dashboard summary helpers
# ---------------------------------------------------------------------------

def _build_audit_dashboard_summary(result) -> dict:
    return build_audit_dashboard_summary(result)

def _write_audit_dashboard_summary(output_dir: str, result) -> str:
    return write_audit_dashboard_summary(output_dir, result)

def _build_policy_usage_dashboard_summary(result) -> dict:
    return build_policy_usage_dashboard_summary(result)

def _write_policy_usage_dashboard_summary(output_dir: str, result) -> str:
    return write_policy_usage_dashboard_summary(output_dir, result)


# ---------------------------------------------------------------------------
# Dashboard chart helpers
# ---------------------------------------------------------------------------

def _spec_to_plotly_figure(spec: dict):
    """Convert a chart_spec dict to a plotly Figure (not HTML)."""
    import math
    import plotly.graph_objects as go

    chart_type = spec.get("type")
    data = spec.get("data", {})
    title = spec.get("title", "")

    if chart_type == "bar":
        fig = go.Figure(go.Bar(x=data.get("labels", []), y=data.get("values", []),
                               marker_color="rgb(55, 83, 109)"))
        fig.update_layout(title=title, xaxis_title=spec.get("x_label", ""),
                          yaxis_title=spec.get("y_label", ""))
    elif chart_type == "pie":
        fig = go.Figure(go.Pie(labels=data.get("labels", []),
                               values=data.get("values", []), hole=0.3))
        fig.update_layout(title=title)
    elif chart_type == "line":
        fig = go.Figure(go.Scatter(x=data.get("x", []), y=data.get("y", []),
                                   mode="lines+markers"))
        fig.update_layout(title=title, xaxis_title=spec.get("x_label", ""),
                          yaxis_title=spec.get("y_label", ""))
    else:
        fig = go.Figure()
        fig.update_layout(title=f"Unsupported type: {chart_type}")
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#cdd3de"), margin=dict(l=40, r=20, t=40, b=40))
    return fig


def _load_state_for_charts() -> dict:
    try:
        state_file = _resolve_state_file()
        if os.path.exists(state_file):
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as _e:
        logger.debug(f"[GUI:load_state] swallowed: {_e}")  # missing/corrupt state file → empty dict
    return {}


def _build_traffic_timeline_spec(cm_ref) -> dict:
    from src.i18n import t, get_language
    from collections import Counter
    state = _load_state_for_charts()
    timeline = state.get("event_timeline", [])
    counts: Counter = Counter()
    for entry in timeline:
        ts = entry.get("timestamp", "")[:10]
        if ts:
            counts[ts] += 1
    sorted_days = sorted(counts.keys())[-14:]
    return {
        "type": "line",
        "title": t("rpt_dash_traffic_title", default="Events Last 14 Days"),
        "x_label": t("rpt_time", default="Date"),
        "y_label": t("rpt_event_count", default="Events"),
        "data": {"x": sorted_days, "y": [counts[d] for d in sorted_days]},
        "i18n": {"lang": get_language()},
    }


def _build_policy_decisions_spec(cm_ref) -> dict:
    from src.i18n import t, get_language
    reports_dir = _resolve_reports_dir(cm_ref)
    snapshot_path = os.path.join(reports_dir, "latest_snapshot.json")
    allowed = blocked = potential = 0
    try:
        if os.path.exists(snapshot_path):
            with open(snapshot_path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            allowed = snap.get("allowed_flows", 0)
            blocked = snap.get("blocked_flows", 0)
            potential = snap.get("potentially_blocked_flows", 0)
    except Exception as _e:
        logger.debug(f"[GUI:snapshot_parse] swallowed: {_e}")  # missing/corrupt snapshot → zero counts
    return {
        "type": "pie",
        "title": t("rpt_dash_pd_title", default="Policy Decisions (Latest Report)"),
        "data": {
            "labels": [t("rpt_pd_allowed", default="Allowed"),
                       t("rpt_pd_blocked", default="Blocked"),
                       t("rpt_pd_potential", default="Potentially Blocked")],
            "values": [allowed, blocked, potential],
        },
        "i18n": {"lang": get_language()},
    }


def _build_ven_status_spec(cm_ref) -> dict:
    from src.i18n import t, get_language
    state = _load_state_for_charts()
    pce_stats = state.get("pce_stats", {})
    health = pce_stats.get("health_status", "unknown")
    ok = 1 if health == "ok" else 0
    err = 1 if health not in ("ok", "unknown") else 0
    unknown = 1 if health == "unknown" else 0
    return {
        "type": "pie",
        "title": t("rpt_dash_ven_title", default="PCE Health Status"),
        "data": {
            "labels": [t("rpt_status_ok", default="OK"),
                       t("rpt_status_error", default="Error"),
                       t("rpt_status_unknown", default="Unknown")],
            "values": [ok, err, unknown],
        },
        "i18n": {"lang": get_language()},
    }


def _build_rule_hits_spec(cm_ref) -> dict:
    from src.i18n import t, get_language
    from collections import Counter
    state = _load_state_for_charts()
    timeline = state.get("event_timeline", [])
    rule_counts: Counter = Counter()
    for entry in timeline:
        if entry.get("kind") == "rule_trigger":
            name = entry.get("title", "unnamed")
            rule_counts[name] += 1
    top = rule_counts.most_common(10)
    return {
        "type": "bar",
        "title": t("rpt_dash_rule_hits_title", default="Top Rule Triggers"),
        "x_label": t("rpt_rule", default="Rule"),
        "y_label": t("rpt_hit_count", default="Hits"),
        "data": {
            "labels": [r for r, _ in top] or [t("rpt_no_triggers", default="No triggers")],
            "values": [c for _, c in top] or [0],
        },
        "i18n": {"lang": get_language()},
    }


# ---------------------------------------------------------------------------
# TLS helpers
# ---------------------------------------------------------------------------

# Default validity period for self-signed certs. 5 years keeps the cert
# effectively "set and forget" for internal deployments while still giving
# the auto-renew path meaningful runway before expiry.
_SELF_SIGNED_VALIDITY_DAYS = 397  # ~13 months (browser-accepted maximum)

def _cert_has_san(cert_path: str) -> bool:
    """Return True if the certificate contains a SubjectAlternativeName extension."""
    import subprocess
    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout", "-ext", "subjectAltName"],
            capture_output=True, text=True,
        )
        return "Subject Alternative Name" in result.stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _get_local_ips() -> list[str]:
    """Return all non-link-local IP addresses on this machine (IPv4 + IPv6)."""
    import socket
    ips: set[str] = {"127.0.0.1", "::1"}
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            # Skip link-local addresses
            if not ip.startswith("fe80") and not ip.startswith("169.254"):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def _generate_self_signed_cert(cert_dir: str, force: bool = False,
                               days: int = _SELF_SIGNED_VALIDITY_DAYS,
                               key_algorithm: str = "ecdsa-p256") -> tuple[str, str]:
    """Generate a self-signed TLS certificate for local HTTPS.

    Includes SubjectAlternativeName (SAN) for localhost and 127.0.0.1 so that
    modern browsers accept the certificate for fetch() / XHR requests (Chrome 58+
    ignores CN entirely and requires SAN for cert validation).

    Uses the `cryptography` library when available (ECDSA P-256 or RSA-2048).
    Falls back to subprocess openssl (RSA-2048) if `cryptography` is not installed.

    Args:
        cert_dir: Directory to store cert and key files.
        force: If True, regenerate even if existing cert is still valid.
        days: Validity period in days.
        key_algorithm: "ecdsa-p256" (default) or "rsa-2048".

    Returns:
        (cert_path, key_path) tuple.
    """
    os.makedirs(cert_dir, exist_ok=True)
    cert_path = os.path.join(cert_dir, "self_signed.pem")
    key_path = os.path.join(cert_dir, "self_signed_key.pem")

    if not force and os.path.exists(cert_path) and os.path.exists(key_path):
        # Regenerate if the existing cert lacks SAN — browsers reject SAN-less certs
        # for fetch()/XHR even when the user has accepted the page-level warning.
        if _cert_has_san(cert_path):
            return cert_path, key_path
        force = True

    local_ips = _get_local_ips()
    logger.info(
        "Generating self-signed cert with SANs: DNS:localhost, {}",
        ", ".join(f"IP:{ip}" for ip in local_ips),
    )

    try:
        from cryptography import x509 as _x509
        from cryptography.x509.oid import NameOID as _NameOID
        from cryptography.hazmat.primitives import hashes as _hashes, serialization as _serial
        from cryptography.hazmat.primitives.asymmetric import ec as _ec, rsa as _rsa
        import ipaddress as _ipaddress
        import datetime as _datetime

        # Generate private key
        if key_algorithm == "rsa-2048":
            private_key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
        else:
            # Default: ECDSA P-256
            private_key = _ec.generate_private_key(_ec.SECP256R1())

        # Build subject / issuer
        name = _x509.Name([
            _x509.NameAttribute(_NameOID.COUNTRY_NAME, "TW"),
            _x509.NameAttribute(_NameOID.ORGANIZATION_NAME, "IllumioPCEOps"),
            _x509.NameAttribute(_NameOID.COMMON_NAME, "localhost"),
        ])

        # Build SAN extension
        san_entries = [_x509.DNSName("localhost")]
        for ip_str in local_ips:
            try:
                san_entries.append(_x509.IPAddress(_ipaddress.ip_address(ip_str)))
            except ValueError:
                pass

        now = _datetime.datetime.now(_datetime.timezone.utc)
        cert = (
            _x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(private_key.public_key())
            .serial_number(_x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + _datetime.timedelta(days=days))
            .add_extension(_x509.SubjectAlternativeName(san_entries), critical=False)
            .add_extension(_x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(private_key, _hashes.SHA256())
        )

        # Write key (restricted permissions) and certificate
        with open(key_path, "wb") as fk:
            fk.write(private_key.private_bytes(
                encoding=_serial.Encoding.PEM,
                format=_serial.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=_serial.NoEncryption(),
            ))
        os.chmod(key_path, 0o600)
        with open(cert_path, "wb") as fc:
            fc.write(cert.public_bytes(_serial.Encoding.PEM))

        algo_label = "ECDSA P-256" if key_algorithm != "rsa-2048" else "RSA-2048"
        print(f"  Self-signed certificate generated ({days} days, {algo_label}): {cert_path}")
        return cert_path, key_path

    except ImportError:
        # Fallback: use openssl subprocess (RSA-2048)
        import subprocess
        import tempfile

        ip_lines = "".join(f"IP.{i + 1} = {ip}\n" for i, ip in enumerate(local_ips))
        san_config = (
            "[req]\n"
            "distinguished_name = req_dn\n"
            "x509_extensions = v3_req\n"
            "prompt = no\n"
            "[req_dn]\n"
            "CN = localhost\n"
            "O = IllumioPCEOps\n"
            "C = TW\n"
            "[v3_req]\n"
            "subjectAltName = @alt_names\n"
            "[alt_names]\n"
            "DNS.1 = localhost\n"
            + ip_lines
        )

        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False) as f:
                f.write(san_config)
                cfg_path = f.name

            try:
                subprocess.run(
                    [
                        "openssl", "req", "-x509", "-newkey", "rsa:2048",
                        "-keyout", key_path, "-out", cert_path,
                        "-days", str(days), "-nodes",
                        "-config", cfg_path,
                    ],
                    check=True,
                    capture_output=True,
                )
            finally:
                try:
                    os.unlink(cfg_path)
                except OSError:
                    pass

            os.chmod(key_path, 0o600)
            print(f"  Self-signed certificate generated ({days} days, RSA-2048 fallback): {cert_path}")
            return cert_path, key_path
        except FileNotFoundError:
            raise RuntimeError(
                "openssl command not found. Install OpenSSL to use self-signed certificates, "
                "or provide your own cert_file and key_file in config."
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to generate self-signed certificate: {e.stderr.decode()}")

def _cert_days_remaining(cert_path: str) -> int | None:
    """Return the number of days until the cert expires, or None if unknown.

    Negative values mean the cert is already expired. Works via openssl's
    enddate field so no Python cryptography dependency is required.
    """
    import subprocess
    from datetime import datetime, timezone

    if not os.path.exists(cert_path):
        return None
    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout", "-enddate"],
            capture_output=True, text=True, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    line = result.stdout.strip()
    if not line.startswith("notAfter="):
        return None
    # "notAfter=Sep  3 12:34:56 2030 GMT"
    raw = line[len("notAfter="):].strip()
    try:
        expiry = datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z")
    except ValueError:
        try:
            expiry = datetime.strptime(raw.replace("GMT", "UTC"), "%b %d %H:%M:%S %Y %Z")
        except ValueError:
            return None
    expiry = expiry.replace(tzinfo=timezone.utc)
    delta = expiry - datetime.now(timezone.utc)
    return int(delta.total_seconds() // 86400)

def _maybe_auto_renew_self_signed(cert_dir: str, threshold_days: int = 30) -> tuple[bool, int | None]:
    """Regenerate the self-signed cert if it expires within ``threshold_days``.

    Called at server startup. Returns ``(renewed, days_remaining_after)`` so
    the caller can log what happened.
    """
    cert_path = os.path.join(cert_dir, "self_signed.pem")
    days = _cert_days_remaining(cert_path)
    if days is None:
        # No cert present (or openssl unavailable) — caller will generate
        # one fresh via the normal path.
        return False, None
    if days > threshold_days:
        return False, days
    try:
        _generate_self_signed_cert(cert_dir, force=True)
    except RuntimeError:
        return False, days
    return True, _cert_days_remaining(cert_path)

def _get_cert_info(cert_path: str) -> dict:
    """Read certificate expiry and subject via openssl."""
    import subprocess
    info = {"path": cert_path, "exists": os.path.exists(cert_path)}
    if not info["exists"]:
        return info
    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout",
             "-subject", "-enddate", "-startdate"],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.strip().splitlines():
            if line.startswith("subject="):
                info["subject"] = line[len("subject="):].strip()
            elif line.startswith("notAfter="):
                info["not_after"] = line[len("notAfter="):].strip()
            elif line.startswith("notBefore="):
                info["not_before"] = line[len("notBefore="):].strip()
        # Check if expired
        check = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout", "-checkend", "0"],
            capture_output=True,
        )
        info["expired"] = check.returncode != 0
        # Check if expiring within 30 days
        check30 = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout", "-checkend", "2592000"],
            capture_output=True,
        )
        info["expiring_soon"] = check30.returncode != 0
    except (FileNotFoundError, subprocess.CalledProcessError):
        info["error"] = "openssl not available"
    return info

def _build_ssl_context(tls_cfg: dict) -> "_ssl.SSLContext":
    """Build and return a hardened ssl.SSLContext from a tls config dict.

    Args:
        tls_cfg: dict with optional keys ``min_version`` (str) and ``ciphers`` (str|None).

    Returns:
        Configured :class:`ssl.SSLContext` (PROTOCOL_TLS_SERVER).
    """
    import ssl as _ssl
    _min_ver_str = tls_cfg.get("min_version", "TLSv1.2")
    _min_ver_map = {
        "TLSv1.2": _ssl.TLSVersion.TLSv1_2,
        "TLSv1.3": _ssl.TLSVersion.TLSv1_3,
    }
    _min_ver = _min_ver_map.get(_min_ver_str, _ssl.TLSVersion.TLSv1_2)

    _cipher_cfg = tls_cfg.get("ciphers")
    _safe_ciphers = (
        "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM"
        ":!aNULL:!MD5:!DSS:!RC4:!3DES:!EXPORT"
    )
    _ciphers = _cipher_cfg if _cipher_cfg else _safe_ciphers

    ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = _min_ver
    ctx.set_ciphers(_ciphers)
    ctx.options |= (
        _ssl.OP_NO_COMPRESSION
        | _ssl.OP_SINGLE_DH_USE
        | _ssl.OP_SINGLE_ECDH_USE
    )
    return ctx
