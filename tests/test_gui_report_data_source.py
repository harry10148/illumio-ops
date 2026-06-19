from src.gui.routes.reports import _data_source_from_payload


def test_payload_explicit_data_source():
    assert _data_source_from_payload({"data_source": "cache-only"}, True)[:2] == (True, True)
    assert _data_source_from_payload({"data_source": "live"}, True)[:2] == (False, False)
    assert _data_source_from_payload({"data_source": "hybrid"}, True)[:2] == (True, False)


def test_payload_legacy_use_cache_false():
    # old GUI clients sent use_cache=false meaning live
    assert _data_source_from_payload({"use_cache": "false"}, True)[:2] == (False, False)


def test_payload_legacy_clip_to_cache_true():
    assert _data_source_from_payload({"clip_to_cache": "true"}, True)[:2] == (True, True)


def test_payload_default_hybrid():
    assert _data_source_from_payload({}, True)[:2] == (True, False)


def test_payload_cache_unavailable_falls_back():
    uc, clip, warn = _data_source_from_payload({"data_source": "cache-only"}, False)
    assert (uc, clip) == (False, False) and warn
