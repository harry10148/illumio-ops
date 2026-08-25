# 放棄 Windows 執行平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「這支工具跑在 Windows 主機上」的所有安裝、打包、服務包裝與平台分支從 repo 移除，同時完整保留「管理 Windows workload」的能力。

**Architecture:** 六個 task，每個 task 的邊界都是「被移除的東西 ＋ 所有斷言它的測試 ＋ 所有指向它的閘門設定」——三者必須同一個 commit，否則測試套件會在計畫中途變紅，而那個紅燈與任何真實缺陷無關。最後一個 task 加上雙向守門（移除守門＋反向守門），並以突變驗證證明兩者真的會紅。

**Tech Stack:** bash、PowerShell（僅移除）、Python 3.10/3.11、pytest、pip-compile

**Spec:** `docs/superpowers/specs/2026-08-25-drop-windows-host-platform-design.md`

## Global Constraints

以下每一條都約束**每一個** task：

- **絕不移除 Windows workload 支援。** 具體白名單（spec §2）：`windows_service_name` / `ex_windows_service_name` 篩選鍵及其七層白名單全鏈、`tests/test_filter_process_winservice.py`、estate inventory 的 OS family 分類（`src/report/analysis/estate_inventory.py:18` 回傳 `"Windows"` 那條分支——**`by_family_windows` 是 `tests/test_estate_inventory.py:79` 的測試方法名，不是產品符號，在 `src/` 裡 grep 不到是正常的**）、報表中的 Windows workload 統計與 VEN OS 分佈、快取攤平保留的 `windows_service_name` 欄位、`src/i18n_en.json` 中 `gui_fb_cat_winservice` / `gui_fb_grp_freetext` / `rule_b001_*` / `rule_l007_rec` 等描述 workload 的字串。用 grep 掃 `windows` 會同時命中兩類——**每一個命中都要先分類再動手**。
- **歷史紀錄一律不動**：`docs/superpowers/plans/` 與 `specs/` 下的既有文件、`docs/_meta/migration-audit.json`、`CHANGELOG.md` 既有版本的條目、`reports/audit/` 下的稽核產物。它們記載的是當時為真的事，不是現況宣告。
- **`tests/test_cli_signal.py:56` 的 `skipif(sys.platform == 'win32')` 保留**（spec §3.5）。那是測試自身的可攜性條件，不是產品的平台支援。
- **每個 task 結束前必須自己跑過該 task 的覆蓋測試並附上指令與輸出**，再 commit。全套由 orchestrator 在 task 之間跑。
- **提交訊息用英文 conventional commits**（本 repo 慣例）。
- **不得 `git add -A`**；一律用明確路徑。

---

### Task 1: 移除 `file_lock.py` 的 msvcrt 分支（含測試改寫）

**Files:**
- Modify: `src/file_lock.py`
- Modify: `tests/test_config_concurrency.py:414-460`

**Interfaces:**
- Consumes: 無
- Produces: `src.file_lock.has_os_backend()` 語意不變（回傳 bool），實作簡化為 `_fcntl is not None`；模組不再有 `_msvcrt` 屬性。

**這個 task 為什麼不能只是刪除：** `tests/test_config_concurrency.py:448` 的
`test_no_lock_backend_degrades_instead_of_crashing` 測的是「兩種 backend 都不可用時退化成行程內鎖」。
這在純 POSIX 下**仍然要測**（`fcntl` 匯入失敗的機器是存在的）。但它用
`monkeypatch.setattr(fl, "_msvcrt", None)` 關掉第二個 backend；`_msvcrt` 一旦從模組移除，
`monkeypatch.setattr` 會直接 `AttributeError`。所以**改寫與移除必須在同一個 commit**。

- [ ] **Step 1: 先確認現況——兩個測試現在都是綠的**

```bash
timeout 300 python3 -m pytest tests/test_config_concurrency.py -q -k "msvcrt or no_lock_backend"
```

預期：2 passed。

- [ ] **Step 2: 刪除只為 msvcrt 分支存在的測試**

整段刪除 `tests/test_config_concurrency.py` 的
`test_windows_msvcrt_branch_locks_and_unlocks`（含其上方的
`# ── Windows / degraded backends（Linux CI 上只能以代理方式驗證）` 區段標題註解，
以及函式內的 `_FakeMsvcrt` class）。

