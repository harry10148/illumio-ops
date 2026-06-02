"""Vendor-derived PCE event catalog.

This list is based on alexgoller/illumio-pretty-cool-events and is used as a
baseline to detect unknown or newly introduced event types.

Some real PCE builds emit additional event types that are not present in the
reference catalog. Those are tracked separately as local extensions so the
viewer can distinguish vendor baseline from environment-observed additions.
"""
from __future__ import annotations

KNOWN_EVENT_TYPES = {
    "access_restriction.create",
    "access_restriction.delete",
    "access_restriction.update",
    "agent.activate",
    "agent.activate_clone",
    "agent.clone_detected",
    "agent.deactivate",
    "agent.generate_maintenance_token",
    "agent.goodbye",
    "agent.machine_identifier",
    "agent.refresh_token",
    "agent.reguest_policy",
    "agent.request_policy",
    "agent.request_upgrade",
    "agent.service_not_available",
    "agent.suspend",
    "agent.tampering",
    "agent.unsuspend",
    "agent.update",
    "agent.update_interactive_users",
    "agent.update_iptables_href",
    "agent.update_running_containers",
    "agent.upgrade_successful",
    "agent.upload_existing_ip_table_rules",
    "agent.upload_support_report",
    "agent_support_report_request.create",
    "agent_support_report_request.delete",
    "agents.clear_conditions",
    "agents.unpair",
    "api_key.create",
    "api_key.delete",
    "api_key.update",
    "auth_security_principal.create",
    "auth_security_principal.delete",
    "auth_security_principal.update",
    "authentication_settings.update",
    "cluster.create",
    "cluster.delete",
    "cluster.update",
    "container_workload.update",
    "container_cluster.create",
    "container_cluster.delete",
    "container_cluster.kubernetes_workloads_bulk_create",
    "container_cluster.kubernetes_workloads_bulk_update",
    "container_cluster.update",
    "container_cluster.update_label_map",
    "container_cluster.update_services",
    "container_workload_profile.create",
    "container_workload_profile.delete",
    "container_workload_profile.update",
    "database.temp_table_autocleanup_started",
    "database.temp_table_autocleanup_completed",
    "deny_rule.create",
    "deny_rule.delete",
    "deny_rule.update",
    "domain.create",
    "domain.delete",
    "domain.update",
    "enforcement_boundary.create",
    "enforcement_boundary.delete",
    "enforcement_boundary.update",
    "event_settings.update",
    "firewall_settings.update",
    "group.create",
    "group.update",
    "ip_list.create",
    "ip_list.delete",
    "ip_list.update",
    "ip_lists.delete",
    "ip_tables_rule.create",
    "ip_tables_rule.delete",
    "ip_tables_rule.update",
    "job.delete",
    "label.create",
    "label.delete",
    "label.update",
    "label_dimension.create",
    "label_dimension.delete",
    "label_dimension.update",
    "label_group.create",
    "label_group.delete",
    "label_group.update",
    "label_mapping_rule.create",
    "label_mapping_rule.delete",
    "label_mapping_rule.update",
    "labels.delete",
    "ldap_config.create",
    "ldap_config.delete",
    "ldap_config.update",
    "ldap_config.verify_connection",
    "license.delete",
    "license.update",
    "login_proxy_ldap_config.create",
    "login_proxy_ldap_config.delete",
    "login_proxy_ldap_config.update",
    "login_proxy_ldap_config.verify_connection",
    "login_proxy_msp_tenants.create",
    "login_proxy_msp_tenants.delete",
    "login_proxy_msp_tenants.update",
    "login_proxy_orgs.create",
    "login_proxy_orgs.delete",
    "login_proxy_orgs.update",
    "lost_agent.found",
    "network.create",
    "network.delete",
    "network.update",
    "network_device.ack_enforcement_instructions_applied",
    "network_device.assign_workload",
    "network_device.create",
    "network_device.delete",
    "network_device.update",
    "network_devices.ack_multi_enforcement_instructions_applied",
    "network_endpoint.create",
    "network_endpoint.delete",
    "network_endpoint.update",
    "network_enforcement_node.activate",
    "network_enforcement_node.clear_conditions",
    "network_enforcement_node.deactivate",
    "network_enforcement_node.degraded",
    "network_enforcement_node.missed_heartbeats",
    "network_enforcement_node.missed_heartbeats_check",
    "network_enforcement_node.network_devices_network_endpoints_workloads",
    "network_enforcement_node.policy_ack",
    "network_enforcement_node.request_policy",
    "network_enforcement_node.update_status",
    "network_enforcement_nodes.clear_conditions",
    "nfc.activate",
    "nfc.delete",
    "nfc.update_discovered_virtual_servers",
    "nfc.update_policy_status",
    "nfc.update_slb_state",
    "org.create",
    "org.recalc_rules",
    "org.update",
    "pairing_profile.create",
    "pairing_profile.create_pairing_key",
    "pairing_profile.delete",
    "pairing_profile.update",
    "pairing_profile.delete_all_pairing_keys",
    "pairing_profiles.delete",
    "password_policy.create",
    "password_policy.delete",
    "password_policy.update",
    "permission.create",
    "permission.delete",
    "permission.update",
    "radius_config.create",
    "radius_config.delete",
    "radius_config.update",
    "radius_config.verify_shared_secret",
    "request.authentication_failed",
    "request.authorization_failed",
    "request.internal_server_error",
    "request.service_unavailable",
    "request.unknown_server_error",
    "resource.create",
    "resource.delete",
    "resource.update",
    "rule_set.create",
    "rule_set.delete",
    "rule_set.update",
    "rule_sets.delete",
    "saml_acs.update",
    "saml_config.create",
    "saml_config.delete",
    "saml_config.pce_signing_cert",
    "saml_config.update",
    "saml_sp_config.create",
    "saml_sp_config.delete",
    "saml_sp_config.update",
    "sec_policy.create",
    "sec_policy_pending.delete",
    "sec_policy.restore",
    "sec_rule.create",
    "sec_rule.delete",
    "sec_rule.update",
    "secure_connect_gateway.create",
    "secure_connect_gateway.delete",
    "secure_connect_gateway.update",
    "security_principal.create",
    "security_principal.delete",
    "security_principal.update",
    "security_principals.bulk_create",
    "service.create",
    "service.delete",
    "service.update",
    "service_account.create",
    "service_account.delete",
    "service_account.update",
    "service_binding.create",
    "service_binding.delete",
    "service_bindings.delete",
    "services.delete",
    "settings.update",
    "slb.create",
    "slb.delete",
    "slb.update",
    "support_report.upload",
    "syslog_destination.create",
    "syslog_destination.delete",
    "syslog_destination.update",
    "system_task.agent_missed_heartbeats_check",
    "system_task.agent_missing_heartbeats_after_upgrade",
    "system_task.agent_offline_check",
    "system_task.agent_self_signed_certs_check",
    "system_task.agent_settings_invalidation_error_state_check",
    "system_task.agent_uninstall_timeout",
    "system_task.clear_auth_recover_condition",
    "system_task.compute_policy_for_unmanaged_workloads",
    "system_task.delete_expired_service_account_api_keys",
    "system_task.delete_old_cached_perspectives",
    "system_task.endpoint_offline_check",
    "system_task.provision_container_cluster_services",
    "system_task.prune_old_log_events",
    "system_task.remove_stale_zone_subsets",
    "system_task.set_server_sync_check",
    "system_task.vacuum_deactivated_agent_and_deleted_workloads",
    "traffic_collector_setting.create",
    "traffic_collector_setting.delete",
    "traffic_collector_setting.update",
    "trusted_proxy_ips.update",
    "user.accept_invitation",
    "user.authenticate",
    "user.create",
    "user.delete",
    "user.invite",
    "user.login",
    "user.login_session_terminated",
    "user.logout",
    "user.pce_session_terminated",
    "user.reset_password",
    "user.sign_in",
    "user.sign_out",
    "user.update",
    "user.update_password",
    "user.use_expired_password",
    "user.verify_mfa",
    "users.auth_token",
    "user_local_profile.create",
    "user_local_profile.delete",
    "user_local_profile.reinvite",
    "user_local_profile.update_password",
    "ven_settings.update",
    "ven_software.upgrade",
    "ven_software_release.create",
    "ven_software_release.delete",
    "ven_software_release.deploy",
    "ven_software_release.update",
    "ven_software_releases.set_default_version",
    "virtual_server.create",
    "virtual_server.delete",
    "virtual_server.update",
    "virtual_service.create",
    "virtual_service.delete",
    "virtual_service.update",
    "virtual_services.bulk_create",
    "virtual_services.bulk_update",
    "vulnerability.create",
    "vulnerability.delete",
    "vulnerability.update",
    "vulnerability_report.delete",
    "vulnerability_report.update",
    "workload.create",
    "workload.delete",
    "workload.online",
    "workload.recalc_rules",
    "workload.redetect_network",
    "workload.undelete",
    "workload.update",
    "workload.upgrade",
    "workload_interface.create",
    "workload_interface.delete",
    "workload_interface.update",
    "workload_interfaces.update",
    "workload_service_report.update",
    "workload_settings.update",
    "workloads.apply_policy",
    "workloads.bulk_create",
    "workloads.bulk_delete",
    "workloads.bulk_update",
    "workloads.remove_labels",
    "workloads.set_flow_reporting_frequency",
    "workloads.set_labels",
    "workloads.unpair",
    "workloads.update",
}

