import json
import re
import time
import gzip
import ssl
import base64
import logging
import urllib.request
import urllib.error
import urllib.parse
from io import BytesIO
from src.utils import Colors
from src.i18n import t

logger = logging.getLogger(__name__)

MAX_TRAFFIC_RESULTS = 200000
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds


def _extract_id(href):
    """Extract the last segment from an Illumio HREF path."""
    return href.split('/')[-1] if href else ""


class ApiClient:
    def __init__(self, config_manager):
        self.cm = config_manager
        self.api_cfg = self.cm.config["api"]
        self.base_url = f"{self.api_cfg['url']}/api/v2/orgs/{self.api_cfg['org_id']}"
        self._auth_header = self._build_auth_header()
        self._ssl_ctx = self._build_ssl_context()
        # Caches for rule scheduler features
        self.label_cache = {}
        self.ruleset_cache = []
        self.service_ports_cache = {}  # {service_href: [{"port":N,"proto":P}, ...]}

    def _build_auth_header(self):
        credentials = f"{self.api_cfg['key']}:{self.api_cfg['secret']}"
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('ascii')
        return f"Basic {encoded}"

    def _build_ssl_context(self):
        ctx = ssl.create_default_context()
        if not self.api_cfg.get('verify_ssl', True):
            logger.debug("SSL verification disabled — API connections are not secure")
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _request(self, url, method="GET", data=None, headers=None, timeout=15, stream=False):
        """
        Core HTTP helper with retry logic.
        Returns (status_code, response_body_bytes | None).
        For stream=True, returns (status_code, raw_response_object) — caller must close it.
        """
        if headers is None:
            headers = {}
        headers.setdefault("Authorization", self._auth_header)
        headers.setdefault("Accept", "application/json")

        body = None
        if data is not None:
            body = json.dumps(data).encode('utf-8')
            headers.setdefault("Content-Type", "application/json")

        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method=method)
                resp = urllib.request.urlopen(req, timeout=timeout, context=self._ssl_ctx)
                if stream:
                    return resp.status, resp
                resp_body = resp.read()
                return resp.status, resp_body
            except urllib.error.HTTPError as e:
                status = e.code
                resp_body = e.read()
                if status == 429 and attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    logger.warning(f"Rate limited (429). Retrying in {wait}s... (attempt {attempt}/{MAX_RETRIES})")
                    time.sleep(wait)
                    last_exc = e
                    continue
                if status in (502, 503, 504) and attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    logger.warning(f"Server error ({status}). Retrying in {wait}s... (attempt {attempt}/{MAX_RETRIES})")
                    time.sleep(wait)
                    last_exc = e
                    continue
                return status, resp_body
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    logger.warning(f"Connection error: {e}. Retrying in {wait}s... (attempt {attempt}/{MAX_RETRIES})")
                    time.sleep(wait)
                    last_exc = e
                    continue
                logger.error(f"Connection failed after {MAX_RETRIES} attempts: {e}")
                return 0, str(e).encode('utf-8')

        # Should not reach here, but safety fallback
        return 0, str(last_exc).encode('utf-8') if last_exc else b""

    def check_health(self):
        url = f"{self.api_cfg['url']}/api/v2/health"
        try:
            status, body = self._request(url, timeout=10)
            text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
            return status, text
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return 0, str(e)

    def fetch_events(self, start_time_str, end_time_str=None, max_results=5000):
        try:
            p = {
                "timestamp[gte]": start_time_str,
                "max_results": max_results
            }
            if end_time_str:
                p["timestamp[lte]"] = end_time_str
            params = urllib.parse.urlencode(p)
            url = f"{self.base_url}/events?{params}"
            status, body = self._request(url, timeout=30)
            if status != 200:
                err_msg = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
                logger.error(f"Get Events Failed: {status} - {err_msg}")
                print(f"{Colors.FAIL}{t('api_get_events_failed', status=status, error=err_msg[:500])}{Colors.ENDC}")
                return []
            return json.loads(body)
        except Exception as e:
            logger.error(f"Fetch Events Error: {e}")
            print(f"{Colors.FAIL}{t('api_fetch_events_error', error=str(e))}{Colors.ENDC}")
            return []

    def execute_traffic_query_stream(self, start_time_str, end_time_str, policy_decisions, filters=None, compute_draft=False):
        """
        Executes an async traffic query and yields results row by row to save memory.
        filters: optional dict — used for Python-side post-filtering, NOT sent to PCE API.
                 PCE sources/destinations/services are always sent empty to avoid API format
                 compatibility issues. Filtering is applied after download in fetch_traffic_for_report().
        """
        import urllib.parse

        # Override policy_decisions if provided in filters (PCE does support this natively)
        f = filters or {}
        if f.get("policy_decisions"):
            policy_decisions = f["policy_decisions"]

        payload = {
            "start_date": start_time_str, "end_date": end_time_str,
            "policy_decisions": policy_decisions,
            "max_results": MAX_TRAFFIC_RESULTS,
            "query_name": "Traffic_Monitor_Query",
            "sources": {"include": [], "exclude": []},
            "destinations": {"include": [], "exclude": []},
            "services": {"include": [], "exclude": []}
        }

        print(t('submitting_query', start=start_time_str, end=end_time_str))
        logger.info(f"Submitting traffic query ({start_time_str} to {end_time_str})")
        try:
            url = f"{self.base_url}/traffic_flows/async_queries"
            status, body = self._request(url, method="POST", data=payload, timeout=10)

            if status not in (200, 201, 202):
                text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
                logger.error(f"API Error {status}: {text}")
                print(t("api_error_status", status=status, text=text))
                return

            result = json.loads(body)
            # Some PCE versions return 200 with status="queued" (not 201/202)
            if result.get("status") in ("queued", "pending") and not result.get("href"):
                logger.error(f"Async query accepted but no href returned: {result}")
                return
            job_url = result.get("href")
            print(t('waiting_traffic', default='Waiting for traffic calculation...'), end="", flush=True)

            # Polling
            poll_url = f"{self.api_cfg['url']}/api/v2{job_url}"
            for _ in range(60):  # Wait up to 2 mins
                time.sleep(2)
                poll_status, poll_body = self._request(poll_url, timeout=15)
                if poll_status != 200:
                    continue

                state = json.loads(poll_body).get("status")
                if state == "completed":
                    print(f" {t('done')}")
                    logger.info("Traffic query completed.")
                    break
                if state == "failed":
                    print(f" {t('query_failed', default='Failed.')}")
                    logger.error("Traffic query failed.")
                    return
                print(".", end="", flush=True)
            else:
                print(f" {t('api_timeout')}")
                logger.error("Traffic query timed out.")
                return

            # Step 3 (optional): update_rules — triggers PCE to compute draft_policy_decision.
            # Only called when compute_draft=True to avoid unnecessary latency on normal queries.
            if compute_draft:
                update_rules_url = f"{self.api_cfg['url']}/api/v2{job_url}/update_rules"
                logger.info(f"Calling update_rules: PUT {update_rules_url}")
                ur_status, ur_body = self._request(update_rules_url, method="PUT", data={}, timeout=30)
                logger.info(f"update_rules response: HTTP {ur_status}")
                if ur_status in (202, 204):
                    ur_text = ur_body.decode('utf-8', errors='replace') if isinstance(ur_body, bytes) else str(ur_body)
                    logger.info(f"update_rules accepted (HTTP {ur_status}), body: {ur_text[:300]}")
                    print(t('waiting_traffic', default='Waiting for traffic calculation...'), end="", flush=True)
                    # Fixed wait: PCE status may stay "completed" during draft computation.
                    # Give PCE time to process before polling to avoid premature exit.
                    time.sleep(10)
                    for attempt in range(30):  # Poll up to 30 more times
                        poll_status, poll_body = self._request(poll_url, timeout=15)
                        if poll_status != 200:
                            time.sleep(2)
                            continue
                        poll_result = json.loads(poll_body)
                        state = poll_result.get("status")
                        logger.info(f"update_rules poll [{attempt}]: status={state}")
                        if state == "completed":
                            print(f" {t('done')}")
                            logger.info("update_rules computation done.")
                            break
                        print(".", end="", flush=True)
                        time.sleep(2)
                    else:
                        logger.warning("update_rules polling timed out, proceeding with available data")
                        print(f" {t('done')}")
                else:
                    ur_text = ur_body.decode('utf-8', errors='replace') if isinstance(ur_body, bytes) else str(ur_body)
                    logger.warning(f"update_rules returned {ur_status}: {ur_text[:200]}, proceeding without draft policy data")

            # Stream Download
            dl_url = f"{self.api_cfg['url']}/api/v2{job_url}/download"
            dl_status, dl_body = self._request(dl_url, timeout=60)
            if dl_status != 200:
                logger.error(f"Download failed: {dl_status}")
                return

            buffer = BytesIO(dl_body)

            # Handle Gzip
            try:
                with gzip.GzipFile(fileobj=buffer, mode='rb') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            if line == b'[' or line == b']':
                                continue
                            if line.endswith(b','):
                                line = line[:-1]
                            data = json.loads(line)
                            if isinstance(data, list):
                                for item in data:
                                    yield item
                            else:
                                yield data
                        except json.JSONDecodeError as je:
                            logger.debug(f"Skipping unparseable line: {je}")
            except (gzip.BadGzipFile, OSError):
                # Fallback if not gzip
                buffer.seek(0)
                text_data = buffer.read().decode('utf-8', errors='replace')
                for line in text_data.splitlines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if isinstance(data, list):
                            for item in data:
                                yield item
                        else:
                            yield data
                    except json.JSONDecodeError as je:
                        logger.debug(f"Skipping unparseable line: {je}")

        except Exception as e:
            logger.error(f"Query Exception: {e}")
            print(t("api_query_exception", error=str(e)))
            return

    @staticmethod
    def _flow_matches_filters(flow: dict, filters: dict) -> bool:
        """
        Python-side filter applied after PCE download.
        Mirrors the label/IP logic from Analyzer.check_flow_match().
        filters keys: src_labels, dst_labels, src_ip, dst_ip, port, proto,
                      ex_src_labels, ex_dst_labels, ex_src_ip, ex_dst_ip, ex_port,
                      any_label, any_ip, ex_any_label, ex_any_ip.
        Label format: "key:value" or "key=value".
        any_label/any_ip: OR logic — matches if EITHER src or dst satisfies the condition.
        """
        src = flow.get('src', {})
        dst = flow.get('dst', {})
        svc = flow.get('service', {})

        def _label_match(side: dict, label_str: str) -> bool:
            """Return True if the flow side has a label matching 'key:value'."""
            for sep in (':', '='):
                if sep in label_str:
                    fk, fv = label_str.split(sep, 1)
                    fk, fv = fk.strip(), fv.strip()
                    for lbl in side.get('workload', {}).get('labels', []):
                        if lbl.get('key') == fk and lbl.get('value') == fv:
                            return True
                    return False
            return False

        def _ip_match(side: dict, ip_str: str) -> bool:
            if side.get('ip') == ip_str:
                return True
            for ipl in side.get('ip_lists', []):
                if ipl.get('name') == ip_str:
                    return True
            return False

        # ── Include filters (must match if specified) ─────────────────────────
        for lbl in (filters.get('src_labels') or []):
            if lbl and not _label_match(src, lbl):
                return False
        for lbl in (filters.get('dst_labels') or []):
            if lbl and not _label_match(dst, lbl):
                return False
        if filters.get('src_ip') and not _ip_match(src, filters['src_ip']):
            return False
        if filters.get('dst_ip') and not _ip_match(dst, filters['dst_ip']):
            return False

        port_filter = filters.get('port', '')
        if port_filter:
            try:
                flow_port = svc.get('port') or flow.get('dst_port')
                if flow_port is None or int(flow_port) != int(port_filter):
                    return False
            except (ValueError, TypeError):
                pass

        proto_filter = filters.get('proto')
        if proto_filter:
            try:
                flow_proto = svc.get('proto') or flow.get('proto')
                if flow_proto is None or int(flow_proto) != int(proto_filter):
                    return False
            except (ValueError, TypeError):
                pass

        # ── Any-side include filters (src OR dst must match) ─────────────────
        any_label = filters.get('any_label')
        if any_label:
            if not (_label_match(src, any_label) or _label_match(dst, any_label)):
                return False
        any_ip = filters.get('any_ip')
        if any_ip:
            if not (_ip_match(src, any_ip) or _ip_match(dst, any_ip)):
                return False

        # ── Exclude filters (must NOT match) ──────────────────────────────────
        for lbl in (filters.get('ex_src_labels') or []):
            if lbl and _label_match(src, lbl):
                return False
        for lbl in (filters.get('ex_dst_labels') or []):
            if lbl and _label_match(dst, lbl):
                return False
        if filters.get('ex_src_ip') and _ip_match(src, filters['ex_src_ip']):
            return False
        if filters.get('ex_dst_ip') and _ip_match(dst, filters['ex_dst_ip']):
            return False

        ex_port = filters.get('ex_port', '')
        if ex_port:
            try:
                flow_port = svc.get('port') or flow.get('dst_port')
                if flow_port is not None and int(flow_port) == int(ex_port):
                    return False
            except (ValueError, TypeError):
                pass

        # ── Any-side exclude filters (exclude if src OR dst matches) ─────────
        ex_any_label = filters.get('ex_any_label')
        if ex_any_label:
            if _label_match(src, ex_any_label) or _label_match(dst, ex_any_label):
                return False
        ex_any_ip = filters.get('ex_any_ip')
        if ex_any_ip:
            if _ip_match(src, ex_any_ip) or _ip_match(dst, ex_any_ip):
                return False

        return True

    def fetch_traffic_for_report(self, start_time_str, end_time_str,
                                 policy_decisions=None, filters=None):
        """
        Convenience wrapper for report generation.
        Fetches all traffic from PCE then applies Python-side filters.
        Returns: list[dict] — filtered flow records, or empty list on failure.
        """
        if policy_decisions is None:
            policy_decisions = ["blocked", "potentially_blocked", "allowed"]

        stream = self.execute_traffic_query_stream(
            start_time_str, end_time_str, policy_decisions, filters=filters
        )
        if stream is None:
            return []

        records = list(stream)

        # Apply Python-side filters if specified (PCE API-level filtering is not used
        # because label key/value format is not reliably accepted by the async query API)
        if filters:
            before = len(records)
            records = [r for r in records if self._flow_matches_filters(r, filters)]
            after = len(records)
            if before != after:
                logger.info(f"[ReportFilter] {before} → {after} flows after applying filters")

        return records

    # ═══════════════════════════════════════════════════════════════════════════════
    # Quarantine Feature: Labels and Workloads
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_labels(self, key: str) -> list:
        try:
            params = urllib.parse.urlencode({"key": key})
            url = f"{self.base_url}/labels?{params}"
            status, body = self._request(url, timeout=10)
            if status != 200:
                logger.error(f"Get Labels Failed: {status}")
                return []
            return json.loads(body)
        except Exception as e:
            logger.error(f"Fetch Labels Error: {e}")
            return []

    def create_label(self, key: str, value: str) -> dict:
        try:
            url = f"{self.base_url}/labels"
            payload = {"key": key, "value": value}
            status, body = self._request(url, method="POST", data=payload, timeout=10)
            if status == 201:
                return json.loads(body)
            logger.error(f"Create Label Failed: {status} - {body.decode(errors='replace')}")
            return {}
        except Exception as e:
            logger.error(f"Create Label Error: {e}")
            return {}

    def check_and_create_quarantine_labels(self):
        """Ensure Quarantine labels (Mild, Moderate, Severe) exist in the PCE. Returns list of their hrefs."""
        existing_labels = self.get_labels("Quarantine")
        existing_values = {lbl.get("value"): lbl.get("href") for lbl in existing_labels if lbl.get("value")}
        
        target_levels = ["Mild", "Moderate", "Severe"]
        label_hrefs = {}
        for level in target_levels:
            if level in existing_values:
                label_hrefs[level] = existing_values[level]
            else:
                logger.info(f"Creating missing Quarantine label: {level}")
                new_lbl = self.create_label("Quarantine", level)
                if new_lbl and "href" in new_lbl:
                    label_hrefs[level] = new_lbl["href"]
        return label_hrefs

    def get_workload(self, href: str) -> dict:
        """Fetch a specific workload by its href"""
        try:
            # href usually looks like /orgs/1/workloads/xx-yy-zz
            url = f"{self.api_cfg['url']}/api/v2{href}"
            status, body = self._request(url, timeout=10)
            if status == 200:
                return json.loads(body)
            logger.error(f"Get Workload Failed: {status} for {href}")
            return {}
        except Exception as e:
            logger.error(f"Get Workload Error: {e}")
            return {}

    def update_workload_labels(self, href: str, labels: list) -> bool:
        """Update a workload's labels. labels list should contain dicts with 'href' keys."""
        try:
            url = f"{self.api_cfg['url']}/api/v2{href}"
            payload = {"labels": labels}
            status, body = self._request(url, method="PUT", data=payload, timeout=10)
            if status == 204:
                return True
            logger.error(f"Update Workload Labels Failed: {status} - {body.decode(errors='replace')}")
            return False
        except Exception as e:
            logger.error(f"Update Workload Labels Error: {e}")
            return False

    def fetch_managed_workloads(self, max_results: int = 10000) -> list:
        """Fetch all VEN-managed workloads (those with an active VEN agent)."""
        try:
            params = urllib.parse.urlencode({'managed': 'true', 'max_results': max_results})
            url = f"{self.base_url}/workloads?{params}"
            status, body = self._request(url, timeout=30)
            if status == 200:
                return json.loads(body)
            err_msg = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
            logger.error(f"Fetch Managed Workloads Failed: {status} - {err_msg}")
            return []
        except Exception as e:
            logger.error(f"Fetch Managed Workloads Error: {e}")
            return []

    def search_workloads(self, params: dict) -> list:
        """Search workloads matching query params (e.g., name, hostname, ip_address, labels)"""
        try:
            query_str = urllib.parse.urlencode(params, doseq=True)
            url = f"{self.base_url}/workloads?{query_str}"
            status, body = self._request(url, timeout=15)
            if status == 200:
                return json.loads(body)
            logger.error(f"Search Workloads Failed: {status}")
            return []
        except Exception as e:
            logger.error(f"Search Workloads Error: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════════════════════
    # Rule Scheduler Features: RuleSet/Rule management, provisioning, notes
    # ═══════════════════════════════════════════════════════════════════════════════

    def _api_get(self, endpoint, timeout=15):
        """GET a PCE API endpoint. Returns (status_code, parsed_json_or_None)."""
        url = f"{self.api_cfg['url']}/api/v2{endpoint}"
        try:
            status, body = self._request(url, timeout=timeout)
            if status == 200:
                return status, json.loads(body)
            if status == 204:
                return status, {}
            return status, None
        except Exception as e:
            logger.error(f"API GET {endpoint}: {e}")
            return 0, None

    def _api_put(self, endpoint, payload, timeout=15):
        """PUT a PCE API endpoint. Returns status_code."""
        url = f"{self.api_cfg['url']}/api/v2{endpoint}"
        try:
            status, body = self._request(url, method="PUT", data=payload, timeout=timeout)
            return status
        except Exception as e:
            logger.error(f"API PUT {endpoint}: {e}")
            return 0

    def _api_post(self, endpoint, payload, timeout=15):
        """POST a PCE API endpoint. Returns (status_code, parsed_json_or_None)."""
        url = f"{self.api_cfg['url']}/api/v2{endpoint}"
        try:
            status, body = self._request(url, method="POST", data=payload, timeout=timeout)
            if status in (200, 201):
                return status, json.loads(body) if body else {}
            return status, None
        except Exception as e:
            logger.error(f"API POST {endpoint}: {e}")
            return 0, None

    def update_label_cache(self, silent=False):
        """Cache labels, IP lists, and services for display resolution."""
        org = self.api_cfg['org_id']
        try:
            status, data = self._api_get(f"/orgs/{org}/labels?max_results=10000")
            if status == 200 and data:
                for i in data:
                    self.label_cache[i['href']] = f"{i.get('key')}:{i.get('value')}"

            status, data = self._api_get(f"/orgs/{org}/sec_policy/draft/ip_lists?max_results=10000")
            if status == 200 and data:
                for i in data:
                    val = f"[IPList] {i.get('name')}"
                    self.label_cache[i['href']] = val
                    self.label_cache[i['href'].replace('/draft/', '/active/')] = val

            status, data = self._api_get(f"/orgs/{org}/sec_policy/draft/services?max_results=10000")
            if status == 200 and data:
                for i in data:
                    name = i.get('name')
                    ports = []
                    port_defs = []  # raw port/proto dicts for query building
                    for svc in i.get('service_ports', []):
                        p = svc.get('port')
                        if p:
                            proto = "UDP" if svc.get('proto') == 17 else "TCP"
                            top = f"-{svc['to_port']}" if svc.get('to_port') else ""
                            ports.append(f"{proto}/{p}{top}")
                            # Build raw port definition for async queries
                            pd = {"port": p}
                            if svc.get('proto') is not None:
                                pd["proto"] = svc['proto']
                            if svc.get('to_port'):
                                pd["to_port"] = svc['to_port']
                            port_defs.append(pd)
                    port_str = f" ({','.join(ports)})" if ports else ""
                    val = f"{name}{port_str}"
                    self.label_cache[i['href']] = val
                    self.label_cache[i['href'].replace('/draft/', '/active/')] = val
                    # Cache resolved port definitions for per-rule queries
                    if port_defs:
                        self.service_ports_cache[i['href']] = port_defs
                        self.service_ports_cache[i['href'].replace('/draft/', '/active/')] = port_defs
        except Exception as e:
            if not silent:
                logger.warning(f"Label cache update error: {e}")

    def resolve_actor_str(self, actors):
        """Resolve actor list to human-readable string using label_cache."""
        if not actors:
            return "Any"
        names = []
        for a in actors:
            if 'label' in a:
                names.append(self.label_cache.get(a['label']['href'], "Label"))
            elif 'ip_list' in a:
                names.append(self.label_cache.get(a['ip_list']['href'], "IPList"))
            elif 'actors' in a:
                names.append(str(a.get('actors')))
        return ", ".join(names)

    def resolve_service_str(self, services):
        """Resolve service references to display strings."""
        if not services:
            return "All Services"
        svcs = []
        for s in services:
            if 'port' in s:
                p, proto = s.get('port'), "UDP" if s.get('proto') == 17 else "TCP"
                top = f"-{s['to_port']}" if s.get('to_port') else ""
                svcs.append(f"{proto}/{p}{top}")
            elif 'href' in s:
                svcs.append(self.label_cache.get(s['href'], f"Service({_extract_id(s['href'])})"))
            else:
                svcs.append("RefObj")
        return ", ".join(svcs)

    def get_all_rulesets(self, force_refresh=False):
        """Get all rulesets from PCE (cached unless force_refresh)."""
        if self.ruleset_cache and not force_refresh:
            return self.ruleset_cache
        org = self.api_cfg['org_id']
        status, data = self._api_get(f"/orgs/{org}/sec_policy/draft/rule_sets?max_results=10000")
        if status == 200 and data:
            self.ruleset_cache = data
            return self.ruleset_cache
        return []

    def get_active_rulesets(self):
        """Get all active (provisioned) rulesets with their rules.

        Uses /sec_policy/active/rule_sets to get the live policy state,
        unlike get_all_rulesets() which uses /draft/.
        Returns a list of ruleset dicts, each containing a 'rules' key.
        """
        org = self.api_cfg['org_id']
        status, data = self._api_get(
            f"/orgs/{org}/sec_policy/active/rule_sets?max_results=10000"
        )
        if status == 200 and data:
            return data
        logger.warning(f"get_active_rulesets: status={status}, returned empty list")
        return []

    # ── Per-rule async traffic query helpers (for Policy Usage Report) ──

    def submit_async_query(self, payload):
        """Submit an async traffic query and return the job href, or None on failure."""
        url = f"{self.base_url}/traffic_flows/async_queries"
        status, body = self._request(url, method="POST", data=payload, timeout=10)
        if status not in (200, 201, 202):
            text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
            logger.debug(f"submit_async_query failed: {status} {text[:200]}")
            return None
        result = json.loads(body)
        return result.get("href")

    def poll_async_query(self, job_href, timeout=120):
        """Poll an async query until completed/failed. Returns True if completed."""
        poll_url = f"{self.api_cfg['url']}/api/v2{job_href}"
        max_polls = timeout // 2
        for _ in range(max_polls):
            time.sleep(2)
            poll_status, poll_body = self._request(poll_url, timeout=15)
            if poll_status != 200:
                continue
            state = json.loads(poll_body).get("status")
            if state == "completed":
                return True
            if state == "failed":
                logger.debug(f"Async query failed: {job_href}")
                return False
        logger.debug(f"Async query timed out: {job_href}")
        return False

    def download_async_query(self, job_href):
        """Download completed async query results. Returns list of flow dicts."""
        dl_url = f"{self.api_cfg['url']}/api/v2{job_href}/download"
        dl_status, dl_body = self._request(dl_url, timeout=60)
        if dl_status != 200:
            logger.debug(f"download_async_query failed: {dl_status}")
            return []

        buffer = BytesIO(dl_body)
        flows = []

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
                    data = json.loads(line)
                    if isinstance(data, list):
                        flows.extend(data)
                    else:
                        flows.append(data)
                except json.JSONDecodeError:
                    pass

        try:
            with gzip.GzipFile(fileobj=buffer, mode='rb') as f:
                _parse_lines(f)
        except (gzip.BadGzipFile, OSError):
            buffer.seek(0)
            text_data = buffer.read().decode('utf-8', errors='replace')
            _parse_lines(text_data.splitlines())

        return flows

    def _build_query_actors(self, actor_list, scope_labels=None):
        """Convert rule consumers/providers to async query sources/destinations include list.

        Workloader format: sources/destinations.include is a **nested array** —
        each inner array is an AND-group of labels. Multiple inner arrays = OR.

        Labels of the SAME dimension (e.g. multiple role labels) become separate inner
        arrays (OR semantics within dimension). Labels of DIFFERENT dimensions are
        AND-grouped within each inner array. Scope labels are only added for dimensions
        not already covered by the actor labels themselves.

        Args:
            actor_list:   rule's consumers or providers list from PCE API
            scope_labels: list of scope label dicts from the parent ruleset's first scope
                          (e.g. [{"label":{"href":"..."}}, ...])
        """
        import itertools
        from collections import defaultdict

        if not actor_list:
            return []

        def _label_dim(href):
            """Return dimension key (e.g. 'role','env') from label_cache, or unique fallback."""
            raw = self.label_cache.get(href, "")
            if raw and ":" in raw:
                return raw.split(":", 1)[0]
            return f"_unknown_{href}"   # treat unknown labels as independent dimensions

        # Build scope item list with dimensions
        scope_items_with_dim = []   # [(dim, item_dict), ...]
        if scope_labels:
            for sl in scope_labels:
                if "label" in sl:
                    dim = _label_dim(sl["label"].get("href", ""))
                    scope_items_with_dim.append((dim, {"label": sl["label"]}))
                elif "label_group" in sl:
                    scope_items_with_dim.append(("_lgroup", {"label_group": sl["label_group"]}))

        # Classify actor list into dimension-keyed label groups or non-label groups
        label_actors_by_dim = defaultdict(list)   # {dim: [item, ...]}
        non_label_groups = []

        for actor in actor_list:
            if actor.get("actors") == "ams":
                non_label_groups.append([{"actors": "ams"}])
            elif "label" in actor:
                dim = _label_dim(actor["label"].get("href", ""))
                label_actors_by_dim[dim].append({"label": actor["label"]})
            elif "label_group" in actor:
                label_actors_by_dim["_lgroup"].append({"label_group": actor["label_group"]})
            elif "ip_list" in actor:
                non_label_groups.append([{"ip_list": actor["ip_list"]}])
            elif "workload" in actor:
                non_label_groups.append([{"workload": actor["workload"]}])
            else:
                non_label_groups.append([actor])

        result = []

        if label_actors_by_dim:
            consumer_dims = set(label_actors_by_dim.keys())
            # Only include scope labels whose dimension is NOT covered by the actor labels
            scope_to_add = [item for dim, item in scope_items_with_dim
                            if dim not in consumer_dims]

            # Cartesian product across dimensions → each combo is one AND-group (inner array)
            # e.g. role:[A,B], env:[X] → [[env:X,role:A], [env:X,role:B]]
            dim_groups = list(label_actors_by_dim.values())
            for combo in itertools.product(*dim_groups):
                inner = list(scope_to_add) + list(combo)
                result.append(inner)

        elif scope_items_with_dim:
            # Actor list had only non-label entries; still add scope as one group
            result.append([item for _, item in scope_items_with_dim])

        result.extend(non_label_groups)
        return result

    def _build_query_services(self, rule):
        """Convert rule ingress_services to async query services include list.

        Named services (href-based) are resolved to their port/proto definitions
        via service_ports_cache, matching workloader behaviour. The async query
        API requires inline port definitions, not service hrefs.
        """
        services = []
        for svc in rule.get("ingress_services", []):
            if "href" in svc:
                # Resolve named service to port definitions
                resolved = self.service_ports_cache.get(svc["href"], [])
                if resolved:
                    services.extend(resolved)
                else:
                    logger.debug(f"Service href not in cache: {svc['href']}")
            elif "port" in svc:
                entry = {"port": svc["port"]}
                if "proto" in svc:
                    entry["proto"] = svc["proto"]
                if svc.get("to_port"):
                    entry["to_port"] = svc["to_port"]
                services.append(entry)
        return services

    def _build_rule_query_payload(self, rule, start_date, end_date):
        """Build the async query payload dict for a single rule.

        Returns a payload dict ready for submit_async_query(), or None on error.
        """
        try:
            scope_labels = rule.get("_ruleset_scopes", [])
            unscoped_consumers = rule.get("unscoped_consumers", False)
            consumer_scope = [] if unscoped_consumers else scope_labels

            sources_include      = self._build_query_actors(rule.get("consumers", []),
                                                            scope_labels=consumer_scope)
            destinations_include = self._build_query_actors(rule.get("providers", []),
                                                            scope_labels=scope_labels)
            services_include     = self._build_query_services(rule)

            rule_href = rule.get('href', '')
            logger.debug(f"Rule payload {rule_href}: "
                         f"src={json.dumps(sources_include)}, "
                         f"dst={json.dumps(destinations_include)}, "
                         f"svc={json.dumps(services_include)}")
            return {
                "query_name":  f"policy-usage-{rule_href}",
                "start_date":  start_date,
                "end_date":    end_date,
                "policy_decisions": [],
                "max_results": 10000,
                "sources":      {"include": sources_include,      "exclude": []},
                "destinations": {"include": destinations_include, "exclude": []},
                "services":     {"include": services_include,     "exclude": []},
                "exclude_workloads_from_ip_list_query": False,
            }
        except Exception as e:
            logger.warning(f"_build_rule_query_payload error for {rule.get('href')}: {e}")
            return None

    def get_rule_traffic_count(self, rule, start_date, end_date):
        """Query traffic count for a single rule (sequential, for compatibility).

        Returns the number of matching flows, or 0 on any failure.
        """
        try:
            payload = self._build_rule_query_payload(rule, start_date, end_date)
            if payload is None:
                return 0
            job_href = self.submit_async_query(payload)
            if not job_href:
                return 0
            if not self.poll_async_query(job_href, timeout=120):
                return 0
            flows = self.download_async_query(job_href)
            return len(flows)
        except Exception as e:
            logger.warning(f"get_rule_traffic_count error for {rule.get('href')}: {e}")
            return 0

    def batch_get_rule_traffic_counts(
        self,
        rules: list,
        start_date: str,
        end_date: str,
        max_concurrent: int = 10,
        on_progress=None,
    ) -> tuple:
        """Submit all rule queries in parallel, poll concurrently, download in parallel.

        Three-phase approach (matches workloader behaviour):
          Phase 1 — Submit all async queries simultaneously.
          Phase 2 — Poll all pending jobs concurrently until every job resolves.
          Phase 3 — Download all completed results simultaneously.

        Args:
            rules:          Flat list of rule dicts (from _build_baseline).
            start_date:     ISO-8601 start date string.
            end_date:       ISO-8601 end date string.
            max_concurrent: Thread pool size (default 10).
            on_progress:    Optional callable(msg: str) for progress updates.

        Returns:
            (hit_hrefs: set, hit_counts: dict[rule_href -> int])
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        total = len(rules)
        if not total:
            return set(), {}

        def _progress(msg):
            if on_progress:
                on_progress(msg)

        # ── Phase 1: Submit ────────────────────────────────────────────────
        job_map = {}   # {async_job_href: rule}
        submitted_count = 0

        def _submit(rule):
            payload = self._build_rule_query_payload(rule, start_date, end_date)
            if payload is None:
                return None, rule
            return self.submit_async_query(payload), rule

        with ThreadPoolExecutor(max_workers=max_concurrent) as ex:
            futs = {ex.submit(_submit, r): r for r in rules}
            for fut in as_completed(futs):
                job_href, rule = fut.result()
                submitted_count += 1
                if job_href:
                    job_map[job_href] = rule
                _progress(f"Submitting {submitted_count}/{total}...")

        _progress(f"Polling {len(job_map)} jobs (0/{len(job_map)} done)...")

        # ── Phase 2: Poll ──────────────────────────────────────────────────
        pending   = set(job_map.keys())
        completed = set()
        deadline  = time.time() + 300   # 5-minute hard timeout

        def _poll_one(job_href):
            url = f"{self.api_cfg['url']}/api/v2{job_href}"
            status, body = self._request(url, timeout=15)
            if status != 200:
                return job_href, "pending"
            try:
                state = json.loads(body).get("status", "pending")
            except Exception:
                state = "pending"
            return job_href, state

        while pending and time.time() < deadline:
            time.sleep(2)
            pending_list = list(pending)
            with ThreadPoolExecutor(max_workers=min(max_concurrent, len(pending_list))) as ex:
                poll_results = list(ex.map(_poll_one, pending_list))

            still_pending = set()
            for job_href, state in poll_results:
                if state == "completed":
                    completed.add(job_href)
                elif state == "failed":
                    logger.debug(f"Async query failed: {job_href}")
                else:
                    still_pending.add(job_href)
            pending = still_pending
            _progress(f"Polling... {len(completed)}/{len(job_map)} done, "
                      f"{len(pending)} pending")

        # ── Phase 3: Download ──────────────────────────────────────────────
        hit_hrefs:  set  = set()
        hit_counts: dict = {}
        downloaded = 0

        def _download(job_href):
            return job_href, len(self.download_async_query(job_href))

        with ThreadPoolExecutor(max_workers=max_concurrent) as ex:
            futs = {ex.submit(_download, jh): jh for jh in completed}
            for fut in as_completed(futs):
                job_href, count = fut.result()
                rule = job_map[job_href]
                downloaded += 1
                if count > 0:
                    href = rule.get("href", "")
                    hit_hrefs.add(href)
                    hit_counts[href] = count
                _progress(f"Downloading {downloaded}/{len(completed)}...")

        logger.info(f"batch_get_rule_traffic_counts: {total} rules → "
                    f"{len(hit_hrefs)} hit, {total - len(hit_hrefs)} unused")
        return hit_hrefs, hit_counts

    def search_rulesets(self, keyword):
        """Search cached rulesets by keyword."""
        all_rs = self.get_all_rulesets()
        return [rs for rs in all_rs if keyword.lower() in rs.get('name', '').lower()]

    def get_ruleset_by_id(self, rs_id):
        """Get a single ruleset by ID."""
        org = self.api_cfg['org_id']
        status, data = self._api_get(f"/orgs/{org}/sec_policy/draft/rule_sets/{rs_id}")
        return data if status == 200 else None

    def provision_changes(self, rs_href):
        """Dependency-aware provisioning: discovers required dependencies first."""
        org = self.api_cfg['org_id']

        # Step 1: Check dependencies
        dep_payload = {"change_subset": {"rule_sets": [{"href": rs_href}]}}
        dep_status, deps = self._api_post(f"/orgs/{org}/sec_policy/draft/dependencies", dep_payload)

        # Step 2: Build complete change_subset including all dependencies
        final_subset = {"rule_sets": [{"href": rs_href}]}

        if dep_status == 200 and deps:
            for obj_type in ['rule_sets', 'ip_lists', 'services', 'label_groups',
                             'virtual_services', 'firewall_settings', 'enforcement_boundaries',
                             'virtual_servers', 'secure_connect_gateways']:
                dep_items = deps.get(obj_type, [])
                if dep_items:
                    existing = final_subset.get(obj_type, [])
                    existing_hrefs = {item['href'] for item in existing}
                    for item in dep_items:
                        if item.get('href') and item['href'] not in existing_hrefs:
                            existing.append({"href": item['href']})
                    final_subset[obj_type] = existing

        # Step 3: Provision with full dependency set
        payload = {
            "update_description": "Auto-Scheduler: Status/Note Update",
            "change_subset": final_subset
        }
        prov_status, _ = self._api_post(f"/orgs/{org}/sec_policy", payload)
        if prov_status == 201:
            return True
        logger.error(f"Provision failed for RuleSet {_extract_id(rs_href)}: status {prov_status}")
        return False

    def has_draft_changes(self, href):
        """Check if an item OR its parent RuleSet has pending draft changes."""
        draft_href = href.replace("/active/", "/draft/")
        status, data = self._api_get(draft_href)
        if status == 200 and data and bool(data.get('update_type')):
            return True
        if "/sec_rules/" in draft_href:
            parent_href = draft_href.split("/sec_rules/")[0]
            status_p, data_p = self._api_get(parent_href)
            if status_p == 200 and data_p and bool(data_p.get('update_type')):
                return True
        return False

    def toggle_and_provision(self, href, target_enabled, is_ruleset=False):
        """Enable/disable a rule or ruleset and provision the change."""
        draft_href = href.replace("/active/", "/draft/")
        
        # Check if it (or parent) has pending changes
        if self.has_draft_changes(draft_href):
            logger.warning(f"toggle_and_provision aborted: {_extract_id(href)} has pending draft changes.")
            return False

        put_status = self._api_put(draft_href, {"enabled": target_enabled})
        if put_status != 204:
            logger.error(f"Toggle failed for {_extract_id(href)}: status {put_status}")
            return False
        rs_href = draft_href if is_ruleset else "/".join(draft_href.split("/")[:7])
        return self.provision_changes(rs_href)

    def update_rule_note(self, href, schedule_info, remove=False):
        """Add/update/remove schedule tags in a rule's description field on the PCE."""
        draft_href = href.replace("/active/", "/draft/")
        status, data = self._api_get(draft_href)
        if status != 200 or not data:
            return False

        has_pending_draft = self.has_draft_changes(draft_href)

        current_desc = data.get('description', '') or ''

        # Strip existing schedule tags
        clean_desc = re.sub(r'\s*\[📅[^\]]*\]', '', current_desc)
        clean_desc = re.sub(r'\s*\[⏳[^\]]*\]', '', clean_desc)
        clean_desc = clean_desc.strip()

        new_desc = clean_desc
        if not remove:
            new_desc = f"{clean_desc}\n{schedule_info}".strip() if clean_desc else schedule_info

        if new_desc == current_desc:
            return True

        put_status = self._api_put(draft_href, {"description": new_desc})
        if put_status == 204:
            if not has_pending_draft:
                rs_href = "/".join(draft_href.split("/")[:7])
                return self.provision_changes(rs_href)
            # Successfully updated rule note but skipped provision due to pending changes
            return True
        return False

    def get_live_item(self, href):
        """Try both active and draft paths to find the item. Returns (status, data) or (0, None)."""
        # Try active first
        active_href = href.replace("/draft/", "/active/")
        status, data = self._api_get(active_href)
        if status == 200:
            return status, data
        # Fallback to draft
        draft_href = href.replace("/active/", "/draft/")
        if draft_href != active_href:
            status, data = self._api_get(draft_href)
            if status == 200:
                return status, data
        return status, data

    def get_provision_state(self, href):
        """Check provision state: 'active' if provisioned, 'draft' if draft-only, 'unknown' on error."""
        active_href = href.replace("/draft/", "/active/")
        url = f"{self.api_cfg['url']}/api/v2{active_href}"
        try:
            status, body = self._request(url, timeout=10)
            if status == 200:
                return 'active'
            return 'draft'
        except Exception:
            return 'unknown'

    def is_provisioned(self, href):
        """Check if a rule/ruleset has been provisioned."""
        return self.get_provision_state(href) == 'active'
