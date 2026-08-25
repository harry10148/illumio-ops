"""Windows 曾經是本工具的執行平台之一；2026-08-25 起不再是。

這兩組守門是雙向的：上半確保 host 支援真的移除乾淨，下半確保移除的過程
沒有連帶砍掉「管理 Windows workload」的能力——那是本工具的核心用途之一，
而且用 grep 掃 "windows" 會同時命中兩類。

守門本身也被對抗式審查過一輪：每條斷言都要能被「一個真實的重新引入」弄紅，
否則就是綠燈假象。註解／docstring 能滿足的斷言一律不算數（見
`_key_bearing_containers`）。
"""
import ast
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tracked(*patterns: str) -> list[str]:
    """git 索引裡符合 pathspec 的檔案（只看追蹤中的，不掃檔案系統）。"""
    out = subprocess.run(["git", "ls-files", *patterns], cwd=ROOT,
                         capture_output=True, text=True, check=True)
    return sorted(line for line in out.stdout.splitlines() if line)


def _key_bearing_containers(path: Path, key: str) -> int:
    """含有 `key` 字面值的 tuple/list/set 元素或 dict 鍵之「容器」數量。

    刻意不用「整檔 substring」或「所有字串常數」：註解與 docstring 都能滿足
    那兩種檢查，於是真正的產品程式碼可以被整段刪掉而測試照樣綠。容器計數只
    數真的參與資料流的字面值，而且把每個轉送點各算一次，因此刪掉任何一處都
    會讓計數掉下門檻。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            children = list(node.elts)
        elif isinstance(node, ast.Dict):
            children = [k for k in node.keys if k is not None]
        else:
            continue
        if any(isinstance(c, ast.Constant) and c.value == key for c in children):
            found += 1
    return found


def test_no_powershell_files_remain():
    """只看 git 追蹤的檔案。

    這台機器上有 20 個 .ps1，其中 17 個在 venv/（`venv/bin/Activate.ps1`）與
    gitignore 掉的 build/ staging tree 裡。用 rglob 掃檔案系統的守門會在每一台
    有 venv 的開發機和 appliance 上永遠假紅——那比沒有守門更糟，因為紅燈會被
    學會忽略。

    副檔名不只 .ps1：Windows 安裝器同樣可以寫成 install.bat / install.cmd，
    module 也可以是 .psm1 / .psd1。
    """
    found = _tracked("*.ps1", "*.psm1", "*.psd1", "*.bat", "*.cmd")
    assert found == [], f"Windows is no longer a host platform: {found}"


# 一次改名（build_win()／PBS_WINDOWS_URL）就能繞過舊的四個字面 needle，
# 重新加回 `--platform win_amd64` 到既有的 build_linux 也一樣。改成用前綴／
# 一般性 token 比對。
_WINDOWS_BUILD_PATTERNS = (
    r"build_win",        # build_win / build_windows
    r"PBS_WIN",          # PBS_WIN_URL / PBS_WINDOWS_URL
    r"offline-win",      # offline-windows-x86_64 及其改名
    r"nssm",
    r"windows",
    r"win32",
    r"win_amd64",
    r"win_arm64",
    r"--platform\s+win",
    r"\.exe\b",
)


def test_build_script_produces_no_windows_bundle():
    src = (ROOT / "scripts" / "build_offline_bundle.sh").read_text(encoding="utf-8")
    for needle in ("build_windows", "PBS_WIN_URL", "offline-windows-x86_64", "nssm"):
        assert needle not in src, f"{needle!r} still in build_offline_bundle.sh"
    for pattern in _WINDOWS_BUILD_PATTERNS:
        hit = re.search(pattern, src, re.IGNORECASE)
        assert hit is None, (
            f"build_offline_bundle.sh matches {pattern!r} ({hit.group(0)!r}) — "
            "Windows bundles are no longer built"
        )


# 列舉具體套件名擋不住 pywin32 / pywin32-ctypes / windows-curses / wmi。
# 一般性的性質是「lock 與 spec 裡不該有任何 Windows 環境標記」。
_WINDOWS_MARKER_RE = re.compile(
    r"""(platform_system|sys_platform|os_name)\s*[=!]=\s*['"]?\s*(windows|win32|nt)\b""",
    re.IGNORECASE,
)


def test_offline_spec_carries_no_windows_only_wheels():
    spec = (ROOT / "requirements-offline.txt").read_text(encoding="utf-8")
    lock = (ROOT / "requirements-offline.lock").read_text(encoding="utf-8")
    for needle in ("colorama", "win32-setctime", "win32_setctime"):
        assert needle not in spec, f"{needle!r} still in requirements-offline.txt"
        assert needle not in lock, f"{needle!r} still in requirements-offline.lock"
    for rel, text in (("requirements-offline.txt", spec),
                      ("requirements-offline.lock", lock)):
        hit = _WINDOWS_MARKER_RE.search(text)
        assert hit is None, f"{rel} carries a Windows environment marker: {hit.group(0)!r}"


# 只擋字面路徑 vendor/windows 的話，改 vendor 到 vendor/nssm/、
# third_party/windows/ 或直接 commit 一個 deploy/nssm.exe 都能溜過去。
# 比對對象刻意選「Windows 服務管理器資產」而不是 "windows" 這個字：後者會
# 打到 Windows *workload* 的產品程式碼。
_WINDOWS_SERVICE_ASSET_RE = re.compile(
    r"nssm"                                                   # NSSM 服務包裝器
    r"|\.(exe|dll|msi|msix|sys)$"                              # Windows 執行檔
    r"|(^|/)(vendor|third_party|thirdparty|3rdparty|external|deps)/[^/]*windows",
    re.IGNORECASE,
)


