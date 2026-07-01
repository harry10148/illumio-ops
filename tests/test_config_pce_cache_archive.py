from src.config_models import PceCacheSettings


def test_archive_defaults_are_off_and_safe():
    s = PceCacheSettings()
    assert s.archive_enabled is False
    assert s.archive_dir == "data/archive"
    assert s.archive_interval_hours == 24
    assert s.archive_gzip_after_days == 7
    assert s.archive_retention_days == 0  # 0 = 永久保留（不刪 archive 檔）


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


def test_archive_retention_days_bounds_and_custom():
    import pytest
    from pydantic import ValidationError
    # 0 合法（永久保留）；正值合法；負值不合法
    assert PceCacheSettings(archive_retention_days=0).archive_retention_days == 0
    assert PceCacheSettings(archive_retention_days=365).archive_retention_days == 365
    with pytest.raises(ValidationError):
        PceCacheSettings(archive_retention_days=-1)


def test_archive_review_max_days_default_and_bounds():
    import pytest
    from pydantic import ValidationError
    assert PceCacheSettings().archive_review_max_days == 31
    assert PceCacheSettings(archive_review_max_days=7).archive_review_max_days == 7
    with pytest.raises(ValidationError):
        PceCacheSettings(archive_review_max_days=0)