區段標題註解改寫為：

```python
# ── Degraded backend（fcntl 不可用時的退化路徑）────────────────────────────
```

- [ ] **Step 3: 改寫 `test_no_lock_backend_degrades_instead_of_crashing`**

把這一行刪掉：

```python
    monkeypatch.setattr(fl, "_msvcrt", None)
```

並把 docstring 改寫為：

```python
    """唯一的 backend（fcntl）不可用時退化成行程內鎖，不得讓寫入路徑整個爆掉。"""
```

其餘不動（`monkeypatch.setattr(fl, "_fcntl", None)` 與
`monkeypatch.setattr(fl, "_warned_degraded", False, raising=False)` 都保留）。

- [ ] **Step 4: 執行測試，確認改寫後的退化測試仍然綠、msvcrt 測試已不存在**

```bash
timeout 300 python3 -m pytest tests/test_config_concurrency.py -q -k "msvcrt or no_lock_backend" -v
```

預期：1 passed（`test_no_lock_backend_degrades_instead_of_crashing`），
且輸出中不再出現 `test_windows_msvcrt_branch_locks_and_unlocks`。
此時它應該還是綠的——因為 `file_lock.py` 尚未改，`_fcntl=None` 之後
`_msvcrt` 仍為 `None`（Linux 上本來就 import 失敗），退化路徑不變。

- [ ] **Step 5: 移除 `src/file_lock.py` 的 msvcrt 分支**

刪除這幾處：

```python
    import msvcrt as _msvcrt
except Exception:
    _msvcrt = None
```

（`:44-46` 整個 try/except 匯入區塊）

```python
    if _msvcrt is not None:  # pragma: no cover - Windows only
```

（`:104` 與 `:122` 兩個分支，連同其內部的 `_msvcrt.locking(...)` 呼叫整段刪除）

`has_os_backend()` 改為：

```python
def has_os_backend() -> bool:
    """True 表示這台機器有可用的 OS 層鎖（fcntl）。"""
    return _fcntl is not None
```

`_warn_degraded` 的訊息從 `"neither fcntl nor msvcrt is available"` 改為
`"fcntl is not available"`。

- [ ] **Step 6: 改寫模組 docstring**

`src/file_lock.py:12` 目前寫：

> `msvcrt.locking`（本專案有 Windows 安裝路徑，兩邊都必須能跑）。兩者皆不可用

該句在移除後為假。改寫該段落，只描述 POSIX：說明 `fcntl.flock` 是
per-(process, open-file-description)，因此擋不住同一行程的第二個 thread，
行程內 RLock 因此仍然必要——**這個理由在純 POSIX 下獨立成立**，不需要靠
Windows 那半段撐著。不得留下任何指涉 Windows 或 msvcrt 的字句。

- [ ] **Step 7: 跑覆蓋測試**

```bash
timeout 600 python3 -m pytest tests/test_config_concurrency.py -q
timeout 300 python3 -m pytest tests/ -q -k "file_lock or lock"
```

預期：全綠。

- [ ] **Step 8: 確認模組真的沒有 `_msvcrt` 了**

```bash
python3 -c "import src.file_lock as fl; print('_msvcrt' in vars(fl))"
grep -rn -i msvcrt src/ tests/ || echo "no msvcrt left in src/ or tests/"
```

預期：`False`，以及 `no msvcrt left in src/ or tests/`。

- [ ] **Step 9: Commit**

```bash
git add src/file_lock.py tests/test_config_concurrency.py
git commit -m "refactor(lock): drop the msvcrt backend

Windows is no longer a host platform, so the branch was dead code on
the only platform that runs this. The degraded-backend test stays --
a machine whose fcntl import fails is still real -- but it now nulls
only _fcntl, since monkeypatching an attribute the module no longer
has raises instead of testing anything."
```

---

### Task 2: 移除 CLI 的 `cls` Windows 分支

