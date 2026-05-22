"""Tests for L-5 / L-6: rotated log files must be chmod'd to 0o640."""
import inspect


def test_loguru_config_chmod_logic_exists():
    """loguru_config must include some chmod-on-rotation logic."""
    from src import loguru_config

    src = inspect.getsource(loguru_config)
    assert "chmod" in src, "loguru_config must apply chmod to log files at some point"
    # Look for 0o640 or 0o600 explicitly
    assert "0o640" in src or "0o600" in src or "0o660" in src, (
        "chmod must target 0o6XX permission (not world-readable)"
    )


def test_compress_and_chmod_produces_gz_with_correct_perms(tmp_path):
    """_compress_and_chmod must produce a .gz file with mode 0o640."""
    import stat
    from src.loguru_config import _compress_and_chmod

    log_file = tmp_path / "test.log"
    log_file.write_text("hello log\n")

    _compress_and_chmod(str(log_file))

    gz_file = tmp_path / "test.log.gz"
    assert gz_file.exists(), "_compress_and_chmod must produce a .gz file"
    assert not log_file.exists(), "_compress_and_chmod must remove the original"

    mode = stat.S_IMODE(gz_file.stat().st_mode)
    assert mode == 0o640, f"Expected 0o640, got {oct(mode)}"
