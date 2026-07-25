"""Contracts for the two packaging security defects found in review 2.

1. scripts/build_offline_bundle.sh staged the BUILD HOST's runtime-generated
   TLS material into the shipped tar.gz/zip, so every install made from one
   bundle served HTTPS with the same private key (and anyone holding a copy of
   the bundle could impersonate any installation). The bundle must ship config
   templates only; each install mints its own cert on first start via
   _generate_self_signed_cert() in src/gui/_helpers.py.

2. scripts/install.ps1 applied no ACLs, so C:\\illumio-ops inherited C:\\'s
   default DACL (BUILTIN\\Users: Read & Execute) and config\\config.json — PCE
   api.key/api.secret, smtp.password, LINE/Telegram tokens, web_gui.secret_key
   — was readable by every interactive user. install.sh keeps exactly those
   files 0600, so the Windows path must not be looser.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build_offline_bundle.sh"
INSTALL_PS1 = ROOT / "scripts" / "install.ps1"


def _bash_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ps_text(path: Path) -> str:
    # PowerShell files in this repo are UTF-8 with BOM (Windows-sensitive).
    return path.read_text(encoding="utf-8-sig")


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


# ── 2. Windows install must restrict the config ACL ──────────────────────────

def test_install_ps1_restricts_install_root_acl():
    src = _ps_text(INSTALL_PS1)
    assert "icacls" in src, (
        "install.ps1 must restrict ACLs; without it config\\config.json is "
        "readable by BUILTIN\\Users via C:\\'s inherited DACL"
    )
    assert "/inheritance:r" in src, (
        "inheritance must be broken, or the permissive ACEs inherited from "
        "C:\\ survive the grant"
    )
    # SIDs, not names: the built-in groups are localized on non-English Windows.
    assert "S-1-5-18" in src, "SYSTEM (S-1-5-18) must keep full control"
    assert "S-1-5-32-544" in src, "Administrators (S-1-5-32-544) must keep full control"
    assert "Set-SecureAcl -Path $InstallRoot" in src, (
        "the install root must be locked down before anything is copied into it"
    )
    assert 'foreach ($d in @("config", "logs"))' in src, (
        "config\\ and logs\\ must be re-asserted recursively so an upgrade over "
        "a pre-hardening install is healed too"
    )


def test_install_ps1_aborts_when_acl_hardening_fails():
    src = _ps_text(INSTALL_PS1)
    assert "failed to restrict ACLs" in src, (
        "a failed icacls must abort the install, not fall through silently"
    )


# ── Parity items fixed alongside the two High findings ───────────────────────

def test_install_ps1_purges_stale_runtime_and_app_files():
    src = _ps_text(INSTALL_PS1)
    assert "/MIR" in src, (
        "the bundled python\\ tree must be mirrored (/MIR), or site-packages "
        "keeps versions that satisfy the ranges in requirements-offline.txt and "
        "pip upgrades nothing on the Windows upgrade path"
    )
    assert "/PURGE" in src, (
        "the app tree must be purged so deleted src modules do not linger as "
        "importable zombie .py files (parity with install.sh's rsync --delete)"
    )
    # Exclusions must be anchored to the install root: bare names match at any
    # depth and would freeze app-tree dirs such as src\i18n\data.
    assert '"$InstallRoot\\config" "$InstallRoot\\data"' in src
    assert '"MIGRATED_FROM"' in src, (
        "MIGRATED_FROM is not in the bundle; without an /XF it would be purged "
        "and the migration would be re-run on the next install"
    )


def test_install_ps1_verifies_service_registration_and_smoke_check():
    src = _ps_text(INSTALL_PS1)
    assert "app smoke check failed" in src, (
        "parity with install.sh: run illumio-ops.py --help before pointing a "
        "service at the install"
    )
    assert "service registration failed" in src, (
        "install.ps1 must check $LASTEXITCODE of deploy\\install_service.ps1 "
        "instead of unconditionally printing 'Installation complete.'"
    )
    assert "IllumioOps is not registered" in src, (
        "verify the observable result — install_service.ps1 prints its success "
        "banner unconditionally"
    )


def test_install_ps1_migration_fallback_keeps_the_web_gui():
    src = _ps_text(INSTALL_PS1)
    assert "--monitor --interval" not in src, (
        "plain --monitor runs headless (no Web GUI); the migration fallback "
        "must match deploy\\install_service.ps1's --monitor-gui"
    )
    assert "illumio-ops.py --monitor-gui --interval 10" in src


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