LOCAL_EXTENSION_EVENT_TYPES = {
    "container_cluster.security_policy_applied",
    "container_cluster.security_policy_acks",
    "user.create_session",
}

KNOWN_EVENT_TYPES |= LOCAL_EXTENSION_EVENT_TYPES


# Resource-prefix → category mapping for events whose exact event_type is
# unknown but whose `resource.action` shape matches a known resource family.
# This is the second line of defence after KNOWN_EVENT_TYPES: when PCE 25.x+
# introduces new actions on existing resources (e.g. deny_rule.bulk_delete,
# agent.upgrade_failed), the analyzer can still classify them rather than
# bucket them into "unknown". The exact event_type IS still recorded in
# unknown_events for catalog maintenance, but the analyzer can choose to
# treat lenient-known events differently (e.g. not alert noise).
KNOWN_RESOURCE_PREFIXES: frozenset[str] = frozenset({
    "access_restriction", "agent", "agent_support_report_request", "agents",
    "api_key", "auth_security_principal", "authentication_settings",
    "cluster", "container_cluster", "container_workload",
    "container_workload_profile", "database", "deny_rule", "domain",
    "enforcement_boundary", "event_settings", "firewall_settings",
    "group", "ip_list", "ip_lists", "ip_tables_rule", "job",
    "label", "label_dimension", "label_group", "label_mapping_rule",
    "labels", "ldap_config", "license",
    "network", "network_enforcement_node",
    "org", "organization", "pairing_profile", "permission",
    "policy_object_selector", "policy_settings", "policy_update",
    "ps_event", "ps_event_export",
    "request", "request_log", "rule_set", "sec_policy",
    "sec_policy_pending", "sec_policy_restore", "sec_rule",
    "secure_connect_gateway", "service", "service_binding",
    "service_provisioner", "session", "settings",
    "support_bundle_request", "syslog_destination", "system_task",
    "trusted_proxy_ips", "user", "user_login", "users",
    "vens", "virtual_server", "virtual_service",
    "vulnerability", "vulnerability_report", "workload",
    "workload_interface_scan", "workload_settings", "workloads",
})


