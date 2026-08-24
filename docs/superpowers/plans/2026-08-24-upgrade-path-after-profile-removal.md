# 升級路徑：PCE profile 移除之後 — 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓升級腳本在既有安裝可能已被兩台 PCE 的資料污染時明確告知操作者，並提供一條真的會清乾淨的指令。

**Architecture:** 三個部分。(1) 新增 `illumio-ops cache flush` CLI 命令——`flush_pce_derived_state` 目前只能經由「換 PCE」或 GUI 觸發，操作者若要留在同一台 PCE 清資料無路可走。(2) `install.sh` 新增一個**具名 shell 函式**做污染偵測（具名是為了可被 `tests/test_install_migration.sh` 既有的 `source <(sed -n ...)` 手法單獨測試），並把 `archive_review_max_days` 加進既有的 deprecated 欄位遷移。(3) `install.ps1` 補上等價實作——Windows 端目前**完全沒有** deprecated 欄位遷移，是既有 parity 缺口。

**Tech Stack:** bash、PowerShell、Python 3.12、click、pytest

**Spec:** `docs/superpowers/specs/2026-08-24-upgrade-path-after-profile-removal-design.md`

## Global Constraints

- **判準是「`pce_profiles` 有兩個以上相異的 (url, org_id)」**，不是「active 與 `api` 不一致」。舊版 `activate_pce_profile()` 切換時會把值複製進 `api`，兩者在真實情境下必然一致。
- **URL/org 比較一律用 `src/pce_target.py` 的 `normalize_pce_url` / `normalize_org_id`**，不得自行實作字串比對，也不得修改這兩個函式的語意（CLI 與 GUI 的 target-change guard 共用它們）。
- **腳本不得刪除 `pce_profiles` / `active_pce_id`**：那是其他 profile 憑證的唯一副本。只有 `archive_review_max_days` 可以刪。
- **腳本不自動沖洗 cache、不自動刪任何資料檔**，只偵測與提示。升級的 exit code 不因偵測結果改變。
- **提示的指令一律用 `illumio-ops` wrapper 並以 `sudo -u illumio-ops` 執行**，不得寫裸的 `python -c`（會 `ModuleNotFoundError`，且相對的 `data/`、`logs/` 路徑會操作到錯誤位置）。
- 新的使用者可見文案進三份字典（`src/i18n_zh_TW.json`、`src/i18n_en.json`、`src/i18n/data/zh_explicit.json`），不得提及端點、狀態碼或內部欄位名。
- 前景執行測試並帶 timeout。

---

### Task 1: `illumio-ops cache flush` 命令

**Files:**
- Modify: `src/cli/cache.py`（`cache_group` 於 `:58`，既有命令 `backfill`/`status`/`retention`）
- Modify: 三份 i18n 字典
- Test: `tests/test_cli_cache.py`（若不存在則新建；先 `ls tests/ | grep cache` 確認）

**Interfaces:**
- Consumes: `src.pce_cache.flush.flush_pce_derived_state(db_path, state_path)`、`src.config.resolve_state_file`
- Produces: `cache flush` 子命令；Task 2/3 的提示文字引用它

- [ ] **Step 1: 寫失敗測試**

照該測試檔既有的 CliRunner 慣例（先讀檔；若新建則比照 `tests/test_cli_*.py` 最近的一個）。要涵蓋：

- 不帶 `--confirm` 時：**不呼叫** `flush_pce_derived_state`，回非零 exit code，訊息說明需要確認
- 帶 `--confirm` 時：呼叫一次，參數為 `cm.models.pce_cache.db_path` 與 `resolve_state_file()` 的回傳值
- 帶 `--confirm --json` 時：stdout 是可解析的 JSON，內含各表清除筆數
- `flush_pce_derived_state` 拋 `TimeoutError`（分析鎖等不到）時：回非零 exit code 且訊息可辨識，不得吞掉

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_cli_cache.py -q -p no:randomly`
Expected: FAIL — `cache flush` 命令不存在

- [ ] **Step 3: 實作**

在 `src/cli/cache.py` 的 `cache_retention` 之後加入。比照同檔既有命令的 `@click.pass_context`、`is_json(ctx)`、`echo_json`、`echo_error`、`ctx.exit(EXIT_*)` 用法：

```python
@cache_group.command("flush")
@click.option("--confirm", is_flag=True, default=False,
              help="Required. Clears every cached PCE row and the PCE-derived state.")
