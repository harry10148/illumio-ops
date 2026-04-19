"""AsyncJobManager — PCE async-query job lifecycle + state persistence.

Extracted from ApiClient in Phase 9 Task 6. State (async job tracking dict,
prune timestamp, state file path, TTL constants) lives on the ApiClient facade;
this class contains the methods that persist to / read from state.json and
submit / poll / download async traffic-flow query jobs.
"""
from __future__ import annotations

import datetime
import gzip
import json
import time
from io import BytesIO

import orjson
from loguru import logger

from src.state_store import load_state_file, update_state_file

_ASYNC_JOB_STATE_KEY = "async_query_jobs"


class AsyncJobManager:
    """Owns async traffic query job lifecycle + persisted state tracking."""

    def __init__(self, client):
        self._client = client

    # ── Timestamp + signature helpers ────────────────────────────────────

    @staticmethod
    def _utc_now_iso():
        return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

    @staticmethod
    def _make_query_signature(payload):
        if not payload:
            return ""
        try:
            return json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _job_timestamp_epoch(job):
        for key in ("updated_at", "created_at", "reused_at"):
            value = job.get(key)
            if not value:
                continue
            try:
                dt = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
                return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
            except ValueError:
                continue
        return 0.0

    # ── State persistence ────────────────────────────────────────────────

    def _save_async_job_state(self, job_href, **fields):
        if not job_href:
            return
        c = self._client

        def _merge(existing):
            data = dict(existing)
            jobs = data.setdefault(_ASYNC_JOB_STATE_KEY, {})
            entry = dict(jobs.get(job_href, {}))
            entry.update({k: v for k, v in fields.items() if v is not None})
            entry["job_href"] = job_href
            entry["updated_at"] = fields.get("updated_at") or self._utc_now_iso()
            if "created_at" not in entry:
                entry["created_at"] = entry["updated_at"]
            jobs[job_href] = entry
            return data

        try:
            update_state_file(c._state_file, _merge)
        except Exception as exc:
            logger.debug("Failed to persist async job state for {}: {}", job_href, exc)

    def _load_async_job_states(self):
        c = self._client
        try:
            self._maybe_prune_async_job_states()
            data = load_state_file(c._state_file)
            jobs = data.get(_ASYNC_JOB_STATE_KEY, {})
            return jobs if isinstance(jobs, dict) else {}
        except Exception as exc:
            logger.debug("Failed to load async job states: {}", exc)
            return {}

    def _job_age_seconds(self, job):
        ts = self._job_timestamp_epoch(job)
        return max(0.0, time.time() - ts) if ts else 0.0

    def _job_is_stale(self, job, max_age_days=None):
        c = self._client
        age_days = float(max_age_days or c._async_job_cache_max_age_days or 0)
        if age_days <= 0:
            return False
        return self._job_age_seconds(job) > (age_days * 86400)

    def _maybe_prune_async_job_states(self):
        c = self._client
        interval = max(0, int(c._async_job_prune_interval_seconds or 0))
        now = time.time()
        if interval and c._last_async_job_prune_at and (now - c._last_async_job_prune_at) < interval:
            return
        c._last_async_job_prune_at = now
        try:
            self.prune_async_job_states(max_age_days=c._async_job_cache_max_age_days)
        except Exception as exc:
            logger.debug("Async job state prune skipped: {}", exc)

    def find_cached_async_summary(self, payload, query_type="rule_usage"):
        signature = self._make_query_signature(payload)
        if not signature:
            return None

        jobs = self._load_async_job_states()
        matches = []
        for job_href, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if job.get("query_type") != query_type:
                continue
            if job.get("query_signature") != signature:
                continue
            if self._job_is_stale(job):
                continue
            if job.get("status") != "completed":
                continue
            if job.get("download_status") != "completed":
                continue
            if "flow_count" not in job:
                continue
            matches.append((job.get("updated_at", ""), job_href, job))

        if not matches:
            return None

        _, job_href, job = max(matches, key=lambda item: item[0])
        return {
            "job_href": job_href,
            "count": int(job.get("flow_count", 0) or 0),
            "flows_by_port": dict(job.get("flows_by_port", {}) or {}),
            "updated_at": job.get("updated_at", ""),
        }

    def find_latest_async_job(self, payload, query_type="rule_usage"):
        signature = self._make_query_signature(payload)
        if not signature:
            return None

        jobs = self._load_async_job_states()
        matches = []
        for job_href, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if job.get("query_type") != query_type:
                continue
            if job.get("query_signature") != signature:
                continue
            if self._job_is_stale(job):
                continue
            matches.append((self._job_timestamp_epoch(job), job_href, job))

        if not matches:
            return None

        _, job_href, job = max(matches, key=lambda item: item[0])
        found = dict(job)
        found["job_href"] = job_href
        return found

    def resume_async_query_job(self, job_href, timeout=120, summarize=False, compute_draft=False):
        poll_result = self._wait_for_async_query(job_href, timeout=timeout, compute_draft=compute_draft)
        result = {
            "job_href": job_href,
            "status": poll_result.get("status"),
            "rules_status": poll_result.get("rules"),
        }
        if result["status"] == "completed" and summarize:
            result.update(self.summarize_async_query(job_href))
        return result

    def retry_async_query_job(self, job_href):
        jobs = self._load_async_job_states()
        job = jobs.get(job_href, {})
        query_body = job.get("query_body")
        query_type = job.get("query_type", "rule_usage")
        if not query_body:
            raise ValueError(f"Async job {job_href} has no query_body for retry")

        new_job_href = self.submit_async_query(query_body, query_type=query_type)
        if not new_job_href:
            raise RuntimeError(f"Failed to resubmit async job {job_href}")

        now = self._utc_now_iso()
        self._save_async_job_state(job_href, retried_at=now, retried_by=new_job_href)
        self._save_async_job_state(new_job_href, retried_from=job_href, retry_submitted_at=now)
        return new_job_href

    def prune_async_job_states(self, max_age_days=7, keep_recent_completed=200):
        c = self._client
        cutoff = time.time() - (max_age_days * 86400)

        def _prune(existing):
            data = dict(existing)
            jobs = dict(data.get(_ASYNC_JOB_STATE_KEY, {}) or {})
            completed_jobs = [
                (self._job_timestamp_epoch(job), href)
                for href, job in jobs.items()
                if isinstance(job, dict) and job.get("status") == "completed"
            ]
            completed_jobs.sort(reverse=True)
            keep_completed = {href for _, href in completed_jobs[:keep_recent_completed]}

            pruned = {}
            removed = 0
            for href, job in jobs.items():
                if not isinstance(job, dict):
                    continue
                ts = self._job_timestamp_epoch(job)
                if job.get("status") == "completed" and href in keep_completed:
                    pruned[href] = job
                    continue
                if ts and ts < cutoff:
                    removed += 1
                    continue
                pruned[href] = job

            data[_ASYNC_JOB_STATE_KEY] = pruned
            data["_last_async_prune"] = {
                "removed": removed,
                "updated_at": self._utc_now_iso(),
            }
            return data

        updated = update_state_file(c._state_file, _prune)
        meta = updated.get("_last_async_prune", {})
        return {
            "removed": int(meta.get("removed", 0) or 0),
            "remaining": len(updated.get(_ASYNC_JOB_STATE_KEY, {}) or {}),
        }

    # ── Async-query submit / poll / download ─────────────────────────────

    def submit_async_query(self, payload, query_type="rule_usage"):
        """Submit an async traffic query and return the job href, or None on failure."""
        c = self._client
        url = f"{c.base_url}/traffic_flows/async_queries"
        status, body = c._request(url, method="POST", data=payload, timeout=10)
        if status not in (200, 201, 202):
            text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
            logger.debug(f"submit_async_query failed: {status} {text[:200]}")
            return None
        result = orjson.loads(body)
        job_href = result.get("href")
        self._save_async_job_state(
            job_href,
            status=result.get("status", "submitted"),
            query_type=query_type,
            query_name=payload.get("query_name"),
            query_body=payload,
            query_signature=self._make_query_signature(payload),
            result_href=result.get("result"),
        )
        return job_href

    def _wait_for_async_query(self, job_href, timeout=120, compute_draft=False):
        """Poll an async query until completed/failed/timeout and return the last poll result."""
        import sys
        from contextlib import nullcontext

        c = self._client
        poll_url = f"{c.api_cfg['url']}/api/v2{job_href}"
        max_polls = timeout // 2
        poll_result = {"status": "pending"}

        show_progress = sys.stderr.isatty()
        if show_progress:
            from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
            progress_ctx = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                transient=True,
            )
        else:
            progress_ctx = nullcontext()

        with progress_ctx as prog:
            task_id = prog.add_task(f"Polling async query...", total=None) if show_progress else None
            for poll_num in range(max_polls):
                time.sleep(2)
                poll_status, poll_body = c._request(poll_url, timeout=15)
                if poll_status != 200:
                    continue
                poll_result = orjson.loads(poll_body)
                state = poll_result.get("status")
                if show_progress and prog is not None:
                    prog.update(task_id, description=f"Async query: {state} (poll {poll_num + 1}/{max_polls})")
                self._save_async_job_state(
                    job_href,
                    status=state,
                    rules_status=poll_result.get("rules"),
                    result_href=poll_result.get("result"),
                )
                if state == "completed":
                    break
                if state == "failed":
                    logger.debug(f"Async query failed: {job_href}")
                    return poll_result
            else:
                logger.debug(f"Async query timed out: {job_href}")
                self._save_async_job_state(job_href, status="timeout")
                return {"status": "timeout"}

        if compute_draft:
            update_rules_url = f"{c.api_cfg['url']}/api/v2{job_href}/update_rules"
            ur_status, ur_body = c._request(update_rules_url, method="PUT", data={}, timeout=30)
            if ur_status in (202, 204):
                time.sleep(10)
                for _ in range(max_polls):
                    poll_status, poll_body = c._request(poll_url, timeout=15)
                    if poll_status != 200:
                        time.sleep(2)
                        continue
                    poll_result = orjson.loads(poll_body)
                    state = poll_result.get("status")
                    rules_state = poll_result.get("rules")
                    self._save_async_job_state(
                        job_href,
                        status=state,
                        rules_status=rules_state,
                        result_href=poll_result.get("result"),
                    )
                    if state == "completed" and rules_state in (None, "", "completed"):
                        return poll_result
                    if state == "failed":
                        return poll_result
                    time.sleep(2)
            else:
                ur_text = ur_body.decode('utf-8', errors='replace') if isinstance(ur_body, bytes) else str(ur_body)
                logger.warning(f"update_rules returned {ur_status}: {ur_text[:200]}, proceeding without draft policy data")

        return poll_result

    def poll_async_query(self, job_href, timeout=120):
        """Poll an async query until completed/failed. Returns True if completed."""
        poll_result = self._wait_for_async_query(job_href, timeout=timeout, compute_draft=False)
        return poll_result.get("status") == "completed"

    def iter_async_query_results(self, job_href):
        """Download completed async query results and yield flow dicts one by one."""
        c = self._client
        dl_url = f"{c.api_cfg['url']}/api/v2{job_href}/download"
        dl_status, dl_body = c._request(dl_url, timeout=60)
        if dl_status != 200:
            logger.debug(f"download_async_query failed: {dl_status}")
            self._save_async_job_state(job_href, download_status=f"failed:{dl_status}")
            return

        buffer = BytesIO(dl_body)

        def _parse_lines(lines_iter):
            for line in lines_iter:
                line = line.strip() if isinstance(line, str) else line.strip()
                if not line or line in (b'[', b']', '[', ']'):
                    continue
                if isinstance(line, bytes) and line.endswith(b','):
                    line = line[:-1]
                elif isinstance(line, str) and line.endswith(','):
                    line = line[:-1]
                try:
                    data = orjson.loads(line)
                    if isinstance(data, list):
                        for item in data:
                            yield item
                    else:
                        yield data
                except json.JSONDecodeError:
                    pass  # intentional fallback: skip non-JSON lines in JSONL stream (e.g. blank or partial lines)

        try:
            with gzip.GzipFile(fileobj=buffer, mode='rb') as f:
                for item in _parse_lines(f):
                    yield item
        except (gzip.BadGzipFile, OSError):
            buffer.seek(0)
            text_data = buffer.read().decode('utf-8', errors='replace')
            for item in _parse_lines(text_data.splitlines()):
                yield item

    def summarize_async_query(self, job_href):
        """Stream an async query and return count plus simple service breakdown."""
        count = 0
        flows_by_port = {}
        for flow in self.iter_async_query_results(job_href):
            count += 1
            svc = flow.get("service", {})
            port = svc.get("port") if isinstance(svc, dict) else None
            proto = svc.get("proto") if isinstance(svc, dict) else None
            if port is None:
                port = flow.get("dst_port")
            if proto is None:
                proto = flow.get("proto")

            if port is None and proto is None:
                key = "all"
            else:
                proto_label = proto
                try:
                    proto_int = int(proto)
                    if proto_int == 6:
                        proto_label = "tcp"
                    elif proto_int == 17:
                        proto_label = "udp"
                    elif proto_int == 1:
                        proto_label = "icmp"
                except (TypeError, ValueError):
                    proto_label = str(proto or "").lower() or "any"
                key = f"{port or 'all'}/{proto_label}"
            flows_by_port[key] = flows_by_port.get(key, 0) + 1

        self._save_async_job_state(
            job_href,
            download_status="completed",
            flow_count=count,
            flows_by_port=flows_by_port,
        )
        return {
            "count": count,
            "flows_by_port": flows_by_port,
        }

    def download_async_query(self, job_href):
        """Download completed async query results. Returns list of flow dicts."""
        flows = list(self.iter_async_query_results(job_href) or [])
        self._save_async_job_state(job_href, download_status="completed", flow_count=len(flows))
        return flows

    def download_async_query_csv(self, job_href, include_draft_policy=False):
        """Download completed async query results as raw CSV text."""
        c = self._client
        dl_url = f"{c.api_cfg['url']}/api/v2{job_href}/download"
        if include_draft_policy:
            dl_url += "?include_draft_policy_in_csv=true"
        dl_status, dl_body = c._request(dl_url, timeout=60)
        if dl_status != 200:
            self._save_async_job_state(job_href, download_status=f"failed:{dl_status}")
            raise RuntimeError(f"CSV download failed with status {dl_status}")

        text = dl_body.decode("utf-8", errors="replace") if isinstance(dl_body, bytes) else str(dl_body)
        line_count = len([line for line in text.splitlines() if line.strip()])
        row_count = max(0, line_count - 1) if line_count else 0
        self._save_async_job_state(
            job_href,
            download_status="completed",
            download_format="csv",
            csv_row_count=row_count,
        )
        return {
            "text": text,
            "row_count": row_count,
        }
