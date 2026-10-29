"""Rule Hit Count (spec §6.5 RHC, P5c-2): whether it is on, turning it on, and pulling the PCE's own report.

Two halves must be on: the PCE's report template, and the VENs' firewall_settings scopes (provisioned). Only the
Owner role reads or changes the template and produces PCE reports (lab and NFR, 2026-10-24), so the optional write
key is used when saved. SaaS does not allow changing report templates through the API at all (NFR 2026-10-27;
Illumio KB 4243): the PCE's refusal is shown as it is, with where to ask. Ported from 5.x rule_hit_count_enablement
and api/reports (lab-verified 2026-07-11)."""
from __future__ import annotations

import csv
import io
import re
import threading
import time
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from pydantic import BaseModel

from illumio_ops.domain.values import DeploymentType, RhcState
from illumio_ops.pce.client import (
    PceBudgetExhausted,
    PceClient,
    PceNotConfigured,
    PceTransportError,
)
from illumio_ops.services.context import AppContext

TEMPLATE = "/report_templates/rule_hit_count_report"
ACTIVE_FW = "/sec_policy/active/firewall_settings"
DRAFT_FW = "/sec_policy/draft/firewall_settings"
ALL_VENS: list[list[Any]] = [[]]
STEPS = ("pce_report_template", "ven_firewall_settings_draft", "provisioned")
PULL_TIMEOUT_SECONDS = 600
POLL_SECONDS = 5
STATUS_CACHE_SECONDS = 300
_TRANSPORT = (PceTransportError, PceBudgetExhausted)
_sleep = time.sleep


class RhcStatus(BaseModel):
    state: RhcState
    pce_report: bool | None  # None: could not be read
    ven_scopes: bool | None
    reason_key: str | None
    detail: str | None
    write_key: bool
    saas: bool


class EnableResult(BaseModel):
    ok: bool
    steps_done: list[str]
    skipped: list[str]  # already on
    error_key: str | None
    detail: str | None


class RhcRow(BaseModel):
    rule_href: str
    ruleset_name: str
    description: str
    hit_count: int
    last_hit_at: str | None


class RhcPull(BaseModel):
    rows: list[RhcRow]
    start: datetime
    end: datetime
    unparsed: int  # rows whose hit count could not be read: left out, not counted as 0


class RhcPullError(Exception):
    def __init__(self, key: str, detail: str | None = None) -> None:
        self.key, self.detail = key, detail
        super().__init__(f"{key}: {detail}" if detail else key)


def _has_write_key(ctx: AppContext) -> bool:
    pce = ctx.settings.current().pce
    return bool(pce.write_api_key and pce.write_api_secret)


def _client(ctx: AppContext) -> PceClient:
    """The write key when saved (Owner), otherwise the main key."""
    return ctx.pce_write_client() if _has_write_key(ctx) else ctx.pce_client(ctx.settings.current().pce)


def _snippet(body: bytes) -> str:
    return body[:200].decode("utf-8", "replace")


def _scopes_on(body: Any) -> bool:
    return isinstance(body, dict) and bool(body.get("rule_hit_count_enabled_scopes"))


_cache: dict[tuple[str, str, bool], tuple[float, RhcStatus]] = {}
_cache_lock = threading.Lock()


def _cache_key(ctx: AppContext) -> tuple[str, str, bool]:
    pce = ctx.settings.current().pce
    return (pce.url, pce.org_id, _has_write_key(ctx))


def forget_status() -> None:
    with _cache_lock:
        _cache.clear()


def cached_status(ctx: AppContext) -> RhcStatus:
    """A check from the last STATUS_CACHE_SECONDS, else a fresh one: the report catalog asks on every load."""
    key = _cache_key(ctx)
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < STATUS_CACHE_SECONDS:
        return hit[1]
    return rhc_status(ctx)


def rhc_status(ctx: AppContext) -> RhcStatus:
    """Never raises: what cannot be read is `unknown`, with the reason. Every check refreshes cached_status."""
    result = _read_status(ctx)
    with _cache_lock:
        _cache[_cache_key(ctx)] = (time.monotonic(), result)
    return result


