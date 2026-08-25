# 放棄 Windows 作為執行平台

> 狀態：設計待使用者審閱。
> 本檔所有對現況的描述皆已對原始碼查證；行號會漂移，以符號為準。

## 1. 要解決什麼

使用者 2026-08-25 裁決：**放棄 Windows 作為這支工具的執行平台**，採「直接移除，下個版本生效」。

觸發點是一個查證結果：Windows 端**唯一的自動化保護是兩個原始碼子字串比對的合約測試**
（`tests/test_windows_install_contract.py` 79 行、`tests/test_ps1_bom_contract.py`）——它們檢查
`install.ps1` 裡有沒有出現某些字串，**從來沒有真的執行過那支腳本**。CI 只跑 `ubuntu-22.04`，
沒有 Windows runner。

對照 Linux：`tests/test_install_migration.sh` 會實際 source 函式、以 PATH stub 攔截、跑真實情境。
2026-08-25 的升級路徑案就是靠它抓到「畸形 config 會中斷整支升級腳本」——**同一個 bug 在 Windows
端不會被抓到，因為那裡沒有等價的測試**。

歷史紀錄佐證這是慢性狀態：`2026-07-12-offline-bundle-db-hardening.md:37` 明寫「Windows 端 parity
列為 follow-up（本案目標環境為 Linux 離線機）」；`2026-08-07-phase2e-final-verification.md` 又得
專門排一個 task 補 parity。**每次都是「先做 Linux、Windows 之後補」，而補的品質只能靠子字串比對。**

## 2. 必須釘住的區分

**放棄的是「這支工具跑在 Windows 上」，不是「管理 Windows workload 的能力」。**

以下屬於後者，**一律不得移除**：

- `windows_service_name` / `ex_windows_service_name` 篩選鍵（七層白名單全鏈）
- `tests/test_filter_process_winservice.py`
- estate inventory 的 OS family 分類：`src/report/analysis/estate_inventory.py:18` 回傳 `"Windows"` 的那條分支
  （**注意：`by_family_windows` 是 `tests/test_estate_inventory.py:79` 的測試方法名，不是產品符號**——
  在 `src/` 裡 grep 它會一無所獲，別因此以為分類已不存在）
- 報表中的 Windows workload 統計、VEN OS 分佈
- 篩選鏈對 `windows_service_name` 的契約（`tests/test_filter_process_winservice.py:80`）
  （**初版誤寫成 `tests/test_cache_flatten_vectorized.py:80`；該檔完全沒有這個欄位**）

這些是客戶環境的真實需求：測試機 PCE 上就有 `win10-jd` 這台 Windows workload，其 flow 在
syslog 中可見。**用 grep 掃 "windows" 會同時命中兩類，這是本案最容易出錯的地方。**

## 3. 決策

### 3.1 全部移除，不保留

使用者確認：**目前沒有任何 Windows 部署**，因此不需考慮相容或保留。

> **本表於 2026-08-25 依原始碼逐面重新盤點後修訂。** 初版是照概念列的，漏了三個測試檔、
> 一支 preflight 腳本、`vendor/windows/`，以及一道會擋住 CI 的文件閘門。漏失原因與
> 2026-08-21 那次相同：用一個識別字 grep，而不是走過每個「表面」。下表按表面分組。

**A. 腳本與資產**

| 對象 | 規模 | 備註 |
|---|---|---|
| `scripts/install.ps1` | 450 行 | |
| `scripts/preflight.ps1` | 4.7 KB | **初版漏列**；Linux 對應 `preflight.sh` 保留 |
| `deploy/install_service.ps1` | 213 行 | NSSM 服務包裝 |
| `vendor/windows/nssm-2.24.zip` ＋ `README.md` | 二進位 vendor 目錄 | **初版漏列**；bundle 於 `build_offline_bundle.sh:284` 由此解出 `nssm.exe` |

**B. 打包**

| 對象 | 備註 |
|---|---|
| `build_offline_bundle.sh` 的 `build_windows()`、`PBS_WIN_URL`、`PBS_SHA256_WIN_X86_64`、`slim_python … windows` 分支 | 26 處 |
| `*-offline-windows-x86_64.zip` 產物 | |
| `requirements-offline.txt:73-78`（`colorama`、`win32-setctime` ＋ 其上的說明段） | |
| `requirements-offline.lock:268,1507` | 鎖檔由 txt 衍生，**必須重產而非手改**；重產後 `test_offline_lock_records_the_sha256_of_its_source_spec` 的 marker 才會對上 |
| `rsync -a "$REPO_ROOT/scripts/"`（`:137`）目前把 `*.ps1` 一併塞進 **Linux** bundle | 移除 ps1 後 Linux bundle 內容會變，屬預期 |

