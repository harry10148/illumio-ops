import json
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


class ApiClient:
    def __init__(self, config_manager):
        self.cm = config_manager
        self.api_cfg = self.cm.config["api"]
        self.base_url = f"{self.api_cfg['url']}/api/v2/orgs/{self.api_cfg['org_id']}"
        self._auth_header = self._build_auth_header()
        self._ssl_ctx = self._build_ssl_context()

    def _build_auth_header(self):
        credentials = f"{self.api_cfg['key']}:{self.api_cfg['secret']}"
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('ascii')
        return f"Basic {encoded}"

    def _build_ssl_context(self):
        ctx = ssl.create_default_context()
        if not self.api_cfg.get('verify_ssl', True):
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

    def fetch_events(self, start_time_str, max_results=1000):
        try:
            params = urllib.parse.urlencode({
                "timestamp[gte]": start_time_str,
                "max_results": max_results
            })
            url = f"{self.base_url}/events?{params}"
            status, body = self._request(url, timeout=15)
            if status != 200:
                logger.error(f"Get Events Failed: {status}")
                print(f"{Colors.FAIL}Get Events Failed: {status}{Colors.ENDC}")
                return []
            return json.loads(body)
        except Exception as e:
            logger.error(f"Fetch Events Error: {e}")
            print(f"{Colors.FAIL}Fetch Events Error: {e}{Colors.ENDC}")
            return []

    def execute_traffic_query_stream(self, start_time_str, end_time_str, policy_decisions):
        """
        Executes an async traffic query and yields results row by row to save memory.
        """
        import urllib.parse

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

            if status not in (201, 202):
                text = body.decode('utf-8', errors='replace') if isinstance(body, bytes) else str(body)
                logger.error(f"API Error {status}: {text}")
                print(f"API Error {status}: {text}")
                return

            result = json.loads(body)
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
                print(" Timeout.")
                logger.error("Traffic query timed out.")
                return

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
            print(f"Query Exception: {e}")
            return

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
