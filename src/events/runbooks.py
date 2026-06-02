from __future__ import annotations

RUNBOOK_CATEGORIES: dict[str, dict] = {
    "security-auth-failure": {
        "patterns": [
            "request.authentication_failed",
            "request.authorization_failed",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/events-administration/event-types.htm",
        "severity_hint": "critical",
        "response": (
            "Immediate action required. Review the source IP and username.\n"
            "Multiple failures from the same IP may indicate brute force attack.\n"
            "Check if the account is locked. Review API key expiration dates.\n"
        ),
    },
    "security-auth-activity": {
        "patterns": [
            "user.login",
            "user.logout",
            "user.sign_in",
            "user.sign_out",
            "user.authenticate",
            "user.create_session",
            "user.pce_session_terminated",
            "user.login_session_terminated",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/events-administration/event-types.htm",
        "severity_hint": "info",
        "response": (
            "Normal authentication activity. Monitor for unusual patterns:\n"
            "logins at odd hours, from new IPs, or failed attempts preceding success.\n"
        ),
    },
    "security-user-management": {
        "patterns": [
            "user.create",
            "user.delete",
            "user.update",
            "user.invite",
            "user.accept_invitation",
            "user.reset_password",
            "user.update_password",
            "user.use_expired_password",
            "user.verify_mfa",
            "user_local_profile.create",
            "user_local_profile.delete",
            "user_local_profile.reinvite",
            "user_local_profile.update_password",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/user-administration/user-management.htm",
        "severity_hint": "warning",
        "response": (
            "User account change detected. Verify the change was authorized.\n"
            "Check who made the change (created_by). Ensure MFA is enforced\n"
            "for all administrative accounts.\n"
        ),
    },
    "security-api-keys": {
        "patterns": [
            "api_key.create",
            "api_key.delete",
            "api_key.update",
            "service_account.create",
            "service_account.delete",
            "service_account.update",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/rest-api/authentication-and-api-keys.htm",
        "severity_hint": "warning",
        "response": (
            "API key lifecycle event. Verify the change was authorized.\n"
            "Deleted keys may break integrations. New keys should follow\n"
            "least-privilege principles. Check key expiration settings.\n"
        ),
    },
    "agent-tampering": {
        "patterns": [
            "agent.tampering",
            "agent.clone_detected",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/ven-administration/ven-tampering-protection.htm",
        "severity_hint": "critical",
        "response": (
            "CRITICAL: VEN tampering or clone detected. This may indicate\n"
            "the workload has been compromised. Immediately:\n"
            "1. Isolate the workload from the network\n"
            "2. Check for unauthorized processes or modifications\n"
            "3. Review recent SSH/RDP access to the workload\n"
            "4. Consider re-pairing the VEN after investigation\n"
        ),
    },
    "agent-lifecycle": {
        "patterns": [
            "agent.activate",
            "agent.deactivate",
            "agent.suspend",
            "agent.unsuspend",
            "agent.update",
            "agent.goodbye",
            "agent.refresh_token",
            "agent.machine_identifier",
            "agents.unpair",
            "agents.clear_conditions",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/ven-administration/managing-vens.htm",
        "severity_hint": "info",
        "response": (
            "VEN lifecycle event. Activation/deactivation is normal during\n"
            "deployment. Unexpected deactivation or unpair may indicate\n"
            "workload decommissioning or administrative action. Check\n"
            "the actor and verify against change management records.\n"
        ),
    },
    "policy-changes": {
        "patterns": [
            "rule_set.create",
            "rule_set.delete",
            "rule_set.update",
            "rule_sets.delete",
            "sec_rule.create",
            "sec_rule.delete",
            "sec_rule.update",
            "sec_policy.create",
            "sec_policy.restore",
            "sec_policy_pending.delete",
            "deny_rule.create",
            "deny_rule.delete",
            "deny_rule.update",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/security-policy/overview-of-security-policy.htm",
        "severity_hint": "warning",
        "response": (
            "Security policy modification detected. Verify the change was\n"
            "authorized and review the policy diff. Key checks:\n"
            "1. Was this change in a change management ticket?\n"
            "2. Does the change follow segmentation standards?\n"
            "3. Are any deny rules being weakened?\n"
            "4. Review the provisioned vs draft policy state.\n"
        ),
    },
    "enforcement-boundary": {
        "patterns": [
            "enforcement_boundary.create",
            "enforcement_boundary.delete",
            "enforcement_boundary.update",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/security-policy/enforcement-boundaries.htm",
        "severity_hint": "warning",
        "response": (
            "Enforcement boundary changed. Boundaries define the scope of\n"
            "policy enforcement. Verify the change doesn't expose\n"
            "previously protected segments.\n"
        ),
    },
    "workload-changes": {
        "patterns": [
            "workload.create",
            "workload.delete",
            "workload.update",
            "workload.undelete",
            "workload.online",
            "workload.upgrade",
            "workloads.bulk_create",
            "workloads.bulk_delete",
            "workloads.bulk_update",
            "workloads.apply_policy",
            "workloads.unpair",
            "workloads.set_labels",
            "workloads.remove_labels",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/workload-management/workload-operations.htm",
        "severity_hint": "info",
        "response": (
            "Workload lifecycle event. Bulk operations should be verified\n"
            "against change management. Label changes affect policy\n"
            "application. Verify labels match intended segmentation.\n"
        ),
    },
    "label-changes": {
        "patterns": [
            "label.create",
            "label.delete",
            "label.update",
            "label_group.create",
            "label_group.delete",
            "label_group.update",
            "labels.delete",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/workload-management/labels-and-label-groups.htm",
        "severity_hint": "info",
        "response": (
            "Label taxonomy change. Labels are the foundation of Illumio\n"
            "segmentation policy. Deleted labels may orphan workloads from\n"
            "policy. New labels should follow naming conventions.\n"
        ),
    },
    "network-infrastructure": {
        "patterns": [
            "network.create",
            "network.delete",
            "network.update",
            "network_device.create",
            "network_device.delete",
            "network_device.update",
            "network_enforcement_node.activate",
            "network_enforcement_node.deactivate",
            "network_enforcement_node.degraded",
            "network_enforcement_node.missed_heartbeats",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/network-enforcement/overview.htm",
        "severity_hint": "warning",
        "response": (
            "Network infrastructure change. NEN degradation or missed\n"
            "heartbeats may indicate connectivity issues. Device changes\n"
            "should align with network change management.\n"
        ),
    },
    "container-events": {
        "patterns": [
            "container_cluster.create",
            "container_cluster.delete",
            "container_cluster.update",
            "container_cluster.security_policy_applied",
            "container_cluster.security_policy_acks",
            "container_workload_profile.create",
            "container_workload_profile.delete",
            "container_workload_profile.update",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/kubernetes-and-openshift/overview.htm",
        "severity_hint": "info",
        "response": (
            "Container/Kubernetes cluster event. Policy application and\n"
            "acknowledgement events are normal during cluster operations.\n"
            "Profile changes affect how container workloads are segmented.\n"
        ),
    },
    "ip-list-changes": {
        "patterns": [
            "ip_list.create",
            "ip_list.delete",
            "ip_list.update",
            "ip_lists.delete",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/security-policy/ip-lists.htm",
        "severity_hint": "warning",
        "response": (
            "IP list modification. IP lists define network ranges in\n"
            "policy rules. Changes may affect which external systems can\n"
            "communicate with segmented workloads.\n"
        ),
    },
    "auth-config": {
        "patterns": [
            "authentication_settings.update",
            "ldap_config.create",
            "ldap_config.delete",
            "ldap_config.update",
            "saml_config.create",
            "saml_config.delete",
            "saml_config.update",
            "radius_config.create",
            "radius_config.delete",
            "radius_config.update",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/user-administration/authentication-configuration.htm",
        "severity_hint": "critical",
        "response": (
            "Authentication configuration changed. This is a high-impact\n"
            "change that affects how all users authenticate. Verify:\n"
            "1. Was this an authorized change?\n"
            "2. Test login with the new configuration immediately\n"
            "3. Have a rollback plan ready\n"
            "4. Monitor for authentication failures after the change\n"
        ),
    },
    "system-tasks": {
        "patterns": [
            "system_task.agent_missed_heartbeats_check",
            "system_task.agent_offline_check",
            "system_task.prune_old_log_events",
            "system_task.compute_policy_for_unmanaged_workloads",
            "system_task.provision_container_cluster_services",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/pce-administration/system-tasks.htm",
        "severity_hint": "info",
        "response": (
            "Automated system maintenance task. These are normal operations.\n"
            "Agent offline/missed heartbeat checks may generate follow-up\n"
            "events if agents are unreachable.\n"
        ),
    },
    "server-errors": {
        "patterns": [
            "request.internal_server_error",
            "request.service_unavailable",
            "request.unknown_server_error",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/pce-administration/troubleshooting.htm",
        "severity_hint": "critical",
        "response": (
            "PCE server error detected. Check PCE health status and logs.\n"
            "Repeated errors may indicate infrastructure issues.\n"
            "Contact Illumio support if errors persist.\n"
        ),
    },
}

_INDEX = {p: c for c, d in RUNBOOK_CATEGORIES.items() for p in d["patterns"]}


def runbook_for(event_type: str) -> dict | None:
    cat = _INDEX.get(event_type)
    return RUNBOOK_CATEGORIES[cat] if cat else None
