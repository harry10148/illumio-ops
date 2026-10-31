import pytest

from illumio_ops.paths import resolve_paths
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import default_settings
from illumio_ops.settings.secrets import hash_password, new_secret_key
from illumio_ops.settings.store import SettingsStore
from illumio_ops.store.db import migrate
from illumio_ops.web.app import create_app

ADMIN_PASSWORD = "illumio"
LOCAL = {"REMOTE_ADDR": "127.0.0.1"}
_HASH_CACHE: dict[str, str] = {}


def cached_hash(plain: str) -> str:
    # argon2 at the production cost (128 MiB, t=4) is slow; tests reuse hashes.
    if plain not in _HASH_CACHE:
        _HASH_CACHE[plain] = hash_password(plain)
    return _HASH_CACHE[plain]


@pytest.fixture(autouse=True)
def _memory_limiter(monkeypatch):
    monkeypatch.setenv("ILLUMIO_OPS_RATELIMIT_URI", "memory://")


@pytest.fixture
def static_dir(tmp_path):
    d = tmp_path / "static"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text('<!doctype html><script type="module" src="/assets/app.js"></script>')
    (d / "assets" / "app.js").write_text("console.log(1)")
    return d


def make_ctx(tmp_path, **web_overrides):
    paths = resolve_paths(tmp_path / "root")
    paths.ensure_dirs()
    store = SettingsStore(paths.settings_file)
    s = default_settings(password_hash=cached_hash(ADMIN_PASSWORD), secret_key=new_secret_key())
    store.create_initial(password_hash=s.web.password_hash, secret_key=s.web.secret_key)
    def mutate(d):
        # The suite was written against full collection; new installs default to lightweight (spec §6.4,
        # 2026-10-29), and the tests about lightweight set it themselves.
        d["collection"]["mode"] = "full"
        d["web"].update(web_overrides)
    store.update(0, mutate)
    ctx = AppContext(paths=paths, settings=store)
    with ctx.db() as conn:
        migrate(conn)
    return ctx


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


@pytest.fixture
def app(ctx, static_dir):
    a = create_app(ctx, use_https=False, static_dir=static_dir)
    a.testing = True
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client) -> str:
    r = client.get("/api/auth/csrf", environ_overrides=LOCAL)
    return r.get_json()["data"]["csrf_token"]


def login(client, password: str = ADMIN_PASSWORD, username: str = "illumio"):
    r = client.post("/api/auth/login", json={"username": username, "password": password},
                    environ_overrides=LOCAL)
    return r


def post(client, url, body=None, token=None):
    return client.post(url, json=body or {}, environ_overrides=LOCAL,
                       headers={"X-CSRFToken": token or csrf(client)})
