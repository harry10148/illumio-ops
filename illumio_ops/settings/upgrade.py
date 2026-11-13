"""Bring a settings file written by an older v6 up to the current schema, in memory only.

validate_settings() calls upgrade() first, so the service, the rescue command, the 5.x
migrator and the installer preflight all read old files the same way. Nothing here writes
or logs: every step is a pure function of the file's data, run again on every load until
the upgraded shape reaches disk — on the next SettingsStore.update(), or at the service
start when a step changed something the operator made (SettingsStore.persist_upgrade,
which is also where what was changed is said, once).
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from illumio_ops.domain.alertpack import ANOMALY_BATCH2, anomaly_rules, system_rule
from illumio_ops.settings.schema import (
    SCHEMA_VERSION,
    default_alerts,
    default_collection,
    default_lateral,
    default_reports,
    default_siem,
)


class NewerSchema(Exception):
    """The file was written by a newer program than this one."""


def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    data["collection"] = default_collection().model_dump(mode="json")
    return data


def _v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    data["lateral"] = default_lateral().model_dump(mode="json")
    return data


def _v3_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    # A v3 file is a v6 install, not a 5.x upgrade: the new default rules notify (spec §7 is about 5.x).
    data["alerts"] = default_alerts(notify_new_defaults=True).model_dump(mode="json")
    return data


def _v4_to_v5(data: dict[str, Any]) -> dict[str, Any]:
    # The anomaly detectors' settings (spec §6.5.8); what the file has stays as it is.
    fresh = default_lateral().model_dump(mode="json")
    lateral = data.setdefault("lateral", fresh)
    if isinstance(lateral, dict):
        for key, value in fresh.items():
            lateral.setdefault(key, value)
        if isinstance(lateral.get("detectors"), dict):
            for key, value in fresh["detectors"].items():
                lateral["detectors"].setdefault(key, value)
    # The anomaly rules join the pack recording only: an upgraded install turns each on (as for 5.x, spec §7).
    alerts = data.get("alerts")
    if isinstance(alerts, dict) and isinstance(alerts.get("rules"), list):
        have = {r.get("pack_key") for r in alerts["rules"] if isinstance(r, dict)}
        alerts["rules"] += [r.model_dump(mode="json") for r in anomaly_rules(notify=False) if r.pack_key not in have]
    return data


def _v5_to_v6(data: dict[str, Any]) -> dict[str, Any]:
    data["reports"] = default_reports().model_dump(mode="json")
    return data


def _v6_to_v7(data: dict[str, Any]) -> dict[str, Any]:
    # The findings rules' thresholds (P5b-1); the rest of the reports section stays as it is.
    reports = data.get("reports")
    if isinstance(reports, dict):
        reports.setdefault("rule_thresholds", default_reports().rule_thresholds.model_dump(mode="json"))
    return data


def _v7_to_v8(data: dict[str, Any]) -> dict[str, Any]:
    # "Events only" became "lightweight" (spec §6.4, 2026-10-29); every other mode stays as installed.
    collection = data.get("collection")
    if isinstance(collection, dict) and collection.get("mode") == "events_only":
        collection["mode"] = "lightweight"
    return data


def _v8_to_v9(data: dict[str, Any]) -> dict[str, Any]:
    data["siem"] = default_siem().model_dump(mode="json")  # P7: forwarding off until a destination is set
    # The SIEM backlog check joins the pack like the other system checks (it says nothing while SIEM is off).
    alerts = data.get("alerts")
    if isinstance(alerts, dict) and isinstance(alerts.get("rules"), list):
        have = {r.get("pack_key") for r in alerts["rules"] if isinstance(r, dict)}
        if "rule_system_siem_backlog" not in have:
            alerts["rules"].append(system_rule("rule_system_siem_backlog").model_dump(mode="json"))
    return data


def _v9_to_v10(data: dict[str, Any]) -> dict[str, Any]:
    # New connections with a public end are left out unless a destination says otherwise (user 2026-10-31).
    siem = data.get("siem")
    if isinstance(siem, dict) and isinstance(siem.get("destinations"), list):
        for d in siem["destinations"]:
            if isinstance(d, dict):
                d.setdefault("new_connection_internal_only", True)
    return data


def _v10_to_v11(data: dict[str, Any]) -> dict[str, Any]:
    # Detection leaves out connections with an end outside the estate (user 2026-10-31: the exclusion is for alerts).
    lateral = data.get("lateral")
    detectors = lateral.get("detectors") if isinstance(lateral, dict) else None
    if isinstance(detectors, dict):
        detectors.setdefault("exclude_public", True)
    return data


def _v11_to_v12(data: dict[str, Any]) -> dict[str, Any]:
    # The public-address exclusion moves from detection to the lateral alert rules (user 2026-10-31: the exclusion is
    # for alerts; the lateral page shows every detection). A file that left public ends out of detection leaves them
    # out of every lateral rule's alerts instead, so what was quiet stays quiet.
    lateral = data.get("lateral")
    detectors = lateral.get("detectors") if isinstance(lateral, dict) else None
    public = bool(detectors.pop("exclude_public", True)) if isinstance(detectors, dict) else True
    alerts = data.get("alerts")
    for rule in alerts.get("rules", []) if isinstance(alerts, dict) and isinstance(alerts.get("rules"), list) else []:
        if isinstance(rule, dict) and rule.get("type") == "lateral":
            rule.setdefault("exclude", {"public": True} if public else None)
    return data


def _v12_to_v13(data: dict[str, Any]) -> dict[str, Any]:
    # The second batch of anomaly detectors (spec §6.5.8 第二批): their thresholds; what the file has stays as it is.
    fresh = default_lateral().model_dump(mode="json")["detectors"]
    lateral = data.get("lateral")
    if isinstance(lateral, dict) and isinstance(lateral.get("detectors"), dict):
        for key, value in fresh.items():
            lateral["detectors"].setdefault(key, value)
    # Their rules join the pack recording only, as the first batch's did (v4 → v5); only these four: a first-batch
    # rule the operator deleted stays deleted (review).
    alerts = data.get("alerts")
    if isinstance(alerts, dict) and isinstance(alerts.get("rules"), list):
        have = {r.get("pack_key") for r in alerts["rules"] if isinstance(r, dict)}
        alerts["rules"] += [r.model_dump(mode="json") for r in anomaly_rules(notify=False)
                            if r.pack_key in ANOMALY_BATCH2 and r.pack_key not in have]
    return data


RHC_REPORT, USAGE_REPORT = "rule_hit_count", "policy_usage"
# The most days back the policy usage report reads when this step was written (services/reports/registry.py
# POLICY_USAGE_MAX_DAYS): a step is what one release did to a file, so the number is written here, not imported.
USAGE_MAX_DAYS = 30


@dataclass(frozen=True)
class ScheduleChange:
    """What the v13 → v14 step does to one report schedule."""
    id: str
    name: str
    converted: bool  # it made the Rule Hit Count report and makes the policy usage report now
    lookback_before: int
    lookback_after: int
    # (id, name) of the schedule it was the same as once converted, which stays in its place; None: this one stays
    same_as: tuple[str, str] | None


def change_text(c: ScheduleChange) -> str:
    """One log line for one changed schedule: its name, the lookback before and after, whether it was removed as the
    same as another — and that the reports a removed one made stay its own. Names are printed escaped (repr)."""
    who = f"report schedule {c.name!r} ({c.id})"
    days = f"lookback {c.lookback_before} -> {c.lookback_after} days"
    if c.same_as is None:
        return (f"settings upgraded: {who} made the Rule Hit Count report, now a chapter of the policy usage report; "
                f"it makes the policy usage report now, {days}")
    other = f"{c.same_as[1]!r} ({c.same_as[0]})"
    kept = "the reports it made are kept (listed as from a deleted schedule) and are not handed to the other schedule"
    if c.converted:
        return (f"settings upgraded: {who} made the Rule Hit Count report, now a chapter of the policy usage report; "
                f"as a policy usage schedule ({days}) it is the same as {other}, so it was removed; {kept}")
    return (f"settings upgraded: {who} was removed: it is the same as {other}, which made the Rule Hit Count report "
            f"and makes the policy usage report now; {kept}")


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """The same schedule but for its id and its name (a key one of them lacks reads as null)."""
    keys = (set(a) | set(b)) - {"id", "name"}
    return all(a.get(k) == b.get(k) for k in keys)


def _merge_rhc_schedules(schedules: list[Any]) -> tuple[list[Any], list[ScheduleChange]]:
    """Rule Hit Count is a chapter of the policy usage report (UI redesign spec §9.2): each schedule for the old
    report becomes one for this, within the days it reads. A converted schedule that is then the same as another
    (id and name apart) is kept once — the one of the two with the smaller id stays; the other's reports already
    made stay its own. Two schedules that were the same before are not compared: the operator had both.
    Returns the new list (new dicts where one changed; the given ones are not touched) and what changed, in the
    order of the file. Pure, and nothing left to do on its own output."""
    out: list[Any] = []
    converted: list[str] = []
    before: dict[str, int] = {}
    for s in schedules:
        if isinstance(s, dict) and s.get("report_type") == RHC_REPORT and isinstance(s.get("id"), str):
            days = s.get("lookback_days")
            capped = min(days, USAGE_MAX_DAYS) if isinstance(days, int) and not isinstance(days, bool) else days
            out.append({**s, "report_type": USAGE_REPORT, "lookback_days": capped})
            converted.append(s["id"])
            before[s["id"]] = days if isinstance(days, int) else 0
        else:
            out.append(s)
    removed: dict[str, tuple[str, str]] = {}  # id -> (id, name) of the one kept in its place
    for cid in converted:
        if cid in removed:
            continue
        mine = next(s for s in out if isinstance(s, dict) and s.get("id") == cid)
        for other in out:
            # a second schedule under the same id is an invalid file: left for validation to refuse, not tidied away
            if other is mine or not isinstance(other, dict) or not isinstance(other.get("id"), str) \
                    or other["id"] == cid or other["id"] in removed or not _same(mine, other):
                continue
            loser, winner = (mine, other) if other["id"] < cid else (other, mine)
            removed[loser["id"]] = (winner["id"], str(winner.get("name", "")))
            if loser is mine:
                break
    kept = [s for s in out if not (isinstance(s, dict) and s.get("id") in removed)]
    changes = []
    for s in out:
        if not isinstance(s, dict) or not (s.get("id") in before or s.get("id") in removed):
            continue
        days = s.get("lookback_days")
        after = days if isinstance(days, int) else 0
        changes.append(ScheduleChange(id=s["id"], name=str(s.get("name", "")), converted=s["id"] in before,
                                      lookback_before=before.get(s["id"], after), lookback_after=after,
                                      same_as=removed.get(s["id"])))
    return kept, changes


def _v13_to_v14(data: dict[str, Any]) -> dict[str, Any]:
    reports = data.get("reports")
    if isinstance(reports, dict) and isinstance(reports.get("schedules"), list):
        reports["schedules"] = _merge_rhc_schedules(reports["schedules"])[0]
    return data


# source version -> function producing source version + 1
UPGRADES: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
    3: _v3_to_v4,
    4: _v4_to_v5,
    5: _v5_to_v6,
    6: _v6_to_v7,
    7: _v7_to_v8,
    8: _v8_to_v9,
    9: _v9_to_v10,
    10: _v10_to_v11,
    11: _v11_to_v12,
    12: _v12_to_v13,
    13: _v13_to_v14,
}


def upgrade(data: Any) -> Any:
    """Return data at SCHEMA_VERSION; anything that is not an upgradable file passes through
    unchanged so validation reports it."""
    if not isinstance(data, dict):
        return data
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        return data
    if version > SCHEMA_VERSION:
        raise NewerSchema()
    if version == SCHEMA_VERSION:
        return data
    out = _upto(data, version, SCHEMA_VERSION)
    return data if out is None else out  # no path from this version: let validation report it


def _upto(data: dict[str, Any], version: int, target: int) -> dict[str, Any] | None:
    """A copy of `data` (at schema `version`) taken up to schema `target`; None when a step on the way is missing."""
    out = copy.deepcopy(data)
    while version < target:
        step = UPGRADES.get(version)
        if step is None:
            return None
        out = step(out)
        version += 1
        out["schema_version"] = version
    return out


def rhc_schedule_changes(data: Any) -> list[ScheduleChange]:
    """The report schedules upgrade() changes in this file because Rule Hit Count joined the policy usage report
    (the v13 → v14 step): nothing for a file already at schema 14 or later, or one upgrade() does not take. Pure:
    the step itself says nothing, and the service start says this once when it writes the upgraded file back."""
    if not isinstance(data, dict):
        return []
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version > 13:
        return []
    at_13 = _upto(data, version, 13)
    reports = at_13.get("reports") if at_13 is not None else None
    if not isinstance(reports, dict) or not isinstance(reports.get("schedules"), list):
        return []
    return _merge_rhc_schedules(reports["schedules"])[1]
