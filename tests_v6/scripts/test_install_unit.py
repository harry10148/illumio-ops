import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "scripts" / "v6" / "install.sh"


def _hardening_directives() -> list[str]:
    """Every directive of the 5.x unit's hardening block, verbatim."""
    text = (REPO / "deploy" / "illumio-ops.service").read_text()
    block = text.split("# --- Hardening ---", 1)[1].split("[Install]", 1)[0]
    lines = [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return [ln for ln in lines if not ln.startswith("ReadWritePaths=")]


def _render(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(INSTALL), "--print-unit", *args], capture_output=True, text=True,
                          timeout=30, check=False)


def test_rendered_unit_keeps_every_5x_hardening_directive():
    r = _render("--prefix", "/opt/illumio-ops-v6", "--service-name", "illumio-ops-v6")
    assert r.returncode == 0, r.stderr
    unit_lines = {ln.strip() for ln in r.stdout.splitlines()}
    missing = [d for d in _hardening_directives() if d not in unit_lines]
    assert missing == [] and len(_hardening_directives()) >= 20


def test_rendered_unit_paths():
    unit = _render("--prefix", "/opt/illumio-ops-v6/", "--service-name", "illumio-ops-v6").stdout
    assert "ExecStart=/opt/illumio-ops-v6/python/bin/python3 -P -m illumio_ops serve --root /opt/illumio-ops-v6\n" in unit
    assert "ReadWritePaths=/opt/illumio-ops-v6/config /opt/illumio-ops-v6/data /opt/illumio-ops-v6/logs " \
           "/opt/illumio-ops-v6/reports\n" in unit
    assert "Environment=PYTHONPATH=/opt/illumio-ops-v6\n" in unit and "Environment=PYTHONNOUSERSITE=1\n" in unit
    assert "WorkingDirectory=/opt/illumio-ops-v6\n" in unit and "SyslogIdentifier=illumio-ops-v6\n" in unit
    assert not re.search(r"@[A-Z_]+@", unit)
    # an invalid settings file or a second instance must end in "failed", not a restart loop
    assert "RestartPreventExitStatus=75 78\n" in unit


def test_bad_arguments_are_refused():
    assert _render("--prefix", "relative/path").returncode != 0
    assert _render("--service-name", "a b").returncode != 0
    r = subprocess.run(["bash", str(INSTALL), "--port", "70000", "--print-unit"], capture_output=True, text=True,
                       timeout=30, check=False)
    assert r.returncode != 0


def test_existing_5x_installation_is_refused(tmp_path):
    (tmp_path / "illumio-ops.py").write_text("# 5.x")
    r = subprocess.run(["bash", str(INSTALL), "--no-systemd", "--prefix", str(tmp_path)], capture_output=True,
                       text=True, timeout=30, check=False)
    assert r.returncode != 0 and "5.x" in r.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["illumio-ops.py"]


def test_existing_v6_installation_is_refused(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.json").write_text("{}")
    r = subprocess.run(["bash", str(INSTALL), "--no-systemd", "--prefix", str(tmp_path)], capture_output=True,
                       text=True, timeout=30, check=False)
    assert r.returncode != 0 and "already" in r.stderr
