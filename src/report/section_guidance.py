"""Section reader-guide registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

ProfileVisibility = Literal["security_risk", "network_inventory"]
DetailLevel = Literal["executive", "standard", "full"]
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
    min_detail_level: DetailLevel = "standard"


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
        min_detail_level="standard",
    ),
    "mod03_uncovered_flows": SectionGuidance(
        module_id="mod03_uncovered_flows",
        purpose_key="rpt_guidance_mod03_purpose",
        watch_signals_key="rpt_guidance_mod03_signals",
        how_to_read_key="rpt_guidance_mod03_how",
        recommended_actions_key="rpt_guidance_mod03_actions",
        primary_audience="security",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="standard",
    ),
    "mod04_ransomware_exposure": SectionGuidance(
        module_id="mod04_ransomware_exposure",
        purpose_key="rpt_guidance_mod04_purpose",
        watch_signals_key="rpt_guidance_mod04_signals",
        how_to_read_key="rpt_guidance_mod04_how",
        recommended_actions_key="rpt_guidance_mod04_actions",
        primary_audience="security",
        profile_visibility=("security_risk",),
        min_detail_level="standard",
    ),
    "mod07_cross_label_matrix": SectionGuidance(
        module_id="mod07_cross_label_matrix",
        purpose_key="rpt_guidance_mod07_purpose",
        watch_signals_key="rpt_guidance_mod07_signals",
        how_to_read_key="rpt_guidance_mod07_how",
        recommended_actions_key="rpt_guidance_mod07_actions",
        primary_audience="network",
        profile_visibility=("network_inventory",),
        min_detail_level="standard",
    ),
    "mod08_unmanaged_hosts": SectionGuidance(
        module_id="mod08_unmanaged_hosts",
        purpose_key="rpt_guidance_mod08_purpose",
        watch_signals_key="rpt_guidance_mod08_signals",
        how_to_read_key="rpt_guidance_mod08_how",
        recommended_actions_key="rpt_guidance_mod08_actions",
        primary_audience="mixed",
        profile_visibility=("security_risk", "network_inventory"),
        min_detail_level="standard",
    ),
}


def get_guidance(module_id: str) -> Optional[SectionGuidance]:
    """Return guidance for a module, or None if not registered."""
    return REGISTRY.get(module_id)


def visible_in(module_id: str, profile: ProfileVisibility, detail_level: DetailLevel) -> bool:
    """Return True if the section should render in the given profile + detail."""
    g = REGISTRY.get(module_id)
    if g is None:
        return True  # unregistered modules render by default
    if profile not in g.profile_visibility:
        return False
    order = ("executive", "standard", "full")
    return order.index(detail_level) >= order.index(g.min_detail_level)
