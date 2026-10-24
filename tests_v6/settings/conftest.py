import json

import pytest

from illumio_ops.settings.schema import default_settings

HASH = "$argon2id$v=19$m=131072,t=4,p=4$c29tZXNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"
KEY = "ab" * 32


@pytest.fixture
def initial():
    return default_settings(password_hash=HASH, secret_key=KEY)


@pytest.fixture
def settings_file(tmp_path, initial):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(initial.model_dump(mode="json")))
    p.chmod(0o600)
    return p
