"""GET /api/filter-objects/browse：分頁、label 分組、totals、workload 不可瀏覽。

Flask app/client fixture 與 mock ApiClient 樣式沿用 tests/test_gui_filter_suggest.py。
"""
from tests._helpers import _csrf


def _login(client):
    r = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.status_code == 200
    return _csrf(r)


def _labels(n_per_key=23):
    """46 筆跨 2 個 key（Net / role），每個 key 內 value 各自唯一遞增。"""
    labels = []
    href = 0
    for key in ("Net", "role"):
        for i in range(n_per_key):
            href += 1
            labels.append({"key": key, "value": f"v{i}", "href": f"/orgs/1/labels/{href}"})
    return labels


LABELS = _labels()
IP_LISTS = [
    {"name": "ipl-a", "href": "/orgs/1/ip_lists/1", "ip_ranges": [{"from_ip": "10.0.0.0"}]},
    {"name": "ipl-b", "href": "/orgs/1/ip_lists/2", "ip_ranges": [{"from_ip": "10.0.1.0"}]},
]
SERVICES = [
    {"name": "svc-a", "href": "/orgs/1/services/1", "service_ports": [{"port": 80, "proto": 6}]},
    {"name": "svc-b", "href": "/orgs/1/services/2", "service_ports": [{"port": 443, "proto": 6}]},
    {"name": "svc-c", "href": "/orgs/1/services/3", "service_ports": [{"port": 22, "proto": 6}]},
]


def _mock_fetchers(monkeypatch):
    monkeypatch.setattr("src.api_client.ApiClient.get_all_labels", lambda self, **kw: LABELS)
    monkeypatch.setattr("src.api_client.ApiClient.get_ip_lists", lambda self, **kw: IP_LISTS)
    monkeypatch.setattr("src.api_client.ApiClient.get_label_groups", lambda self, **kw: [])
    monkeypatch.setattr("src.api_client.ApiClient.get_services", lambda self, **kw: SERVICES)


def test_browse_totals(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    _login(client)
    from src.gui.filter_object_cache import invalidate_object_cache
    invalidate_object_cache()
    _mock_fetchers(monkeypatch)

    r = client.get('/api/filter-objects/browse?type=_totals',
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    body = r.get_json()
    assert body["ok"] and body["totals"]["label"] == 46 and body["totals"]["service"] == 3
    assert body["totals"]["iplist"] == 2 and body["totals"]["label_group"] == 0


def test_browse_label_grouped_and_paged(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    _login(client)
    from src.gui.filter_object_cache import invalidate_object_cache
    invalidate_object_cache()
    _mock_fetchers(monkeypatch)

    r = client.get('/api/filter-objects/browse?type=label&offset=0&limit=20',
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    body = r.get_json()
    assert body["total"] == 46 and len(body["items"]) == 20 and body["truncated"] is True
    assert {g["key"] for g in body["groups"]} == {"Net", "role"}
    # 排序穩定：offset 接續不重複
    r2 = client.get('/api/filter-objects/browse?type=label&offset=20&limit=20',
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    names1 = {i["name"] for i in body["items"]}
    names2 = {i["name"] for i in r2.get_json()["items"]}
    assert not names1 & names2


def test_browse_service_items_have_summary(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    _login(client)
    from src.gui.filter_object_cache import invalidate_object_cache
    invalidate_object_cache()
    _mock_fetchers(monkeypatch)

    r = client.get('/api/filter-objects/browse?type=service&offset=0&limit=20',
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert all("summary" in i for i in r.get_json()["items"])


def test_browse_workload_not_browseable(app_persistent):
    client = app_persistent.test_client()
    _login(client)
    body = client.get('/api/filter-objects/browse?type=workload',
                      environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()
    assert body["ok"] and body["browseable"] is False


def test_browse_unknown_type_400(app_persistent):
    client = app_persistent.test_client()
    _login(client)
    r = client.get('/api/filter-objects/browse?type=bogus',
                  environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.status_code == 400


def test_browse_pce_unreachable_502(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    _login(client)
    from src.gui.filter_object_cache import invalidate_object_cache
    invalidate_object_cache()

    def _boom(self, **kw):
        raise RuntimeError("pce down")
    monkeypatch.setattr("src.api_client.ApiClient.get_all_labels", _boom)
    monkeypatch.setattr("src.api_client.ApiClient.get_ip_lists", lambda self, **kw: [])
    monkeypatch.setattr("src.api_client.ApiClient.get_label_groups", lambda self, **kw: [])
    monkeypatch.setattr("src.api_client.ApiClient.get_services", lambda self, **kw: [])

    r = client.get('/api/filter-objects/browse?type=label',
                  environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.status_code == 502
    assert r.get_json() == {"ok": False, "error": "pce_unreachable"}
