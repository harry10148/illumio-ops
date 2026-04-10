import gzip
import json
import os
import tempfile
import time
import unittest
import datetime
from unittest.mock import MagicMock

from src.api_client import ApiClient, TrafficQuerySpec


class TestApiClientNativeTrafficBuilder(unittest.TestCase):
    def setUp(self):
        self.mock_cm = MagicMock()
        self.mock_cm.config = {
            "api": {
                "url": "https://pce.example.com:8443",
                "org_id": "1",
                "key": "key",
                "secret": "secret",
                "verify_ssl": True,
            }
        }
        self.client = ApiClient(self.mock_cm)
        self.client._label_href_cache = {"role:web": "/orgs/1/labels/1"}
        self.client._label_group_href_cache = {"lg:web": "/orgs/1/sec_policy/draft/label_groups/3"}
        self.client._iplist_href_cache = {"corp-net": "/orgs/1/sec_policy/draft/ip_lists/2"}
        self._temp_dir = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._temp_dir.name, "state.json")

    def tearDown(self):
        self._temp_dir.cleanup()

    def test_build_native_payload_pushes_supported_filters(self):
        payload, effective_spec = self.client._build_native_traffic_payload(
            "2026-04-01T00:00:00Z",
            "2026-04-01T01:00:00Z",
            ["allowed"],
            filters={
                "src_label": "role:web",
                "dst_ip_in": "10.0.0.5",
                "port": "443",
                "proto": "6",
                "ex_src_ip": "corp-net",
                "query_operator": "or",
                "any_label": "env:prod",
                "src_ams": True,
                "transmission_excludes": ["broadcast", "multicast"],
                "port_range": "1000-2000/6",
            },
        )

        self.assertEqual(
            payload["sources"]["include"],
            [[{"label": {"href": "/orgs/1/labels/1"}}, {"actors": "ams"}]],
        )
        self.assertEqual(
            payload["destinations"]["include"],
            [[{"ip_address": {"value": "10.0.0.5"}}]],
        )
        self.assertEqual(
            payload["sources"]["exclude"],
            [{"ip_list": {"href": "/orgs/1/sec_policy/draft/ip_lists/2"}}],
        )
        self.assertEqual(
            payload["services"]["include"],
            [{"port": 443, "proto": 6}, {"port": 1000, "to_port": 2000, "proto": 6}],
        )
        self.assertEqual(
            payload["destinations"]["exclude"][-2:],
            [{"transmission": "broadcast"}, {"transmission": "multicast"}],
        )
        self.assertEqual(payload["sources_destinations_query_op"], "or")
        self.assertEqual(effective_spec.fallback_filters, {"any_label": "env:prod"})
        self.assertEqual(effective_spec.native_filters["src_ams"], True)

    def test_build_native_payload_leaves_unresolved_filters_for_fallback(self):
        payload, effective_spec = self.client._build_native_traffic_payload(
            "2026-04-01T00:00:00Z",
            "2026-04-01T01:00:00Z",
            ["allowed"],
            filters={"src_label": "env:prod", "dst_ip_in": "named-iplist"},
        )

        self.assertEqual(payload["sources"]["include"], [])
        self.assertEqual(payload["destinations"]["include"], [])
        self.assertEqual(
            effective_spec.fallback_filters,
            {"src_label": "env:prod", "dst_ip_in": "named-iplist"},
        )

    def test_build_traffic_query_spec_separates_filter_classes(self):
        spec = self.client.build_traffic_query_spec({
            "src_label": "role:web",
            "any_ip": "10.0.0.5",
            "sort_by": "bandwidth",
            "search": "dns",
        })

        self.assertIsInstance(spec, TrafficQuerySpec)
        self.assertEqual(spec.native_filters, {"src_label": "role:web"})
        self.assertEqual(spec.fallback_filters, {"any_ip": "10.0.0.5"})
        self.assertEqual(spec.report_only_filters, {"sort_by": "bandwidth", "search": "dns"})

    def test_capability_matrix_classifies_filters(self):
        matrix = self.client.get_traffic_query_capability_matrix()

        self.assertEqual(matrix["src_label"]["execution"], "native")
        self.assertEqual(matrix["any_ip"]["execution"], "fallback")
        self.assertEqual(matrix["search"]["execution"], "report_only")
        self.assertEqual(matrix["src_label_group"]["execution"], "native")

        spec = self.client.build_traffic_query_spec({
            "src_label_group": "lg:web",
            "search": "dns",
        })
        self.assertIn("src_label_group", spec.native_filters)
        self.assertEqual(spec.diagnostics["capabilities"]["src_label_group"]["execution"], "native")

    def test_build_native_payload_supports_label_groups(self):
        payload, effective_spec = self.client._build_native_traffic_payload(
            "2026-04-01T00:00:00Z",
            "2026-04-01T01:00:00Z",
            ["allowed"],
            filters={
                "src_label_group": "lg:web",
                "ex_dst_label_group": "lg:web",
            },
        )

        self.assertEqual(
            payload["sources"]["include"],
            [[{"label_group": {"href": "/orgs/1/sec_policy/draft/label_groups/3"}}]],
        )
        self.assertEqual(
            payload["destinations"]["exclude"],
            [{"label_group": {"href": "/orgs/1/sec_policy/draft/label_groups/3"}}],
        )
        self.assertEqual(effective_spec.fallback_filters, {})

    def test_build_native_payload_supports_or_groups(self):
        payload, effective_spec = self.client._build_native_traffic_payload(
            "2026-04-01T00:00:00Z",
            "2026-04-01T01:00:00Z",
            ["allowed"],
            filters={
                "src_include_groups": [
                    ["role:web", "10.0.0.5"],
                    ["ams"],
                ],
            },
        )

        self.assertEqual(
            payload["sources"]["include"],
            [
                [{"label": {"href": "/orgs/1/labels/1"}}, {"ip_address": {"value": "10.0.0.5"}}],
                [{"actors": "ams"}],
            ],
        )
        self.assertEqual(effective_spec.fallback_filters, {})

    def test_resolve_label_filter_refreshes_stale_lookup_cache(self):
        self.client._label_href_cache = {}
        self.client._label_group_href_cache = {}
        self.client._iplist_href_cache = {}
        self.client.service_ports_cache = {}
        self.client._query_lookup_cache_refreshed_at = 0

        refresh_calls = []

        def fake_refresh(silent=False, force_refresh=True):
            refresh_calls.append((silent, force_refresh))
            self.client._label_href_cache["role:web"] = "/orgs/1/labels/1"
            self.client._label_group_href_cache["lg:web"] = "/orgs/1/sec_policy/draft/label_groups/3"
            self.client._iplist_href_cache["corp-net"] = "/orgs/1/sec_policy/draft/ip_lists/2"
            self.client.service_ports_cache["/orgs/1/sec_policy/draft/services/1"] = [{"port": 443, "proto": 6}]
            self.client._query_lookup_cache_refreshed_at = time.time()

        self.client.update_label_cache = fake_refresh

        actor = self.client._resolve_label_filter_to_actor("role:web")

        self.assertEqual(actor, {"label": {"href": "/orgs/1/labels/1"}})
        self.assertGreaterEqual(len(refresh_calls), 1)

    def test_summarize_async_query_streams_and_persists_state(self):
        payload_lines = b'\n'.join([
            json.dumps({"service": {"port": 443, "proto": 6}}).encode("utf-8"),
            json.dumps({"service": {"port": 443, "proto": 6}}).encode("utf-8"),
            json.dumps({"dst_port": 53, "proto": 17}).encode("utf-8"),
        ])
        compressed = gzip.compress(payload_lines)

        def fake_request(url, **kwargs):
            self.assertTrue(url.endswith("/download"))
            return 200, compressed

        self.client._request = fake_request

        summary = self.client.summarize_async_query("/orgs/1/traffic_flows/async_queries/99")

        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["flows_by_port"]["443/tcp"], 2)
        self.assertEqual(summary["flows_by_port"]["53/udp"], 1)

        with open(self.client._state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        job_state = state["async_query_jobs"]["/orgs/1/traffic_flows/async_queries/99"]
        self.assertEqual(job_state["flow_count"], 3)
        self.assertEqual(job_state["download_status"], "completed")

    def test_submit_async_query_persists_query_metadata(self):
        self.client._request = lambda url, **kwargs: (
            202,
            json.dumps({
                "href": "/orgs/1/traffic_flows/async_queries/123",
                "status": "queued",
                "result": "/orgs/1/traffic_flows/async_queries/123/download",
            }).encode("utf-8"),
        )

        payload = {"query_name": "policy-usage-test", "sources": {"include": [], "exclude": []}}
        job_href = self.client.submit_async_query(payload)

        self.assertEqual(job_href, "/orgs/1/traffic_flows/async_queries/123")
        with open(self.client._state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        job_state = state["async_query_jobs"][job_href]
        self.assertEqual(job_state["query_type"], "rule_usage")
        self.assertEqual(job_state["query_name"], "policy-usage-test")
        self.assertEqual(job_state["status"], "queued")

    def test_batch_get_rule_traffic_counts_reuses_cached_summary(self):
        rule = {
            "href": "/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/9",
            "_ruleset_scopes": [],
            "consumers": [],
            "providers": [],
            "ingress_services": [],
        }
        payload = self.client._build_rule_query_payload(
            rule,
            "2026-04-01T00:00:00Z",
            "2026-04-02T00:00:00Z",
        )
        job_href = "/orgs/1/traffic_flows/async_queries/555"
        self.client._save_async_job_state(
            job_href,
            query_type="rule_usage",
            query_name=payload["query_name"],
            query_body=payload,
            query_signature=self.client._make_query_signature(payload),
            status="completed",
            download_status="completed",
            flow_count=7,
            flows_by_port={"443/tcp": 7},
        )
        self.client._request = lambda *args, **kwargs: self.fail("API should not be called for cached summary reuse")

        hit_hrefs, hit_counts = self.client.batch_get_rule_traffic_counts(
            [rule],
            "2026-04-01T00:00:00Z",
            "2026-04-02T00:00:00Z",
        )

        self.assertEqual(hit_hrefs, {rule["href"]})
        self.assertEqual(hit_counts, {rule["href"]: 7})
        stats = self.client.get_last_rule_usage_batch_stats()
        self.assertEqual(stats["cached_rules"], 1)
        self.assertEqual(stats["submitted_rules"], 0)
        self.assertEqual(stats["hit_rules"], 1)
        self.assertEqual(stats["top_hit_ports"][0]["port_proto"], "443/tcp")
        self.assertEqual(stats["flows_by_port_totals"]["443/tcp"], 7)
        self.assertEqual(stats["hit_rule_port_details"][0]["top_hit_ports"], "443/tcp (7)")
        self.assertEqual(len(stats["reused_rule_details"]), 1)
        self.assertEqual(stats["reused_rule_details"][0]["status"], "reused")
        self.assertEqual(stats["pending_rule_details"], [])
        self.assertEqual(stats["failed_rule_details"], [])
        with open(self.client._state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertIn("reused_at", state["async_query_jobs"][job_href])

    def test_retry_async_query_job_resubmits_saved_payload(self):
        old_job_href = "/orgs/1/traffic_flows/async_queries/200"
        payload = {"query_name": "retry-me", "sources": {"include": [], "exclude": []}}
        self.client._save_async_job_state(
            old_job_href,
            query_type="rule_usage",
            query_body=payload,
            status="failed",
        )
        self.client._request = lambda url, **kwargs: (
            202,
            json.dumps({
                "href": "/orgs/1/traffic_flows/async_queries/201",
                "status": "queued",
                "result": "/orgs/1/traffic_flows/async_queries/201/download",
            }).encode("utf-8"),
        )

        new_job_href = self.client.retry_async_query_job(old_job_href)

        self.assertEqual(new_job_href, "/orgs/1/traffic_flows/async_queries/201")
        jobs = self.client._load_async_job_states()
        self.assertEqual(jobs[old_job_href]["retried_by"], new_job_href)
        self.assertEqual(jobs[new_job_href]["retried_from"], old_job_href)

    def test_batch_get_rule_traffic_counts_resumes_pending_job(self):
        rule = {
            "href": "/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/12",
            "_ruleset_scopes": [],
            "consumers": [],
            "providers": [],
            "ingress_services": [],
        }
        payload = self.client._build_rule_query_payload(
            rule,
            "2026-04-01T00:00:00Z",
            "2026-04-02T00:00:00Z",
        )
        job_href = "/orgs/1/traffic_flows/async_queries/700"
        self.client._save_async_job_state(
            job_href,
            query_type="rule_usage",
            query_name=payload["query_name"],
            query_body=payload,
            query_signature=self.client._make_query_signature(payload),
            status="pending",
        )

        download_payload = gzip.compress(
            b'{"service":{"port":443,"proto":6}}\n{"service":{"port":443,"proto":6}}\n'
        )

        def fake_request(url, **kwargs):
            if url.endswith(job_href):
                return 200, json.dumps({
                    "status": "completed",
                    "rules": "completed",
                    "result": f"{job_href}/download",
                }).encode("utf-8")
            if url.endswith(job_href + "/download"):
                return 200, download_payload
            self.fail(f"Unexpected request: {url}")

        self.client._request = fake_request

        hit_hrefs, hit_counts = self.client.batch_get_rule_traffic_counts(
            [rule],
            "2026-04-01T00:00:00Z",
            "2026-04-02T00:00:00Z",
        )

        self.assertEqual(hit_hrefs, {rule["href"]})
        self.assertEqual(hit_counts[rule["href"]], 2)
        stats = self.client.get_last_rule_usage_batch_stats()
        self.assertEqual(stats["resumed_jobs"], 1)
        self.assertEqual(stats["retried_jobs"], 0)

    def test_prune_async_job_states_removes_old_entries(self):
        recent_ts = self.client._utc_now_iso()
        old_ts = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.client._save_async_job_state("/jobs/recent", status="completed", updated_at=recent_ts)
        self.client._save_async_job_state("/jobs/old", status="failed", updated_at=old_ts)

        result = self.client.prune_async_job_states(max_age_days=7, keep_recent_completed=10)

        self.assertEqual(result["removed"], 1)
        jobs = self.client._load_async_job_states()
        self.assertIn("/jobs/recent", jobs)
        self.assertNotIn("/jobs/old", jobs)


if __name__ == "__main__":
    unittest.main()