def _split_event_type(event_type: str) -> tuple[str, str]:
    """Split 'resource.action' into (resource, action). Returns ('', '') if
    event_type is malformed (no '.' separator, empty, etc.)."""
    if not event_type or "." not in event_type:
        return "", ""
    resource, _, action = event_type.partition(".")
    return resource, action


def is_known_event_type(
    event_type: str,
    lenient: bool = False,
    *,
    resource_type: str | None = None,
) -> bool:
    """Return True if event_type is in the explicit catalog.

    When `lenient=True`, also return True if EITHER:
      (a) the event_type resource prefix (`<resource>.<action>` → `<resource>`)
          is in KNOWN_RESOURCE_PREFIXES; OR
      (b) the optional `resource_type` hint (typically extracted by the
          normalizer from `resource_changes[0].resource` first key in the
          PCE payload) is in KNOWN_RESOURCE_PREFIXES.

    The (b) path is the third fallback: it salvages events whose event_type
    is malformed (e.g. missing the dot) or whose action prefix doesn't
    match an event_type pattern but whose payload structure clearly
    identifies the resource family.
    """
    if event_type in KNOWN_EVENT_TYPES:
        return True
    if lenient:
        resource, action = _split_event_type(event_type)
        if resource and action and resource in KNOWN_RESOURCE_PREFIXES:
            return True
        if resource_type and resource_type in KNOWN_RESOURCE_PREFIXES:
            return True
    return False


