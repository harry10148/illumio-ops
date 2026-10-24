"""PCE HTTP core, ported from 5.x src/api_client.py (session, retry, POST 429 handling).

Difference from 5.x on purpose: a connection-layer failure raises
PceTransportError instead of returning (0, bytes) — 5.x callers turned that
into empty results that looked like "the PCE has nothing".
"""
from __future__ import annotations

import errno
import json as _json
import math
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Literal, Self

import requests
import urllib3
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from illumio_ops.pce.rate_limit import RateLimiter
from illumio_ops.settings.schema import PceSettings

TransportKind = Literal["dns", "refused", "timeout", "tls", "ca_bundle", "other"]

MAX_RETRIES = 3
POST_429_DEFAULT_WAIT = 2.0
POST_429_MAX_WAIT = 30.0

_sleep = time.sleep  # module-level so tests can observe waits without sleeping

# "Verify with the system's trusted CAs" means the operating system's store, where an
# organisation installs its own CA. requests' default (certifi) is a fixed public list that
# ignores it. First existing file wins; none → requests' bundled list.
SYSTEM_CA_BUNDLES: tuple[str, ...] = (
    "/etc/ssl/certs/ca-certificates.crt",   # Debian, Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",     # RHEL, Rocky, Fedora
    "/etc/ssl/ca-bundle.pem",               # SUSE
    "/etc/ssl/cert.pem",                    # Alpine, macOS
)


def _system_ca_bundle() -> str | None:
    return next((p for p in SYSTEM_CA_BUNDLES if os.path.isfile(p)), None)


class PceNotConfigured(Exception):
    """The PCE connection has not been filled in yet."""


class PceBudgetExhausted(Exception):
    """The outbound rate limiter had no budget within the allowed wait."""


class PceTransportError(Exception):
    def __init__(self, path: str, kind: TransportKind) -> None:
        self.path = path
        self.kind: TransportKind = kind
        super().__init__(f"PCE request {path} failed: {kind}")


@dataclass(frozen=True)
class PceResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return _json.loads(self.body)


def _transport_kind(exc: BaseException) -> TransportKind:
    if isinstance(exc, requests.exceptions.SSLError):
        return "tls"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, urllib3.exceptions.NameResolutionError):
            return "dns"
        if isinstance(cur, ConnectionRefusedError) or getattr(cur, "errno", None) == errno.ECONNREFUSED:
            return "refused"
        if isinstance(cur, OSError) and "Name or service not known" in str(cur):
            return "dns"
        nxt = cur.__cause__ or cur.__context__
        if nxt is None and cur.args and isinstance(cur.args[-1], BaseException):
            nxt = cur.args[-1]
        if nxt is None:
            reason = getattr(cur, "reason", None)
            nxt = reason if isinstance(reason, BaseException) else None
        cur = nxt
    return "other"


_tls_off_warned = False


def _make_session(cfg: PceSettings, *, retries: bool) -> requests.Session:
    global _tls_off_warned
    s = requests.Session()
    if isinstance(cfg.verify_tls, str):
        s.verify = cfg.verify_tls
    elif cfg.verify_tls:
        s.verify = _system_ca_bundle() or True
    else:
        s.verify = False
    if s.verify is False:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        if not _tls_off_warned:
            _tls_off_warned = True
            logger.warning("TLS certificate verification is disabled for the PCE connection")
    s.auth = (cfg.api_key, cfg.api_secret)
    s.headers.update({"Accept": "application/json"})
    if retries:
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=1.0,
            status_forcelist=[429, 502, 503, 504],
            # POST is never retried automatically: after a read timeout the PCE may
            # already have acted (provision/create would run twice). POST 429 is
            # handled in request(): a 429 means the PCE did not process it.
            allowed_methods=frozenset({"GET", "HEAD", "PUT", "DELETE"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=retry)
    else:
        # One attempt: callers that own a deadline (events) run their own loop.
        adapter = HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=0)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def _retry_after_seconds(raw: str | None) -> float:
    try:
        wait = float(raw) if raw is not None else POST_429_DEFAULT_WAIT
    except (TypeError, ValueError):
        wait = POST_429_DEFAULT_WAIT
    if not math.isfinite(wait):
        wait = POST_429_DEFAULT_WAIT
    return min(max(wait, 0.0), POST_429_MAX_WAIT)


class PceClient:
    def __init__(self, cfg: PceSettings, *, rate_limiter: RateLimiter | None = None) -> None:
        self._cfg = cfg
        self._rate_limiter = rate_limiter
        self._session: requests.Session | None = _make_session(cfg, retries=True)
        self._bounded_session: requests.Session | None = _make_session(cfg, retries=False)

    def _url(self, path: str, org_scoped: bool) -> str:
        if org_scoped:
            return f"{self._cfg.url}/api/v2/orgs/{self._cfg.org_id}{path}"
        return f"{self._cfg.url}/api/v2{path}"

    def _acquire(self, timeout: float) -> bool:
        return self._rate_limiter is None or self._rate_limiter.acquire(timeout=timeout)

    def request(self, method: str, path: str, *, json: Any = None, timeout: float = 15,
                org_scoped: bool = True, bounded: bool = False, deadline: float | None = None,
                budget_timeout: float = 30.0, headers: Mapping[str, str] | None = None) -> PceResponse:
        session = self._bounded_session if bounded else self._session
        if session is None:
            raise RuntimeError("PceClient is closed")
        if deadline is not None:
            budget_timeout = min(budget_timeout, max(deadline - time.monotonic(), 0.0))
        if not self._acquire(budget_timeout):
            raise PceBudgetExhausted(path)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PceTransportError(path, "timeout")
            timeout = min(timeout, remaining)
        send_headers: dict[str, str] = dict(headers or {})
        body = None
        if json is not None:
            body = _json.dumps(json).encode("utf-8")
            send_headers["Content-Type"] = "application/json"
        url = self._url(path, org_scoped)

        def send() -> requests.Response:
            assert session is not None
            try:
                return session.request(method=method, url=url, data=body, headers=send_headers, timeout=timeout)
            except requests.exceptions.RequestException as exc:
                kind = _transport_kind(exc)
                logger.warning("PCE {} {} failed: {} ({})", method, path, kind, type(exc).__name__)
                raise PceTransportError(path, kind) from None
            except OSError as exc:
                # requests raises a bare OSError when the configured CA bundle cannot be read.
                kind = "ca_bundle" if "CA certificate bundle" in str(exc) else "other"
                logger.warning("PCE {} {} failed: {} ({})", method, path, kind, type(exc).__name__)
                raise PceTransportError(path, kind) from None

        resp = send()
        if method == "POST" and resp.status_code == 429:
            _sleep(_retry_after_seconds(resp.headers.get("Retry-After")))
            # A 429 is a throttling signal: the retry needs fresh budget, or we give
            # the caller the original 429 rather than pushing harder.
            if not self._acquire(budget_timeout):
                logger.warning("POST 429 retry skipped for {}: no rate budget", path)
            else:
                resp = send()
        return PceResponse(resp.status_code, resp.content, dict(resp.headers))

    def close(self) -> None:
        for attr in ("_session", "_bounded_session"):
            s = getattr(self, attr)
            if s is not None:
                s.close()
                setattr(self, attr, None)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> Literal[False]:
        self.close()
        return False


def client_from_settings(cfg: PceSettings, *, rate_limiter: RateLimiter | None = None) -> PceClient:
    if not (cfg.url and cfg.org_id and cfg.api_key and cfg.api_secret):
        raise PceNotConfigured()
    return PceClient(cfg, rate_limiter=rate_limiter)
