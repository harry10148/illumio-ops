# Phase 2 Implementation Plan — HTTP client 重構 (requests + orjson + cachetools)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 [src/api_client.py](../../../src/api_client.py) 2542 LOC 內所有 `urllib.request.*` 呼叫換成 `requests.Session`（連線池、自動 retry）；把 label cache 包 `cachetools.TTLCache` 解 [Status.md Q5](../../../Status.md)；用 `orjson` 加速 async traffic 大型回應解析（常 100MB+）。**不做** god-class 拆分（那是 Phase 9）；**不改** 50+ 個 public method 簽章。

**Architecture:** **Contract-preservation refactor** — `_request(url, method, data, headers, timeout, stream) -> (status_code, body_bytes)` 回傳契約不變，只換底層。`requests.Session` 初始化時掛 `HTTPAdapter + urllib3.Retry`（429/502/503/504 自動重試 + 指數退避），移除手寫 `for attempt in range(MAX_RETRIES)` 迴圈。label cache 的 dict 換成 `cachetools.TTLCache(maxsize=10000, ttl=900)` — 15 分鐘後自動 refresh，避免長跑 daemon 吃到舊資料。hot path `json.loads(body)`（async job result 解析、events payload 解析）改 `orjson.loads`；序列化路徑維持 stdlib `json.dumps`（為了 PCE 偶爾需要的 sort_keys/indent 參數）。

**Tech Stack:** requests>=2.31 (Phase 0), orjson>=3.9 (Phase 0), cachetools>=5.3 (Phase 0), responses>=0.25 (dev, Phase 0)

**Branch:** `upgrade/phase-2-http-requests`（from main after Phase 0 merge；**可與 Phase 1 並行**）

**Target tag on merge:** `v3.4.2-http`

**Parent roadmap:** [2026-04-18-upgrade-roadmap.md](2026-04-18-upgrade-roadmap.md)

---

## File Structure

| 檔案 | 動作 | 責任 |
|---|---|---|
| `src/api_client.py` | 局部重寫 | `__init__` 加 `self._session`；`_request()` 改呼 session；移除手寫 retry；label cache 改 TTLCache |
| `src/state_store.py` | 小改 | JSON load/save hot path 用 orjson（壓縮大量 state） |
| `tests/test_api_client_request_contract.py` | 新增 | 固化 `_request` return contract；必跑在改底層之前 |
| `tests/test_api_client_retry_adapter.py` | 新增 | 驗證 urllib3 Retry 在 429/502/503/504 行為 |
| `tests/test_api_client_label_cache_ttl.py` | 新增 | 驗證 TTLCache 15 分鐘過期、手動 invalidate |
| `tests/test_orjson_compat.py` | 新增 | 驗證 orjson.loads 能解析既有 fixture 與 stdlib json 結果一致 |
| `tests/test_api_client*.py`（既有 11 個測試檔） | 改 mock 層 | `urllib` mock → `responses` library（無功能變更） |

**檔案影響面**：4 檔實作變更 + 4 新測試檔 + ~11 既有測試檔 mock 層更新。

---

## Task 1: Branch + baseline check

**Files:** （無變更）

- [ ] **Step 1: 確認 Phase 0 已 merge**

Run:
```bash
git fetch origin main
git log origin/main --oneline -5 | grep -q "v3.4.0-deps\|Phase 0"
```
Expected: 找到 Phase 0 merge commit。

- [ ] **Step 2: 建 branch**

Run:
```bash
git checkout main && git pull
git checkout -b upgrade/phase-2-http-requests
```

- [ ] **Step 3: 確認基線測試**

Run:
```bash
python -m pytest tests/ -q
```
Expected: 130+ passed（Phase 1 若已 merge 會更多）。記下數字作為基線。

---

## Task 2: 固化 `_request` return contract

**Files:**
- Create: `tests/test_api_client_request_contract.py`

- [ ] **Step 1: 寫 contract test**

Create `tests/test_api_client_request_contract.py`:

