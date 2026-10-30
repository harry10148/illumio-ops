"""Rule Hit Count (spec §6.5 RHC, P5c-2): whether it is on, turning it on, and pulling the PCE's own report.

Two halves must be on: the PCE's report template, and the VENs' firewall_settings scopes (provisioned). Only the
Owner role reads or changes the template and produces PCE reports (lab and NFR, 2026-10-24), so the optional write
key is used when saved. SaaS does not allow changing report templates through the API at all (NFR 2026-10-27;
Illumio KB 4243): the PCE's refusal is shown as it is, with where to ask. Ported from 5.x rule_hit_count_enablement
and api/reports (lab-verified 2026-07-11)."""
from __future__ import annotations

import csv
import hashlib
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
    PceResponse,
    PceTransportError,
)
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import PceSettings

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


def _has_write_key(pce: PceSettings) -> bool:
    return bool(pce.write_api_key and pce.write_api_secret)


def _client(ctx: AppContext, pce: PceSettings) -> PceClient:
    """The write key when saved (Owner), otherwise the main key."""
    return ctx.pce_write_client(pce) if _has_write_key(pce) else ctx.pce_client(pce)


def _snippet(body: bytes) -> str:
    return body[:200].decode("utf-8", "replace")


def _json(resp: PceResponse) -> Any:
    """The body as JSON, or None: a 200 sign-in page from a proxy is not an answer (final review #5)."""
    try:
        return resp.json()
    except ValueError:
        return None


def _scopes_on(body: Any) -> bool:
    return isinstance(body, dict) and bool(body.get("rule_hit_count_enabled_scopes"))


# Every check is for one PCE and one set of credentials (final review #4): another destination, key or TLS check is
# another answer. A digest, so the cache holds no secret of its own.
_cache: dict[str, tuple[float, RhcStatus]] = {}
_cache_lock = threading.Lock()


def _cache_key(pce: PceSettings) -> str:
    parts = (pce.url, pce.org_id, pce.api_key, pce.api_secret, pce.write_api_key, pce.write_api_secret,
             str(pce.verify_tls), pce.deployment_type.value)
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def forget_status() -> None:
    with _cache_lock:
        _cache.clear()


def cached_status(ctx: AppContext) -> RhcStatus:
    """A check from the last STATUS_CACHE_SECONDS, else a fresh one: the report catalog asks on every load."""
    with _cache_lock:
        hit = _cache.get(_cache_key(ctx.settings.current().pce))
    if hit is not None and time.monotonic() - hit[0] < STATUS_CACHE_SECONDS:
        return hit[1]
    return rhc_status(ctx)


def rhc_status(ctx: AppContext) -> RhcStatus:
    """Never raises: what cannot be read is `unknown`, with the reason. Every check refreshes cached_status — for
    the settings it read, and only while they are still the ones in force (final review #4)."""
    pce = ctx.settings.current().pce
    key = _cache_key(pce)
    result = _read_status(ctx, pce)
    with _cache_lock:
        if _cache_key(ctx.settings.current().pce) == key:
            _cache[key] = (time.monotonic(), result)
    return result


def _read_status(ctx: AppContext, cfg: PceSettings) -> RhcStatus:
    write_key, saas = _has_write_key(cfg), cfg.deployment_type is DeploymentType.SAAS

    def status(state: RhcState, pce: bool | None, ven: bool | None, reason: str | None,
               detail: str | None = None) -> RhcStatus:
        return RhcStatus(state=state, pce_report=pce, ven_scopes=ven, reason_key=reason, detail=detail,
                         write_key=write_key, saas=saas)
    try:
        with _client(ctx, cfg) as client:
            tpl = client.request("GET", TEMPLATE, timeout=30)
            fw = client.request("GET", ACTIVE_FW, timeout=30)
    except PceNotConfigured:
        return status(RhcState.UNKNOWN, None, None, "rhc_reason_not_configured")
    except _TRANSPORT as exc:
        return status(RhcState.UNKNOWN, None, None, "rhc_reason_unreachable", str(exc))
    fw_body, tpl_body = _json(fw), _json(tpl)
    ven = _scopes_on(fw_body) if fw.status == 200 and isinstance(fw_body, dict) else None
    if tpl.status == 404:
        return status(RhcState.UNSUPPORTED, False, ven, "rhc_reason_unsupported")
    if tpl.status == 403:
        return status(RhcState.UNKNOWN, None, ven,
                      "rhc_reason_write_key_denied" if write_key else "rhc_reason_needs_write_key")
    if tpl.status != 200 or not isinstance(tpl_body, dict) or ven is None:
        bad = tpl if tpl.status != 200 or not isinstance(tpl_body, dict) else fw
        detail = f"HTTP {bad.status}" if bad.status != 200 else "unexpected response"
        return status(RhcState.UNKNOWN, None, ven, "rhc_reason_unreachable", detail)
    pce = bool(tpl_body.get("enabled"))
    if pce and ven:
        return status(RhcState.ENABLED, True, True, None)
    if not pce and not ven:
        return status(RhcState.DISABLED, False, False, None)
    return status(RhcState.PARTIAL, pce, ven, "rhc_reason_partial_ven" if pce else "rhc_reason_partial_template")