**Files:**
- Modify: `src/cli/menus/_root.py:17`
- Modify: `src/cli/menus/alert.py:13`
- Modify: `src/cli/menus/bandwidth.py:49`
- Modify: `src/cli/menus/event.py:20`
- Modify: `src/cli/menus/manage_rules.py:42`
- Modify: `src/cli/menus/report_schedule.py:27,134`
- Modify: `src/cli/menus/system_health.py:14`
- Modify: `src/cli/menus/traffic.py:49`
- Modify: `src/cli/menus/web_gui.py:13,18,82`

**Interfaces:**
- Consumes: 無
- Produces: 無（純內部行為，清畫面）

共 **12 處、9 檔**。這是機械性替換，一次做完。

- [ ] **Step 1: 確認命中數與現況**

```bash
git grep -c 'os.name == "nt"' -- src/ | awk -F: '{s+=$2} END {print "occurrences:", s}'
git grep -l 'os.name == "nt"' -- src/ | wc -l
```

預期：`occurrences: 12`、`9`。若數字不符，**停下來回報**——代表 repo 已與計畫脫節。

- [ ] **Step 2: 全部替換**

每一處：

```python
        os.system("cls" if os.name == "nt" else "clear")
```

改為：

```python
        os.system("clear")
```

（縮排依原處保留；`bandwidth.py:49`、`report_schedule.py:134`、`traffic.py:49` 等在模組層級縮排較淺的處也照原縮排。）

- [ ] **Step 3: 清掉因此變成孤兒的 `import os`**

替換後 `os` 仍被 `os.system` 使用，**因此每一檔的 `import os` 都要保留**。
逐檔確認沒有其他只為 `os.name` 而存在的匯入：

```bash
for f in $(git grep -l 'os.system("clear")' -- src/); do
  python3 -c "import ast,sys; ast.parse(open('$f').read())" || echo "SYNTAX ERROR: $f"
done
```

預期：無輸出。

- [ ] **Step 4: 確認沒有殘留**

```bash
git grep -n 'os.name' -- src/ && echo "STILL PRESENT" || echo "clean"
```

預期：`clean`。

- [ ] **Step 5: 跑 CLI 測試**

```bash
timeout 900 python3 -m pytest tests/ -q -k "cli or menu"
```

預期：全綠。

- [ ] **Step 6: Commit**

```bash
git add src/cli/menus/
git commit -m "refactor(cli): clear the screen the POSIX way only

The cls branch could only ever run on a host platform this tool no
longer supports."
```

---

### Task 3: 移除三支 `.ps1` 與所有斷言它們的測試與閘門

**Files:**
- Delete: `scripts/install.ps1`
- Delete: `scripts/preflight.ps1`
- Delete: `deploy/install_service.ps1`
- Delete: `tests/test_windows_install_contract.py`
- Delete: `tests/test_ps1_bom_contract.py`
- Modify: `tests/test_packaging_security_contract.py`
- Modify: `tests/test_docs_contracts.py:130`
- Modify: `docs/guide/installation.md`（僅 frontmatter，正文留給 Task 5）

**Interfaces:**
- Consumes: 無
- Produces: repo 中不再有任何 `.ps1` 檔。

**這個 task 為什麼是一包：** `docs/guide/installation.md` 的 YAML frontmatter
`verified_against` 列出三支 ps1，那是 `scripts/docs_check.py` 的閘門輸入；
`tests/test_docs_contracts.py:130` 與 `tests/test_packaging_security_contract.py`
的 7 個測試直接讀那些檔案。任何一項落在別的 commit，套件就會在計畫中途變紅。

- [ ] **Step 1: 記下現況**

```bash
git ls-files | grep -Ei '\.ps1$'
timeout 300 python3 -m pytest tests/test_packaging_security_contract.py tests/test_docs_contracts.py -q
```

預期：三支 ps1、測試全綠。

- [ ] **Step 2: 刪除三支腳本與兩個整檔測試**

```bash
git rm scripts/install.ps1 scripts/preflight.ps1 deploy/install_service.ps1
git rm tests/test_windows_install_contract.py tests/test_ps1_bom_contract.py
```

- [ ] **Step 3: 移除 `test_packaging_security_contract.py` 的 Windows 測試**

刪除以下 7 個函式，連同它們上方的區段標題註解
`# ── 2. Windows install must restrict the config ACL ──…` 與
`# ── Parity items fixed alongside the two High findings ──…` 中僅屬 Windows 的部分：

