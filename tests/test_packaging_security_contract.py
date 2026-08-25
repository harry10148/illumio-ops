"""Contracts for the packaging security defects found in review 2 (+ the wheel
pinning defect found later).

1. scripts/build_offline_bundle.sh staged the BUILD HOST's runtime-generated
   TLS material into the shipped tar.gz/zip, so every install made from one
   bundle served HTTPS with the same private key (and anyone holding a copy of
   the bundle could impersonate any installation). The bundle must ship config
   templates only; each install mints its own cert on first start via
   _generate_self_signed_cert() in src/gui/_helpers.py.

3. The offline bundle resolved its wheels live from the ranges in
   requirements-offline.txt: no pinning, no hash verification, no audit. Two
   builds of the same source shipped different dependency sets, and a
   substituted wheel would have installed silently on every offline host. The
   bundle now downloads and installs requirements-offline.lock (pip-compile
   --generate-hashes) with --require-hashes on both platforms.
"""
import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build_offline_bundle.sh"
INSTALL_SH = ROOT / "scripts" / "install.sh"
OFFLINE_REQ = ROOT / "requirements-offline.txt"
OFFLINE_LOCK = ROOT / "requirements-offline.lock"


def _bash_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_fn(src: str, name: str) -> str:
    """Return the body of a top-level `name() { ... }` shell function."""
    m = re.search(rf"^{re.escape(name)}\(\)\s*\{{.*?^\}}", src, re.S | re.M)
    assert m, f"{name}() not found in build_offline_bundle.sh"
    return m.group(0)


# ── 1. Offline bundle must never carry key material ──────────────────────────

def test_build_script_excludes_tls_dir_from_config_stage():
    src = _bash_text(BUILD_SCRIPT)
    stage = _extract_fn(src, "stage_app")
    assert "--exclude='tls/'" in stage, (
        "stage_app must exclude config/tls/ — it holds the build host's "
        "self-signed cert AND private key, which would then be shared by every "
        "install made from the bundle"
    )
    for pat in ("--exclude='*.pem'", "--exclude='*.key'"):
        assert pat in stage, f"stage_app must exclude {pat} (key material)"


def test_build_script_asserts_no_secrets_after_staging():
    src = _bash_text(BUILD_SCRIPT)
    assert "assert_no_secrets_staged()" in src, (
        "build_offline_bundle.sh must define the post-stage secret gate"
    )
    stage = _extract_fn(src, "stage_app")
    assert "assert_no_secrets_staged" in stage, (
        "stage_app must call assert_no_secrets_staged so the excludes above "
        "are proven, not merely intended"
    )


def _extract_assert_fn() -> str:
    return _extract_fn(_bash_text(BUILD_SCRIPT), "assert_no_secrets_staged")


