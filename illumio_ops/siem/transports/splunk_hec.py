from __future__ import annotations

import json
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from illumio_ops.siem.transports.base import Transport


class SplunkHECTransport(Transport):
    def __init__(self, endpoint: str, token: str, verify_tls: bool = True, sourcetype: str = "illumio_ops",
                 timeout: float = 10.0, ca_bundle: str | None = None) -> None:
        self._endpoint = endpoint.rstrip("/") + "/services/collector/event"
        self._token = token
        self._verify: bool | str = ca_bundle if (verify_tls and ca_bundle) else verify_tls
        self._sourcetype = sourcetype
        self._timeout = timeout
        self._session: requests.Session | None = self._build_session()

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        # POST is resent automatically only when it surely was not taken: connect failures, 429, 503 (HEC queue
        # full). 500/502/504 and read timeouts may already be in Splunk: the dispatcher decides about those.
        retry = Retry(total=3, connect=3, read=0, status=3, backoff_factor=0.5, status_forcelist=[429, 503],
                      allowed_methods=["POST"], respect_retry_after_header=True)
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update({"Authorization": f"Splunk {self._token}"})
        return s

    def send(self, payload: str) -> None:
        self.send_record(payload)

    def send_record(self, payload: str, event_time: float | None = None) -> None:
        event_data: Any
        try:
            event_data = json.loads(payload)
        except (ValueError, TypeError):
            event_data = payload  # CEF and other non-JSON formats stay as string
        body: dict[str, Any] = {"event": event_data, "sourcetype": self._sourcetype}
        # /services/collector/event takes no time from the content: without `time` a backlog or a DLQ resend
        # lands at the time it was received.
        if event_time is not None:
            body["time"] = round(float(event_time), 3)
        if self._session is None:
            self._session = self._build_session()
        resp = self._session.post(self._endpoint, json=body, verify=self._verify, timeout=self._timeout)
        resp.raise_for_status()

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            finally:
                self._session = None