- `test_install_ps1_restricts_install_root_acl`（`:130`）
- `test_install_ps1_aborts_when_acl_hardening_fails`（`:152`）
- `test_install_ps1_purges_stale_runtime_and_app_files`（`:161`）
- `test_install_ps1_verifies_service_registration_and_smoke_check`（`:181`）
- `test_install_ps1_migration_fallback_keeps_the_web_gui`（`:197`）
- `test_install_ps1_installs_the_lock_with_require_hashes`（`:315`）

**保留**同區段中的 Linux 測試：`test_setup_sh_unit_matches_the_shipped_unit`、
`test_setup_sh_does_not_emit_an_unstartable_protecthome_unit`、
`test_uninstall_sh_does_not_orphan_secrets_to_a_reusable_uid`、
`test_install_sh_installs_the_lock_with_require_hashes`。

同時刪除檔頭模組 docstring 中僅描述 Windows ACL 的段落（`:11-15`）與
常數 `INSTALL_PS1 = ROOT / "scripts" / "install.ps1"`（`:34`），
以及 `:45` 註解 `# PowerShell files in this repo are UTF-8 with BOM (Windows-sensitive).`
所屬的 helper 若已無呼叫者則一併移除（**先確認無呼叫者再刪**）。

- [ ] **Step 4: 移除 `test_docs_contracts.py:130` 的 preflight.ps1 斷言**

刪除這一行：

```python
    assert "alerts.json" in _read("scripts/preflight.ps1")
```

其上方若有 `preflight.sh` 的對應斷言則**保留**。

- [ ] **Step 5: 更新 `installation.md` 的 frontmatter**

從 `verified_against` 刪除這三行：

```yaml
  - scripts/install.ps1
  - scripts/preflight.ps1
  - deploy/install_service.ps1
```

其餘項目與 `last_verified` 暫不動（Task 5 改正文時再更新 `last_verified`）。

- [ ] **Step 6: 跑覆蓋測試與文件閘門**

```bash
timeout 300 python3 -m pytest tests/test_packaging_security_contract.py tests/test_docs_contracts.py -q
python3 scripts/docs_check.py
python3 scripts/check_doc_links.py
```

預期：測試全綠、兩個文件閘門通過。**這是確定的，不是希望**：
`scripts/docs_check.py` 的 `check_verified_against_paths`（`:134-153`）只檢查
frontmatter 列出的路徑是否存在，而 `check_links`（`:156`）只檢查 md→md 連結；
全 repo 沒有任何 markdown 連結指向 `.ps1`（已查證），正文裡的 ps1 都是 code span，
不構成連結。所以正文留到 Task 5 處理不會讓本 task 的閘門變紅。

- [ ] **Step 7: 確認 repo 已無 ps1**

```bash
git ls-files | grep -Ei '\.ps1$' && echo "STILL PRESENT" || echo "clean"
```

預期：`clean`。

- [ ] **Step 8: Commit**

```bash
git add -u scripts deploy tests docs/guide/installation.md
git commit -m "build: remove the PowerShell installers and their contracts

Their only automated protection was substring matching against source
that CI never executed, on a platform CI never ran."
```

---

### Task 4: 移除打包路徑的 Windows 分支

**Files:**
- Modify: `scripts/build_offline_bundle.sh`
- Modify: `requirements-offline.txt`
- Regenerate: `requirements-offline.lock`
- Delete: `vendor/windows/nssm-2.24.zip`, `vendor/windows/README.md`
- Modify: `tests/test_build_offline_bundle_doc.py`

**Interfaces:**
- Consumes: Task 3 已移除 `.ps1`（`rsync -a "$REPO_ROOT/scripts/"` 因此不再把它們搬進 Linux bundle）
- Produces: `build_offline_bundle.sh` 只產出 `illumio-ops-<version>-offline-linux-x86_64.tar.gz`

- [ ] **Step 1: 移除 `build_offline_bundle.sh` 的 Windows 分支**

刪除：