**C. 原始碼**

| 對象 | 備註 |
|---|---|
| `src/file_lock.py` 的 `msvcrt` 分支（`:44,46,64-65,104-111,122-125`） | `has_os_backend()` 簡化為 `_fcntl is not None` |
| `src/file_lock.py:12` 的 docstring：「本專案有 Windows 安裝路徑，兩邊都必須能跑」 | 該句在移除後為假，必須改寫 |
| CLI 的 `os.system("cls" if os.name == "nt" else "clear")` | **12 處、9 檔**（初版列 9 檔正確，處數為 12：`report_schedule.py` 與 `web_gui.py` 各有多處）|
| `illumio-ops.py:61` 說明文字提到 NSSM 的 `logs/service_stderr.log` | **初版漏列** |

**D. 測試**（初版只列 2 檔，實為 5 檔）

| 對象 | 備註 |
|---|---|
| `tests/test_windows_install_contract.py`（79 行） | 整檔刪除 |
| `tests/test_ps1_bom_contract.py` | 整檔刪除 |
| `tests/test_packaging_security_contract.py` 的 7 個 Windows 測試 | **初版漏列**：`:130,152,161,181,197,315` ＋ §2 標題；`test_install_sh_installs_the_lock_with_require_hashes` 等 Linux 測試**保留** |
| `tests/test_docs_contracts.py:130`（斷言 `preflight.ps1` 內含 `alerts.json`） | **初版漏列** |
| `tests/test_build_offline_bundle_doc.py:15` `test_vendor_windows_readme_exists` | **初版漏列**；隨 `vendor/windows/` 一起移除 |
| `tests/test_config_concurrency.py:414-449` msvcrt 群（AttributeError 的實際觸發點是 `:449`） | **初版漏列，且不是單純刪除**——見下方 §3.4 |

**E. 文件**

| 對象 | 備註 |
|---|---|
| `docs/guide/installation.md` | 35 行命中；**frontmatter `verified_against` 列有 3 支 ps1**，不同步更新 `docs_check` 會紅 |
| `docs/guide/troubleshooting.md`(2)、`configuration.md`(1)、`INDEX.md`(1)、`reference/glossary.md`(1，NSSM 詞條)、`README_zh.md`(1) | glossary 詞條移除須過 glossary 閘門 |
| `CHANGELOG.md` 的 `## [Unreleased] ### Removed` | 新增條目；**歷史條目（`:486-492` 等）不得改動** |

**初稿曾主張保留 `msvcrt` 守衛與 `cls` 分支**，理由是它們在 Linux 上 inert、且 `msvcrt` 的存在
說明了行程內 RLock 為何必要。重新檢視後**撤回該主張**：`file_lock.py` 的 RLock 在 POSIX 上本來
就必要（`flock` 是 per-(process, open-file-description)，擋不住同一行程的第二個 thread），該註解
的 POSIX 半段獨立成立，不需要靠 Windows 那半段撐著。既然唯一受支援的平台上那些程式碼是死的，
留著只是讓讀者以為還有第二個平台。

`has_os_backend()` 相應簡化為 `_fcntl is not None`。
### 3.4 `msvcrt` 測試群不是單純刪除

`tests/test_config_concurrency.py` 有兩個測試碰 `_msvcrt`：

- `:414 test_windows_msvcrt_branch_locks_and_unlocks` —— 只為讓 msvcrt 分支是活碼而存在，**整個刪除**。
- `:448 test_no_lock_backend_degrades_instead_of_crashing` —— 測的是「兩種 backend 都不可用時退化成
  行程內鎖」，這在純 POSIX 下**仍然要測**（`fcntl` 匯入失敗的機器存在）。但它用
  `monkeypatch.setattr(fl, "_msvcrt", None)` 把第二個 backend 關掉；`_msvcrt` 一旦從模組移除，
  `monkeypatch.setattr` 會直接 `AttributeError`。**必須在移除 `file_lock.py` 的 msvcrt 分支的同一個
  task 內改寫成只關 `_fcntl`**，否則整套測試在計畫中途變紅，而那個紅燈與任何真實缺陷無關。

### 3.5 兩個邊界的裁決