def _read_status(ctx: AppContext) -> RhcStatus:
    write_key, saas = _has_write_key(ctx), ctx.settings.current().pce.deployment_type is DeploymentType.SAAS

    def status(state: RhcState, pce: bool | None, ven: bool | None, reason: str | None,
               detail: str | None = None) -> RhcStatus:
        return RhcStatus(state=state, pce_report=pce, ven_scopes=ven, reason_key=reason, detail=detail,
                         write_key=write_key, saas=saas)
    try:
        with _client(ctx) as client:
            tpl = client.request("GET", TEMPLATE, timeout=30)
            fw = client.request("GET", ACTIVE_FW, timeout=30)
    except PceNotConfigured:
        return status(RhcState.UNKNOWN, None, None, "rhc_reason_not_configured")
    except _TRANSPORT as exc:
        return status(RhcState.UNKNOWN, None, None, "rhc_reason_unreachable", str(exc))
    ven = _scopes_on(fw.json()) if fw.status == 200 else None
    if tpl.status == 404:
        return status(RhcState.UNSUPPORTED, False, ven, "rhc_reason_unsupported")
    if tpl.status == 403:
        return status(RhcState.UNKNOWN, None, ven,
                      "rhc_reason_write_key_denied" if write_key else "rhc_reason_needs_write_key")
    if tpl.status != 200 or ven is None:
        bad = tpl if tpl.status != 200 else fw
        return status(RhcState.UNKNOWN, None, ven, "rhc_reason_unreachable", f"HTTP {bad.status}")
    pce = bool(tpl.json().get("enabled"))
    if pce and ven:
        return status(RhcState.ENABLED, True, True, None)
    if not pce and not ven:
        return status(RhcState.DISABLED, False, False, None)
    return status(RhcState.PARTIAL, pce, ven, "rhc_reason_partial_ven" if pce else "rhc_reason_partial_template")


def enable_rhc(ctx: AppContext) -> EnableResult:
    """Turns on whichever half is off: the template, then the VENs' draft firewall_settings, then provisions only
    firewall_settings. Everything is read first, so a refusal writes nothing; the first failed write stops it and
    says which steps were done. Callers confirm with the person first: this provisions policy."""
    done: list[str] = []
    skipped: list[str] = []
    saas = ctx.settings.current().pce.deployment_type is DeploymentType.SAAS

    def fail(key: str, detail: str | None = None) -> EnableResult:
        logger.warning("Rule Hit Count enable stopped after {}: {} {}", done, key, detail or "")
        return EnableResult(ok=False, steps_done=done, skipped=skipped, error_key=key, detail=detail)
    if not _has_write_key(ctx):
        return fail("rhc_err_no_write_key")
    try:
        with ctx.pce_write_client() as client:
            tpl = client.request("GET", TEMPLATE, timeout=30)
            if tpl.status == 404:
                return fail("rhc_err_unsupported")
            if tpl.status == 403:
                return fail("rhc_err_refused_saas" if saas else "rhc_err_refused", "HTTP 403")
            fw = client.request("GET", ACTIVE_FW, timeout=30)
            if tpl.status != 200 or fw.status != 200:
                bad = tpl if tpl.status != 200 else fw
                return fail("rhc_err_unreachable", f"HTTP {bad.status}")
            need_template = not tpl.json().get("enabled")
            need_vens = not _scopes_on(fw.json())
            if not need_template:
                skipped.append(STEPS[0])
            if not need_vens:
                skipped.extend(STEPS[1:])
            if need_vens:
                # Provisioning firewall_settings ships the whole draft object: someone's unreviewed edits would
                # reach every VEN. Refused, and nothing written (5.x checked only after enabling the template).
                draft = client.request("GET", DRAFT_FW, timeout=30)
                if draft.status != 200 or not isinstance(draft.json(), dict):
                    return fail("rhc_err_unreachable", f"HTTP {draft.status}")
                if draft.json().get("update_type"):
                    return fail("rhc_err_pending_firewall")
                logger.info("Rule Hit Count: firewall_settings scopes before change: {}",
                            draft.json().get("rule_hit_count_enabled_scopes"))
            if need_template:
                r = client.request("PUT", TEMPLATE, json={"enabled": True}, timeout=30)
                if r.status == 403:
                    return fail("rhc_err_refused_saas" if saas else "rhc_err_refused", f"HTTP 403 {_snippet(r.body)}")
                if r.status not in (200, 204):
                    return fail("rhc_err_step_failed", f"{STEPS[0]}: HTTP {r.status} {_snippet(r.body)}")
                done.append(STEPS[0])
            if need_vens:
                r = client.request("PUT", DRAFT_FW, json={"rule_hit_count_enabled_scopes": ALL_VENS}, timeout=30)
                if r.status not in (200, 204):
                    return fail("rhc_err_step_failed", f"{STEPS[1]}: HTTP {r.status} {_snippet(r.body)}")
                done.append(STEPS[1])
                org = ctx.settings.current().pce.org_id
                r = client.request("POST", "/sec_policy", json={
                    "update_description": "Enable Rule Hit Count (illumio-ops)",
                    "change_subset": {"firewall_settings": [{"href": f"/orgs/{org}{DRAFT_FW}"}]}}, timeout=60)
                if r.status != 201:
                    return fail("rhc_err_step_failed", f"{STEPS[2]}: HTTP {r.status} {_snippet(r.body)}")
                done.append(STEPS[2])
    except _TRANSPORT as exc:
        return fail("rhc_err_unreachable", str(exc))
    logger.info("Rule Hit Count enabled (steps: {}, already on: {})", done, skipped)
    return EnableResult(ok=True, steps_done=done, skipped=skipped, error_key=None, detail=None)