- 檔頭註解中的 `dist/illumio-ops-<version>-offline-windows-x86_64.zip` 那行（`:6`）與 `:2` 的 "and Windows"
- `PBS_WIN_URL`（`:23`）
- `PBS_SHA256_WIN_X86_64`（`:33`）
- `slim_python` 中的 `else  # windows` 分支（`:171` 起）與 `:152-155` 註解裡描述 Windows 的句子
- 整個 `build_windows()` 函式（`:230-292` 附近，含 `# ── Windows bundle ──` 區段標題）
- 頂層的 `build_windows` 呼叫（`:296`）

`slim_python "$BUILD" windows` 的第二個參數若在移除後只剩一種取值，
**保留該參數不動**（外科手術式改動：不重構沒壞的東西）。

- [ ] **Step 2: 移除 vendor 目錄**

```bash
git rm vendor/windows/nssm-2.24.zip vendor/windows/README.md
rmdir vendor/windows 2>/dev/null || true
```

- [ ] **Step 3: 移除斷言該目錄的測試**

`tests/test_build_offline_bundle_doc.py` 刪除 `test_vendor_windows_readme_exists`（`:15`），
並更新檔頭 docstring `"""Tests for L-7 + L-10: nssm hash documentation and PBS TOFU risk disclosure."""`
——移除 nssm 那半，只留 PBS TOFU。若移除後檔案中其他測試也只為 nssm 存在，一併移除。

- [ ] **Step 4: 更新 `requirements-offline.txt`**

刪除底部的 Windows-only 區段（`:73-78`，含其上方說明註解與
`colorama>=0.4,<1.0`、`win32-setctime>=1.0,<2.0` 兩行）。

同時更新檔頭：

- `:5-6` 提到 `install.sh / install.ps1` → 只留 `install.sh`
- `:21-23` 的 `--platform win_amd64` pip download 範例整段刪除
- `:28` 括號中 `see the Windows-only section at the bottom` → 改寫，該區段已不存在

- [ ] **Step 5: 重新產生鎖檔**

**不可手改鎖檔。** 依 `requirements-offline.txt` 檔頭記載的指令：

```bash
pip-compile --generate-hashes --strip-extras \
    --output-file=requirements-offline.lock requirements-offline.txt
printf '# requirements-offline.txt sha256: %s\n' \
    "$(sha256sum requirements-offline.txt | cut -d' ' -f1)" >> requirements-offline.lock
```

`pip-compile` **不在本機環境中**（已查證）：先 `pip install pip-tools`。

**不要加 `--upgrade`。** pip-compile 預設會沿用 output file 裡既有的釘選版本，
只重解受影響的部分；加了 `--upgrade` 就會把每個套件重解成最新版，等於把一次
依賴升級偷渡進一個移除案，並且讓 `pip-audit` 的結論失效。

- [ ] **Step 5b: 檢查鎖檔 diff 的範圍**

```bash
git diff --stat requirements-offline.lock
git diff requirements-offline.lock | grep -E '^[+-][a-zA-Z]' | head -40
```

預期：只有 `colorama`、`win32-setctime` 相關行消失，加上尾端 marker 那一行改變。

**若 diff 動到其他套件的版本，停下來回報。** 那不是本案要做的事——移除兩個
Windows-only wheel 不應該改變任何 Linux 套件的版本。

- [ ] **Step 6: 驗證鎖檔新鮮度閘門**

```bash
timeout 300 python3 -m pytest tests/test_packaging_security_contract.py -q -k "lock"
```

預期：全綠，特別是 `test_offline_lock_records_the_sha256_of_its_source_spec`
（它比對鎖檔尾端 marker 與 `requirements-offline.txt` 的實際 sha256）。

- [ ] **Step 7: 確認 colorama / win32-setctime 已從鎖檔消失**

```bash
grep -n -i -E 'colorama|win32.setctime' requirements-offline.lock && echo "STILL PRESENT" || echo "clean"
```

預期：`clean`。**若仍存在**，代表它們是某個 Linux 套件的無條件相依而非
marker 隔離的 Windows-only 相依——記進報告後繼續，不要手改鎖檔。

- [ ] **Step 8: 確認 Linux bundle 仍可建置**

```bash
grep -n 'build_linux' scripts/build_offline_bundle.sh
bash -n scripts/build_offline_bundle.sh && echo "syntax ok"
timeout 300 python3 -m pytest tests/test_build_offline_bundle_doc.py tests/test_packaging_security_contract.py -q
```