@click.option("--json", "json_output", is_flag=True, default=False,
              help="Emit the per-table counts as JSON.")
@click.pass_context
def cache_flush(ctx: click.Context, confirm: bool, json_output: bool):
    """Clear the cached PCE data and the state derived from it.

    For an appliance whose cache accumulated rows from more than one PCE:
    `config login --pce-target-change flush` only clears when the PCE also
    changes, so staying on the current PCE needs this instead.
    """
    if not confirm:
        echo_error(ctx, t("cli_cache_flush_needs_confirm"))
        ctx.exit(EXIT_USAGE)
        return
    from src.config import ConfigManager, resolve_state_file
    from src.pce_cache.flush import flush_pce_derived_state
    cm = ConfigManager()
    try:
        counts = flush_pce_derived_state(cm.models.pce_cache.db_path, resolve_state_file())
    except TimeoutError as exc:
        echo_error(ctx, t("cli_cache_flush_busy", error=str(exc)[:200]))
        ctx.exit(EXIT_UNAVAILABLE)
        return
    if json_output or is_json(ctx):
        echo_json(ctx, counts)
    elif not is_quiet(ctx):
        table = Table(t("cli_cache_col_setting"), t("cli_cache_col_rows_deleted"))
        for key, val in sorted(counts.items()):
            table.add_row(key, str(val))
        console.print(table)
        click.echo(t("cli_cache_flush_restart_required"))
```

**實作前先確認**：`EXIT_USAGE` / `EXIT_UNAVAILABLE` 是否已在該檔 import（`grep -n "EXIT_" src/cli/cache.py`），`Table`/`console`/`is_quiet` 同理。缺的補進既有 import 行，不要新開一組。

新 i18n 鍵（三份字典）：`cli_cache_flush_needs_confirm`、`cli_cache_flush_busy`（帶 `{error}`）、`cli_cache_flush_restart_required`。文案要說明「執行中的服務會沿用舊連線並把剛清掉的資料填回來，必須重啟」——比照 `cli_config_login_pce_restart_required` 的既有措辭。

- [ ] **Step 4: 測試通過**

```bash
timeout 600 ./venv/bin/python -m pytest tests/test_cli_cache.py -q -p no:randomly
timeout 300 ./venv/bin/python -m pytest tests/test_i18n_no_reviewer_copy.py tests/test_i18n_zh_explicit_sync.py -q
timeout 300 ./venv/bin/python scripts/audit_i18n_usage.py
```

- [ ] **Step 5: Commit**

```bash
git add src/cli/cache.py src/i18n_zh_TW.json src/i18n_en.json src/i18n/data/zh_explicit.json tests/test_cli_cache.py
git commit -m "feat(cli): add cache flush for an appliance staying on the same PCE"
```

---

### Task 2: `install.sh` 的偵測函式與遷移擴充

**Files:**
- Modify: `scripts/install.sh`（deprecated 遷移區塊於 `:229-247`；既有具名函式 `migrate_from_underscore_root()` 於 `:23`）
- Test: `tests/test_install_migration.sh`（既有；用 `source <(sed -n '/^fn()/,/^}/p')` 抽單一函式測試）

**Interfaces:**
- Consumes: Task 1 的 `cache flush` 命令名（出現在提示文字裡）
- Produces: `check_pce_profile_contamination()` 具名函式；Task 4 的 parity 守門比對其鍵集合

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_install_migration.sh` 末尾加測試。**先讀該檔前 45 行**，照它既有的 `source <(sed -n ...)`、`mktemp -d`、PATH stub 慣例寫。四個情境：