# firewall_settings fields that say who changed it when, not what it is; ours is the scopes.
_FW_META = frozenset({"href", "update_type", "updated_at", "updated_by", "created_at", "created_by", "deleted_at",
                      "deleted_by", "rule_hit_count_enabled_scopes"})


def _fw_content(body: Any) -> dict[str, Any] | None:
    return {k: v for k, v in body.items() if k not in _FW_META} if isinstance(body, dict) else None


def enable_rhc(ctx: AppContext) -> EnableResult:
    """Turns on whichever half is off: the template, then the VENs' draft firewall_settings, then provisions only
    firewall_settings. Everything is read first, so a refusal writes nothing; the first failed write stops it and
    says which steps were done. One run uses the settings it started with and stops if they change (final review
    #3). Callers confirm with the person first: this provisions policy."""
    done: list[str] = []
    skipped: list[str] = []
    cfg = ctx.settings.current().pce
    saas = cfg.deployment_type is DeploymentType.SAAS

    def fail(key: str, detail: str | None = None) -> EnableResult:
        logger.warning("Rule Hit Count enable stopped after {}: {} {}", done, key, detail or "")
        return EnableResult(ok=False, steps_done=done, skipped=skipped, error_key=key, detail=detail)

    def switched() -> bool:
        return _cache_key(ctx.settings.current().pce) != _cache_key(cfg)
    if not _has_write_key(cfg):
        return fail("rhc_err_no_write_key")
    try:
        with _ENABLE_LOCK, ctx.pce_write_client(cfg) as client:  # one enable at a time from this product
            tpl = client.request("GET", TEMPLATE, timeout=30)
            if tpl.status == 404:
                return fail("rhc_err_unsupported")
            if tpl.status == 403:
                return fail("rhc_err_refused_saas" if saas else "rhc_err_refused", "HTTP 403")
            fw = client.request("GET", ACTIVE_FW, timeout=30) if tpl.status == 200 else tpl
            tpl_body, fw_body = _json(tpl), _json(fw)
            if tpl.status != 200 or fw.status != 200 or not isinstance(tpl_body, dict) \
                    or not isinstance(fw_body, dict):
                bad = tpl if tpl.status != 200 or not isinstance(tpl_body, dict) else fw
                return fail("rhc_err_unreachable", f"HTTP {bad.status}" if bad.status != 200 else
                            "unexpected response")
            need_template = not tpl_body.get("enabled")
            need_vens = not _scopes_on(fw_body)
            if not need_template:
                skipped.append(STEPS[0])
            if not need_vens:
                skipped.extend(STEPS[1:])
            if need_vens:
                # Provisioning firewall_settings ships the whole draft object: someone's unreviewed edits would
                # reach every VEN. Refused, and nothing written (5.x checked only after enabling the template).
                draft = client.request("GET", DRAFT_FW, timeout=30)
                draft_body = _json(draft)
                if draft.status != 200 or not isinstance(draft_body, dict):
                    return fail("rhc_err_unreachable", f"HTTP {draft.status}")
                if draft_body.get("update_type"):
                    return fail("rhc_err_pending_firewall")
                logger.info("Rule Hit Count: firewall_settings scopes before change: {}",
                            draft_body.get("rule_hit_count_enabled_scopes"))
            if need_template:
                if switched():
                    return fail("rhc_err_pce_changed")
                r = client.request("PUT", TEMPLATE, json={"enabled": True}, timeout=30)
                if r.status == 403:
                    return fail("rhc_err_refused_saas" if saas else "rhc_err_refused", f"HTTP 403 {_snippet(r.body)}")
                if r.status not in (200, 204):
                    return fail("rhc_err_step_failed", f"{STEPS[0]}: HTTP {r.status} {_snippet(r.body)}")
                done.append(STEPS[0])
            if need_vens:
                if switched():
                    return fail("rhc_err_pce_changed")
                r = client.request("PUT", DRAFT_FW, json={"rule_hit_count_enabled_scopes": ALL_VENS}, timeout=30)
                if r.status not in (200, 204):
                    return fail("rhc_err_step_failed", f"{STEPS[1]}: HTTP {r.status} {_snippet(r.body)}")
                done.append(STEPS[1])
                # Someone may have edited Draft firewall_settings since it was checked (final review #1): provision
                # only when the draft differs from active in our scopes alone.
                active_now = _fw_content(_json(client.request("GET", ACTIVE_FW, timeout=30)))
                draft_now = _fw_content(_json(client.request("GET", DRAFT_FW, timeout=30)))
                if active_now is None or draft_now is None or active_now != draft_now:
                    return fail("rhc_err_firewall_changed")
                if switched():
                    return fail("rhc_err_pce_changed")
                r = client.request("POST", "/sec_policy", json={
                    "update_description": "Enable Rule Hit Count (illumio-ops)",
                    "change_subset": {"firewall_settings": [{"href": f"/orgs/{cfg.org_id}{DRAFT_FW}"}]}}, timeout=60)
                if r.status != 201:
                    return fail("rhc_err_step_failed", f"{STEPS[2]}: HTTP {r.status} {_snippet(r.body)}")
                done.append(STEPS[2])
    except _TRANSPORT as exc:
        return fail("rhc_err_unreachable", str(exc))
    logger.info("Rule Hit Count enabled (steps: {}, already on: {})", done, skipped)
    return EnableResult(ok=True, steps_done=done, skipped=skipped, error_key=None, detail=None)