def classify_unknown_event_type(
    event_type: str,
    *,
    resource_type: str | None = None,
) -> str:
    """Best-effort category for an event_type not in KNOWN_EVENT_TYPES.

    Resolution order:
      1. event_type resource prefix matches KNOWN_RESOURCE_PREFIXES
      2. explicit `resource_type` hint (from payload) matches KNOWN_RESOURCE_PREFIXES
      3. 'unclassified' for genuinely novel resource families

    The `resource_type` hint should come from the normalizer's
    `resource_changes[0].resource` first-key extraction (see
    `src/events/normalizer.py::_resource_from_changes`).
    """
    resource, action = _split_event_type(event_type)
    if resource and action and resource in KNOWN_RESOURCE_PREFIXES:
        return resource
    if resource_type and resource_type in KNOWN_RESOURCE_PREFIXES:
        return resource_type
    return "unclassified"


# ---------------------------------------------------------------------------
# Wizard-facing event catalog (extracted from src/settings/_legacy.py, H6).
# ---------------------------------------------------------------------------

# 1. Legacy stub dict — seeds _LEGACY_EVENT_CATALOG / _EVENT_CATEGORY_OVERRIDES
#    before the full catalog is built.  Renamed from the original FULL_EVENT_CATALOG
#    stub to avoid a forward-reference conflict with the real FULL_EVENT_CATALOG below.
_LEGACY_STUB = {
    "General": {"*": "event_all_events"},
    "Agent Health": {
        "system_task.agent_missed_heartbeats_check": "event_agent_missed_heartbeats",
        "system_task.agent_offline_check": "event_agent_offline",
        "lost_agent.found": "event_lost_agent_found",
        "agent.service_not_available": "event_agent_service_not_available",
    },
    "Agent Security": {
        "agent.tampering": "event_agent_tampering",
        "agent.clone_detected": "event_agent_clone_detected",
        "agent.activate": "event_agent_activate",
        "agent.deactivate": "event_agent_deactivate",
    },
    "User Access": {
        "user.authenticate": "event_user_authenticate",
        "user.sign_in": "event_user_sign_in",
        "user.sign_out": "event_user_sign_out",
        "user.login_session_terminated": "event_user_login_session_terminated",
        "user.pce_session_terminated": "event_user_pce_session_terminated",
    },
    "Agent Health Detail": {
        "agent.goodbye": "event_agent_goodbye",
        "agent.suspend": "event_agent_suspend",
        "agent.refresh_policy": "event_agent_refresh_policy",
        "agent.upgrade_successful": "event_agent_upgrade_successful",
    },
    "Auth & API": {
        "request.authentication_failed": "event_api_auth_failed",
        "request.authorization_failed": "event_api_authz_failed",
        "api_key.create": "event_api_key_create",
        "api_key.delete": "event_api_key_delete",
    },
    "Policy": {
        "rule_set.delete": "event_ruleset_delete",
        "rule_set.create": "event_ruleset_create",
        "rule_set.update": "event_ruleset_update",
        "sec_rule.create": "event_rule_create",
        "sec_rule.update": "event_rule_update",
        "sec_rule.delete": "event_rule_delete",
        "sec_policy.create": "event_policy_prov",
    },
    "System": {
        "cluster.update": "event_cluster_update",
    },
}

# 2. Intermediate constants built from _LEGACY_STUB
_LEGACY_EVENT_CATALOG = _LEGACY_STUB
_EVENT_CATEGORY_OVERRIDES = {
    event_id: category
    for category, events in _LEGACY_EVENT_CATALOG.items()
    for event_id in events
}
_EVENT_DESCRIPTION_OVERRIDES = {
    event_id: description
    for events in _LEGACY_EVENT_CATALOG.values()
    for event_id, description in events.items()
}