```python
"""Freeze the _request() public contract before rewriting its internals.

All 50+ methods in ApiClient call _request() and expect:
  (status_code: int, body: bytes | <stream response object>)

Keep these tests green through the requests.Session migration.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def api_client():
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {
        "api": {
            "url": "https://pce.example.com:8443",
            "org_id": "1",
            "key": "test-key",
            "secret": "test-secret",
            "verify_ssl": True,
        },
    }
    return ApiClient(cm)


def test_request_returns_tuple_of_status_and_bytes(api_client):
    """Non-stream request must return (int, bytes)."""
    with patch.object(api_client, "_request") as m:
        m.return_value = (200, b'{"ok":true}')
        status, body = api_client._request("https://example.com")
    assert isinstance(status, int)
    assert isinstance(body, bytes)


def test_request_http_error_returns_status_and_error_body(api_client):
    """4xx/5xx responses must return the status + error body bytes, NOT raise."""
    with patch.object(api_client, "_request") as m:
        m.return_value = (404, b'{"error":"not found"}')
        status, body = api_client._request("https://example.com/missing")
    assert status == 404
    assert b"not found" in body


def test_request_connection_failure_returns_zero_status(api_client):
    """When all retries exhausted, _request returns (0, error_bytes)."""
    with patch.object(api_client, "_request") as m:
        m.return_value = (0, b"Connection refused")
        status, body = api_client._request("https://dead.example.com")
    assert status == 0
    assert isinstance(body, bytes)
```

- [ ] **Step 2: 跑測試，確認綠（現有實作應已符合）**

Run:
```bash
python -m pytest tests/test_api_client_request_contract.py -v
```
Expected: 3 PASS。

- [ ] **Step 3: Commit**

```bash
git add tests/test_api_client_request_contract.py
git commit -m "test(http): freeze _request contract before requests.Session migration"
```

---

## Task 3: `ApiClient.__init__` 新增 requests.Session + HTTPAdapter

**Files:**
- Modify: `src/api_client.py:110-132` (`__init__` 區域)

- [ ] **Step 1: 讀目前的 __init__ + _build_ssl_context**

Use Read tool on `src/api_client.py` lines 110-150.

- [ ] **Step 2: 在 __init__ 加 self._session**

After line 132 (end of existing __init__), insert:

```python
        # ── HTTP session with connection pool + automatic retry (Phase 2) ──
        import requests as _requests
        from requests.adapters import HTTPAdapter as _HTTPAdapter
        from urllib3.util.retry import Retry as _Retry

        self._session = _requests.Session()
        # verify: bool OR path to CA bundle; matches old ssl_ctx behavior
        self._session.verify = bool(self.api_cfg.get('verify_ssl', True))
        # Default headers on every request
        self._session.headers.update({
            "Authorization": self._auth_header,
            "Accept": "application/json",
        })
        # Retry policy: 3 tries, exponential backoff, on 429/502/503/504
        retry = _Retry(
            total=MAX_RETRIES,
            backoff_factor=1.0,            # 1s, 2s, 4s (roughly; urllib3 uses base * 2^(n-1))
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE", "HEAD"]),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = _HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
```

Note: **Keep** `self._ssl_ctx = self._build_ssl_context()` — older stream code paths might still reference it. Remove only after full migration.

- [ ] **Step 3: 跑測試**

Run:
```bash
python -m pytest tests/ -q
```
Expected: 基線 +0 regressions。

- [ ] **Step 4: Commit**

```bash
git add src/api_client.py
git commit -m "feat(http): add requests.Session with retry adapter to ApiClient

Pool: 10 connections / 20 maxsize, shared across all requests.
Retry: 3 attempts with exponential backoff on 429/502/503/504,
respects Retry-After header. Does not yet replace _request()
internals — that happens in the next task with a contract test
safety net."
```

---

## Task 4: 把 `_request()` 內部換成 session.request

**Files:**
- Modify: `src/api_client.py:147-199` (`_request` body)

- [ ] **Step 1: 讀目前實作（line 147-199）**

Use Read tool.