- config 有兩個相異 (url, org) 的 profile → 輸出含警告關鍵字、含兩個 url、含 `cache flush`、含 `sudo -u illumio-ops`；**exit code 為 0**
- config 只有一個 profile → 輸出為單行提示，**不含**警告關鍵字
- config 無 `pce_profiles` 且無標記檔 → 輸出「判定不了」的提示
- 兩個 profile 的 url 只差尾端斜線 → 視為**同一台**，走單一 profile 那條路徑

每個情境跑完都斷言標記檔 `config/.pce-profile-migration.json` 已建立且可被 `python3 -m json.tool` 解析。

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 300 bash tests/test_install_migration.sh`
Expected: FAIL — `check_pce_profile_contamination` 無法從 `install.sh` source 出來

- [ ] **Step 3: 實作**

在 `install.sh` 的 `migrate_from_underscore_root()` 之後加入具名函式（**必須具名且自足**，否則不可測）：

```bash
# Warn when this appliance's cache may hold rows from more than one PCE.
# Named + self-contained so tests/test_install_migration.sh can source just
# this function, the same way it sources migrate_from_underscore_root.
# $1 = INSTALL_ROOT, $2 = python interpreter
check_pce_profile_contamination() {
    local root="$1" py="$2"
    [ -f "$root/config/config.json" ] || return 0
    "$py" - "$root" <<'PYEOF'
import json, os, sys, datetime
root = sys.argv[1]
cfg_path = os.path.join(root, "config", "config.json")
marker_path = os.path.join(root, "config", ".pce-profile-migration.json")
sys.path.insert(0, root)
try:
    from src.pce_target import normalize_pce_url, normalize_org_id
except Exception:
    def normalize_pce_url(v): return str(v or "").rstrip("/")
    def normalize_org_id(v): return str(v or "1")
try:
    with open(cfg_path) as fh:
        cfg = json.load(fh)
except Exception as exc:
    print("    PCE profile check skipped (config unreadable): %s" % exc)
    sys.exit(0)

profiles = cfg.get("pce_profiles")
targets = set()
if isinstance(profiles, list):
    for p in profiles:
        if isinstance(p, dict):
            targets.add((normalize_pce_url(p.get("url")), normalize_org_id(p.get("org_id"))))

if profiles is None and os.path.exists(marker_path):
    sys.exit(0)                      # 先前已檢查過且無風險
if profiles is None:
    print("    NOTE: PCE profiles were removed in a newer version. This config no")
    print("          longer carries them, so whether this appliance ever switched")
    print("          PCEs cannot be determined here. If it did, its cache may hold")
    print("          rows from both. Check with: illumio-ops cache status")
else:
    api_t = (normalize_pce_url(cfg.get("api", {}).get("url")),
             normalize_org_id(cfg.get("api", {}).get("org_id")))
    if len(targets) > 1:
        print("")
        print("    ============================================================")
        print("    WARNING: this appliance was configured with more than one PCE.")
        print("    Switching between them did NOT clear the cache, so the cached")
        print("    traffic, events and ingestion positions may hold rows from")
        print("    both, with nothing marking which came from which. Reports,")
        print("    alerts and searches built on that cache span both environments.")
        print("")
        print("    PCEs found in this config:")
        for url, org in sorted(targets):
            mark = "  <- api currently points here" if (url, org) == api_t else ""
            print("      %s (org %s)%s" % (url, org, mark))
        print("")
        print("    To keep the current PCE and clear what the others left behind:")
        print("      sudo systemctl stop illumio-ops")
        print("      sudo -u illumio-ops illumio-ops cache flush --confirm")
        print("      sudo systemctl start illumio-ops")
        print("")
        print("    To move to a different PCE instead (clears as part of the switch):")
        print("      sudo systemctl stop illumio-ops")
        print("      sudo -u illumio-ops illumio-ops config login \\")
        print("          --url <PCE URL> --org-id <org> --pce-target-change flush")
        print("      sudo systemctl start illumio-ops")
        print("")
        print("    Archive day files may span both PCEs too; clearing the cache")
        print("    does not touch them. To start a clean archive, MOVE (do not")
        print("    delete) the existing archive directory aside — the PCE keeps")
        print("    only about three months, so older archives have no other copy.")
        print("")
        print("    The other profiles' API credentials are still in config.json")
        print("    under 'pce_profiles' and stay there until the next save.")
        print("    ============================================================")
        print("")
    else:
        print("    NOTE: PCE profiles were removed in a newer version; the stored")
        print("          credentials stay in config.json until the next save.")

review_db = os.path.join(root, "data", "archive_review.sqlite")
if os.path.exists(review_db):
    mb = os.path.getsize(review_db) / (1024 * 1024)
    print("    NOTE: %s (%.1f MB) is no longer read by any code and can be deleted."
          % (review_db, mb))

try:
    with open(marker_path, "w") as fh:
        json.dump({"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "distinct_pce_targets": len(targets)}, fh, indent=2)
except Exception:
    pass
PYEOF
    return 0
}
```

在既有 deprecated 遷移區塊（`:229`）的 `changed` 判斷中，把 `archive_review_max_days` 加進去（`pce_profiles`/`active_pce_id` **不加**）：

```python
    pc = cfg.get('pce_cache', {})
    if 'archive_review_max_days' in pc:
        del pc['archive_review_max_days']
        changed.append('pce_cache.archive_review_max_days')
```

並在該區塊之後、post-install verification 之前呼叫：

```bash
if [ "$IS_UPGRADE" = true ]; then
    check_pce_profile_contamination "$INSTALL_ROOT" "$INSTALL_ROOT/python/bin/python3"
fi
```

- [ ] **Step 4: 測試通過**

```bash
timeout 300 bash tests/test_install_migration.sh
timeout 600 ./venv/bin/python -m pytest tests/test_install_lifecycle_contract.py -q -p no:randomly
```

- [ ] **Step 5: Commit**

```bash
git add scripts/install.sh tests/test_install_migration.sh
git commit -m "feat(install): warn on upgrade when the cache may span two PCEs"
```

---

### Task 3: `install.ps1` parity

**Files:**
- Modify: `scripts/install.ps1`（`$IsUpgrade` 於 `:241`，升級守門區塊 `:244-303`）
- Test: `tests/test_windows_install_contract.py`（既有；以原始碼子字串斷言，見 `test_install_ps1_has_upgrade_guards`）

**Interfaces:**
- Consumes: Task 2 的行為（同一份判準與同一組輸出元素）
- Produces: Task 4 的 parity 守門比對其鍵集合

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_windows_install_contract.py` 加測試，照該檔既有 `test_install_ps1_has_upgrade_guards` 的子字串斷言風格：`install.ps1` 必須含 `archive_review_max_days`、`http_redirect_port`、`pce_profiles`、`cache flush --confirm`、`.pce-profile-migration.json`。

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 300 ./venv/bin/python -m pytest tests/test_windows_install_contract.py -q -p no:randomly`
Expected: FAIL — 這些字串都不在 `install.ps1` 裡

- [ ] **Step 3: 實作**

在 `$IsUpgrade` 區塊內加入：(a) deprecated 欄位遷移（Windows 端目前**完全沒有**，要同時涵蓋 `web_gui.tls.http_redirect_port` 與 `pce_cache.archive_review_max_days`）；(b) Task 2 那段偵測。兩者都以 `& $BundlePy -c` 執行（比照 `:286` 讀 `PRAGMA user_version` 的既有寫法）。

提示指令改為 Windows 形式：服務以 NSSM 管理，停/起用 `nssm stop IllumioOps` / `nssm start IllumioOps`；CLI 以 bundle 內的 python 執行並先 `Set-Location $InstallRoot`（Windows 沒有 `/usr/local/bin` wrapper——**這一點與 Linux 不同，不可照抄**）。

- [ ] **Step 4: 測試通過**

```bash
timeout 300 ./venv/bin/python -m pytest tests/test_windows_install_contract.py tests/test_packaging_security_contract.py -q -p no:randomly
```

- [ ] **Step 5: Commit**

```bash
git add scripts/install.ps1 tests/test_windows_install_contract.py
git commit -m "feat(install): bring the Windows installer's config migration to parity"
```

---

### Task 4: parity 守門與文件

**Files:**
- Test: `tests/test_windows_install_contract.py`（新增守門）
- Modify: `docs/guide/configuration.md`、`docs/reference/cli.md`、`CHANGELOG.md`

**Interfaces:**
- Consumes: Task 2、3 的兩支腳本

- [ ] **Step 1: 寫失敗測試**

守門：兩支腳本處理的 deprecated 設定鍵集合必須**相等**。用集合相等而非子字串——子字串通過不代表兩邊一致，那正是 parity 漂移的成因。

```python
_DEPRECATED_KEYS = {"http_redirect_port", "archive_review_max_days"}

def _keys_in(path: str) -> set:
    src = (ROOT / path).read_text(encoding="utf-8")
    return {k for k in _DEPRECATED_KEYS if k in src}

def test_both_installers_migrate_the_same_deprecated_keys():
    sh, ps1 = _keys_in("scripts/install.sh"), _keys_in("scripts/install.ps1")
    assert sh == ps1 == _DEPRECATED_KEYS, {"install.sh": sh, "install.ps1": ps1}
```

**驗證這條守門能變紅**：暫時從其中一支腳本移除一個鍵，確認測試失敗並指名該腳本，再還原。RED 輸出留進報告。

- [ ] **Step 2: 跑測試確認**

Run: `timeout 300 ./venv/bin/python -m pytest tests/test_windows_install_contract.py -q -p no:randomly`

- [ ] **Step 3: 文件**

`docs/reference/cli.md` 的 `cache` 子命令表加入 `flush`（照該表既有列的格式）。`docs/guide/configuration.md` 說明升級時可能出現的污染警告與兩條處理路徑。`CHANGELOG.md` 的 `### Added` 記 `cache flush` 與升級偵測，照既有條目的散文語氣，說明它解決的是「切換 PCE 沒沖 cache」留下的歷史問題。

- [ ] **Step 4: 閘門通過**

```bash
timeout 300 ./venv/bin/python -m pytest tests/test_docs_check.py -q -p no:randomly
timeout 300 ./venv/bin/python scripts/docs_check.py --all
timeout 300 ./venv/bin/python scripts/check_doc_links.py
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_windows_install_contract.py docs/reference/cli.md docs/guide/configuration.md CHANGELOG.md
git commit -m "docs: record the upgrade contamination check and cache flush"
```

---

## 自我檢查（撰寫時已執行）

- **Spec 覆蓋**：§3.1 判準→T2/T3；§3.2 不刪憑證→T2 Step 3 明文；§3.3 `archive_review_max_days`→T2/T3；§3.4 孤兒檔→T2 的 `review_db` 區段；§4.1 四種情形→T2 Step 1 的四個情境；§4.2 兩種情境的指令→T2 Step 3 的輸出；§4.3 封存提示→同上；§4.5 Windows→T3；§5 測試→逐條對應。§4.2 的 `cache flush` 前置需求→T1。
- **符號查證**：`normalize_pce_url`/`normalize_org_id`/`pce_target_changed` 存在於 `src/pce_target.py:24,48,53`；`cache_group` 於 `src/cli/cache.py:58`；`flush_pce_derived_state` 於 `src/pce_cache/flush.py:78`；`migrate_from_underscore_root()` 是 `install.sh` 目前唯一的具名函式（`:23`）；`test_install_migration.sh` 的 source 手法見該檔 `:36`。
- **已知取捨**：偵測會對「裝了兩個 profile 但從未切過」的機器誤報。Spec §3.1 已裁定接受——警告不具破壞性，且腳本無從得知是否切過。
- **未驗證處**：`tests/test_cli_cache.py` 是否已存在未確認，T1 Step 1 已要求實作者先 `ls`。`install.ps1` 的 NSSM 服務名以 `:136` 的 `Invoke-NssmSet IllumioOps` 為準，T3 實作者需自行確認停/起指令的既有寫法。

## 本計畫不處理

- 自動沖洗、憑證搬移（Spec §6）
- 封存檔與 cache 列的 PCE 來源標記（Spec §6）
- 已安裝機器的既有污染清理——只保證升級時會被告知