預期：語法正確、測試全綠。（**不要**實際跑一次完整 bundle 建置——它會下載
數百 MB 並需要網路；orchestrator 會在合併前另行決定是否實跑。）

- [ ] **Step 9: Commit**

```bash
git add -u scripts requirements-offline.txt requirements-offline.lock vendor tests
git commit -m "build: stop producing the Windows offline bundle

Drops the PBS Windows download, the NSSM vendoring, and the two
Windows-only wheels; the lock is regenerated from the trimmed spec
rather than hand-edited, so the build's freshness gate still agrees."
```

---

### Task 5: 文件、CHANGELOG、詞彙表與殘留文案

**Files:**
- Modify: `docs/guide/installation.md`（正文）
- Modify: `docs/guide/troubleshooting.md`
- Modify: `docs/guide/configuration.md`
- Modify: `docs/INDEX.md`
- Modify: `docs/reference/glossary.md`
- Modify: `README_zh.md`
- Modify: `illumio-ops.py:61`
- Modify: `design/v2/mockup/i18n-supplement.json:2656-2657`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 3 已從 frontmatter 移除 ps1；Task 4 已移除 Windows bundle
- Produces: 無

- [ ] **Step 1: `installation.md` 正文**

移除 Windows 安裝章節（`:132-161` 一帶共 35 行命中）：`preflight.ps1` /
`install.ps1` 的執行範例、Windows 10 / Server 2019+ 的前置檢查說明、
`C:\illumio-ops` 路徑、`-InstallRoot` 參數、`deploy/install_service.ps1` 的表格列、
NSSM 服務註冊說明、以及提到 Windows bundle 自動取用 NSSM 的段落。

**保留**所有 Linux 內容。把 frontmatter 的 `last_verified` 更新為 `2026-08-25`。

- [ ] **Step 2: 其餘文件的單點命中**

逐檔處理（每檔 1-2 行）：`troubleshooting.md`、`configuration.md`、`INDEX.md`、`README_zh.md`。
**先逐一分類是 host 還是 workload**，只改 host。

- [ ] **Step 3: `glossary.md` 的 NSSM 詞條**

移除該詞條。移除後必須過詞彙表閘門（見 Step 7）——若詞彙表閘門要求
文件中出現的每個術語都有詞條，確認移除後沒有任何文件還提到 NSSM。

- [ ] **Step 4: `illumio-ops.py:61`**

該行說明文字提到 `journal 與 NSSM 的 logs/service_stderr.log`。
改寫為只提 journal。

- [ ] **Step 5: mockup 文案**

`design/v2/mockup/i18n-supplement.json:2656-2657` 的 zh/en 兩句
提到「systemd／NSSM」/「systemd, NSSM…」。改為只提 systemd（spec §3.5）。
**兩句都要改，且 zh 與 en 的語意必須一致。**

- [ ] **Step 6: CHANGELOG**

在 `## [Unreleased]` 的 `### Removed` 新增條目（英文，本 repo 慣例）。
必須包含一句明說**這不影響管理 Windows workload**（spec §3.2）——理由不是
相容性，是避免讀者把「不再支援 Windows」誤讀成「不能管 Windows 主機了」。

**不得改動任何既有版本的條目。**

- [ ] **Step 7: 跑所有文件與 i18n 閘門**

```bash
python3 scripts/docs_check.py
python3 scripts/check_doc_links.py
timeout 300 python3 -m pytest tests/test_docs_check.py tests/test_docs_contracts.py -q
timeout 300 python3 -m pytest tests/ -q -k "glossary"
python3 scripts/audit_i18n_usage.py
python3 scripts/precompute_zh_translations.py --dry-run
```

預期：文件閘門全過；glossary 測試全綠；i18n audit `Total: 0 finding(s)`；
`precompute --dry-run` 回報 `would update 0 keys`（本 task 不新增 i18n 鍵）。

- [ ] **Step 8: Commit**

```bash
git add -u docs README_zh.md illumio-ops.py design/v2/mockup/i18n-supplement.json CHANGELOG.md
git commit -m "docs: drop the Windows host installation path

The CHANGELOG entry says explicitly that managing Windows workloads is
unaffected -- read alone, 'Windows is no longer supported' invites
exactly the wrong reading of a tool whose job includes segmenting
Windows servers."
```