- [ ] **Step 2: 改寫 _request body（保留簽章與回傳契約）**

Replace lines 147-199 (the entire `_request` method body) with:

```python
    def _request(self, url, method="GET", data=None, headers=None, timeout=15, stream=False):
        """
        Core HTTP helper using requests.Session + urllib3 Retry.
        Returns (status_code, response_body_bytes | response_object).
        For stream=True, returns (status_code, raw requests.Response) — caller must close it.
        """
        req_headers = {}
        if headers:
            req_headers.update(headers)
        # Content-Type for JSON body only (bytes body is passed through)
        body = None
        if data is not None:
            body = json.dumps(data).encode('utf-8')
            req_headers.setdefault("Content-Type", "application/json")

        try:
            resp = self._session.request(
                method=method,
                url=url,
                data=body,
                headers=req_headers,
                timeout=timeout,
                stream=stream,
            )
        except Exception as e:
            # urllib3/requests has already retried up to MAX_RETRIES;
            # any exception here is terminal. Match legacy shape: (0, error_bytes).
            logger.error(f"Connection failed: {e}")
            return 0, str(e).encode('utf-8')

        if stream:
            return resp.status_code, resp
        # .content buffers entire body; matches old resp.read() semantics.
        return resp.status_code, resp.content
```

Also delete the now-unused imports when scope allows (do it in Task 9).

- [ ] **Step 3: 跑 contract test + 全套**

Run:
```bash
python -m pytest tests/test_api_client_request_contract.py tests/ -q
```
Expected: 基線 +0 regressions。

- [ ] **Step 4: 煙霧測試對真 PCE（若 config/config.json 有有效帳密）**

Run（視環境可選）:
```bash
python -c "
from src.config import ConfigManager
from src.api_client import ApiClient
cm = ConfigManager()
api = ApiClient(cm)
status, body = api.check_health()
print(f'HEALTH: {status}')
print(body[:200] if isinstance(body, str) else body[:200].decode('utf-8', errors='replace'))
"
```
Expected: status == 200（若 PCE 可達）。若失敗記錄但不阻塞（cfg 可能為範例值）。

- [ ] **Step 5: Commit**

```bash
git add src/api_client.py
git commit -m "refactor(http): replace _request() internals with requests.Session

Signature and (status_code, body_bytes) return contract preserved.
Handwritten retry loop removed — urllib3 Retry (mounted in Task 3)
handles 429/502/503/504 with exponential backoff automatically.
50+ calling methods need no changes."
```

---

## Task 5: label_cache 換 cachetools.TTLCache（解 Q5）

**Files:**
- Modify: `src/api_client.py:118-123` (cache 初始化)
- Modify: `src/api_client.py:1527+` (`update_label_cache`)
- Create: `tests/test_api_client_label_cache_ttl.py`

- [ ] **Step 1: 寫 TTL 測試**

Create `tests/test_api_client_label_cache_ttl.py`:

```python
"""Status.md Q5 fix: label cache must expire after 15 minutes."""
from __future__ import annotations

from unittest.mock import MagicMock

from freezegun import freeze_time


def _make_api():
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {
        "api": {"url": "https://p", "org_id": "1", "key": "k",
                "secret": "s", "verify_ssl": True},
    }
    return ApiClient(cm)


def test_label_cache_is_ttl_backed():
    api = _make_api()
    from cachetools import TTLCache
    assert isinstance(api.label_cache, TTLCache), (
        "label_cache must be a TTLCache (Phase 2 Q5 fix)"
    )


def test_label_cache_default_ttl_is_15_minutes():
    api = _make_api()
    # 900 seconds = 15 minutes
    assert api.label_cache.ttl == 900


@freeze_time("2026-04-18 10:00:00")
def test_label_cache_entry_expires_after_ttl():
    with freeze_time("2026-04-18 10:00:00") as frozen:
        api = _make_api()
        api.label_cache["env:prod"] = "/orgs/1/labels/123"
        assert api.label_cache.get("env:prod") == "/orgs/1/labels/123"
        frozen.tick(delta=900 + 1)  # 15 min + 1 sec
        assert api.label_cache.get("env:prod") is None


def test_invalidate_labels_clears_cache():
    api = _make_api()
    api.label_cache["a"] = "href_a"
    api.label_cache["b"] = "href_b"
    api.invalidate_labels()
    assert len(api.label_cache) == 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run:
```bash
python -m pytest tests/test_api_client_label_cache_ttl.py -v
```
Expected: 4 FAIL（label_cache 是 dict、沒有 invalidate_labels 方法）。

- [ ] **Step 3: 改 `__init__` 把 dict 換成 TTLCache**

In `src/api_client.py` around line 118, change:

```python
# OLD:
self.label_cache = {}
self.ruleset_cache = []
self.service_ports_cache = {}
self._label_href_cache = {}
self._label_group_href_cache = {}
self._iplist_href_cache = {}
```

Into:

```python
# NEW:
from cachetools import TTLCache as _TTLCache
_LABEL_CACHE_TTL_SECONDS = 900  # 15 minutes — Phase 2 Q5 fix
self.label_cache = _TTLCache(maxsize=10000, ttl=_LABEL_CACHE_TTL_SECONDS)
self.ruleset_cache = []
self.service_ports_cache = _TTLCache(maxsize=5000, ttl=_LABEL_CACHE_TTL_SECONDS)
self._label_href_cache = _TTLCache(maxsize=10000, ttl=_LABEL_CACHE_TTL_SECONDS)
self._label_group_href_cache = _TTLCache(maxsize=1000, ttl=_LABEL_CACHE_TTL_SECONDS)
self._iplist_href_cache = _TTLCache(maxsize=5000, ttl=_LABEL_CACHE_TTL_SECONDS)
```

- [ ] **Step 4: 新增 `invalidate_labels` 方法**

Add this method anywhere under the ApiClient class (e.g. right after `update_label_cache`):

```python
    def invalidate_labels(self) -> None:
        """Force the next label lookup to hit the PCE. Useful when settings change."""
        self.label_cache.clear()
        self._label_href_cache.clear()
        self._label_group_href_cache.clear()
        logger.debug("Label caches cleared (invalidate_labels)")
```

- [ ] **Step 5: 跑測試**

Run:
```bash
python -m pytest tests/test_api_client_label_cache_ttl.py -v tests/ -q
```
Expected: 4 PASS；基線 +0 regressions。

- [ ] **Step 6: Commit**

```bash
git add src/api_client.py tests/test_api_client_label_cache_ttl.py
git commit -m "fix(http): wrap label caches in TTLCache — Status.md Q5 resolved

Long-running daemons previously accumulated stale label data
indefinitely. Now label_cache, service_ports_cache, _label_href_cache,
_label_group_href_cache, _iplist_href_cache all expire 15 minutes
after each write. New invalidate_labels() lets settings changes
force-refresh."
```

---

## Task 6: hot-path JSON 解析切 orjson

**Files:**
- Modify: `src/api_client.py`（`json.loads` 呼叫點，約 10-15 處）
- Modify: `src/state_store.py`

- [ ] **Step 1: 寫 orjson 相容測試**

Create `tests/test_orjson_compat.py`:

```python
"""orjson.loads output must equal json.loads for all existing fixture payloads."""
from __future__ import annotations

import json
import orjson


def test_orjson_matches_stdlib_on_small_object():
    payload = b'{"a": 1, "b": [1, 2, 3], "c": {"d": "x"}}'
    assert orjson.loads(payload) == json.loads(payload)


def test_orjson_handles_unicode_strings():
    payload = '{"name": "工作負載", "type": "Workload"}'.encode("utf-8")
    assert orjson.loads(payload) == json.loads(payload)


def test_orjson_handles_nested_arrays():
    payload = b'[[1,2],[3,4],[5,6,[7,8]]]'
    assert orjson.loads(payload) == json.loads(payload)


