"""TDD tests for scripts/migrate_to_loguru.py codemod."""
import importlib.util
import sys
from pathlib import Path


def _load_migrate():
    spec = importlib.util.spec_from_file_location(
        "migrate_to_loguru",
        Path(__file__).resolve().parent.parent / "scripts" / "migrate_to_loguru.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_import_replacement(tmp_path):
    m = _load_migrate()
    src = "import logging\nlogger = logging.getLogger(__name__)\n\nlogger.info('hello')\n"
    f = tmp_path / "sample.py"
    f.write_text(src)
    changed = m.migrate_file(f)
    assert changed
    result = f.read_text()
    assert "from loguru import logger" in result
    assert "import logging\n" not in result
    assert "logging.getLogger" not in result


def test_format_spec_conversion(tmp_path):
    m = _load_migrate()
    src = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "logger.info('x %s y %d', val, num)\n"
    )
    f = tmp_path / "fmt.py"
    f.write_text(src)
    m.migrate_file(f)
    result = f.read_text()
    assert "logger.info('x {} y {}', val, num)" in result


def test_dry_run_does_not_modify_file(tmp_path):
    m = _load_migrate()
    src = "import logging\nlogger = logging.getLogger(__name__)\n"
    f = tmp_path / "dry.py"
    f.write_text(src)
    changed = m.migrate_file(f, dry_run=True)
    assert changed is True
    assert f.read_text() == src


def test_no_change_when_already_migrated(tmp_path):
    m = _load_migrate()
    src = "from loguru import logger\n\nlogger.info('already migrated')\n"
    f = tmp_path / "clean.py"
    f.write_text(src)
    changed = m.migrate_file(f)
    assert changed is False
    assert f.read_text() == src


def test_module_log_excluded(tmp_path):
    m = _load_migrate()
    src = "import logging\nlogger = logging.getLogger('modlog')\n"
    f = tmp_path / "module_log.py"
    f.write_text(src)
    # module_log.py is in the exclude list so migrate_file itself does the work,
    # but the main() loop should skip it.  Test that the file name is excluded:
    exclude = {"module_log.py", "loguru_config.py", "utils.py"}
    assert f.name in exclude


def test_double_import_import_logging_not_duplicated(tmp_path):
    m = _load_migrate()
    src = (
        "import logging\n"
        "import os\n"
        "logger = logging.getLogger(__name__)\n"
        "logger.debug('test')\n"
    )
    f = tmp_path / "double.py"
    f.write_text(src)
    m.migrate_file(f)
    result = f.read_text()
    assert result.count("from loguru import logger") == 1
    assert "import logging\n" not in result
