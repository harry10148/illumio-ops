"""Normalized PCE event parsing derived from vendor samples and local usage."""

from __future__ import annotations

from typing import Any

from .catalog import is_known_event_type
from .poller import event_identity

_RESOURCE_TYPE_PRIORITY = (
    "user",
    "agent",
    "workload",
    "sec_policy",
    "sec_rule",
    "rule_set",
    "permission",
    "ip_list",
    "label",
    "label_group",
    "service",
    "service_account",
    "network_device",
    "virtual_service",
    "virtual_server",
    "container_cluster",
    "container_workload_profile",
    "cluster",
    "domain",
    "group",
)


def _string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _pick_first(*values: Any) -> str:
    for value in values:
        text = _string(value)
        if text:
            return text
    return ""


def _href_tail(value: Any) -> str:
    text = _string(value)
    if not text or "/" not in text:
        return text
    return text.rstrip("/").rsplit("/", 1)[-1]


def _shorten_api_endpoint(endpoint: str) -> str:
    if not endpoint:
        return ""
    if "/orgs/" not in endpoint:
        return endpoint
    _, _, rest = endpoint.partition("/orgs/")
    _, _, suffix = rest.partition("/")
    for prefix in ("sec_policy/draft/", "sec_policy/active/", "sec_policy/"):
        if suffix.startswith(prefix):
            return "/" + suffix[len(prefix):]
    return "/" + suffix if suffix else endpoint


def _resource_name(resource: Any) -> str:
    if isinstance(resource, list):
        if not resource:
            return ""
        return _resource_name(resource[0])
    if not isinstance(resource, dict):
        return _string(resource)

    if resource.get("key") and resource.get("value"):
        return f"{resource['key']}={resource['value']}"

    if resource.get("first_name") or resource.get("last_name"):
        full_name = f"{_string(resource.get('first_name'))} {_string(resource.get('last_name'))}".strip()
        if full_name:
            return full_name

    for field in ("username", "hostname", "name", "fqdn", "commit_message", "api_endpoint", "href", "value", "ip"):
        value = _string(resource.get(field))
        if value:
            return value

    auth_principal = resource.get("auth_security_principal")
    if isinstance(auth_principal, dict):
        name = _string(auth_principal.get("name"))
        if name:
            return name

    role = resource.get("role")
    if isinstance(role, dict):
        href = _string(role.get("href"))
        if href:
            return href.rsplit("/", 1)[-1]

    return ""


def _extract_resource_entry(resource: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(resource, dict):
        return "", {}

    for resource_type in _RESOURCE_TYPE_PRIORITY:
        value = resource.get(resource_type)
        if isinstance(value, dict):
            return resource_type, value

    for key, value in resource.items():
        if isinstance(value, dict):
            return key, value

    return "", {}


def _resource_from_changes(resource_changes: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(resource_changes, list):
        return "", {}

    for entry in resource_changes:
        if not isinstance(entry, dict):
            continue
        resource_type, resource_obj = _extract_resource_entry(entry.get("resource"))
        if resource_type:
            return resource_type, resource_obj
    return "", {}


def _extract_actor(event: dict[str, Any]) -> tuple[str, str, str, str]:
    created_by = event.get("created_by") or {}
    if not isinstance(created_by, dict):
        text = _string(created_by) or "System"
        return text, "", "", "unknown"

    user = created_by.get("user") or {}
    agent = created_by.get("agent") or {}
    workload = created_by.get("workload") or {}
    container_cluster = created_by.get("container_cluster") or {}

    actor_user = _pick_first(
        user.get("username"),
        user.get("name"),
        workload.get("username"),
    )
    actor_agent = _pick_first(
        agent.get("hostname"),
        agent.get("name"),
        workload.get("hostname"),
        workload.get("name"),
        f"agent:{_href_tail(agent.get('href'))}" if _href_tail(agent.get("href")) else "",
    )
    actor_cluster = _pick_first(
        container_cluster.get("name"),
        f"container_cluster:{_href_tail(container_cluster.get('href'))}" if _href_tail(container_cluster.get("href")) else "",
    )

    if actor_user and actor_agent:
        return f"{actor_user} @ {actor_agent}", actor_user, actor_agent, "user+agent"
    if actor_user:
        return actor_user, actor_user, actor_agent, "user"
    if actor_agent:
        return actor_agent, actor_user, actor_agent, "agent"
    if actor_cluster:
        return actor_cluster, "", actor_cluster, "container_cluster"
    if created_by.get("system") is not None:
        return "System", actor_user, actor_agent, "system"

    return "System", actor_user, actor_agent, "system"


def _extract_source_ip(event: dict[str, Any]) -> str:
    action = event.get("action") or {}
    return _pick_first(
        event.get("src_ip"),
        action.get("src_ip"),
        action.get("source_ip"),
    )


def _extract_action(event: dict[str, Any]) -> tuple[str, str, str]:
    action = event.get("action") or {}
    if not isinstance(action, dict):
        return "", "", ""

    method = _pick_first(action.get("api_method"), action.get("method"))
    path = _pick_first(action.get("api_endpoint"), action.get("path"), action.get("endpoint"))
    path = _shorten_api_endpoint(path)
    action_label = " ".join(part for part in (method, path) if part).strip()
    return method, path, action_label


def _extract_workloads_affected(event: dict[str, Any]) -> int:
    workloads = event.get("workloads_affected")
    if isinstance(workloads, dict):
        for key in ("total_affected", "count", "after"):
            value = workloads.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, dict):
                nested = value.get("total_affected")
                if isinstance(nested, int):
                    return nested

    resource_changes = event.get("resource_changes")
    if not isinstance(resource_changes, list):
        return 0

    for entry in resource_changes:
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("workloads_affected"), int):
            return entry["workloads_affected"]
        changes = entry.get("changes") or {}
        workloads_change = changes.get("workloads_affected")
        if isinstance(workloads_change, dict):
            after = workloads_change.get("after")
            if isinstance(after, int):
                return after
            if isinstance(after, dict):
                nested = after.get("total_affected")
                if isinstance(nested, int):
                    return nested

    return 0


