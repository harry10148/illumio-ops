"""Native Rule Hit Count feature — enablement detection and enable flow.

Vendor facts (verified 2026-07-05 against the Illumio NotebookLM notebook):
  * PCE side:  PUT /orgs/:org/report_templates/rule_hit_count_report {"enabled": true}
  * VEN side:  PUT /orgs/:org/sec_policy/draft/firewall_settings
               {"rule_hit_count_enabled_scopes": [[]]}   ([[]] = all VENs)
               then POST /orgs/:org/sec_policy to provision — this WRITES to
               production policy, so callers must obtain explicit human
               confirmation before calling enable_rule_hit_count().
  * Version floors: SaaS PCE >= 24.2.0 / on-prem >= 23.5.10 / VEN >= 23.2.30.
    A 404 on the report template endpoint is treated as 'unsupported'.
"""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger


@dataclass
class EnablementStatus:
    state: str                  # 'enabled' | 'partial' | 'disabled' | 'unsupported'
    pce_report_enabled: bool
    ven_scopes_enabled: bool
    detail: str


class RuleHitCountNotEnabled(RuntimeError):
    """Raised by the generator when the native feature is not fully enabled."""

    def __init__(self, status: EnablementStatus):
        self.status = status
        super().__init__(f"rule hit count not enabled: {status.state} ({status.detail})")


class EnablementError(RuntimeError):
    """Enable flow failed part-way. steps_done lists what already succeeded."""

    def __init__(self, message: str, steps_done: list):
        self.steps_done = steps_done
        super().__init__(message)


def check_enablement(api) -> EnablementStatus:
    """Two lightweight GETs. Raises ConnectionError if the PCE is unreachable."""
    org = api.api_cfg['org_id']

    status, tpl = api._api_get(f"/orgs/{org}/report_templates/rule_hit_count_report")
    if status == 404:
        return EnablementStatus(
            state="unsupported", pce_report_enabled=False, ven_scopes_enabled=False,
            detail="report template not found — PCE below version floor "
                   "(SaaS 24.2.0 / on-prem 23.5.10) or feature absent")
    if status != 200 or tpl is None:
        raise ConnectionError(f"report_templates query failed: HTTP {status}")
    pce_on = bool(tpl.get("enabled"))

    status, fw = api._api_get(f"/orgs/{org}/sec_policy/active/firewall_settings")
    if status != 200 or fw is None:
        raise ConnectionError(f"firewall_settings query failed: HTTP {status}")
    scopes = fw.get("rule_hit_count_enabled_scopes") or []
    ven_on = len(scopes) > 0

    if pce_on and ven_on:
        state, detail = "enabled", "PCE report template and VEN scopes both enabled"
    elif not pce_on and not ven_on:
        state, detail = "disabled", "PCE report template and VEN scopes both disabled"
    else:
        missing = "VEN firewall_settings scopes" if pce_on else "PCE report template"
        state, detail = "partial", f"missing: {missing}"
    return EnablementStatus(state=state, pce_report_enabled=pce_on,
                            ven_scopes_enabled=ven_on, detail=detail)


def enable_rule_hit_count(api, scopes: list | None = None) -> list:
    """Enable the native feature. scopes=None enables ALL VENs ([[]]).

    Executes: PCE report template -> VEN draft firewall_settings -> provision.
    Stops at the first failure (never leaves provision running after a failed
    draft write) and raises EnablementError carrying the completed steps.
    """
    org = api.api_cfg['org_id']
    steps_done: list = []

    st = api._api_put(f"/orgs/{org}/report_templates/rule_hit_count_report",
                      {"enabled": True})
    if st not in (200, 204):
        raise EnablementError(f"PCE report template enable failed: HTTP {st}", steps_done)
    steps_done.append("pce_report_template")

    payload = {"rule_hit_count_enabled_scopes": scopes if scopes is not None else [[]]}
    st = api._api_put(f"/orgs/{org}/sec_policy/draft/firewall_settings", payload)
    if st not in (200, 204):
        raise EnablementError(f"VEN firewall_settings draft update failed: HTTP {st}", steps_done)
    steps_done.append("ven_firewall_settings_draft")

    st, _body = api._api_post(f"/orgs/{org}/sec_policy", {
        "update_description": "Enable rule hit count (illumio-ops)",
        "change_subset": {
            "firewall_settings": [{"href": f"/orgs/{org}/sec_policy/draft/firewall_settings"}]
        },
    })
    if st != 201:
        raise EnablementError(f"provision failed: HTTP {st}", steps_done)
    steps_done.append("provisioned")
    logger.info(f"Rule hit count enabled (steps: {steps_done})")
    return steps_done
