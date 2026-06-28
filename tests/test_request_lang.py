"""_request_lang must fall back to the configured language, not always 'en'.

Regression: `from src.config import cm` (no such module-level symbol) always
raised ImportError, so the "config default" tier was dead and unauthenticated /
session-less requests rendered in English regardless of settings.language.
"""


def _app_with_lang(lang: str):
    from flask import Flask
    from src.config import ConfigManager
    cm = ConfigManager()
    cm.config.setdefault("settings", {})["language"] = lang
    app = Flask(__name__)
    app.secret_key = "test"
    app.config["CM"] = cm
    return app


def test_request_lang_uses_configured_language_when_no_session_lang():
    from src.gui import _request_lang
    app = _app_with_lang("zh_TW")
    with app.test_request_context("/"):
        assert _request_lang() == "zh_TW"


def test_request_lang_prefers_session_lang_over_config():
    from flask import session
    from src.gui import _request_lang
    app = _app_with_lang("zh_TW")
    with app.test_request_context("/"):
        session["lang"] = "en"
        assert _request_lang() == "en"


def test_request_lang_defaults_to_en_outside_request_context():
    from src.gui import _request_lang
    assert _request_lang() == "en"
