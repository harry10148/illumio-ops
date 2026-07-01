from src.config_models import PceCacheSettings


def test_archive_defaults_are_off_and_safe():
    s = PceCacheSettings()
    assert s.archive_enabled is False
    assert s.archive_dir == "data/archive"
    assert s.archive_interval_hours == 24
    assert s.archive_gzip_after_days == 7


def test_archive_fields_parse_custom_values():
    s = PceCacheSettings(
        archive_enabled=True,
        archive_dir="/mnt/wormstore/illumio",
        archive_interval_hours=6,
        archive_gzip_after_days=3,
    )
    assert s.archive_enabled is True
    assert s.archive_dir == "/mnt/wormstore/illumio"
    assert s.archive_interval_hours == 6
    assert s.archive_gzip_after_days == 3


def test_archive_interval_and_gzip_have_lower_bounds():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PceCacheSettings(archive_interval_hours=0)
    with pytest.raises(ValidationError):
        PceCacheSettings(archive_gzip_after_days=0)
