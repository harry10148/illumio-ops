"""Windows 曾經是本工具的執行平台之一；2026-08-25 起不再是。

這兩組守門是雙向的：上半確保 host 支援真的移除乾淨，下半確保移除的過程
沒有連帶砍掉「管理 Windows workload」的能力——那是本工具的核心用途之一，
而且用 grep 掃 "windows" 會同時命中兩類。
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_powershell_files_remain():
    """只看 git 追蹤的檔案。

    這台機器上有 20 個 .ps1，其中 17 個在 venv/（`venv/bin/Activate.ps1`）與
    gitignore 掉的 build/ staging tree 裡。用 rglob 掃檔案系統的守門會在每一台
    有 venv 的開發機和 appliance 上永遠假紅——那比沒有守門更糟，因為紅燈會被
    學會忽略。
    """
    out = subprocess.run(["git", "ls-files", "*.ps1"], cwd=ROOT,
                         capture_output=True, text=True, check=True)
    found = sorted(l for l in out.stdout.splitlines() if l)
    assert found == [], f"Windows is no longer a host platform: {found}"


def test_build_script_produces_no_windows_bundle():
    src = (ROOT / "scripts" / "build_offline_bundle.sh").read_text(encoding="utf-8")
    for needle in ("build_windows", "PBS_WIN_URL", "offline-windows-x86_64", "nssm"):
        assert needle not in src, f"{needle!r} still in build_offline_bundle.sh"


def test_offline_spec_carries_no_windows_only_wheels():
    spec = (ROOT / "requirements-offline.txt").read_text(encoding="utf-8")
    lock = (ROOT / "requirements-offline.lock").read_text(encoding="utf-8")
    for needle in ("colorama", "win32-setctime", "win32_setctime"):
        assert needle not in spec, f"{needle!r} still in requirements-offline.txt"
        assert needle not in lock, f"{needle!r} still in requirements-offline.lock"


def test_no_vendored_windows_assets():
    assert not (ROOT / "vendor" / "windows").exists()


def test_file_lock_has_no_msvcrt_backend():
    import src.file_lock as fl
    assert not hasattr(fl, "_msvcrt")


def test_no_nssm_in_shipped_copy():
    """NSSM 是 Windows 服務管理器；產品文案不該再提它。

    這條守的是本案最容易漏的一項：mockup 改了、正式字典沒改，任何閘門都不會紅，
    但使用者在 GUI 上還是看得到 NSSM。
    """
    # zh_explicit 目前就沒有 NSSM（該 key 不在其中），一併納入是為了擋住
    # 「未來有人把這句加進正本」。
    for rel in ("src/i18n_en.json", "src/i18n_zh_TW.json",
                "src/i18n/data/zh_explicit.json"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "NSSM" not in text, f"{rel} still mentions NSSM"


def test_doc_coverage_no_longer_requires_the_powershell_scripts():
    text = (ROOT / "scripts" / "check_doc_coverage.sh").read_text(encoding="utf-8")
    assert "install.ps1" not in text
    assert "preflight.ps1" not in text


# ── 反向守門：管理 Windows workload 的能力不得被連帶移除 ──────────────────

def test_estate_inventory_still_classifies_windows_workloads():
    """`by_family_windows` 是測試方法名，不是產品符號；產品端是這條分支。"""
    src_text = (ROOT / "src" / "report" / "analysis" / "estate_inventory.py").read_text(encoding="utf-8")
    assert '"Windows"' in src_text


def test_windows_service_filter_key_survives_in_the_query_layer():
    src_text = (ROOT / "src" / "api" / "traffic_query.py").read_text(encoding="utf-8")
    assert "windows_service_name" in src_text


def test_windows_workload_copy_survives_in_i18n():
    en = json.loads((ROOT / "src" / "i18n_en.json").read_text(encoding="utf-8"))
    assert en["gui_fb_cat_winservice"] == "Windows Service"
    assert "Windows" in en["rule_l007_rec"]
