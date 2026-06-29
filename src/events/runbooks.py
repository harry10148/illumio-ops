from __future__ import annotations

# Event-type -> operator remediation mapping. Responses are grounded in the
# user's curated Illumio NotebookLM notebook (full Admin/REST/Architecture/Events
# references; regenerated 2026-06-29) and consumed by the alert reporter
# (src/reporter.py add_event_alert). The legacy runbook_url values are retained
# as metadata but are NOT rendered (stale links).

RUNBOOK_CATEGORIES: dict[str, dict] = {
    "security-auth-failure": {
        "patterns": [
            "request.authentication_failed",
            "request.authorization_failed",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/events-administration/event-types.htm",
        "severity_hint": "critical",
        "response": "Review the PCE web console Troubleshooting > Events to identify the source IP address and username attempting access. Check the event details for exceptions, failed authentication, or authorization errors to determine if it is a misconfiguration or a brute force attack. If unexpected API request failures persist, verify the credentials, API key permissions, or SAML integration settings.",
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
        "response": "Navigate to the PCE web console Troubleshooting > Events or Access Management > User Activity to review user session data. Confirm that the login, logout, and session creation events correspond to authorized personnel accessing the system. Investigate any unusual login times, unexpected source IP addresses, or concurrent sessions that might indicate compromised credentials.",
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
        "response": "View these organizational events in the PCE web console under Troubleshooting > Events to audit role based access control modifications. Verify that any user creation, deletion, or permission updates were authorized by a Global Organization Owner. Ensure that users are granted the least privilege required and that scoped roles restrict access to the correct application, environment, and location labels.",
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
        "response": "Check the Organization events export or Troubleshooting > Events in the PCE web console to monitor the lifecycle of API keys. Because API keys provide persistent REST API access for automation and scripts, verify that any new key creation or modification was requested by an authorized user or service account. Ensure that deleted or updated keys belong to inactive scripts or departing administrators.",
    },
    "agent-tampering": {
        "patterns": [
            "agent.tampering",
            "agent.clone_detected",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/ven-administration/ven-tampering-protection.htm",
        "severity_hint": "critical",
        "response": "Immediately investigate the affected workload, as firewall tampering is an early indicator of compromise. View the event details in the PCE web console Troubleshooting > Events to identify if an attacker or administrator added, modified, or flushed the Illumio firewall rules. For clone detected events, determine if a legitimate virtual machine clone occurred and verify if automatic cloned VEN remediation resolved the issue.",
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
        "response": "Monitor these events in the PCE web console Troubleshooting > Events for changes to the VEN protection state. If an agent suspend event appears without scheduled maintenance, investigate immediately because the VEN firewall rules are completely removed and the workload is exposed. For unpair or upgrade events, confirm they align with approved administrative actions or maintenance windows.",
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
        "response": "Review the PCE web console Troubleshooting > Events to pinpoint overly broad ruleset scopes, such as those missing application or environment restrictions. When monitoring security policy create events, check the workloads affected field to see how many workloads received the updated policy. If the number of affected workloads exceeds an acceptable threshold, investigate the associated policy changes for misconfigurations.",
    },
    "enforcement-boundary": {
        "patterns": [
            "enforcement_boundary.create",
            "enforcement_boundary.delete",
            "enforcement_boundary.update",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/security-policy/enforcement-boundaries.htm",
        "severity_hint": "warning",
        "response": "Check the PCE web console Troubleshooting > Events to audit changes to selective enforcement boundaries. Verify that the updated or deleted deny rules correctly reflect the intended restrictions for your high risk ports or applications. Ensure that these enforcement boundaries are not inadvertently blocking legitimate critical traffic or exposing protected workloads.",
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
        "response": "Review the Organization events export or Troubleshooting > Events to track when workloads are created, updated, deleted, or marked unmanaged. Monitor these events to ensure that the workload network interfaces and IP addresses accurately match your environment topology. Investigate unexpected changes to high value workloads, as these modifications can directly alter the security posture and policy enforcement.",
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
        "response": "Navigate to the PCE web console Troubleshooting > Events to audit creations, updates, or deletions of labels and label groups. Monitor these events closely for high value labels, as removing or adding them can represent a significant shift in application environments or security boundaries. Verify that these label changes do not inadvertently grant lower security workloads access to higher security resources.",
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
        "response": "Check the PCE web console Troubleshooting > Events to review modifications to network objects and secure connect gateways. Validate that the network creations or updates correctly represent your current corporate and external data center zones. Ensure these infrastructure changes were performed by an authorized Global Administrator or Organization Owner to prevent disruptions to workload connectivity.",
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
        "response": "View these organizational events in the PCE web console under Troubleshooting > Events to track changes within your Kubernetes or OpenShift environments. Verify that container cluster creations, deletions, and workload profile updates align with expected deployments. Ensure that the enforcement modes and labels applied to these container clusters maintain the required security segmentation.",
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
        "response": "Monitor the PCE web console Troubleshooting > Events to track when IP lists are created, updated, or deleted. Since IP lists are global policy objects used in security rules to allow or block traffic, verify that the IP addresses and CIDR blocks accurately reflect trusted networks or known threats. Confirm that these changes were authorized to prevent accidentally permitting unauthorized external access.",
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
        "response": "Review the PCE web console Troubleshooting > Events to audit any modifications to the PCE authentication settings, including LDAP and SAML configurations. Verify that changes to password policies or single sign on parameters were performed by a Global Organization Owner. Investigate any unauthorized modifications, as they could compromise user authentication and enable unauthorized access to the PCE.",
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
        "response": "Investigate workloads generating these events by viewing the PCE web console Troubleshooting > Events or Organization events export. A missed heartbeats check event indicates a VEN failed to communicate, and the PCE may take the workload offline after a sustained period, removing its IP address from policy. Verify the network connectivity of the affected workloads and ensure the VEN processes are running correctly.",
    },
    "server-errors": {
        "patterns": [
            "request.internal_server_error",
            "request.service_unavailable",
            "request.unknown_server_error",
        ],
        "runbook_url": "https://docs.illumio.com/core/24.2/Content/Guides/pce-administration/troubleshooting.htm",
        "severity_hint": "critical",
        "response": "Review the PCE web console Troubleshooting > Events to identify the specific API endpoint and HTTP status code causing the failure. Examine the application logs on the core nodes and monitor the system resource utilization across the PCE cluster for high CPU, memory, or disk latency. If the server errors are persistent and disrupt PCE operations, gather a PCE Support Report and contact Illumio Support.",
    },
}

_INDEX = {p: c for c, d in RUNBOOK_CATEGORIES.items() for p in d["patterns"]}


def runbook_for(event_type: str) -> dict | None:
    cat = _INDEX.get(event_type)
    return RUNBOOK_CATEGORIES[cat] if cat else None