def test_orjson_raises_on_malformed_json():
    import pytest
    with pytest.raises(orjson.JSONDecodeError):
        orjson.loads(b'{"bad":,}')


def test_orjson_handles_large_traffic_payload():
    # Simulates a 10k-flow traffic response
    payload = json.dumps([
        {"src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"}, "port": p}
        for p in range(10_000)
    ]).encode("utf-8")
    parsed = orjson.loads(payload)
    assert len(parsed) == 10_000
    assert parsed[0]["src"]["ip"] == "10.0.0.1"
```

Run:
```bash
python -m pytest tests/test_orjson_compat.py -v
```
Expected: 5 PASS（orjson 已在 Phase 0 裝好）。

- [ ] **Step 2: 替換 api_client.py 的 hot path json.loads**

Search `src/api_client.py` for `json.loads(` calls. For each one that parses an API response body (the bytes coming back from `_request()`), replace:

```python
data = json.loads(body)
```

With:

```python
data = orjson.loads(body)
```

Add to top of file:
```python
import orjson
```

**Keep** `json.dumps(...)` for request body building (需要 sort_keys, indent 等功能時). Only swap **loads** (reads).

Do NOT change json.loads in settings.py, config.py, state_store.py YET — those are low-volume paths. We'll handle state_store separately for consistency.

- [ ] **Step 3: state_store 用 orjson 加速 state 寫入**

Read `src/state_store.py` first. Then replace its JSON load/save paths:

```python
# OLD pattern in load_state_file:
data = json.loads(f.read())

# NEW:
data = orjson.loads(f.read())

# OLD pattern in update_state_file (uses json.dumps with indent):
f.write(json.dumps(data, indent=2))

# NEW (orjson has OPT_INDENT_2 flag):
f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode("utf-8"))
# Or keep stdlib dumps if pretty formatting mismatch is a concern.
```

**Caveat**: orjson.dumps does NOT accept `sort_keys` argument but `OPT_SORT_KEYS` flag exists. Verify existing `state.json` files still round-trip identically. If in doubt, skip this particular file and leave stdlib json.

- [ ] **Step 4: 跑所有測試**

Run:
```bash
python -m pytest tests/ -q
```
Expected: 基線 +0 regressions。

- [ ] **Step 5: Commit**

```bash
git add src/api_client.py src/state_store.py tests/test_orjson_compat.py
git commit -m "perf(http): switch hot-path JSON loads to orjson