- **`tests/test_cli_signal.py:56` 的 `skipif(sys.platform == 'win32')`：保留。** 它描述的是 POSIX signal
  測試在非 POSIX 上該跳過，是測試本身的可攜性條件，不是產品的 Windows 支援。刪掉沒有好處，
  且會讓任何人在非 Linux 開發機上跑測試時吃到一個無關的失敗。
- **所有提到「systemd／NSSM」的文案：改寫為只提 systemd。** 這條初版只裁決了 mockup，
  但第二輪盤點發現**正式產品的字典裡就有同一句**，而且那才是使用者現在看得到的：
  - `src/i18n_en.json:5098` 與 `src/i18n_zh_TW.json:5097` 的 `gui_sy_restart_i_409`
    （以及 `src/i18n/data/zh_explicit.json` 的對應條目——三本字典必須同步）
  - `src/static/js/v2/areas/system.mjs:1002` 的註解
  - `design/v2/mockup/i18n-supplement.json:2656-2657`

  只改 mockup 而不改 live catalog 不會讓任何閘門變紅，卻會讓產品繼續顯示 NSSM。
  **鍵名 `gui_sy_restart_i_409` 不得更動**，只改值。

### 3.2 CHANGELOG 仍要明說，但不需遷移指引

使用者確認目前無 Windows 部署，故**不需要**為既有使用者提供搬移步驟。

`CHANGELOG.md` 的 `### Removed` 仍須記載，且必須包含一句：**這不影響管理 Windows workload**。
理由不是相容性，是**避免讀者誤解**——「不再支援 Windows」這句話單獨出現時，最自然的誤讀就是
「連 Windows 主機都不能管了」，而那正好是這個工具的核心用途之一。

### 3.3 版本號

移除受支援平台是 breaking change。版本號調整不在本案決定，但 CHANGELOG 條目須放在能讓
版本決策者看見的位置（`## [Unreleased]` 的 `### Removed`）。

## 3.6 第二輪盤點（Codex 對抗式掃描，2026-08-25）

第一輪修訂後又派了一次獨立掃描，明確要求「用你自己的搜尋策略，不要跟著 spec 的」。
它再找出 15 個漏面，逐條查證後**全部屬實**。這是同一個失效模式的第三次證據：
按概念列表無法窮舉，只有逐面掃描可以。

**F. 真的是分支或設定的（要改行為或設定）**

| 對象 | 性質 |
|---|---|
| `scripts/check_doc_coverage.sh:31-32` | **閘門**：明文要求 installation guide 必須提到 `preflight.ps1`、`install.ps1`。清掉文件卻不改它，這道 gate 會紅 |
| `tests/test_packaging_security_contract.py:330` | `for fn in ("build_linux", "build_windows")` ——**必須改寫，不能刪**，否則 `_extract_fn` 找不到函式 |
| `docs/guide/installation.md:34` | OS 需求表格的**同一列**同時寫著 Linux glibc 下限與 Windows 版本；`test_installation_doc_states_the_same_glibc_floor` 斷言那一列。**整列刪掉會誤傷 Linux 閘門**，只能改該列的 Windows 部分 |
| `src/file_lock.py:158-160` | `if os.fstat(fd).st_size == 0: os.write(fd, b"0")` ——寫入 placeholder byte，註解寫明是給 Windows byte-range lock 用的。已實測 POSIX `flock` 對零長度檔完全可用，因此**連同寫入一起移除**；代價若判斷錯，只是鎖檔變成零長度，`flock` 行為不變 |
| `scripts/build_offline_bundle.sh:300` | 收尾的 `ls ... *.{tar.gz,zip}` glob |
| `docs/handover/development.md:312` | **現行**開發文件宣告同時產出 Linux tar.gz 與 Windows zip，不是歷史文件 |

**G. 只是註解／文案（功能保留，理由改寫）**

| 對象 | 保留什麼 |
|---|---|
| `src/cli/_runtime.py:70` | `except (AttributeError, ValueError)` 仍然正確（非主執行緒會拋 ValueError），只改註解 |
| `src/config.py:515` 「On Windows, os.replace handles atomic rename」 | `os.replace` 在 POSIX 上同樣是原子的，程式碼不動，註解改寫或刪除 |
| `src/gui/_helpers.py:801` 「hosts without the openssl CLI (e.g. Windows service installs)」 | openssl fallback 仍要保留（沒裝 openssl CLI 的 Linux 主機是存在的），只改舉例 |
| `src/alerts/plugins.py:41` 「ASCII marker … for cross-platform (Windows console) safety」 | ASCII marker 保留，理由改寫 |
| `.gitignore:95-97` | 忽略規則保留，說明中的 Windows byte-range lock 理由改寫 |
| `src/file_lock.py:25`、`:51-53` | docstring 與 registry 註解中的 Windows 半句 |
| `tests/test_config_concurrency.py:100,125,185` | skip 訊息 `"no OS-level lock backend (fcntl/msvcrt)"` 與 byte-range 註解 |
| `scripts/build_offline_bundle.sh:2,139` | 檔頭雙平台宣告、共用 staging 段落提到 `install.ps1` 的註解 |
| `requirements-offline.txt:6,21-23,27,71` | 檔頭的 `install.ps1`、Windows wheel download 範例、Windows-only section 指涉 |

