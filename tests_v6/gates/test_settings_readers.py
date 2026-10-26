"""Gate 5: every settings field has a reader.

Matching a bare attribute name proves nothing (`.url`, `.level`, `.enabled` exist on
many objects), so each leaf path is registered with the module that reads it, and that
module must show both the attribute read and evidence of the owning model: the model
class name or the parent field (e.g. `.pce`, `.tls`).
"""
from __future__ import annotations

import ast
from pathlib import Path

from pydantic import BaseModel

from illumio_ops.settings.schema import Settings
from tests_v6.gates._scan import PKG_ROOT, iter_modules

SETTINGS_READERS: dict[str, str] = {
    "revision": "illumio_ops.settings.store",
    "pce.url": "illumio_ops.pce.client",
    "pce.org_id": "illumio_ops.pce.client",
    "pce.api_key": "illumio_ops.pce.client",
    "pce.api_secret": "illumio_ops.pce.client",
    "pce.verify_tls": "illumio_ops.pce.client",
    "pce.deployment_type": "illumio_ops.services.pce_health",
    "web.username": "illumio_ops.web.auth",
    "web.password_hash": "illumio_ops.web.auth",
    "web.must_change_password": "illumio_ops.web.auth",
    "web.secret_key": "illumio_ops.web.app",
    "web.allowed_ips": "illumio_ops.web.app",
    "web.session_lifetime_seconds": "illumio_ops.web.app",
    "web.host": "illumio_ops.__main__",
    "web.port": "illumio_ops.__main__",
    "logging.level": "illumio_ops.__main__",
    "web.tls.enabled": "illumio_ops.runtime",
    "web.tls.mode": "illumio_ops.runtime",
    "web.tls.cert_file": "illumio_ops.runtime",
    "web.tls.key_file": "illumio_ops.runtime",
    "web.tls.auto_renew": "illumio_ops.web.tls",
    "web.tls.auto_renew_days": "illumio_ops.web.tls",
    "web.tls.validity_days": "illumio_ops.web.tls",
    "web.tls.key_algorithm": "illumio_ops.web.tls",
    "web.tls.min_version": "illumio_ops.web.tls",
    "web.tls.ciphers": "illumio_ops.web.tls",
    "display.language": "illumio_ops.web.auth",
    "collection.rate_limit_per_minute": "illumio_ops.services.context",
    "pce.events_timeout_seconds": "illumio_ops.pce.events",
    "collection.enabled": "illumio_ops.services.collect.mode",
    "collection.mode": "illumio_ops.services.collect.mode",
    "collection.traffic_interval_seconds": "illumio_ops.jobs.scheduler",
    "collection.events_interval_seconds": "illumio_ops.jobs.scheduler",
    "collection.inventory_interval_seconds": "illumio_ops.jobs.scheduler",
    "collection.backfill_days": "illumio_ops.services.collect.backfill",
    "collection.retention.flow_days": "illumio_ops.services.collect.retention",
    "collection.retention.event_days": "illumio_ops.services.collect.retention",
    "collection.retention.rollup_days": "illumio_ops.services.collect.retention",
    "collection.retention.baseline_days": "illumio_ops.services.collect.retention",
    "collection.archive.enabled": "illumio_ops.services.collect.archive",
    "collection.archive.retention_days": "illumio_ops.services.collect.archive",
    "collection.disk_free_warn_gb": "illumio_ops.services.collect.status",
    "lateral.extra_admin_ports": "illumio_ops.services.analysis.context",
    "lateral.removed_admin_ports": "illumio_ops.services.analysis.context",
    "lateral.include_pce_admin_services": "illumio_ops.services.analysis.context",
    "lateral.critical_assets": "illumio_ops.services.analysis.context",
    "lateral.admin_groups": "illumio_ops.services.analysis.context",
    "lateral.environment_label_key": "illumio_ops.services.analysis.exposure",
    "lateral.graph_hops": "illumio_ops.services.analysis.exposure",
    "lateral.observation_days": "illumio_ops.services.analysis.exposure",
    "lateral.expected_initiators": "illumio_ops.services.analysis.detect",
    "lateral.detectors.fanout_targets": "illumio_ops.services.analysis.detect",
    "lateral.detectors.fanout_window_minutes": "illumio_ops.services.analysis.detect",
    "lateral.detectors.account_fanout_targets": "illumio_ops.services.analysis.detect",
    "lateral.detectors.account_fanout_window_minutes": "illumio_ops.services.analysis.detect",
    "lateral.detectors.chain_window_minutes": "illumio_ops.services.analysis.detect",
    "lateral.detectors.blocked_targets": "illumio_ops.services.analysis.detect",
    "lateral.detectors.blocked_window_minutes": "illumio_ops.services.analysis.detect",
    "lateral.detectors.blocked_surge_factor": "illumio_ops.services.analysis.detect",
    "lateral.detectors.exclude_system_accounts": "illumio_ops.services.analysis.detect",
    "lateral.detectors.precursor_hours": "illumio_ops.services.analysis.detect",
    "alerts.rules": "illumio_ops.services.alerts.evaluate",
    "alerts.retention_days": "illumio_ops.services.alerts.retention",
    "pce.console_url": "illumio_ops.services.alerts.messages",
    "display.timezone": "illumio_ops.services.alerts.messages",
    "alerts.channels.smtp.enabled": "illumio_ops.services.alerts.channels",
    "alerts.channels.smtp.host": "illumio_ops.services.alerts.channels",
    "alerts.channels.smtp.port": "illumio_ops.services.alerts.channels",
    "alerts.channels.smtp.security": "illumio_ops.services.alerts.channels",
    "alerts.channels.smtp.username": "illumio_ops.services.alerts.channels",
    "alerts.channels.smtp.password": "illumio_ops.services.alerts.channels",
    "alerts.channels.smtp.sender": "illumio_ops.services.alerts.channels",
    "alerts.channels.smtp.recipients": "illumio_ops.services.alerts.channels",
    "alerts.channels.line.enabled": "illumio_ops.services.alerts.channels",
    "alerts.channels.line.access_token": "illumio_ops.services.alerts.channels",
    "alerts.channels.line.target_id": "illumio_ops.services.alerts.channels",
    "alerts.channels.telegram.enabled": "illumio_ops.services.alerts.channels",
    "alerts.channels.telegram.bot_token": "illumio_ops.services.alerts.channels",
    "alerts.channels.telegram.chat_id": "illumio_ops.services.alerts.channels",
    "alerts.channels.teams.enabled": "illumio_ops.services.alerts.channels",
    "alerts.channels.teams.webhook_url": "illumio_ops.services.alerts.channels",
    "alerts.channels.webhook.enabled": "illumio_ops.services.alerts.channels",
    "alerts.channels.webhook.url": "illumio_ops.services.alerts.channels",
}
# Fields whose reader arrives later: value = the task or phase that adds it.
PENDING_READERS: dict[str, str] = {
    "lateral.peer_group_keys": "P4.5 Task 7",
    "lateral.directory_servers": "P4.5 Task 7",
    "lateral.directory_server_ips": "P4.5 Task 7",
    "lateral.suspicious_tools": "P4.5 Task 7",
    "lateral.detectors.peer_min_group": "P4.5 Task 7",
    "lateral.detectors.volume_surge_factor": "P4.5 Task 7",
    "lateral.detectors.volume_min_connections": "P4.5 Task 7",
    "lateral.detectors.volume_min_mb": "P4.5 Task 7",
    "lateral.detectors.directory_min_connections": "P4.5 Task 7",
    "lateral.detectors.account_history_days": "P4.5 Task 7",
    "lateral.detectors.process_history_days": "P4.5 Task 7",
    "lateral.detectors.directory_min_sources": "P4.5 Task 7",
    "lateral.detectors.directory_followup_minutes": "P4.5 Task 7",
}
# Fields with no runtime reader by design.
STRUCTURAL: dict[str, str] = {
    "schema_version": "enforced by the schema's Literal type when the file is loaded",
}