def _run_gate(dest: Path):
    return subprocess.run(
        ["bash", "-c", f"{_extract_assert_fn()}\nassert_no_secrets_staged '{dest}'"],
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_secret_gate_passes_on_a_template_only_config(tmp_path):
    cfg = tmp_path / "app" / "config"
    cfg.mkdir(parents=True)
    (cfg / "config.json.example").write_text("{}")
    (cfg / "report_config.yaml").write_text("x: 1\n")
    r = _run_gate(tmp_path)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
@pytest.mark.parametrize(
    "relpath",
    [
        "tls/self_signed_key.pem",   # the actual leak that shipped
        "tls/csr_key.pem",
        "config.json",               # PCE credentials
        "alerts.json",
    ],
)
def test_secret_gate_fails_when_key_or_operator_file_staged(tmp_path, relpath):
    cfg = tmp_path / "app" / "config"
    cfg.mkdir(parents=True)
    (cfg / "config.json.example").write_text("{}")
    target = cfg / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("SECRET")
    r = _run_gate(tmp_path)
    assert r.returncode != 0, (
        f"the build must fail when {relpath} is staged; gate returned 0"
    )
    assert "staged into the bundle" in r.stderr


# ── Parity items fixed alongside the two High findings ───────────────────────

def test_setup_sh_unit_matches_the_shipped_unit():
    setup = _bash_text(ROOT / "scripts" / "setup.sh")
    assert "--monitor-gui --interval" in setup, (
        "setup.sh is a documented production install path; --monitor gives no "
        "Web GUI and forces a two-process topology in which the in-process "
        "locks (analysis_lock, _rs_db_lock, _BACKFILL_LOCK) protect nothing"
    )
    assert "illumio-ops.py --monitor --interval" not in setup
    assert "ReadWritePaths=$REPO_ROOT/logs" in setup, (
        "ReadWritePaths=$REPO_ROOT let the service account rewrite its own "
        "Python source (the clone is chowned to it)"
    )
    assert "ReadWritePaths=$REPO_ROOT\n" not in setup
    for directive in ("PrivateTmp=true", "CapabilityBoundingSet=",
                      "SystemCallFilter=@system-service",
                      "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX"):
        assert directive in setup, (
            f"setup.sh's generated unit is missing {directive!r} from "
            "deploy/illumio-ops.service"
        )


def test_setup_sh_does_not_emit_an_unstartable_protecthome_unit():
    setup = _bash_text(ROOT / "scripts" / "setup.sh")
    assert "ProtectHome=$PROTECT_HOME" in setup, (
        "ProtectHome=true hides /home and /root, so a clone under either has "
        "neither a usable WorkingDirectory nor a mountable ReadWritePaths "
        "target and the unit fails 226/NAMESPACE at every start"
    )
    assert "PROTECT_HOME=false" in setup


def test_uninstall_sh_does_not_orphan_secrets_to_a_reusable_uid():
    src = _bash_text(ROOT / "scripts" / "uninstall.sh")
    assert "chown -R root:root" in src, (
        "the non-purge path keeps config/ (PCE credentials) and data/ but then "
        "deletes the illumio-ops account; useradd --system reuses freed UIDs, "
        "so the survivors must be re-homed to root before userdel"
    )
    userdel_at = src.index("userdel")
    chown_at = src.index("chown -R root:root")
    assert chown_at < userdel_at, "chown must happen before userdel"


# ── 3. Offline wheels must be pinned + hash-verified end to end ──────────────

def _lock_requirement_lines(text: str) -> list[str]:
    """Return the lock's logical requirement lines (backslash continuations joined)."""
    joined = re.sub(r"\\\n\s*", " ", text)
    return [
        line.strip()
        for line in joined.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_offline_lock_exists():
    assert OFFLINE_LOCK.is_file(), (
        "requirements-offline.lock is missing — the offline bundle would fall "
        "back to resolving requirements-offline.txt's ranges live, which pins "
        "nothing and verifies nothing"
    )


def test_every_offline_lock_entry_is_pinned_and_hashed():
    lines = _lock_requirement_lines(OFFLINE_LOCK.read_text(encoding="utf-8"))
    assert lines, "requirements-offline.lock has no requirements"
    unpinned = [ln[:60] for ln in lines if not re.match(r"^[A-Za-z0-9._-]+==", ln)]
    assert not unpinned, f"unpinned entries in requirements-offline.lock: {unpinned}"
    unhashed = [ln.split()[0] for ln in lines if "--hash=" not in ln]
    assert not unhashed, (
        f"entries without --hash= in requirements-offline.lock: {unhashed}; "
        "regenerate with pip-compile --generate-hashes"
    )


def test_offline_lock_records_the_sha256_of_its_source_spec():
    """The freshness marker the build gate compares against must be present and correct."""
    text = OFFLINE_LOCK.read_text(encoding="utf-8")
    m = re.findall(r"^# requirements-offline\.txt sha256: *([0-9a-f]{64})$", text, re.M)
    assert m, (
        "requirements-offline.lock must end with a "
        "'# requirements-offline.txt sha256: <hex>' marker; without it "
        "build_offline_bundle.sh cannot tell a fresh lock from a stale one"
    )
    expected = hashlib.sha256(OFFLINE_REQ.read_bytes()).hexdigest()
    assert m[-1] == expected, (
        "requirements-offline.lock is stale: it was generated from a different "
        "requirements-offline.txt. Regenerate it (see that file's header)."
    )


def test_install_sh_installs_the_lock_with_require_hashes():
    src = _bash_text(INSTALL_SH)
    assert "--require-hashes" in src, (
        "install.sh must install the bundled wheels with --require-hashes; "
        "without it a substituted wheel installs silently"
    )
    assert "requirements-offline.lock" in src, (
        "install.sh must install from the hash-pinned lock, not from the "
        "range-only requirements-offline.txt"
    )
    assert '-r "$INSTALL_ROOT/requirements-offline.txt"' not in src
    # set -e means a hash mismatch (non-zero pip exit) aborts the install.
    assert re.search(r"^set -euo pipefail$", src, re.M), (
        "install.sh relies on set -e to turn a failed hash check into an abort"
    )


def test_build_script_downloads_wheels_from_the_lock():
    src = _bash_text(BUILD_SCRIPT)
    for fn in ("build_linux", "build_windows"):
        body = _extract_fn(src, fn)
        assert '-r "$LOCK_FILE"' in body, (
            f"{fn}() must download wheels from requirements-offline.lock"
        )
        assert "--require-hashes" in body, (
            f"{fn}() must pass --require-hashes so a tampered wheel fails the build"
        )
        assert '-r "$REPO_ROOT/requirements-offline.txt"' not in body


def test_build_script_stages_the_lock_into_the_bundle():
    stage = _extract_fn(_bash_text(BUILD_SCRIPT), "stage_app")
    assert '"$LOCK_FILE" "$dest/app/"' in stage, (
        "the lock must ship inside the bundle — install.sh/install.ps1 install "
        "from it at the customer site"
    )


def test_build_script_runs_the_freshness_gate_before_building():
    src = _bash_text(BUILD_SCRIPT)
    assert "require_fresh_lock()" in src
    assert re.search(r"^require_fresh_lock$", src, re.M), (
        "require_fresh_lock must actually run at top level, before build_linux"
    )
    gate_at = src.index("\nrequire_fresh_lock\n")
    assert gate_at < src.index("\nbuild_linux\n")


def _run_lock_gate(tmp_path: Path, lock_body: str | None):
    """Run require_fresh_lock() against a synthetic repo root."""
    fn = _extract_fn(_bash_text(BUILD_SCRIPT), "require_fresh_lock")
    (tmp_path / "requirements-offline.txt").write_text("flask>=3.0,<4.0\n")
    lock = tmp_path / "requirements-offline.lock"
    if lock_body is not None:
        lock.write_text(lock_body)
    script = (
        f'REPO_ROOT="{tmp_path}"\nLOCK_FILE="{lock}"\n{fn}\nrequire_fresh_lock\n'
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_lock_gate_passes_when_the_marker_matches(tmp_path):
    digest = hashlib.sha256(b"flask>=3.0,<4.0\n").hexdigest()
    r = _run_lock_gate(tmp_path, f"flask==3.1.3 --hash=sha256:deadbeef\n"
                                 f"# requirements-offline.txt sha256: {digest}\n")
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
@pytest.mark.parametrize(
    "lock_body, expected",
    [
        (None, "is missing"),
        ("flask==3.1.3\n", "no source sha256 marker"),
        ("flask==3.1.3\n# requirements-offline.txt sha256: " + "0" * 64 + "\n",
         "is stale"),
    ],
)
def test_lock_gate_fails_closed(tmp_path, lock_body, expected):
    r = _run_lock_gate(tmp_path, lock_body)
    assert r.returncode != 0, "the build must not proceed on a missing/stale lock"
    assert expected in r.stderr, r.stderr


# ── CI: the offline lock must be audited on the interpreter it ships ────────
# The lock pins versions that only install on the bundle's py3.12 target
# (matplotlib==3.11.1 requires Python >= 3.11), but the test matrix runs
# 3.10/3.11. pip-audit installs the requirements into a throwaway venv to
# resolve them — --no-deps does NOT prevent that (verified: run 30155387549) —
# so auditing this lock anywhere but 3.12 dies with "No matching distribution
# found". Hence a dedicated job.

def _ci() -> dict:
    import yaml
    return yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _offline_audit_job() -> dict:
    jobs = _ci()["jobs"]
    for job in jobs.values():
        for step in job.get("steps", []):
            if "requirements-offline.lock" in str(step.get("run", "")):
                return job
    raise AssertionError("no CI job audits requirements-offline.lock")


def test_offline_lock_is_audited_on_the_bundled_python():
    job = _offline_audit_job()
    versions = [str(s.get("with", {}).get("python-version", ""))
                for s in job["steps"] if "setup-python" in str(s.get("uses", ""))]
    assert versions, "the offline-audit job does not pin a Python version"
    bundled = _bundled_python_major_minor()
    assert any(v.strip('"\'') == bundled for v in versions), (
        f"the offline lock must be audited on Python {bundled} (what the bundle "
        f"ships, per build_offline_bundle.sh PBS_PYTHON); job pins {versions}")


def test_offline_audit_is_not_in_the_test_matrix():
    """It must not ride the 3.10/3.11 matrix — that is the failure this fixes."""
    job = _offline_audit_job()
    assert "matrix" not in str(job.get("strategy", {})), (
        "the offline audit must be a standalone job, not a matrix entry")


def _bundled_python_major_minor() -> str:
    body = (ROOT / "scripts" / "build_offline_bundle.sh").read_text(encoding="utf-8")
    m = re.search(r'PBS_PYTHON="?(\d+)\.(\d+)\.', body)
    assert m, "could not read PBS_PYTHON from build_offline_bundle.sh"
    return f"{m.group(1)}.{m.group(2)}"


def test_offline_audit_still_blocks_the_build():
    job = _offline_audit_job()
    for step in job["steps"]:
        if "requirements-offline.lock" in str(step.get("run", "")):
            assert step.get("continue-on-error") is not True, (
                "the offline audit must fail the build, not warn")
            assert "--strict" in step["run"]


# ── glibc floor must agree across build script / preflight / docs ────────────
# These three drifted before the manylinux_2_28 bump: the docs table listed
# RHEL/Rocky 8+ (glibc 2.28) while the same line's parenthetical said
# "glibc >= 2.17", and preflight.sh gated on 2.17 with a message naming
# RHEL 7+. Whichever is loosest is what an operator actually gets past, so a
# mismatch means preflight waves through a host the wheels will not run on.

def _linux_wheel_platform_floor() -> tuple[int, int]:
    """Highest manylinux_x_y tag the build script downloads for."""
    body = (ROOT / "scripts" / "build_offline_bundle.sh").read_text(encoding="utf-8")
    tags = re.findall(r"--platform\s+manylinux_(\d+)_(\d+)_x86_64", body)
    assert tags, "build_offline_bundle.sh declares no manylinux platform"
    return max((int(a), int(b)) for a, b in tags)


def _preflight_glibc_floor() -> tuple[int, int]:
    body = (ROOT / "scripts" / "preflight.sh").read_text(encoding="utf-8")
    m = re.search(r'GLIBC_MINOR"\s+-ge\s+(\d+)', body)
    assert m, "could not read the glibc minor threshold from preflight.sh"
    return (2, int(m.group(1)))


def test_preflight_glibc_floor_matches_the_wheel_platform():
    wheel = _linux_wheel_platform_floor()
    pre = _preflight_glibc_floor()
    assert pre == wheel, (
        f"preflight.sh gates on glibc {pre[0]}.{pre[1]} but the bundle's wheels "
        f"need {wheel[0]}.{wheel[1]} — preflight would pass a host the bundle "
        f"cannot run on")


def test_installation_doc_states_the_same_glibc_floor():
    doc = (ROOT / "docs" / "guide" / "installation.md").read_text(encoding="utf-8")
    wheel = _linux_wheel_platform_floor()
    expected = f"glibc >= {wheel[0]}.{wheel[1]}"
    assert expected in doc, (
        f"installation.md must state {expected!r} to match the wheel platform")
    stale = re.findall(r"glibc >= (\d+)\.(\d+)", doc)
    assert all((int(a), int(b)) == wheel for a, b in stale), (
        f"installation.md still names a different glibc floor: {stale}")


def test_offline_audit_needs_no_vulnerability_waivers():
    """The 2_28 bump exists to remove the pillow waivers — keep them gone.

    A reappearing --ignore-vuln means something is shipping with a known
    unpatched CVE; that should be a deliberate, reviewed change, not a quiet
    line in CI.
    """
    job = _offline_audit_job()
    for step in job["steps"]:
        run = str(step.get("run", ""))
        if "requirements-offline.lock" in run:
            assert "--ignore-vuln" not in run, (
                "the offline lock audit must not waive vulnerabilities; if a "
                "waiver is genuinely unavoidable, document why here and update "
                "this test deliberately")
