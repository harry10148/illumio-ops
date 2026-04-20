from __future__ import annotations
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger
from src.siem.transports.base import Transport


class SplunkHECTransport(Transport):
    def __init__(
        self,
        endpoint: str,
        token: str,
        verify_tls: bool = True,
        sourcetype: str = "illumio_ops",
        timeout: float = 10.0,
    ):
        self._endpoint = endpoint.rstrip("/") + "/services/collector/event"
        self._token = token
        self._verify = verify_tls
        self._sourcetype = sourcetype
        self._timeout = timeout
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update({"Authorization": f"Splunk {self._token}"})
        return s

    def send(self, payload: str) -> None:
        body = {"event": payload, "sourcetype": self._sourcetype}
        resp = self._session.post(
            self._endpoint,
            json=body,
            verify=self._verify,
            timeout=self._timeout,
        )
        resp.raise_for_status()

    def close(self) -> None:
        self._session.close()