---

### Task 6: 雙向守門與突變驗證

**Files:**
- Create: `tests/test_windows_host_removed.py`

**Interfaces:**
- Consumes: Task 1-5 的全部移除
- Produces: 無

守門必須是**雙向**的：一條確保 host 支援真的移除了，一條確保 **workload**
支援沒有被連帶誤刪。本案最可能的失誤正是後者。

- [ ] **Step 1: 寫移除守門**

```python
"""Windows 曾經是本工具的執行平台之一；2026-08-25 起不再是。

這兩組守門是雙向的：上半確保 host 支援真的移除乾淨，下半確保移除的過程
沒有連帶砍掉「管理 Windows workload」的能力——那是本工具的核心用途之一，
而且用 grep 掃 "windows" 會同時命中兩類。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_powershell_files_remain():
    found = sorted(p.relative_to(ROOT).as_posix()
                   for p in ROOT.rglob("*.ps1")
                   if ".git" not in p.parts)
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
```

- [ ] **Step 2: 寫反向守門**

七層白名單的 `windows_service_name` **已經由 `tests/test_filter_key_chain_invariants.py`
守著**（`:38`、`:106`）——不要重複造一個。新守門只補它沒蓋到的面：

```python
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
```

- [ ] **Step 3: 確認既有的白名單守門仍然綠**

```bash
timeout 300 python3 -m pytest tests/test_filter_key_chain_invariants.py tests/test_filter_process_winservice.py tests/test_estate_inventory.py -q
```

預期：全綠。這三個檔案本案**一行都不該改**；若它們紅了，代表 workload
支援被誤刪，停下來回報。

- [ ] **Step 4: 跑守門**

```bash
timeout 300 python3 -m pytest tests/test_windows_host_removed.py -q -v
```

預期：全綠。

- [ ] **Step 5: 突變驗證——移除守門必須會紅**

閘門回報 0 不代表它有在看。**實測**：

```bash
printf '# mutation probe\n' > scripts/_probe.ps1
timeout 120 python3 -m pytest tests/test_windows_host_removed.py -q -k "powershell"
rm scripts/_probe.ps1
```

預期：**FAILED**（`test_no_powershell_files_remain`）。若是綠的，守門是壞的，
停下來修好再繼續。清理後再跑一次，確認回綠。

- [ ] **Step 6: 突變驗證——反向守門必須會紅**

```bash
# 用 sed 暫時把白名單中的 windows_service_name 改名，確認反向守門變紅
```

在實際檔案上做**可逆**的暫時改動（用 `cp` 備份原檔，驗證後 `cp` 還原，
**不要用 `git checkout --`**——本 session 已有子代理用它毀掉自己未提交的工作）：

```bash
cp src/report/analysis/estate_inventory.py /tmp/ei.bak
sed -i 's/return "Windows"/return "Redacted"/' src/report/analysis/estate_inventory.py
timeout 120 python3 -m pytest tests/test_windows_host_removed.py -q -k "estate_inventory"
cp /tmp/ei.bak src/report/analysis/estate_inventory.py
```

預期：**FAILED**。還原後再跑一次確認回綠。**兩次輸出都要附在報告裡。**

- [ ] **Step 7: Commit**

```bash
git add tests/test_windows_host_removed.py
git commit -m "test: gate the Windows host removal in both directions

The forward gate catches a reintroduced installer. The reverse gate
catches the likelier mistake: grepping 'windows' and deleting the
workload-management support along with the host support. Both were
verified by mutation, not by reading green."
```

---

## 收尾（orchestrator 執行，不是 task）

- [ ] 全套：`timeout 2400 python3 -m pytest tests/ -q`
- [ ] 六道 CI 硬閘門：`pip-audit`、`check_no_naive_datetime`、`check_doc_links`、`audit_i18n_usage`、`mypy`（三個 entry 檔）、`pytest`
- [ ] 詞彙表閘門
- [ ] `precompute_zh_translations.py --dry-run` → `would update 0 keys`
- [ ] 確認 `git status` 乾淨、主 checkout 未被污染
- [ ] 合 main → push → `gh run watch` → 部署測試機