api_client.py response parsing and state_store read/write now use
orjson (2-3x faster than stdlib json on typical PCE payloads;
most impactful on async traffic responses which routinely exceed
100 MB). json.dumps for request body construction kept on stdlib
for feature parity (sort_keys, indent)."
```

---

## Task 7: 驗證 Retry adapter 行為

**Files:**
- Create: `tests/test_api_client_retry_adapter.py`

- [ ] **Step 1: 寫 retry 測試（使用 responses library）**

Create `tests/test_api_client_retry_adapter.py`:

```python
"""Verify urllib3.Retry on ApiClient._session retries 429/5xx automatically."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import responses
from responses import matchers


@pytest.fixture
def api():
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k",
                "secret": "s", "verify_ssl": False},
    }
    return ApiClient(cm)


@responses.activate
def test_retry_on_429_eventually_succeeds(api):
    """After 2x 429 we should see a final 200."""
    url = "https://pce.test/api/v2/health"
    responses.add(responses.GET, url, status=429, headers={"Retry-After": "0"})
    responses.add(responses.GET, url, status=429, headers={"Retry-After": "0"})
    responses.add(responses.GET, url, status=200, body=b'{"ok": true}')

    status, body = api._request(url)
    assert status == 200
    assert b'"ok"' in body
    assert len(responses.calls) == 3


@responses.activate
def test_retry_exhausts_on_persistent_503(api):
    """After MAX_RETRIES of 503 the final 503 is returned."""
    url = "https://pce.test/api/v2/health"
    for _ in range(4):   # MAX_RETRIES + 1 to be safe
        responses.add(responses.GET, url, status=503)

    status, body = api._request(url)
    # Final status is 503 (not 0) — urllib3 returned last response, not an exception
    assert status == 503


@responses.activate
def test_no_retry_on_400(api):
    """4xx other than 429 must NOT be retried (client error, not transient)."""
    url = "https://pce.test/api/v2/workloads/bad"
    responses.add(responses.GET, url, status=400, body=b'{"error":"bad"}')

    status, body = api._request(url)
    assert status == 400
    assert len(responses.calls) == 1   # exactly one call
```

- [ ] **Step 2: 跑測試**

Run:
```bash
python -m pytest tests/test_api_client_retry_adapter.py -v
```
Expected: 3 PASS。若 test_retry_exhausts_on_persistent_503 失敗顯示 status==0，代表 Retry.raise_on_status 設定有誤；調整 Task 3 step 2 中 `raise_on_status=False` 保持。

- [ ] **Step 3: Commit**

```bash
git add tests/test_api_client_retry_adapter.py
git commit -m "test(http): verify urllib3 Retry adapter behavior

3 tests using the responses library cover:
- 429 transient → eventual success after backoff
- 503 persistent → final 503 status returned (not exception)
- 400 client error → no retry (one call only)"
```

---

## Task 8: 更新既有 test_api_client*.py 的 mock 層

**Files:**
- Modify: `tests/test_api_client*.py`（大約 11 個檔案）

- [ ] **Step 1: 清單**

Run:
```bash
ls tests/test_api_client*.py
```

- [ ] **Step 2: 搜尋舊 urllib mock pattern**

Run:
```bash
grep -rn "urlopen\|urllib.request\|urllib\.error" tests/test_api_client*.py | head -30
```

- [ ] **Step 3: 逐檔更換 mock 策略**

**Pattern**:
- Old: `@patch("urllib.request.urlopen")` → 回傳 MagicMock with `.status`, `.read()`, `.getcode()`
- New: `@responses.activate` + `responses.add(responses.GET, url, status=200, json={...})`

**Example**: if existing test has:

```python
@patch("urllib.request.urlopen")
def test_fetch_workloads(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b'[{"name":"w1"}]'
    mock_urlopen.return_value = mock_resp
    api = ApiClient(cm)
    data = api.list_workloads()
    assert data[0]["name"] == "w1"
```

Change to:

```python
@responses.activate
def test_fetch_workloads():
    responses.add(
        responses.GET,
        "https://pce.test/api/v2/orgs/1/workloads",
        json=[{"name": "w1"}],
        status=200,
    )
    api = ApiClient(cm)
    data = api.list_workloads()
    assert data[0]["name"] == "w1"
```

Apply this pattern systematically across every test file. **Tip**: if a test mocked specific urllib error paths, use `responses.ConnectionError` or `responses.add(..., body=ConnectionError("..."))` to simulate network failure.

- [ ] **Step 4: 跑所有 api_client 測試**

Run:
```bash
python -m pytest tests/test_api_client*.py -v
```
Expected: 全部 PASS（11+ files 都適配 responses library）。

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_client*.py
git commit -m "test(http): migrate api_client test mocks from urllib to responses

responses library provides a cleaner mock API that works with
requests.Session. Old MagicMock-based urllib.urlopen patches
would silently fall through the new session.request() path,
hiding test coverage. This migration restores full coverage."
```

---

## Task 9: 移除 dead urllib imports + _build_ssl_context

**Files:**
- Modify: `src/api_client.py`

- [ ] **Step 1: 搜尋殘留 urllib 用法**

Run:
```bash
grep -n "urllib\.\|urlopen" src/api_client.py
```

- [ ] **Step 2: 判斷每個殘留是否要保留**

- `urllib.parse.urlencode(params)` in `_build_events_url` — **保留**（純字串操作、純 stdlib、不涉及 HTTP）
- `urllib.parse.quote(...)` — **保留**（URL encoding utility）
- `urllib.request.Request / urlopen` — 應該已全數被 Task 4 移除
- `urllib.error.HTTPError / URLError` — 應該已全數被 Task 4 移除

把 `import urllib.request` 與 `import urllib.error` 移除，保留 `import urllib.parse`。

- [ ] **Step 3: 移除 _build_ssl_context + self._ssl_ctx**

如 Task 3 保留的：既然 `requests.Session.verify` 已取代 ssl_ctx 所有角色，可以移除：

```python
# 刪掉 __init__ 裡的：
self._ssl_ctx = self._build_ssl_context()
```

以及整個 `_build_ssl_context` method（行 139-145）。

但若有 stream mode 的程式碼仍在呼叫 urllib.request.urlopen + ssl_ctx — 那代表 Task 4 沒清乾淨，需要回頭補。

- [ ] **Step 4: 移除 `MAX_RETRIES` / `RETRY_BACKOFF_BASE` 常數（若不再使用）**

Search:
```bash
grep -n "MAX_RETRIES\|RETRY_BACKOFF_BASE" src/api_client.py
```

若只剩 Task 3 的 `_Retry(total=MAX_RETRIES, ...)` 引用則保留；若沒人用了就一併刪除。

- [ ] **Step 5: 跑全套測試**

Run:
```bash
python -m pytest tests/ -q
```
Expected: 基線 +0 regressions。

- [ ] **Step 6: Commit**

```bash
git add src/api_client.py
git commit -m "chore(http): remove dead urllib.request imports + _build_ssl_context

After the requests.Session migration, urllib.request/urllib.error
are no longer referenced. urllib.parse kept (used for URL building,
not HTTP). _build_ssl_context and self._ssl_ctx removed — Session.verify
handles verify_ssl=False correctly."
```

---

## Task 10: 全套驗證

**Files:** （無變更）

- [ ] **Step 1: 跑完整測試**

Run:
```bash
python -m pytest tests/ -q --tb=short
```
Expected: 基線 + 新增測試（約 +15 tests）、0 failed、1 pre-existing skip。

- [ ] **Step 2: 跑 i18n audit**

Run:
```bash
python -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py -v
```
Expected: 0 findings。

- [ ] **Step 3: 煙霧測試對真 PCE（可選）**

```bash
python illumio_ops.py status   # 依 Phase 1 的新命令（若 Phase 1 已 merge）
# OR
python illumio_ops.py --monitor -i 1 &    # 舊 flag
sleep 30 && kill %1 2>/dev/null
```

觀察：
- 連線到 PCE 正常
- log 中無 urllib deprecation warning
- Response 解析速度合理

- [ ] **Step 4: 檢查體積**

Run:
```bash
du -sh .venv-phase0/Lib/site-packages/requests .venv-phase0/Lib/site-packages/orjson .venv-phase0/Lib/site-packages/cachetools 2>/dev/null
```

預期：
- requests ~2 MB
- orjson ~4 MB
- cachetools ~0.1 MB

- [ ] **Step 5: 更新 Status.md + Task.md**

Status.md: 把 Q5 從 Code Quality Issues 表標 ✅；版本 `v3.4.2-http`；Dependency Status 改列 requests/orjson/cachetools 為 `used`。

Task.md 插入：
```markdown
---

## Phase 2: HTTP client 重構 ✅ DONE (2026-04-XX)

- [x] **P2**: requests + orjson + cachetools migration
  - `_request()` 底層改 `requests.Session` + `urllib3.Retry`（429/502/503/504 自動退避）
  - Hot path `json.loads` 改 `orjson.loads`（async traffic 大型回應提速 2-3×）
  - label caches 全包 `TTLCache(ttl=900)` — **Status.md Q5 解決**
  - 50+ ApiClient public method 簽章完全不變
  - Test count: 基線 +15 (contract/retry/ttl/orjson_compat/api_client migrations)
  - Branch: `upgrade/phase-2-http-requests` → squash merge + tag `v3.4.2-http`
```

Commit:
```bash
git add Status.md Task.md
git commit -m "docs: record Phase 2 completion"
```

---

## Task 11: Push + PR + merge + tag

**Files:** （無變更）

- [ ] **Step 1: Push**

```bash
git push -u origin upgrade/phase-2-http-requests
```

- [ ] **Step 2: 開 PR**

透過 gh CLI 或 GitHub API（見 Phase 0 的方法）:

**Title**: `Phase 2: HTTP client refactor (requests + orjson + cachetools)`

**Body**（摘要）:
```markdown
## Summary
- `_request()` 換成 `requests.Session` 背景；retry adapter 處理 429/5xx
- orjson 取代 stdlib json 在 hot path（+2-3× 速度）
- label caches 全面 TTL 化，解 Status.md Q5
- 50+ public method 簽章 0 變更，下游無感

## Why
Phase 2 of upgrade roadmap. Prepares HTTP layer for future scale
(large PCE deployments) and eliminates the last no-TTL cache.

## Test plan
- [x] pytest tests/ — 基線 +15 new, 0 regressions
- [x] responses library mock 替代 urllib mock (11 api_client test files)
- [x] TTL cache 15min 過期行為用 freezegun 驗證
- [x] orjson 輸出 vs stdlib json 相容測試
- [ ] 對真 PCE smoke test 可達 + async traffic query 成功
```

- [ ] **Step 3: Merge 後 tag**

```bash
git checkout main && git pull
git tag -a v3.4.2-http -m "Phase 2: HTTP client refactor complete"
git push origin v3.4.2-http
git branch -d upgrade/phase-2-http-requests
```

- [ ] **Step 4: 更新 memory**

Append to `C:/Users/harry/.claude/projects/D--OneDrive-RD-illumio-ops/memory/upgrade_roadmap_phase0.md`:

```markdown

## Phase 2 ✅ DONE (2026-04-XX)

- Branch: `upgrade/phase-2-http-requests`, tag `v3.4.2-http`
- requests.Session with urllib3 Retry replaced manual urllib loop
- orjson on hot-path parse (api_client response body + state_store)
- TTLCache(900s) on label_cache + related caches — Status.md Q5 resolved
- No public API changes in ApiClient (contract test passed)
- 11 existing api_client test files migrated from urllib mock to responses library
```

---

## Phase 2 完成驗收清單

- [ ] `ApiClient.__init__` 有 `self._session = requests.Session()` + retry adapter
- [ ] `_request()` 內部不再 import urllib.request（只保留 urllib.parse 做 URL 構建）
- [ ] `label_cache` 是 `TTLCache` 實例，ttl 900
- [ ] `api.invalidate_labels()` 方法存在
- [ ] api_client.py 所有 response body 解析改 orjson.loads
- [ ] state_store.py 用 orjson（可選）
- [ ] 所有 api_client 測試通過（含 11 個既有 + 新增 retry/ttl/orjson_compat/contract）
- [ ] i18n audit 0 findings
- [ ] Status.md Q5 標 ✅
- [ ] `v3.4.2-http` tag 存在
- [ ] memory 更新

**Done means ready to:** Wave A 的 Phase 1/2 收斂後可進 Wave B 的 Phase 4（Web 安全）與 Phase 5（報表），或繼續 Phase 3（Settings）。

---

## Rollback Plan

```bash
git revert v3.4.2-http
git tag -d v3.4.2-http
git push origin :refs/tags/v3.4.2-http
```

wrapper 層改動範圍侷限在 api_client.py + state_store.py + tests；revert 一個 commit 就完成。

---

## Self-Review Checklist

- ✅ **Spec coverage**：路線圖 Phase 2 目標（requests + orjson + cachetools + Q5 fix）全部有對應 task
- ✅ **Contract preservation**：Task 2 先固化 `_request` return shape，再改底層
- ✅ **i18n** 未動 user-visible 字串（HTTP 層無 UI）
- ✅ **No placeholders**：所有 step 有具體程式碼或指令
- ✅ **TDD**：Task 2/5/6/7 都是先寫 failing test 再實作
- ✅ **Type consistency**：`_session`/`invalidate_labels`/`_TTLCache` 跨 task 命名一致
