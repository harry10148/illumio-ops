"""Phase 4c：規則儲存端點（traffic/bandwidth/PUT）收 FilterBar filters dict，
label_group 明確拒絕（400）。三端點共用 tests/conftest.py 的 client fixture。"""
from tests._helpers import _csrf


def _login(client):
    login = client.post('/api/login', json={"username": "admin", "password": "testpass"},
                        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert login.status_code == 200
    return _csrf(login)


def test_add_traffic_rule_stores_filterbar_keys(client):
    csrf_token = _login(client)

    r = client.post('/api/rules/traffic', json={
        "name": "R1", "pd": -1, "threshold_count": 5, "threshold_window": 10,
        "filters": {
            "src_labels": ["app=erp", "app=web"],
            "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
            "src_workloads": ["/orgs/1/workloads/abc"],
            "src_ip_in": ["10.0.0.1"],
            "ex_dst_ip": ["10.9.9.9"],
            "any_label": "env=prod",
            "any_workload": "/orgs/1/workloads/xyz",
        },
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    rules = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()
    rule = next(x for x in rules if x["name"] == "R1")
    assert rule["src_labels"] == ["app=erp", "app=web"]
    assert rule["dst_iplists"] == ["/orgs/1/sec_policy/active/ip_lists/7"]
    assert rule["src_workloads"] == ["/orgs/1/workloads/abc"]
    assert rule["src_ip_in"] == ["10.0.0.1"]
    assert rule["ex_dst_ip"] == ["10.9.9.9"]
    assert rule["any_label"] == "env=prod"
    assert rule["any_workload"] == "/orgs/1/workloads/xyz"


def test_add_traffic_rule_rejects_label_groups(client):
    csrf_token = _login(client)

    r = client.post('/api/rules/traffic', json={
        "name": "R2", "threshold_count": 5, "threshold_window": 10,
        "filters": {"src_label_groups": ["PG-Prod"]},
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False

    rules = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()
    assert all(x.get("name") != "R2" for x in rules)


def test_add_traffic_rule_legacy_branch_unchanged(client):
    csrf_token = _login(client)

    r = client.post('/api/rules/traffic', json={
        "name": "L1", "src": "app=erp", "dst": "10.0.0.5",
        "threshold_count": 5, "threshold_window": 10,
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    rules = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()
    rule = next(x for x in rules if x["name"] == "L1")
    assert rule["src_label"] == "app=erp"
    assert rule["dst_ip_in"] == "10.0.0.5"


def test_add_bandwidth_rule_stores_filterbar_keys(client):
    csrf_token = _login(client)

    r = client.post('/api/rules/bandwidth', json={
        "name": "BW1", "pd": -1, "threshold_count": 100, "threshold_window": 10,
        "filters": {
            "src_labels": ["app=erp"],
            "dst_ip_in": ["10.0.0.9"],
        },
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    rules = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()
    rule = next(x for x in rules if x["name"] == "BW1")
    assert rule["src_labels"] == ["app=erp"]
    assert rule["dst_ip_in"] == ["10.0.0.9"]


def test_add_bandwidth_rule_rejects_label_groups(client):
    csrf_token = _login(client)

    r = client.post('/api/rules/bandwidth', json={
        "name": "BW2", "threshold_count": 100, "threshold_window": 10,
        "filters": {"ex_dst_label_group": "PG-DB"},
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False

    rules = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()
    assert all(x.get("name") != "BW2" for x in rules)


def test_add_bandwidth_rule_legacy_branch_unchanged(client):
    csrf_token = _login(client)

    r = client.post('/api/rules/bandwidth', json={
        "name": "BWL1", "src": "app=erp", "dst": "10.0.0.5",
        "threshold_count": 100, "threshold_window": 10,
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    rules = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()
    rule = next(x for x in rules if x["name"] == "BWL1")
    assert rule["src_label"] == "app=erp"
    assert rule["dst_ip_in"] == "10.0.0.5"


def test_update_rule_rejects_label_groups(client):
    csrf_token = _login(client)

    r = client.post('/api/rules/traffic', json={
        "name": "PutBase", "src": "app=erp", "threshold_count": 5, "threshold_window": 10,
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    idx = next(i for i, x in enumerate(
        client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()
    ) if x["name"] == "PutBase")

    r2 = client.put(f'/api/rules/{idx}', json={
        "filters": {"dst_label_groups": ["PG-Web"]},
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r2.status_code == 400
    assert r2.get_json()["ok"] is False


def test_update_rule_filters_replace_semantics_no_stale_keys(client):
    """PUT 帶 filters 更新後，物件 key 整組替換，legacy scalar 與舊物件 key 不殘留混存。"""
    csrf_token = _login(client)

    r = client.post('/api/rules/traffic', json={
        "name": "PutReplace",
        "filters": {
            "src_labels": ["app=erp", "app=web"],
            "dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/7"],
        },
        "threshold_count": 5, "threshold_window": 10,
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    idx = next(i for i, x in enumerate(
        client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()
    ) if x["name"] == "PutReplace")

    r2 = client.put(f'/api/rules/{idx}', json={
        "filters": {"src_workloads": ["/orgs/1/workloads/abc"]},
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r2.status_code == 200
    assert r2.get_json()["ok"] is True

    updated = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()[idx]
    assert updated["src_workloads"] == ["/orgs/1/workloads/abc"]
    assert "src_labels" not in updated
    assert "dst_iplists" not in updated
    assert not updated.get("src_label")
    assert not updated.get("src_ip_in")


def test_update_rule_legacy_branch_unchanged(client):
    csrf_token = _login(client)

    r = client.post('/api/rules/traffic', json={
        "name": "PutLegacy", "threshold_count": 5, "threshold_window": 10,
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r.status_code == 200
    idx = next(i for i, x in enumerate(
        client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()
    ) if x["name"] == "PutLegacy")

    r2 = client.put(f'/api/rules/{idx}', json={
        "src": "app=erp", "dst": "10.0.0.5",
    }, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, headers={'X-CSRF-Token': csrf_token})
    assert r2.status_code == 200

    updated = client.get('/api/rules', environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).get_json()[idx]
    assert updated["src_label"] == "app=erp"
    assert updated["dst_ip_in"] == "10.0.0.5"
