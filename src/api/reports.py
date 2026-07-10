"""PCE Reports API — native Rule Hit Count report pull.

Flow: POST /orgs/:org/reports (rule_hit_count template, csv format)
      -> poll GET <report href> until status == done
      -> GET <report href>/download, write bytes to a temp CSV file.
"""
from __future__ import annotations

import os
import tempfile
import time
import uuid

from loguru import logger


class RuleHitCountPullTimeout(TimeoutError):
    """Polling exceeded timeout_seconds. report_href allows a later retry/CSV path."""

    def __init__(self, report_href: str):
        self.report_href = report_href
        super().__init__(f"rule hit count report not ready in time: {report_href}")


class ReportsApi:
    def __init__(self, client):
        self._c = client   # ApiClient (facade) — uses its _api_post/_api_get/_request

    def pull_rule_hit_count_report(
        self,
        last_num_days: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        rule_sets: list | None = None,
        timeout_seconds: int = 600,
        poll_interval_seconds: int = 5,
    ) -> str:
        """Generate + download the native report. Returns a local temp CSV path.

        Caller owns (and should unlink) the returned file.

        PCE-side cleanup: the reports API has no DELETE endpoint; generated
        report objects are purged automatically by the PCE once
        report_retention_days (max 7 days) elapses (official API guide /
        Visualization Guide). Repeated pulls therefore accumulate at most a
        bounded, self-expiring set of report objects — no manual cleanup is
        possible or required.
        """
        org = self._c.api_cfg['org_id']
        if start_date and end_date:
            time_range = {"start_date": start_date, "end_date": end_date}
        else:
            time_range = {"last_num_days": int(last_num_days or 30)}

        payload = {
            "report_template": {"href": f"/orgs/{org}/report_templates/rule_hit_count_report"},
            "description": "illumio-ops rule hit count pull",
            "report_parameters": {
                "report_time_range": time_range,
                "rule_sets": rule_sets or [],   # [] = all rulesets
            },
            "report_format": "csv",
        }
        status, body = self._c._api_post(f"/orgs/{org}/reports", payload)
        if status not in (200, 201) or not body:
            raise RuntimeError(f"rule hit count report submit failed: HTTP {status}")
        href = body.get("href", "")
        logger.info(f"Rule hit count report submitted: {href}")

        deadline = time.monotonic() + timeout_seconds
        while True:
            status, rep = self._c._api_get(href)
            state = str((rep or {}).get("status", "")).lower() if status == 200 else ""
            if state == "done":
                break
            if state in ("failed", "error"):
                raise RuntimeError(f"rule hit count report failed on PCE: {href}")
            if time.monotonic() >= deadline:
                raise RuleHitCountPullTimeout(href)
            time.sleep(poll_interval_seconds)

        url = f"{self._c.api_cfg['url']}/api/v2{href}/download"
        status, content = self._c._request(url, timeout=60)
        if status != 200:
            raise RuntimeError(f"rule hit count report download failed: HTTP {status}")
        out = os.path.join(tempfile.gettempdir(), f"rhc_native_{uuid.uuid4().hex}.csv")
        with open(out, "wb") as fh:
            fh.write(content if isinstance(content, bytes) else bytes(content))
        return out
