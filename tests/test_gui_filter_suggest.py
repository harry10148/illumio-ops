from tests._helpers import _csrf


def _login(client):
    r = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.status_code == 200
    return _csrf(r)


def test_suggest_cached_and_workload(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    _login(client)
    from src.gui.filter_object_cache import invalidate_object_cache
    invalidate_object_cache()
    monkeypatch.setattr("src.api_client.ApiClient.get_all_labels",
                        lambda self: [{"key": "env", "value": "Production", "href": "/orgs/1/labels/3"}])
    monkeypatch.setattr("src.api_client.ApiClient.get_ip_lists", lambda self: [])
    monkeypatch.setattr("src.api_client.ApiClient.get_label_groups", lambda self: [])

    calls = []
    def fake_search(self, params):
        calls.append(params)
        if params.get("name") == "prod":
            return [{"name": "prod-web-01", "hostname": "prod-web-01",
                     "href": "/orgs/1/workloads/1",
                     "interfaces": [{"address": "10.1.2.3"}]}]
        return []
    monkeypatch.setattr("src.api_client.ApiClient.search_workloads", fake_search)

    r = client.get('/api/filter-objects/suggest?q=prod&types=label,workload&limit=10',
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.status_code == 200
    body = r.json["results"]
    assert any(i["value"] == "Production" for i in body["label"]["items"])
    assert body["workload"]["items"][0]["name"] == "prod-web-01"
    # workload 同時查 name 與 hostname
    assert {"name": "prod", "max_results": 10} in [
        {k: v for k, v in c.items() if k in ("name", "max_results")} for c in calls]


def test_suggest_workload_offline_degrades(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    _login(client)
    from src.gui.filter_object_cache import invalidate_object_cache
    invalidate_object_cache()
    monkeypatch.setattr("src.api_client.ApiClient.get_all_labels",
                        lambda self: [{"key": "env", "value": "Prod", "href": "/orgs/1/labels/3"}])
    monkeypatch.setattr("src.api_client.ApiClient.get_ip_lists", lambda self: [])
    monkeypatch.setattr("src.api_client.ApiClient.get_label_groups", lambda self: [])
    # 真實生產路徑：ApiClient.search_workloads 失敗時吞例外回 []（不 raise），
    # 必須靠 check_health 才能區分「PCE 不通」vs「真的無符合」。
    monkeypatch.setattr("src.api_client.ApiClient.search_workloads", lambda self, params: [])
    monkeypatch.setattr("src.api_client.ApiClient.check_health", lambda self: (0, "unreachable"))

    r = client.get('/api/filter-objects/suggest?q=prod&types=label,workload&limit=10',
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.status_code == 200
    # cached label 照常，workload 降級
    assert r.json["results"]["label"]["items"]
    assert r.json["results"]["workload"]["error"] == "pce_unreachable"


def test_suggest_workload_empty_but_pce_up(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    _login(client)
    from src.gui.filter_object_cache import invalidate_object_cache
    invalidate_object_cache()
    monkeypatch.setattr("src.api_client.ApiClient.get_all_labels",
                        lambda self: [{"key": "env", "value": "Prod", "href": "/orgs/1/labels/3"}])
    monkeypatch.setattr("src.api_client.ApiClient.get_ip_lists", lambda self: [])
    monkeypatch.setattr("src.api_client.ApiClient.get_label_groups", lambda self: [])
    # 真的沒有符合的 workload（PCE 正常）：search_workloads 回 []，check_health 回 200
    monkeypatch.setattr("src.api_client.ApiClient.search_workloads", lambda self, params: [])
    monkeypatch.setattr("src.api_client.ApiClient.check_health", lambda self: (200, "ok"))

    r = client.get('/api/filter-objects/suggest?q=zzz-no-match&types=workload&limit=10',
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert r.status_code == 200
    assert r.json["results"]["workload"]["items"] == []
    assert r.json["results"]["workload"]["error"] is None


def test_suggest_workload_dedup_name_hostname(app_persistent, monkeypatch):
    client = app_persistent.test_client()
    _login(client)
    monkeypatch.setattr("src.api_client.ApiClient.search_workloads",
                        lambda self, params: [{"name": "w1", "hostname": "w1",
                                               "href": "/orgs/1/workloads/1",
                                               "interfaces": [{"address": "10.0.0.1"}]}])
    r = client.get('/api/filter-objects/suggest?q=w&types=workload&limit=10',
                   environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    # name 查與 hostname 查回同一 workload → 去重成 1 筆
    assert len(r.json["results"]["workload"]["items"]) == 1
