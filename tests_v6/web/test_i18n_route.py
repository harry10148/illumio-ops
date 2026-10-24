from .conftest import LOCAL


def test_dictionary_is_public_and_per_language(client):
    zh = client.get("/api/i18n/zh_TW", environ_overrides=LOCAL)
    en = client.get("/api/i18n/en", environ_overrides=LOCAL)
    assert zh.status_code == en.status_code == 200
    assert set(zh.get_json()["data"]) == set(en.get_json()["data"])
    assert zh.get_json()["data"]["login_submit"] != en.get_json()["data"]["login_submit"]


def test_unknown_language_is_404(client):
    r = client.get("/api/i18n/fr", environ_overrides=LOCAL)
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "not_found"
