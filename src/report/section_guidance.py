"""Section reader-guide registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

ProfileVisibility = Literal["security_risk", "network_inventory"]
DetailLevel = Literal["full"]
Audience = Literal["security", "network", "platform", "app_owner", "executive", "mixed"]


@dataclass(frozen=True)
class SectionGuidance:
    module_id: str
    purpose_key: str
    watch_signals_key: str
    how_to_read_key: str
    recommended_actions_key: str
    primary_audience: Audience = "mixed"
    profile_visibility: tuple[ProfileVisibility, ...] = ("security_risk", "network_inventory")
    min_detail_level: DetailLevel = "full"


# Registry — module_id → SectionGuidance.
# Populated by Tasks 8-11; this skeleton starts empty.
REGISTRY: dict[str, SectionGuidance] = {
    "mod02_policy_decisions": SectionGuidance(
        module_id="mod02_policy_decisions",
        purpose_key="rpt_guidance_mod02_purpose",
        watch_signals_key="rpt_guidance_mod02_signals",
        how_to_read_key="rpt_guidance_mod02_how",
        recommended_actions_key="rpt_guidance_mod02_actions",
        primary_audience="mixed",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="full",
    ),
    "mod03_uncovered_flows": SectionGuidance(
        module_id="mod03_uncovered_flows",
        purpose_key="rpt_guidance_mod03_purpose",
        watch_signals_key="rpt_guidance_mod03_signals",
        how_to_read_key="rpt_guidance_mod03_how",
        recommended_actions_key="rpt_guidance_mod03_actions",
        primary_audience="security",
        profile_visibility=("security_risk",),
        min_detail_level="full",
    ),
    "mod04_ransomware_exposure": SectionGuidance(
        module_id="mod04_ransomware_exposure",
        purpose_key="rpt_guidance_mod04_purpose",
        watch_signals_key="rpt_guidance_mod04_signals",
        how_to_read_key="rpt_guidance_mod04_how",
        recommended_actions_key="rpt_guidance_mod04_actions",
        primary_audience="security",
        profile_visibility=("security_risk",),
        min_detail_level="full",
    ),
    "mod07_cross_label_matrix": SectionGuidance(
        module_id="mod07_cross_label_matrix",
        purpose_key="rpt_guidance_mod07_purpose",
        watch_signals_key="rpt_guidance_mod07_signals",
        how_to_read_key="rpt_guidance_mod07_how",
        recommended_actions_key="rpt_guidance_mod07_actions",
        primary_audience="network",
        profile_visibility=("network_inventory",),
        min_detail_level="full",
    ),
    "mod08_unmanaged_hosts": SectionGuidance(
        module_id="mod08_unmanaged_hosts",
        purpose_key="rpt_guidance_mod08_purpose",
        watch_signals_key="rpt_guidance_mod08_signals",
        how_to_read_key="rpt_guidance_mod08_how",
        recommended_actions_key="rpt_guidance_mod08_actions",
        primary_audience="network",
        profile_visibility=("network_inventory",),
        min_detail_level="full",
    ),
    "mod13_readiness": SectionGuidance(
        module_id="mod13_readiness",
        purpose_key="rpt_guidance_mod13_purpose",
        watch_signals_key="rpt_guidance_mod13_signals",
        how_to_read_key="rpt_guidance_mod13_how",
        recommended_actions_key="rpt_guidance_mod13_actions",
        primary_audience="mixed",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="full",
    ),
    "mod15_lateral_movement": SectionGuidance(
        module_id="mod15_lateral_movement",
        purpose_key="rpt_guidance_mod15_purpose",
        watch_signals_key="rpt_guidance_mod15_signals",
        how_to_read_key="rpt_guidance_mod15_how",
        recommended_actions_key="rpt_guidance_mod15_actions",
        primary_audience="security",
        profile_visibility=("security_risk",),
        min_detail_level="full",
    ),
    "mod_change_impact": SectionGuidance(
        module_id="mod_change_impact",
        purpose_key="rpt_guidance_mod_change_impact_purpose",
        watch_signals_key="rpt_guidance_mod_change_impact_signals",
        how_to_read_key="rpt_guidance_mod_change_impact_how",
        recommended_actions_key="rpt_guidance_mod_change_impact_actions",
        primary_audience="network",
        profile_visibility=("network_inventory",),
        min_detail_level="full",
    ),
    "mod_draft_actions": SectionGuidance(
        module_id="mod_draft_actions",
        purpose_key="rpt_guidance_mod_draft_actions_purpose",
        watch_signals_key="rpt_guidance_mod_draft_actions_signals",
        how_to_read_key="rpt_guidance_mod_draft_actions_how",
        recommended_actions_key="rpt_guidance_mod_draft_actions_actions",
        primary_audience="mixed",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="full",
    ),
    "mod_enforcement_rollout": SectionGuidance(
        module_id="mod_enforcement_rollout",
        purpose_key="rpt_guidance_mod_enf_rollout_purpose",
        watch_signals_key="rpt_guidance_mod_enf_rollout_signals",
        how_to_read_key="rpt_guidance_mod_enf_rollout_how",
        recommended_actions_key="rpt_guidance_mod_enf_rollout_actions",
        primary_audience="security",
        profile_visibility=("security_risk",),
        min_detail_level="full",
    ),
    "mod_exfiltration_intel": SectionGuidance(
        module_id="mod_exfiltration_intel",
        purpose_key="rpt_guidance_mod_exfil_purpose",
        watch_signals_key="rpt_guidance_mod_exfil_signals",
        how_to_read_key="rpt_guidance_mod_exfil_how",
        recommended_actions_key="rpt_guidance_mod_exfil_actions",
        primary_audience="security",
        profile_visibility=("security_risk",),
        min_detail_level="full",
    ),
    "mod_ringfence": SectionGuidance(
        module_id="mod_ringfence",
        purpose_key="rpt_guidance_mod_ringfence_purpose",
        watch_signals_key="rpt_guidance_mod_ringfence_signals",
        how_to_read_key="rpt_guidance_mod_ringfence_how",
        recommended_actions_key="rpt_guidance_mod_ringfence_actions",
        primary_audience="network",
        profile_visibility=("network_inventory",),
        min_detail_level="full",
    ),
    "audit_mod03_policy": SectionGuidance(
        module_id="audit_mod03_policy",
        purpose_key="rpt_guidance_audit_mod03_purpose",
        watch_signals_key="rpt_guidance_audit_mod03_signals",
        how_to_read_key="rpt_guidance_audit_mod03_how",
        recommended_actions_key="rpt_guidance_audit_mod03_actions",
        primary_audience="security",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="full",
    ),
    "audit_mod04_correlation": SectionGuidance(
        module_id="audit_mod04_correlation",
        purpose_key="rpt_guidance_audit_mod04_purpose",
        watch_signals_key="rpt_guidance_audit_mod04_signals",
        how_to_read_key="rpt_guidance_audit_mod04_how",
        recommended_actions_key="rpt_guidance_audit_mod04_actions",
        primary_audience="security",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="full",
    ),
    "pu_mod03_unused_detail": SectionGuidance(
        module_id="pu_mod03_unused_detail",
        purpose_key="rpt_guidance_pu_mod03_purpose",
        watch_signals_key="rpt_guidance_pu_mod03_signals",
        how_to_read_key="rpt_guidance_pu_mod03_how",
        recommended_actions_key="rpt_guidance_pu_mod03_actions",
        primary_audience="mixed",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="full",
    ),
    "pu_mod04_deny_effectiveness": SectionGuidance(
        module_id="pu_mod04_deny_effectiveness",
        purpose_key="rpt_guidance_pu_mod04_purpose",
        watch_signals_key="rpt_guidance_pu_mod04_signals",
        how_to_read_key="rpt_guidance_pu_mod04_how",
        recommended_actions_key="rpt_guidance_pu_mod04_actions",
        primary_audience="security",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="full",
    ),
    "ven_offline": SectionGuidance(
        module_id="ven_offline",
        purpose_key="rpt_guidance_ven_offline_purpose",
        watch_signals_key="rpt_guidance_ven_offline_signals",
        how_to_read_key="rpt_guidance_ven_offline_how",
        recommended_actions_key="rpt_guidance_ven_offline_actions",
        primary_audience="mixed",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="full",
    ),
    "ven_lost_heartbeat_24h": SectionGuidance(
        module_id="ven_lost_heartbeat_24h",
        purpose_key="rpt_guidance_ven_lost_heartbeat_purpose",
        watch_signals_key="rpt_guidance_ven_lost_heartbeat_signals",
        how_to_read_key="rpt_guidance_ven_lost_heartbeat_how",
        recommended_actions_key="rpt_guidance_ven_lost_heartbeat_actions",
        primary_audience="mixed",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="full",
    ),
    "ven_lost_heartbeat_48h": SectionGuidance(
        module_id="ven_lost_heartbeat_48h",
        purpose_key="rpt_guidance_ven_lost_heartbeat_purpose",
        watch_signals_key="rpt_guidance_ven_lost_heartbeat_signals",
        how_to_read_key="rpt_guidance_ven_lost_heartbeat_how",
        recommended_actions_key="rpt_guidance_ven_lost_heartbeat_actions",
        primary_audience="mixed",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="full",
    ),
}


def get_guidance(module_id: str) -> Optional[SectionGuidance]:
    """Return guidance for a module, or None if not registered."""
    return REGISTRY.get(module_id)


def visible_in(module_id: str, profile: ProfileVisibility, detail_level: DetailLevel = "full") -> bool:
    """Return True if the section should render in the given profile."""
    g = REGISTRY.get(module_id)
    if g is None:
        return True  # unregistered modules render by default
    return profile in g.profile_visibility
