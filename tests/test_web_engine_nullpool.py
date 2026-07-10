from types import SimpleNamespace


def test_cache_web_sf_uses_cached_engine(monkeypatch, tmp_path):
    import flask
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from src.pce_cache import web as cache_web

    calls = []

    def fake_get_engine(path):
        calls.append(path)
        return create_engine(f"sqlite:///{tmp_path / 'w.sqlite'}", poolclass=NullPool)

    monkeypatch.setattr("src.gui._helpers._get_cache_engine", fake_get_engine)
    app = flask.Flask(__name__)
    app.config["CM"] = SimpleNamespace(models=SimpleNamespace(
        pce_cache=SimpleNamespace(db_path=str(tmp_path / "w.sqlite"))))
    with app.test_request_context():
        sf = cache_web._get_sf()
    assert calls == [str(tmp_path / "w.sqlite")]
    assert sf is not None
