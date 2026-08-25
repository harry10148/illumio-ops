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
- estate inventory 的 `by_family_windows` 與 `os_type` 分類（`tests/test_estate_inventory.py`）
- 報表中的 Windows workload 統計、VEN OS 分佈
- 快取攤平時保留的 `windows_service_name` 欄位（`tests/test_cache_flatten_vectorized.py:80`）

這些是客戶環境的真實需求：測試機 PCE 上就有 `win10-jd` 這台 Windows workload，其 flow 在
syslog 中可見。**用 grep 掃 "windows" 會同時命中兩類，這是本案最容易出錯的地方。**

## 3. 決策

### 3.1 全部移除，不保留

使用者確認：**目前沒有任何 Windows 部署**，因此不需考慮相容或保留。

| 對象 | 行數／規模 |
|---|---|
| `scripts/install.ps1` | 450 行 |
| `deploy/install_service.ps1` ＋ NSSM 服務包裝 | 213 行 |
| `tests/test_windows_install_contract.py`、`tests/test_ps1_bom_contract.py` | 79 ＋ 約 40 行 |
| `scripts/build_offline_bundle.sh` 的 Windows 分支與 `*-offline-windows-x86_64.zip` 產物 | 26 處 |
| Windows-only wheels（`colorama`、`win32-setctime`） | requirements-offline |
| `src/file_lock.py` 的 `msvcrt` 分支 | 約 6 行 |
| CLI 的 `os.system("cls" if os.name == "nt" else "clear")` | 9 檔 |
| `docs/guide/installation.md` 等的 Windows 安裝章節 | 6 份文件 |

**初稿曾主張保留 `msvcrt` 守衛與 `cls` 分支**，理由是它們在 Linux 上 inert、且 `msvcrt` 的存在
說明了行程內 RLock 為何必要。重新檢視後**撤回該主張**：`file_lock.py` 的 RLock 在 POSIX 上本來
就必要（`flock` 是 per-(process, open-file-description)，擋不住同一行程的第二個 thread），該註解
的 POSIX 半段獨立成立，不需要靠 Windows 那半段撐著。既然唯一受支援的平台上那些程式碼是死的，
留著只是讓讀者以為還有第二個平台。

`has_os_backend()` 相應簡化為 `_fcntl is not None`。
### 3.2 CHANGELOG 仍要明說，但不需遷移指引

使用者確認目前無 Windows 部署，故**不需要**為既有使用者提供搬移步驟。

`CHANGELOG.md` 的 `### Removed` 仍須記載，且必須包含一句：**這不影響管理 Windows workload**。
理由不是相容性，是**避免讀者誤解**——「不再支援 Windows」這句話單獨出現時，最自然的誤讀就是
「連 Windows 主機都不能管了」，而那正好是這個工具的核心用途之一。

### 3.3 版本號

移除受支援平台是 breaking change。版本號調整不在本案決定，但 CHANGELOG 條目須放在能讓
版本決策者看見的位置（`## [Unreleased]` 的 `### Removed`）。

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
`windows_service_name` 仍在七層白名單、`by_family_windows` 仍在 estate inventory。
本案最可能的失誤是連帶刪掉這些，守門要能抓到。

### 4.3 不動的東西

- `docs/` 中描述 Windows **workload** 的段落
- `pyproject.toml` / `requirements.lock` 中同時被 Linux 使用的套件

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
