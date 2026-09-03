"""SIEM per-destination traffic policy-decision filter (`traffic_pd`).

A destination may ask for only some policy decisions of the traffic log
(e.g. blocked only). The gate sits where a row *enters the queue* — the
ingestor's inline enqueue and the safety-net backfill — mirroring how
`source_types` is enforced, so a blocked-only destination never has an
allowed row queued for it, and backfill agrees with ingest.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw, SiemDispatch


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _mk_flow(i, action):
    ts = datetime.now(timezone.utc)
    return {
        "src_ip": f"10.0.{i}.1", "dst_ip": f"10.1.{i}.1", "port": 443,
        "protocol": "tcp", "action": action, "flow_count": 1,
        "bytes_in": 100, "bytes_out": 200,
        "first_detected": ts.isoformat(),
        "last_detected": (ts + timedelta(seconds=1)).isoformat(),
        "src_workload": "web", "dst_workload": "db",
    }


class FakeApiClient:
    def __init__(self, flows):
        self._flows = flows

    def get_traffic_flows_async(self, max_results=200000, rate_limit=False, **kw):
        return self._flows[:max_results]


# ── normalisation ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("allowed", "allowed"), (0, "allowed"), ("0", "allowed"),
    ("potentially_blocked", "potentially_blocked"), (1, "potentially_blocked"), ("1", "potentially_blocked"),
    ("blocked", "blocked"), (2, "blocked"), ("2", "blocked"),
    ("unknown", "unknown"), (None, "unknown"), ("", "unknown"), ("garbage", "unknown"), (7, "unknown"),
])
def test_normalise_pd_maps_every_stored_form(raw, expected):
    from src.siem.pd import normalise_pd
    assert normalise_pd(raw) == expected


# ── config model ─────────────────────────────────────────────────────────────

def test_destination_traffic_pd_defaults_to_empty_meaning_all():
    from src.config_models import SiemDestinationSettings
    d = SiemDestinationSettings(name="x")
    assert d.traffic_pd == []


def test_destination_traffic_pd_rejects_unknown_value():
    from pydantic import ValidationError
    from src.config_models import SiemDestinationSettings
    with pytest.raises(ValidationError):
        SiemDestinationSettings(name="x", traffic_pd=["denied"])


def test_destination_traffic_pd_dedupes_preserving_order():
    from src.config_models import SiemDestinationSettings
    d = SiemDestinationSettings(name="x", traffic_pd=["blocked", "allowed", "blocked"])
    assert d.traffic_pd == ["blocked", "allowed"]


# ── ingest-side gate ─────────────────────────────────────────────────────────

def _dispatched(session_factory):
    with session_factory() as s:
        rows = s.execute(
            select(SiemDispatch.destination, PceTrafficFlowRaw.action)
            .join(PceTrafficFlowRaw, PceTrafficFlowRaw.id == SiemDispatch.source_id)
            .where(SiemDispatch.source_table == "pce_traffic_flows_raw")
        ).all()
    return sorted((d, a) for d, a in rows)


def test_ingestor_enqueues_only_matching_pd_to_filtered_destination(session_factory):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    flows = [_mk_flow(1, "blocked"), _mk_flow(2, "allowed"), _mk_flow(3, "potentially_blocked")]
    ing = TrafficIngestor(
        api=FakeApiClient(flows), session_factory=session_factory,
        watermark=WatermarkStore(session_factory),
        siem_destinations=["soc", "lake"],
        siem_pd_filters={"soc": {"blocked"}},   # lake: no entry = everything
    )
    ing.run_once()
    assert _dispatched(session_factory) == [
        ("lake", "allowed"), ("lake", "blocked"), ("lake", "potentially_blocked"),
        ("soc", "blocked"),
    ]


def test_ingestor_empty_filter_set_means_everything(session_factory):
    """An explicit empty set must behave like 'no filter', matching the config
    default `traffic_pd: []` = all — never 'send nothing'."""
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    ing = TrafficIngestor(
        api=FakeApiClient([_mk_flow(1, "allowed")]), session_factory=session_factory,
        watermark=WatermarkStore(session_factory),
        siem_destinations=["soc"], siem_pd_filters={"soc": set()},
    )
    ing.run_once()
    assert _dispatched(session_factory) == [("soc", "allowed")]


def test_ingestor_filter_normalises_numeric_stored_action(session_factory):
    from src.pce_cache.ingestor_traffic import TrafficIngestor
    from src.pce_cache.watermark import WatermarkStore

    flows = [_mk_flow(1, "2"), _mk_flow(2, "0")]   # numeric-as-string forms
    ing = TrafficIngestor(
        api=FakeApiClient(flows), session_factory=session_factory,
        watermark=WatermarkStore(session_factory),
        siem_destinations=["soc"], siem_pd_filters={"soc": {"blocked"}},
    )
    ing.run_once()
    assert _dispatched(session_factory) == [("soc", "2")]


# ── backfill gate ────────────────────────────────────────────────────────────

def _seed_traffic(session_factory, actions):
    now = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        for i, action in enumerate(actions, start=1):
            s.add(PceTrafficFlowRaw(
                flow_hash=f"hash-{i}", src_ip="1.2.3.4", dst_ip="5.6.7.8", port=443,
                protocol="tcp", action=action, flow_count=1, bytes_in=0, bytes_out=0,
                first_detected=now, last_detected=now, raw_json="{}", ingested_at=now,
            ))


def test_backfill_respects_pd_filter_per_destination(session_factory):
    from src.siem.dispatcher import enqueue_new_records

    _seed_traffic(session_factory, ["blocked", "allowed", "unknown"])
    created = enqueue_new_records(
        session_factory,
        {"pce_traffic_flows_raw": ["soc", "lake"]},
        pd_filters={"soc": {"blocked", "unknown"}},
    )
    assert created == 5
    assert _dispatched(session_factory) == [
        ("lake", "allowed"), ("lake", "blocked"), ("lake", "unknown"),
        ("soc", "blocked"), ("soc", "unknown"),
    ]
    # idempotent: a second pass finds nothing, and does not now queue the
    # filtered-out row either
    assert enqueue_new_records(
        session_factory, {"pce_traffic_flows_raw": ["soc", "lake"]},
        pd_filters={"soc": {"blocked", "unknown"}},
    ) == 0


def test_backfill_pd_filter_ignores_event_table(session_factory):
    """The filter is a traffic concept; an audit destination that happens to
    share a name must still receive every event row."""
    from src.pce_cache.models import PceEvent
    from src.siem.dispatcher import enqueue_new_records

    now = datetime.now(timezone.utc)
    with session_factory.begin() as s:
        s.add(PceEvent(
            pce_href="/orgs/1/events/1", pce_event_id="uuid-1", timestamp=now,
            event_type="policy.update", severity="info", status="success",
            pce_fqdn="pce.test", raw_json="{}", ingested_at=now,
        ))
    created = enqueue_new_records(
        session_factory, {"pce_events": ["soc"]}, pd_filters={"soc": {"blocked"}},
    )
    assert created == 1


# ── scheduler wiring ─────────────────────────────────────────────────────────

def _cm_with_destinations(*dests):
    from src.config_models import SiemDestinationSettings, SiemForwarderSettings
    siem = SiemForwarderSettings(enabled=True, destinations=[SiemDestinationSettings(**d) for d in dests])
    return SimpleNamespace(models=SimpleNamespace(siem=siem))


def test_traffic_pd_filters_helper_lists_only_filtered_enabled_traffic_destinations():
    from src.scheduler.jobs import _traffic_pd_filters
    cm = _cm_with_destinations(
        {"name": "soc", "traffic_pd": ["blocked"]},
        {"name": "lake"},                                             # no filter
        {"name": "off", "enabled": False, "traffic_pd": ["blocked"]},  # disabled
        {"name": "audit", "source_types": ["audit"], "traffic_pd": ["blocked"]},  # not traffic
    )
    assert _traffic_pd_filters(cm) == {"soc": {"blocked"}}


def test_traffic_pd_filters_empty_when_siem_disabled():
    from src.config_models import SiemDestinationSettings, SiemForwarderSettings
    from src.scheduler.jobs import _traffic_pd_filters
    siem = SiemForwarderSettings(enabled=False, destinations=[
        SiemDestinationSettings(name="soc", traffic_pd=["blocked"])])
    assert _traffic_pd_filters(SimpleNamespace(models=SimpleNamespace(siem=siem))) == {}


class _FakeIngestor:
    SOURCE = "traffic"
    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs
        self.last_run_overflow = None

    def run_once(self):
        return 0


class _FakeApi:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_run_traffic_ingest_passes_pd_filters_to_the_ingestor(monkeypatch, tmp_path):
    """Wiring guard (same shape as test_traffic_ingest_wiring): the kwarg is
    Optional with a harmless default, so forgetting it would silently disable
    the feature rather than fail."""
    from src.config_models import TrafficFilterSettings, TrafficSamplingSettings
    from src.scheduler import jobs

    class _Cfg:
        db_path = str(tmp_path / "cache.sqlite")
        traffic_filter = TrafficFilterSettings()
        traffic_sampling = TrafficSamplingSettings()
        async_threshold_events = 1
        flow_delta_enabled = True
        flow_obs_retention_hours = 6

    class _CM:
        class models:
            pce_cache = _Cfg()
        config: dict = {}

    _FakeIngestor.last_kwargs = {}
    monkeypatch.setattr("src.pce_cache.ingestor_traffic.TrafficIngestor", _FakeIngestor)
    monkeypatch.setattr("src.api_client.ApiClient", lambda cm: _FakeApi())
    monkeypatch.setattr(jobs, "_guard_cache_target", lambda *a, **k: None)
    monkeypatch.setattr(jobs, "_enabled_siem_destinations", lambda cm, kind: ["soc"])
    monkeypatch.setattr(jobs, "_traffic_pd_filters", lambda cm: {"soc": {"blocked"}})
    monkeypatch.setattr(jobs, "_record_ingest_pce_result", lambda *a, **k: None)
    monkeypatch.setattr(jobs, "_record_traffic_overflow", lambda *a, **k: None)

    class _WM:
        def get(self, _src):
            return None

    monkeypatch.setattr("src.pce_cache.watermark.WatermarkStore", lambda sf: _WM())
    jobs.run_traffic_ingest(_CM())
    assert _FakeIngestor.last_kwargs.get("siem_pd_filters") == {"soc": {"blocked"}}


def test_run_siem_dispatch_passes_pd_filters_to_backfill(monkeypatch, tmp_path):
    from src.scheduler import jobs

    cm = _cm_with_destinations({"name": "soc", "traffic_pd": ["blocked"]})
    cm.models.pce_cache = SimpleNamespace(db_path=str(tmp_path / "cache.sqlite"))
    cm.config = {}
    seen = {}

    def _fake_enqueue(sf, dests, *a, **kw):
        seen["dests"] = dests
        seen["pd_filters"] = kw.get("pd_filters")
        return 0

    def _stop(*a, **k):
        raise RuntimeError("stop")   # stop before any real dispatcher is built

    # run_siem_dispatch imports these locally from src.siem.dispatcher
    monkeypatch.setattr("src.siem.dispatcher.enqueue_new_records", _fake_enqueue)
    monkeypatch.setattr("src.siem.dispatcher.build_dispatcher", _stop)
    monkeypatch.setattr(jobs, "_get_cache_engine", lambda p: create_engine("sqlite://"))
    with patch.object(jobs, "logger"):
        try:
            jobs.run_siem_dispatch(cm)
        except RuntimeError:
            pass
    assert seen["pd_filters"] == {"soc": {"blocked"}}


# ── web + CLI surfaces ───────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path):
    import json
    from src.config import ConfigManager
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "api": {"url": "https://pce.test", "key": "test", "secret": "test", "org_id": "1"},
        "rules": [],
        "web_gui": {"username": "admin", "password": "testpass",
                    "allowed_ips": ["127.0.0.1"], "secret_key": "test-secret"},
    }))
    cm = ConfigManager(config_file=str(path))
    cm.load()
    from src.gui import _create_app
    app = _create_app(cm, persistent_mode=True)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/api/login", json={"username": "admin", "password": "testpass"},
               environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        yield c


def test_web_add_and_update_persist_traffic_pd(client, monkeypatch):
    # _get_siem_cfg builds its own ConfigManager on the default path; point it
    # at this app's CM the way test_siem_web does.
    monkeypatch.setattr("src.siem.web._get_siem_cfg",
                        lambda: client.application.config["CM"].models.siem)
    r = client.post("/api/siem/destinations",
                    json={"name": "soc", "transport": "tcp", "host": "1.2.3.4", "port": 5514,
                          "traffic_pd": ["blocked", "potentially_blocked"]},
                    environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.get_json()["ok"] is True, r.get_json()
    cm = client.application.config["CM"]
    d = next(x for x in cm.models.siem.destinations if x.name == "soc")
    assert d.traffic_pd == ["blocked", "potentially_blocked"]

    r = client.put("/api/siem/destinations/soc", json={"traffic_pd": []},
                   environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.get_json()["ok"] is True
    d = next(x for x in cm.models.siem.destinations if x.name == "soc")
    assert d.traffic_pd == []

    r = client.get("/api/siem/destinations", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    listed = next(x for x in r.get_json()["destinations"] if x["name"] == "soc")
    assert listed["traffic_pd"] == []


def test_web_rejects_unknown_traffic_pd_value(client):
    r = client.post("/api/siem/destinations",
                    json={"name": "soc", "transport": "tcp", "host": "1.2.3.4", "port": 5514,
                          "traffic_pd": ["denied"]},
                    environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_cli_prompt_parses_traffic_pd(monkeypatch):
    from src import siem_cli
    answers = iter([
        "soc",        # name
        "",           # enabled
        "tcp",        # transport
        "",           # format
        "1.2.3.4:5514",  # endpoint
        "",           # tls_verify
        "",           # tls_ca_bundle
        "",           # hec_token
        "",           # batch_size
        "traffic",    # source_types
        "blocked, potentially_blocked",  # traffic_pd
        "",           # max_retries
    ])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    data = siem_cli._prompt_destination()
    assert data["traffic_pd"] == ["blocked", "potentially_blocked"]
    assert data["source_types"] == ["traffic"]


def test_cli_prompt_blank_traffic_pd_keeps_existing(monkeypatch):
    from src import siem_cli
    answers = iter(["", "", "", "", "", "", "", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    data = siem_cli._prompt_destination({"name": "soc", "traffic_pd": ["blocked"]})
    assert data["traffic_pd"] == ["blocked"]


def test_gui_drawer_and_i18n_carry_traffic_pd():
    """Source-level guard for the v2 drawer (the real DOM is covered by the
    env-gated SIEM e2e test): the field must be tracked and every i18n key it
    uses must exist in both catalogues."""
    import json
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    js = (root / "src/static/js/v2/areas/system.mjs").read_text(encoding="utf-8")
    assert 'b.traffic_pd = ' in js
    assert 'dataset.field = "traffic_pd"' in js
    keys = set(re.findall(r't\("(gui_siem_traffic_pd[a-z_]*)"\)', js))
    assert keys >= {"gui_siem_traffic_pd", "gui_siem_traffic_pd_help"}
    en = json.loads((root / "src/i18n_en.json").read_text(encoding="utf-8"))
    zh = json.loads((root / "src/i18n_zh_TW.json").read_text(encoding="utf-8"))
    for k in keys | {"sic_traffic_pd_prompt"}:
        assert en.get(k), f"missing en key {k}"
        assert zh.get(k), f"missing zh key {k}"