def test_no_vendored_windows_assets():
    assert not (ROOT / "vendor" / "windows").exists()
    offenders = [p for p in _tracked() if _WINDOWS_SERVICE_ASSET_RE.search(p)]
    assert offenders == [], f"vendored Windows service assets are back: {offenders}"


def test_file_lock_has_no_msvcrt_backend():
    """`hasattr` 只擋得住 `import msvcrt as _msvcrt` 這一種寫法。

    `import msvcrt`（綁定名 `msvcrt`）、函式內的 inline import、
    `from msvcrt import locking` 都不會產生 `_msvcrt` 屬性。改成也看原始碼
    文字，三種寫法一次擋掉。
    """
    import src.file_lock as fl
    assert not hasattr(fl, "_msvcrt")
    text = (ROOT / "src" / "file_lock.py").read_text(encoding="utf-8")
    assert "msvcrt" not in text, "src/file_lock.py still references the msvcrt backend"


# 出貨文案：使用者看得到的字典、GUI 樣板、前端 JS/mjs、正式文件。
# 刻意排除 CHANGELOG.md——它的 Removed 條目與歷史條目本來就會提到 NSSM，
# 而歷史條目永遠不得竄改。docs/superpowers/ 與 reports/audit/ 同理（設計
# 文件與稽核紀錄），tests/ 亦然（本檔自己就寫著 NSSM）。
_SHIPPED_COPY_PREFIXES = ("src/", "design/", "docs/guide/", "docs/reference/",
                          "docs/handover/")
_SHIPPED_COPY_FILES = ("README.md", "README_zh.md", "docs/INDEX.md")
_SHIPPED_COPY_SUFFIXES = (".json", ".js", ".mjs", ".html", ".htm", ".md",
                          ".txt", ".py", ".css", ".jinja", ".jinja2")


def _shipped_copy_files() -> list[str]:
    out = []
    for rel in _tracked():
        if not rel.endswith(_SHIPPED_COPY_SUFFIXES):
            continue
        if rel in _SHIPPED_COPY_FILES or rel.startswith(_SHIPPED_COPY_PREFIXES):
            out.append(rel)
    return out


def test_no_nssm_in_shipped_copy():
    """NSSM 是 Windows 服務管理器；產品文案不該再提它。

    這條守的是本案最容易漏的一項：mockup 改了、正式字典沒改，任何閘門都不會紅，
    但使用者在 GUI 上還是看得到 NSSM。原本只掃三個 JSON 且大小寫敏感——
    前端 .mjs、GUI 樣板、正式文件裡的 "nssm"／"Nssm" 全部溜過去。
    """
    # zh_explicit 目前就沒有 NSSM（該 key 不在其中），一併納入是為了擋住
    # 「未來有人把這句加進正本」。
    for rel in ("src/i18n_en.json", "src/i18n_zh_TW.json",
                "src/i18n/data/zh_explicit.json"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "NSSM" not in text, f"{rel} still mentions NSSM"

    shipped = _shipped_copy_files()
    assert shipped, "shipped-copy file set is empty — the guard would scan nothing"
    offenders = []
    for rel in shipped:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if "nssm" in text.lower():
            offenders.append(rel)
    assert offenders == [], f"shipped copy still mentions NSSM: {offenders}"


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
    """整檔 substring 會被第 ~1198 行的**註解**滿足。

    改成兩種註解無法偽造的斷言：capability 表要真的 import 得到該鍵，且參與
    資料流的字面值容器數要維持——`_TRAFFIC_FILTER_CAPABILITIES` 的兩個項目、
    payload 組裝的 (key, field, target) 三元組、以及 fallback 比對器的
    (inc_key, ex_key, svc_field) 三元組。
    """
    import src.api.traffic_query as tq
    for key in ("windows_service_name", "ex_windows_service_name"):
        assert key in tq._TRAFFIC_FILTER_CAPABILITIES, \
            f"{key} dropped out of the traffic filter capability table"

    path = ROOT / "src" / "api" / "traffic_query.py"
    # 目前的四處：capability dict、include 三元組、exclude 三元組、fallback
    # 比對三元組。門檻釘在實際數量，少掉任何一處都會紅。
    assert _key_bearing_containers(path, "windows_service_name") >= 4
    assert _key_bearing_containers(path, "ex_windows_service_name") >= 3


def test_windows_service_filter_key_survives_in_gui_forwarding():
    """GUI 的兩個轉送點：dashboard 與 report 產生。

    這兩處在本案之前完全沒有測試覆蓋——把鍵從 dashboard 或報表轉送刪掉，
    整套測試照樣全綠，但 Windows Service 篩選會在儀表板與產出的報表上悄悄
    失效（`tests/test_filter_key_chain_invariants.py` 只走 actions.py）。
    """
    dashboard = ROOT / "src" / "gui" / "routes" / "dashboard.py"
    reports = ROOT / "src" / "gui" / "routes" / "reports.py"
    for key in ("windows_service_name", "ex_windows_service_name"):
        # dashboard 兩處：fallback key 白名單 tuple，以及 top-flows query 的
        # params dict。
        assert _key_bearing_containers(dashboard, key) >= 2, \
            f"{key} lost a forwarding site in gui/routes/dashboard.py"
        # reports 一處：report_filters dict。
        assert _key_bearing_containers(reports, key) >= 1, \
            f"{key} lost its forwarding site in gui/routes/reports.py"


def test_windows_workload_copy_survives_in_i18n():
    en = json.loads((ROOT / "src" / "i18n_en.json").read_text(encoding="utf-8"))
    assert en["gui_fb_cat_winservice"] == "Windows Service"
    assert "Windows" in en["rule_l007_rec"]