_ENABLE_LOCK = threading.Lock()


def _iso(t: datetime) -> str:
    """Full ISO timestamps: a bare date gets 406 (lab 25.2.40, 2026-07-11)."""
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def pull_rhc(ctx: AppContext, start: datetime, end: datetime, *,
             timeout_seconds: float = PULL_TIMEOUT_SECONDS) -> RhcPull:
    """The PCE's own Rule Hit Count report for [start, end), every ruleset. Raises RhcPullError (a refusal, a failed
    or late report, an unreadable file) or a PCE transport failure. The PCE purges generated reports itself
    (report_retention_days); there is no delete endpoint."""
    cfg = ctx.settings.current().pce
    with _client(ctx, cfg) as client:
        r = client.request("POST", "/reports", timeout=60, json={
            "report_template": {"href": f"/orgs/{cfg.org_id}{TEMPLATE}"},
            "description": "illumio-ops rule hit count",
            "report_parameters": {"report_time_range": {"start_date": _iso(start), "end_date": _iso(end)},
                                  "rule_sets": []},  # [] = every ruleset
            "report_format": "csv"})
        if r.status == 403:
            raise RhcPullError("rhc_err_pull_refused", _snippet(r.body))
        body = _json(r) if r.status in (200, 201) else None
        href = body.get("href") if isinstance(body, dict) else None
        if not href:
            raise RhcPullError("rhc_err_pull_failed", f"HTTP {r.status} {_snippet(r.body)}")
        deadline = time.monotonic() + timeout_seconds
        while True:
            p = client.request("GET", href, org_scoped=False, timeout=30)
            pb = _json(p) if p.status == 200 else None
            state = str(pb.get("status", "")).lower() if isinstance(pb, dict) else ""
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


def _when(value: str) -> str | None:
    """The PCE writes "N/A" for a rule never hit (lab, 2026-10-30)."""
    return None if value.strip().upper() in ("", "N/A", "NA", "-") else value.strip()


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
                           last_hit_at=_when(rec.get("last_hit_at", ""))))
    return rows, unparsed