def leaf_paths(model: type[BaseModel] = Settings, prefix: str = "") -> dict[str, tuple[str, str]]:
    """leaf path -> (owner model class name, parent field name)."""
    out: dict[str, tuple[str, str]] = {}
    parent = prefix.rstrip(".").rsplit(".", 1)[-1] if prefix else ""
    for name, field in model.model_fields.items():
        ann = field.annotation
        path = f"{prefix}{name}"
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            out |= leaf_paths(ann, f"{path}.")
        else:
            out[path] = (model.__name__, parent)
    return out


def _evidence(tree: ast.Module) -> tuple[set[str], set[str]]:
    attrs, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attrs.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.rsplit(".", 1)[-1])
    return attrs, names


def find_reader_violations(readers: dict[str, str], pending: dict[str, str], structural: dict[str, str],
                           leaves: dict[str, tuple[str, str]], pkg: Path = PKG_ROOT) -> list[str]:
    out = []
    registered = [*readers, *pending, *structural]
    dupes = {p for p in registered if registered.count(p) > 1}
    out += [f"{p} is registered more than once" for p in sorted(dupes)]
    out += [f"{p} has no registered reader" for p in sorted(set(leaves) - set(registered))]
    out += [f"{p} is registered but not a settings field" for p in sorted(set(registered) - set(leaves))]
    modules = {name: tree for name, tree, _ in iter_modules(pkg)}
    for path, module in sorted(readers.items()):
        if path not in leaves:
            continue
        tree = modules.get(module)
        if tree is None:
            out.append(f"{path}: reader module {module} does not exist")
            continue
        attrs, names = _evidence(tree)
        owner, parent = leaves[path]
        leaf = path.rsplit(".", 1)[-1]
        if leaf not in attrs:
            out.append(f"{path}: {module} never reads .{leaf}")
        elif owner not in names and (not parent or parent not in attrs):
            out.append(f"{path}: {module} reads .{leaf} but shows no sign of {owner}")
    return out


