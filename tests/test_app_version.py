import re

import src


def test_version_is_pure_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", src.__version__), src.__version__


def test_version_value():
    assert src.__version__ == "5.0.0"