def _extract_notification_user(event: dict[str, Any]) -> str:
    notifications = event.get("notifications")
    if not isinstance(notifications, list):
        return ""
    for entry in notifications:
        if not isinstance(entry, dict):
            continue
        info = entry.get("info") or {}
        user = info.get("user") or {}
        username = _pick_first(user.get("username"), user.get("name"))
        if username:
            return username
    return ""


def _build_parser_notes(event: dict[str, Any], normalized: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    event_type = normalized.get("event_type", "")
    action = event.get("action") or {}
    action_has_endpoint = False
    if isinstance(action, dict):
        action_has_endpoint = any(
            _string(action.get(key))
            for key in ("api_method", "api_endpoint", "method", "path", "endpoint")
        )
    if not normalized.get("known_event_type"):
        notes.append("unknown_event_type")
    if action_has_endpoint and not normalized.get("action"):
        notes.append("action_unresolved")
    if event.get("resource") and not normalized.get("resource_name"):
        notes.append("resource_unresolved")
    if event_type.startswith(("user.", "request.")) and not normalized.get("target_name"):
        notes.append("principal_unresolved")
    if event_type.startswith(("agent.", "agents.")) and not normalized.get("target_name"):
        notes.append("workload_unresolved")
    return notes


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = _string(event.get("event_type"))
    resource_type, resource_obj = _extract_resource_entry(event.get("resource"))
    if not resource_type:
        resource_type, resource_obj = _resource_from_changes(event.get("resource_changes"))

    actor, actor_user, actor_agent, actor_type = _extract_actor(event)
    resource_name = _resource_name(resource_obj)

    target_type = resource_type
    target_name = resource_name
    if event_type.startswith(("user.", "request.")):
        target_type = "user"
        target_name = _pick_first(
            _resource_name((event.get("resource") or {}).get("user")),
            _extract_notification_user(event),
            resource_name,
            actor_user,
        )
    elif event_type.startswith(("agent.", "agents.")):
        target_type = "agent" if resource_type == "agent" else "workload"
        target_name = _pick_first(
            _resource_name((event.get("resource") or {}).get("agent")),
            _resource_name((event.get("resource") or {}).get("workload")),
            resource_name,
            actor_agent,
        )
    elif event_type.startswith("container_cluster."):
        target_type = "container_cluster"
        target_name = _pick_first(
            _resource_name((event.get("resource") or {}).get("container_cluster")),
            resource_name,
            actor if actor_type == "container_cluster" else "",
        )

    if not target_name and actor_type in {"agent", "container_cluster"}:
        target_name = actor if actor != "System" else ""
        if target_name and not target_type:
            target_type = actor_type

    action_method, action_path, action_label = _extract_action(event)
    source_ip = _extract_source_ip(event)
    source = actor + (f" | {source_ip}" if source_ip else "")

    normalized = {
        "event_id": event_identity(event),
        "href": _string(event.get("href")),
        "timestamp": _string(event.get("timestamp")),
        "event_type": event_type,
        "category": event_type.split(".", 1)[0] if "." in event_type else event_type,
        "verb": event_type.rsplit(".", 1)[-1] if "." in event_type else "",
        "status": _string(event.get("status")),
        "severity": _string(event.get("severity")),
        "known_event_type": is_known_event_type(event_type),
        "actor": actor,
        "actor_type": actor_type,
        "actor_user": actor_user,
        "actor_agent": actor_agent,
        "source_ip": source_ip,
        "source": source,
        "target_type": target_type,
        "target_name": target_name,
        "resource_type": resource_type,
        "resource_name": resource_name,
        "action_method": action_method,
        "action_path": action_path,
        "action": action_label,
        "resource_changes_count": len(event.get("resource_changes") or []) if isinstance(event.get("resource_changes"), list) else 0,
        "notifications_count": len(event.get("notifications") or []) if isinstance(event.get("notifications"), list) else 0,
        "workloads_affected": _extract_workloads_affected(event),
    }
    normalized["parser_notes"] = _build_parser_notes(event, normalized)
    return normalized