def _iso(t: datetime) -> str:
    """Full ISO timestamps: a bare date gets 406 (lab 25.2.40, 2026-07-11)."""
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def pull_rhc(ctx: AppContext, start: datetime, end: datetime, *,
             timeout_seconds: float = PULL_TIMEOUT_SECONDS) -> RhcPull:
    """The PCE's own Rule Hit Count report for [start, end), every ruleset. Raises RhcPullError (a refusal, a failed
    or late report, an unreadable file) or a PCE transport failure. The PCE purges generated reports itself
    (report_retention_days); there is no delete endpoint."""
    org = ctx.settings.current().pce.org_id
    with _client(ctx) as client:
        r = client.request("POST", "/reports", timeout=60, json={
            "report_template": {"href": f"/orgs/{org}{TEMPLATE}"},
            "description": "illumio-ops rule hit count",
            "report_parameters": {"report_time_range": {"start_date": _iso(start), "end_date": _iso(end)},
                                  "rule_sets": []},  # [] = every ruleset
            "report_format": "csv"})
        if r.status == 403:
            raise RhcPullError("rhc_err_pull_refused", _snippet(r.body))
        href = r.json().get("href") if r.status in (200, 201) and r.body else None
        if not href:
            raise RhcPullError("rhc_err_pull_failed", f"HTTP {r.status} {_snippet(r.body)}")
        deadline = time.monotonic() + timeout_seconds
        while True:
            p = client.request("GET", href, org_scoped=False, timeout=30)
            state = str(p.json().get("status", "")).lower() if p.status == 200 else ""
            if state == "done":
                break
            if state in ("failed", "error"):
                raise RhcPullError("rhc_err_pull_failed", f"{href}: {state}")
            if time.monotonic() >= deadline:
                raise RhcPullError("rhc_err_pull_timeout", href)
            _sleep(POLL_SECONDS)
        d = client.request("GET", f"{href}/download", org_scoped=False, timeout=120)
        if d.status != 200:
            raise RhcPullError("rhc_err_pull_download", f"HTTP {d.status}")
    rows, unparsed = parse_rhc_csv(d.body.decode("utf-8-sig", "replace"))
    if unparsed:
        logger.warning("Rule Hit Count report: {} row(s) with an unreadable hit count left out", unparsed)
    return RhcPull(rows=rows, start=start, end=end, unparsed=unparsed)


# The PCE's CSV headers, normalized (lowercase, non-alphanumerics → "_"), to fields (5.x _CSV_ALIASES).
_ALIASES = {"rule_href": "rule_href", "rule_hit_count": "hit_count", "hit_count": "hit_count",
            "rule_name": "description", "rule_description": "description", "rule_set_name": "ruleset_name",
            "ruleset_name": "ruleset_name", "timestamp_of_last_hit": "last_hit_at"}


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")


def parse_rhc_csv(text: str) -> tuple[list[RhcRow], int]:
    """Rows with a rule and a readable hit count, and how many were left out. A blank or unreadable count is left
    out rather than read as 0, which would list the rule as unused."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    fields = [_ALIASES.get(_norm(h)) for h in header or []]
    if "rule_href" not in fields or "hit_count" not in fields:
        raise RhcPullError("rhc_err_csv_columns", ", ".join(header or [])[:200])
    rows: list[RhcRow] = []
    unparsed = 0
    for raw in reader:
        rec = {f: v.strip() for f, v in zip(fields, raw, strict=False) if f}
        if not rec.get("rule_href"):
            continue
        try:
            hits = int(float(rec.get("hit_count", "")))
        except ValueError:
            unparsed += 1
            continue
        rows.append(RhcRow(rule_href=rec["rule_href"], ruleset_name=rec.get("ruleset_name", ""),
                           description=rec.get("description", ""), hit_count=hits,
                           last_hit_at=rec.get("last_hit_at") or None))
    return rows, unparsed
