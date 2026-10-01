from __future__ import annotations
import json
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
        self.send_record(payload)

    def send_record(self, payload: str, event_time: float | None = None) -> None:
        try:
            event_data = json.loads(payload)
        except (ValueError, TypeError):
            event_data = payload  # CEF and other non-JSON formats stay as string
        body = {"event": event_data, "sourcetype": self._sourcetype}
        # /services/collector/event 不會從內容抽時間：沒帶 `time` 時 Splunk 以
        # 收到當下為事件時間，積壓或 DLQ replay 時時間軸就會偏移數小時。
        if event_time is not None:
            body["time"] = round(float(event_time), 3)
        resp = self._session.post(
            self._endpoint,
            json=body,
            verify=self._verify,
            timeout=self._timeout,
        )
        resp.raise_for_status()

    def close(self) -> None:
        if getattr(self, "_session", None) is not None:
            try:
                self._session.close()
            except Exception:
                pass
            finally:
                self._session = None
