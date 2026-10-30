"""The optional write key (spec §6.5 key decision): an owner service account used only for Rule Hit Count (and later
quarantine); the main key stays read-only."""
import pytest

from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.settings.schema import default_settings
from illumio_ops.settings.secrets import MASK, redact
from tests_v6.services.collect.conftest import configured_ctx

from .conftest import HASH, KEY


def test_write_key_optional_default_empty():
    s = default_settings(password_hash=HASH, secret_key=KEY)
    assert (s.pce.write_api_key, s.pce.write_api_secret) == ("", "")


def test_write_key_masked():
    s = default_settings(password_hash=HASH, secret_key=KEY)
    s = s.model_copy(update={"pce": s.pce.model_copy(update={"write_api_key": "wk", "write_api_secret": "ws"})})
    d = redact(s)
    assert d["pce"]["write_api_key"] == MASK and d["pce"]["write_api_secret"] == MASK


def test_write_client_uses_write_key(tmp_path):
    ctx = configured_ctx(tmp_path)
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["pce"].update(write_api_key="wk", write_api_secret="ws"))
    seen = []
    ctx.pce_factory = lambda cfg, **kw: seen.append((cfg.api_key, cfg.api_secret)) or object()
    ctx.pce_write_client()
    assert seen == [("wk", "ws")]


def test_write_client_missing_key(tmp_path):
    ctx = configured_ctx(tmp_path)
    with pytest.raises(PceNotConfigured):
        ctx.pce_write_client()