def test_every_settings_field_has_a_reader():
    assert find_reader_violations(SETTINGS_READERS, PENDING_READERS, STRUCTURAL, leaf_paths()) == []


def _pkg(tmp_path: Path, src: str) -> Path:
    root = tmp_path / "illumio_ops"
    root.mkdir()
    (root / "__init__.py").touch()
    (root / "r.py").write_text(src)
    return root


class _Log(BaseModel):
    level: str


class _Other(BaseModel):
    level: str


class _Root(BaseModel):
    logging: _Log
    other: _Other


def test_selftest_unregistered_leaf_is_red(tmp_path):
    v = find_reader_violations({}, {}, {}, leaf_paths(_Root), _pkg(tmp_path, "x = 1\n"))
    assert "logging.level has no registered reader" in v


def test_selftest_same_name_on_another_model_is_red(tmp_path):
    pkg = _pkg(tmp_path, "def f(o):\n    return o.other.level\n")
    v = find_reader_violations({"logging.level": "illumio_ops.r"}, {"other.level": "P9"}, {}, leaf_paths(_Root), pkg)
    assert v == ["logging.level: illumio_ops.r reads .level but shows no sign of _Log"]


def test_selftest_proper_reader_is_green(tmp_path):
    pkg = _pkg(tmp_path, "def f(s):\n    return s.logging.level\n")
    v = find_reader_violations({"logging.level": "illumio_ops.r"}, {"other.level": "P9"}, {}, leaf_paths(_Root), pkg)
    assert v == []


def test_no_p1_pending_left():
    assert [p for p, due in PENDING_READERS.items() if due.startswith("P1-")] == []


def test_no_p4_pending_left():
    # Tasks 5 and 6 add these readers; the gate is green again by the end of Task 9.
    assert [p for p, due in PENDING_READERS.items() if due.startswith("P4-")] == []


def test_no_p2_pending_left():
    assert [p for p, due in PENDING_READERS.items() if due.startswith("P2-")] == []