# 3. Builder configuration
_CATEGORY_ORDER = [
    "General",
    "Agent Health",
    "Agent Operations",
    "Agent Security",
    "User Access",
    "Auth & API",
    "Policy",
    "Containers & Workloads",
    "Network & Integrations",
    "Platform & System",
    "Inventory & Identity",
]
_HIDDEN_EVENT_TYPES = {
    "agent.reguest_policy",
}
_STATUS_FILTER_EVENT_TYPES = {
    "request.authentication_failed",
    "request.authorization_failed",
    "request.internal_server_error",
    "request.service_unavailable",
    "request.unknown_server_error",
    "user.authenticate",
    "user.login",
    "user.logout",
    "user.sign_in",
    "user.sign_out",
    "user.verify_mfa",
}
_SEVERITY_FILTER_EVENT_TYPES = set(_STATUS_FILTER_EVENT_TYPES)

# 4. Helper functions
def _humanize_event_id(event_id: str) -> str:
    if event_id == "*":
        return "All events"
    text = event_id.replace(".", " ").replace("_", " ").strip()
    if not text:
        return event_id
    return " ".join(part.capitalize() for part in text.split())

def _event_category(event_id: str) -> str:
    if event_id == "*":
        return "General"
    if event_id.startswith(("ip_tables_rule.", "sec_policy_pending.")):
        return "Policy"
    if event_id.startswith(("security_principals.", "security_principal.")):
        return "Inventory & Identity"
    if event_id.startswith(("system_task.", "database.", "event_settings.", "settings.", "org.", "cluster.", "job.", "license.")):
        return "Platform & System"
    if event_id.startswith(("agent.", "agents.", "lost_agent.")):
        if any(token in event_id for token in ("tampering", "clone", "missed_heartbeats", "offline")):
            return "Agent Security"
        if event_id.startswith((
            "agent.generate_maintenance_token",
            "agent.machine_identifier",
            "agent.refresh_token",
            "agent.reguest_policy",
            "agent.request_policy",
            "agent.request_upgrade",
            "agent.update",
            "agent.update_",
            "agent.upload_",
            "agent.activate",
            "agent.deactivate",
            "agent.unsuspend",
            "agents.clear_conditions",
            "agents.unpair",
            "agent_support_report_request.",
        )):
            return "Agent Operations"
        return "Agent Health"
    if event_id in _EVENT_CATEGORY_OVERRIDES:
        category = _EVENT_CATEGORY_OVERRIDES[event_id]
        if category == "Agent Health Detail":
            return "Agent Health"
        if category == "System":
            return "Platform & System"
        return category
    if event_id.startswith(("user.", "users.", "user_local_profile.")):
        return "User Access"
    if event_id.startswith((
        "request.",
        "api_key.",
        "auth_security_principal.",
        "authentication_settings.",
        "ldap_config.",
        "login_proxy_",
        "password_policy.",
        "radius_config.",
        "saml_",
        "security_principal.",
    )):
        return "Auth & API"
    if event_id.startswith((
        "rule_set.",
        "rule_sets.",
        "sec_rule.",
        "sec_policy.",
        "access_restriction.",
        "enforcement_boundary.",
        "firewall_settings.",
        "ip_list.",
        "ip_lists.",
        "label.",
        "label_group.",
        "labels.",
        "pairing_profile.",
        "pairing_profiles.",
        "permission.",
        "service.",
        "services.",
        "service_binding.",
        "service_bindings.",
        "service_account.",
        "trusted_proxy_ips.",
    )):
        return "Policy"
    if event_id.startswith((
        "container_cluster.",
        "container_workload.",
        "container_workload_profile.",
        "ven_settings.",
        "ven_software",
        "workload.",
        "workload_interface.",
        "workload_interfaces.",
        "workload_service_report.",
        "workload_settings.",
        "workloads.",
    )):
        return "Containers & Workloads"
    if event_id.startswith((
        "network.",
        "network_device.",
        "network_devices.",
        "network_endpoint.",
        "network_enforcement_node.",
        "network_enforcement_nodes.",
        "nfc.",
        "secure_connect_gateway.",
        "slb.",
        "syslog_destination.",
        "traffic_collector_setting.",
        "virtual_server.",
        "virtual_service.",
        "virtual_services.",
    )):
        return "Network & Integrations"
    if event_id.startswith((
        "domain.",
        "group.",
        "resource.",
        "support_report.",
        "agent_support_report_request.",
        "vulnerability.",
        "vulnerability_report.",
    )):
        return "Inventory & Identity"
    return "General"