**H. 本機產物（未進版控，只需本機清理）**

`dist/illumio-ops-*-offline-windows-x86_64.zip`（約 83 MB）與
`build/illumio-ops-*-offline-windows-x86_64/` staging tree。兩者都在 `.gitignore` 內，
不影響任何 commit，但留著會讓下一個人以為 Windows bundle 還在產。

**Codex 有一條說錯：** 它稱 `docs_check` 目前有 11 個既存問題。實測
`python3 scripts/docs_check.py` 回 `OK — no issues`；要帶 `--frontmatter` 才會顯示
既存的 6 條 dangling 路徑（都指向早已移除的 JS 檔，與本案無關），而且**該腳本無論如何都 exit 0**。
它也不在 CI workflow 裡——CI 只跑 `check_doc_links.py`。所以「docs_check 會擋住 CI」是錯的，
但「frontmatter 必須同步」仍然成立（否則會多出三條 dangling）。

## 4. 設計

### 4.1 移除順序

先移除**引用者**，最後移除**被引用者**——與本 repo 移除 PCE profile 時同一條紀律：

1. 測試（`test_windows_install_contract.py`、`test_ps1_bom_contract.py`）
2. 打包腳本的 Windows 分支與產物
3. `requirements-offline.txt` 的 Windows-only wheels ＋ 重新產生 lock（若該檔由 lock 衍生）
4. `scripts/install.ps1`、`deploy/install_service.ps1`
5. 文件
6. CHANGELOG

### 4.2 守門測試

新增一條移除守門，比照本 repo 既有的命名守門寫法（`tests/test_config_models.py:131` 用集合相等
而非子字串）：

- `install.ps1` / `install_service.ps1` **不存在**
- `scripts/build_offline_bundle.sh` 不含 Windows 產物名稱、不含 `PBS_WIN_URL`
- `requirements-offline.txt` 不含 `colorama` / `win32-setctime`

**同時必須有一條「反向守門」**，確保 Windows **workload** 支援未被誤刪：
estate inventory 的 `"Windows"` family 分支仍在、i18n 的 workload 文案仍在。
**七層白名單的 `windows_service_name` 已由既有的 `tests/test_filter_key_chain_invariants.py` 守著**
（`:38`、`:106`），不要重複造一個——新守門只補它沒蓋到的面。
本案最可能的失誤是連帶刪掉這些，守門要能抓到。

### 4.3 不動的東西

- `docs/` 中描述 Windows **workload** 的段落
- `requirements.lock` 中同時被 Linux 使用的套件（**本 repo 沒有 `pyproject.toml`**，初版誤列）
- **歷史紀錄一律不動**：`docs/superpowers/plans/` 與 `specs/` 下的既有文件、
  `docs/_meta/migration-audit.json`、`CHANGELOG.md` 既有版本的條目、
  `reports/audit/` 下的稽核產物。它們記載的是當時為真的事，不是現況宣告。
  實作者最常在此處「順手修正」——明文禁止。
- `tests/test_cli_signal.py:56` 的 `skipif`（見 §3.5）

## 5. 測試

- §4.2 的移除守門與反向守門，各自以**集合相等**斷言
- **突變驗證**：把 `install.ps1` 放回去，移除守門必須變紅；把 `windows_service_name` 從白名單移除，
  反向守門必須變紅。兩條都要實測，不可只寫測試
- `scripts/build_offline_bundle.sh` 移除 Windows 分支後仍能產出 Linux bundle（既有的
  `tests/test_build_offline_bundle_doc.py` 需檢查是否仍適用）
- 全套 ＋ CI 六道硬閘門

## 6. 本設計不處理

- **Windows workload 的管理能力**：完全不動（見 §2）
- **版本號決定**：由使用者依 CHANGELOG 裁決
- **既有 Windows 部署的遷移**：使用者確認無此類部署，不處理