def _event_translation_key(event_id: str) -> str:
    if event_id in _EVENT_DESCRIPTION_OVERRIDES:
        return _EVENT_DESCRIPTION_OVERRIDES[event_id]
    return "event_label_" + event_id.replace(".", "_")

def _build_full_event_catalog() -> dict[str, dict[str, str]]:
    buckets: dict[str, dict[str, str]] = {category: {} for category in _CATEGORY_ORDER}
    for event_id in sorted({"*"} | set(KNOWN_EVENT_TYPES)):
        if event_id in _HIDDEN_EVENT_TYPES:
            continue
        category = _event_category(event_id)
        buckets.setdefault(category, {})
        buckets[category][event_id] = _event_translation_key(event_id)
    return {category: events for category, events in buckets.items() if events}

# 5. Final computed constants — module-load-time
FULL_EVENT_CATALOG = _build_full_event_catalog()
ACTION_EVENTS = sorted(event_id for event_id in KNOWN_EVENT_TYPES if event_id in _STATUS_FILTER_EVENT_TYPES)
SEVERITY_FILTER_EVENTS = sorted(event_id for event_id in KNOWN_EVENT_TYPES if event_id in _SEVERITY_FILTER_EVENT_TYPES)
DISCOVERY_EVENTS = sorted(set(KNOWN_EVENT_TYPES) - set(ACTION_EVENTS))

# 6. Description / tips lookup dicts
EVENT_DESCRIPTION_KEYS = {
    et: "event_desc_" + et.replace(".", "_")
    for et in sorted(KNOWN_EVENT_TYPES - _HIDDEN_EVENT_TYPES)
}

EVENT_TIPS_KEYS = {
    "*":                                          "event_tips_all",
    "agent.goodbye":                              "event_tips_agent_goodbye",
    "agent.service_not_available":                "event_tips_agent_service_not_available",
    "agent.suspend":                              "event_tips_agent_suspend",
    "agent.refresh_policy":                       "event_tips_agent_refresh_policy",
    "agent.activate":                             "event_tips_agent_activate",
    "agent.deactivate":                           "event_tips_agent_deactivate",
    "agent.tampering":                            "event_tips_agent_tampering",
    "agent.clone_detected":                       "event_tips_agent_clone_detected",
    "lost_agent.found":                           "event_tips_lost_agent_found",
    "system_task.agent_missed_heartbeats_check":  "event_tips_system_task_agent_missed_heartbeats_check",
    "system_task.agent_offline_check":            "event_tips_system_task_agent_offline_check",
    "user.authenticate":                          "event_tips_user_authenticate",
    "user.sign_in":                               "event_tips_user_sign_in",
    "user.sign_out":                              "event_tips_user_sign_out",
    "user.login_session_terminated":              "event_tips_user_login_session_terminated",
    "user.pce_session_terminated":                "event_tips_user_pce_session_terminated",
    "request.authentication_failed":              "event_tips_request_authentication_failed",
    "request.authorization_failed":               "event_tips_request_authorization_failed",
    "api_key.create":                             "event_tips_api_key_create",
    "api_key.delete":                             "event_tips_api_key_delete",
    "rule_set.create":                            "event_tips_rule_set_create",
    "rule_set.update":                            "event_tips_rule_set_update",
    "rule_set.delete":                            "event_tips_rule_set_delete",
    "sec_rule.create":                            "event_tips_sec_rule_create",
    "sec_rule.update":                            "event_tips_sec_rule_update",
    "sec_rule.delete":                            "event_tips_sec_rule_delete",
    "sec_policy.create":                          "event_tips_sec_policy_create",
    "enforcement_boundary.create":                "event_tips_enforcement_boundary_create",
    "enforcement_boundary.delete":                "event_tips_enforcement_boundary_delete",
    "firewall_settings.update":                   "event_tips_firewall_settings_update",
    "cluster.update":                             "event_tips_cluster_update",
    "workloads.unpair":                           "event_tips_workloads_unpair",
    "network_enforcement_node.missed_heartbeats": "event_tips_nen_missed_heartbeats",
    "network_enforcement_node.degraded":          "event_tips_nen_degraded",
}
