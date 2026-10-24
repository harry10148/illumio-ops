# illumio-ops v6 P1 基礎骨架 Implementation Plan

> **For agentic workers:** 執行方式已定為 **Native**（使用者 2026-10-24 選定）：以 superpowers:executing-plans 逐任務實作；Task 6（安全機制）與 Task 12（遷移器）完成後各加一次 Codex 對抗式審查，P1 結束做一次全分支審查。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 v6 的可安裝骨架——分層套件、設定與狀態存放、PCE client、安全的 Web 層、型別化 API 契約、React 殼層——並以「系統 › PCE 連線＋健康檢查」打通第一個垂直切片，並排安裝到測試機 .106 實機驗證。

**Architecture:** 新套件 `illumio_ops/`（Python 3.12，單一行程：Flask＋APScheduler）與 `web/`（Vite＋React＋TypeScript，建置輸出到 `illumio_ops/web/static/`）。每個 API 的請求／回應以 pydantic 定義一次，匯出 JSON Schema 產生前端型別。舊 `src/`、`tests/`、`scripts/` 完全不動。

**Tech Stack:** Python 3.12、Flask 3、flask-login、flask-wtf、flask-limiter、flask-talisman、cheroot、pydantic 2、requests、argon2-cffi、cryptography、APScheduler 3、stdlib sqlite3、loguru；React、TypeScript、Vite（版本於 Task 8 釘死）；pytest、Playwright（Python）。

**Spec:** `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md`；路線圖 `docs/superpowers/plans/2026-10-24-v6-roadmap.md`。

## Global Constraints

- Python **3.12**（與離線 bundle 的 PBS CPython 3.12.7 同版）；依賴只有一份鎖檔 `requirements-v6.lock`（`pip-compile --generate-hashes`），CI 與 bundle 都用它。
- node 只在開發與建置時使用；bundle 只帶建置好的靜態檔。
- **舊 `src/`、`tests/`、`scripts/`、`.github/workflows/ci.yml`、`requirements*.txt|lock` 一行都不改。**
- 所有路徑由 `illumio_ops.paths.InstallPaths` 從單一根目錄推出；禁止 `os.getcwd()`／`Path.cwd()`／相對路徑字面值開檔。
- 每張 SQLite 表只有一個寫入模組（登錄於 `illumio_ops/store/ownership.py`）；不得新增任何共寫的 JSON 狀態檔。
- 失敗不得看起來像成功或空結果：不吞例外回 `[]`／`None`／預設值；設定載入失敗拒絕啟動。
- 值域只定義在 `illumio_ops/domain/values.py`，一律字串值，不用整數編碼。
- 憑證只存在設定檔（mode `0600`）；不得出現在 log、API 回應、畫面。
- `illumio_ops/` 內不得有 `print(`（`illumio_ops/rescue.py` 除外）。
- UI 文案：繁中與英文；畫面不印路由、設定鍵名、原始 JSON；視覺沿用 Direction D（`src/static/css/v2/tokens.css`）與 v3.1 IA（左側導覽、清單→詳情、每頁一顆主要動作）。
- Commit 訊息：英文 conventional commits；結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。只 `git add <明確路徑>`，不得 `git add -A`。
- 測試一律前景執行並加 timeout；本計畫的測試命令都可照抄。
- 每次 commit 後 `git status --porcelain illumio_ops tests_v6 web scripts/v6` 必須為空——本機有未追蹤的必要檔案時測試會綠、CI checkout 會紅。
- 「前端建置」一律指 `bash scripts/v6/gen_contracts.sh && npm --prefix web run typecheck && npm --prefix web run build`（Task 7 起；Task 8 前只有第一步有效）。
- 分支 `feat/v6-p1-foundation`，worktree `.worktrees/v6-p1`；每個任務開始前 `pwd && git branch --show-current` 確認在 worktree。

## Review Focus

1. **設定檔存在但不合法**（手改壞、寫到一半、缺欄位、多了未知鍵）：服務必須拒絕啟動並指出哪一欄，絕不回退預設值、絕不覆寫該檔（5.x 兩種錯都犯過）。→ Task 3 `test_load_invalid_never_writes`、`test_load_missing_field_is_invalid_not_defaulted`、`test_load_nested_unknown_key_is_invalid`、Task 11 `test_serve_refuses_invalid_settings`。
2. **憑證外洩或被佔位字串覆蓋**：GET 回應必須遮罩；PUT 帶空字串或遮罩字串時保留原值，不得把 `********` 存進檔案。→ Task 9 `test_put_masked_secret_keeps_existing`。
3. **允許 IP 把自己鎖在門外**：儲存的允許清單不含目前連線者 IP 時，必須拒絕（除非明確確認）。→ Task 13 `test_allowlist_excluding_requester_is_refused`。
4. **PCE 不可達／憑證錯／TLS 驗證失敗**時，健康檢查要分別說清楚是哪一種，而不是一個籠統錯誤或誤報正常。→ Task 5 `test_probe_categories`、Task 9 e2e。
5. **兩個分頁同時存設定**：後存的不能無聲蓋掉先存的。→ Task 3 `test_update_with_stale_revision_conflicts`、`test_failed_update_leaves_current_untouched`、Task 9 `test_put_stale_revision_returns_409`。

---

### Task 0: PCE 事實實測（NFR SaaS，無程式碼）

**Files:**
- Modify: `docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md`（§6.5 RHC 與唯讀角色兩段）
- Create: `tmp/v6-p1-verification/task0-pce-facts.md`（gitignored，紀錄過程）

- [ ] **Step 1：取得 NFR SaaS 憑證。** 依全域規則以 `ai-agent` service account 讀 1Password `Lab` vault（`op item list --vault Lab` 找 NFR 項目）；憑證只注入子行程，不印出。
- [ ] **Step 2：取得一把 Read Only 權限的 API key。** 先試以 API 建立唯讀 service account；若權限不足，**停下來請使用者在 PCE 主控台建立一個 Read Only 角色的 service account**，把 key 放進 1Password `Lab` vault 後告知項目名稱。
- [ ] **Step 3：用唯讀 key 實測三個 POST**：`POST /orgs/{org}/traffic_flows/async_queries`（最小查詢：最近 1 小時、max_results 10）、`POST /orgs/{org}/sec_policy/active/rule_search`（任一 label 條件）、`POST /orgs/{org}/reports`（`report_template.href` = rule_hit_count_report，最近 1 天）。記錄各自 HTTP 狀態與錯誤本文。
- [ ] **Step 4：實測 RHC 累計起點（依 spec §6.5 的防護執行，不得直接照搬 5.x 三步）。**
  1. `GET /orgs/{org}/sec_policy/active/firewall_settings`：`rule_hit_count_enabled_scopes` 已非空 → RHC 已啟用，跳到 4。
  2. `GET .../sec_policy/draft/firewall_settings` 與 active 比對（忽略 `href`、`updated_at`、`updated_by`、`created_*`）；**有任何差異 → 停止**，紀錄差異的欄位名稱（不記值）並回報使用者，因為 provision 會把別人的草稿變更一起推出去。
  3. 在終端列出將執行的三步（`PUT report_templates/rule_hit_count_report` → `PUT draft/firewall_settings` → `POST sec_policy` 只含 firewall_settings）後再執行；任一步非 2xx 即停並記錄已完成的步驟。唯讀 key 拿到 403 也照實記錄（這就是 spec「權限不足要明說」的實測依據）。
  4. 啟用後立即拉一份「啟用前 7 天到現在」的 RHC 報表，看啟用前的期間是否有命中數。紀錄啟用時間與結果。
- [ ] **Step 5：把結果寫回 spec §6.5**（唯讀角色段落改成實測結論；RHC 累計起點寫成事實並註明實測日期與租戶版本），commit：

```bash
git add docs/superpowers/specs/2026-10-24-illumio-ops-v6-rebuild-design.md
git commit -m "docs(v6): record read-only role and RHC accumulation facts measured on NFR SaaS"
```

---

### Task 1: 套件骨架、依賴鎖檔、CI 與分層守門

**Files:**
- Create: `illumio_ops/__init__.py`、`illumio_ops/paths.py`、空套件 `illumio_ops/{domain,settings,store,pce,services,web,jobs,migrate,i18n}/__init__.py`
- Create: `requirements-v6.in`、`requirements-v6.lock`、`requirements-v6-dev.txt`、`mypy-v6.ini`
- Create: `.github/workflows/ci-v6.yml`
- Create: `tests_v6/__init__.py`、`tests_v6/conftest.py`、`tests_v6/test_paths.py`、`tests_v6/gates/__init__.py`、`tests_v6/gates/_scan.py`、`tests_v6/gates/test_layering.py`、`tests_v6/gates/test_no_print.py`、`tests_v6/gates/test_no_cwd.py`

**Interfaces:**
- Produces:
  - `illumio_ops.__version__ = "6.0.0.dev0"`
  - `@dataclass(frozen=True) class InstallPaths: root: Path`，屬性 `config_dir=root/"config"`、`settings_file=config_dir/"settings.json"`、`tls_dir=config_dir/"tls"`、`data_dir=root/"data"`、`app_db=data_dir/"app.sqlite"`、`service_lock=data_dir/"service.lock"`、`limiter_dir=data_dir/"limiter"`、`logs_dir=root/"logs"`、`reports_dir=root/"reports"`；方法 `ensure_dirs(self) -> None`（建立 config／tls／data／limiter／logs／reports，mode `0o700`，已存在不改權限）——**任何取 lock 或開 DB 的入口都先呼叫它**（全新 root 沒有 `data/` 時，先開 lock 會 `FileNotFoundError`）
  - `def resolve_paths(root: Path | None = None) -> InstallPaths`：優先序 參數 → 環境變數 `ILLUMIO_OPS_ROOT` → `Path(illumio_ops.__file__).resolve().parent.parent`
  - `tests_v6/gates/_scan.py`：`def iter_modules(pkg_root: Path) -> Iterator[tuple[str, ast.Module, Path]]`（模組點名稱、AST、路徑），供所有守門共用
  - 分層規則常數 `LAYER_RULES: dict[str, frozenset[str]]`（在 `test_layering.py`）：`domain` 不得 import `illumio_ops` 其他任何子套件；`store`、`pce`、`settings` 不得 import `services`、`web`、`jobs`；`services` 不得 import `web`

- [ ] **Step 1：寫依賴。** `requirements-v6.in` 只列 v6 執行期依賴（flask、flask-login、flask-wtf、flask-limiter、flask-talisman、cheroot、pydantic、requests、argon2-cffi、cryptography、APScheduler、loguru；版本範圍照抄 `requirements.txt` 對應行）；以 `pip-compile --generate-hashes --strip-extras --output-file=requirements-v6.lock requirements-v6.in` 在 **Python 3.12** 產生鎖檔。`requirements-v6-dev.txt`：pytest、pytest-xdist、responses、freezegun、playwright、mypy、ruff、pip-audit、pip-tools（範圍照抄 `requirements-dev.txt`；沒有的取當下穩定版並釘下限）。
- [ ] **Step 2：寫失敗測試 `tests_v6/test_paths.py`**

```python
def test_env_root_wins_over_package_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ILLUMIO_OPS_ROOT", str(tmp_path))
    p = resolve_paths()
    assert p.root == tmp_path
    assert p.settings_file == tmp_path / "config" / "settings.json"
    assert p.app_db == tmp_path / "data" / "app.sqlite"

def test_explicit_root_wins_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ILLUMIO_OPS_ROOT", "/nonexistent")
    assert resolve_paths(tmp_path).root == tmp_path

def test_ensure_dirs_on_fresh_root(tmp_path):
    p = resolve_paths(tmp_path / "fresh")
    p.ensure_dirs()
    assert p.data_dir.is_dir() and p.tls_dir.is_dir() and p.limiter_dir.is_dir()
    assert (p.data_dir.stat().st_mode & 0o777) == 0o700
```

- [ ] **Step 3：跑測試確認失敗**：`timeout 300 python3.12 -m pytest tests_v6/test_paths.py -q` → FAIL（ImportError）。
- [ ] **Step 4：實作 `illumio_ops/paths.py`**，跑同一命令 → PASS。
- [ ] **Step 5：寫三支守門與各自的「注入違規必紅」自我測試。** 每支守門提供一個純函式（例如 `def find_layer_violations(modules) -> list[str]`），正式測試對 `illumio_ops/` 斷言空清單；自我測試用 `tmp_path` 造一個違規模組（例如 `illumio_ops/domain/bad.py` 內 `import illumio_ops.web`、`print("x")`、`os.getcwd()`）斷言被抓到。`test_no_print` 豁免 `illumio_ops/rescue.py`；`test_no_cwd` 也抓 `open("` 後接非絕對路徑字面值。
- [ ] **Step 6：跑** `timeout 300 python3.12 -m pytest tests_v6 -q` → 全 PASS。
- [ ] **Step 7：CI。** `mypy-v6.ini`：`[mypy] python_version = 3.12`、`strict = True`、`files = illumio_ops`。`.github/workflows/ci-v6.yml`（觸發：push 到 `main` 與 `feat/v6-**`、對 main 的 PR）單一 job、`python-version: "3.12"`，步驟依序：`pip install --require-hashes -r requirements-v6.lock`、`pip install -r requirements-v6-dev.txt`、`python -m playwright install --with-deps chromium`（Task 9 起有 e2e；乾淨 runner 沒有瀏覽器，見 `.github/workflows/ci.yml:52`）、`pip-audit -r requirements-v6.lock --strict`、`ruff check illumio_ops tests_v6`、`mypy --config-file mypy-v6.ini`、`python -m pytest tests_v6 -n auto --dist loadfile`。本機先照順序跑一次全綠。
- [ ] **Step 8：Commit**

```bash
git add illumio_ops requirements-v6.in requirements-v6.lock requirements-v6-dev.txt mypy-v6.ini .github/workflows/ci-v6.yml tests_v6
git commit -m "feat(v6): package skeleton, single py3.12 lock, ci-v6 and layering gates"
```

---

### Task 2: 值域登錄

**Files:**
- Create: `illumio_ops/domain/values.py`、`tests_v6/domain/test_values.py`

**Interfaces:**
- Produces（全部 `enum.StrEnum`，值即字串）：
  - `PolicyDecision`：`allowed`、`potentially_blocked`、`blocked`、`unknown`
  - `RuleAction`：`allow`、`deny`、`override_deny`
  - `AlertRuleType`：`event`、`traffic`、`bandwidth`、`volume`、`system`
  - `DeploymentType`：`on_prem`、`saas`
  - `Language`：`en`、`zh_TW`
  - `ProbeName`：`noop`、`health`、`node_available`
  - `DraftPolicyDecision`：**開放值域**。`KNOWN_DRAFT_POLICY_DECISIONS: frozenset[str]` 列已知值；`def parse_draft_policy_decision(raw: str) -> str` 小寫化後原樣回傳（不拒絕未知值，PCE 新增值時不漂移；見 `src/config_models.py:251` 註解）。已知值集合實作時以 Illumio 知識庫（`microseg-kb` skill，Illumio 庫）查證後填入，至少含 `blocked_by_boundary`、`potentially_blocked_by_boundary`、`blocked_by_override_deny`、`potentially_blocked_by_override_deny`、`allowed_across_boundary`。
  - `def export_value_domains() -> dict[str, list[str]]`：鍵為類別名，值為排序後的值清單（`DraftPolicyDecision` 輸出已知值），供 Task 7 匯出給前端。

- [ ] **Step 1：寫失敗測試**

```python
def test_policy_decision_values_are_exact_strings():
    assert [v.value for v in PolicyDecision] == ["allowed", "potentially_blocked", "blocked", "unknown"]

def test_alert_rule_types_include_volume():
    assert {v.value for v in AlertRuleType} == {"event", "traffic", "bandwidth", "volume", "system"}

def test_draft_decision_unknown_value_passes_through():
    assert parse_draft_policy_decision("Some_New_Value") == "some_new_value"

def test_export_has_every_enum_and_no_ints():
    d = export_value_domains()
    assert set(d) >= {"PolicyDecision", "RuleAction", "AlertRuleType", "DeploymentType", "Language", "ProbeName", "DraftPolicyDecision"}
    assert all(isinstance(v, str) for vals in d.values() for v in vals)
```

- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/domain/test_values.py -q` → FAIL。
- [ ] **Step 3：實作 `illumio_ops/domain/values.py`**（純定義，不 import 套件內任何模組）。
- [ ] **Step 4：跑同一命令 → PASS；再跑** `timeout 300 python3.12 -m pytest tests_v6/gates -q` → PASS。
- [ ] **Step 5：Commit** `git add illumio_ops/domain tests_v6/domain && git commit -m "feat(v6): value-domain registry with string-only enums"`

---

### Task 3: 設定 schema 與 SettingsStore

**Files:**
- Create: `illumio_ops/settings/schema.py`、`illumio_ops/settings/store.py`、`illumio_ops/settings/secrets.py`、`tests_v6/settings/test_schema.py`、`tests_v6/settings/test_store.py`

**Interfaces:**
- Produces:
  - `class StrictModel(BaseModel)`：`model_config = ConfigDict(extra="forbid", frozen=True)`。**所有**設定子模型都繼承它（只在外層設 `extra="forbid"` 時，pydantic 會無聲丟掉巢狀未知鍵）。
  - **模型欄位一律沒有預設值**（`X | None` 也必須出現在檔案裡，可為 `null`）：檔案缺任何欄位 → `SettingsInvalid`。預設值只存在 `default_settings(...)`，供全新安裝與遷移器使用——載入既有檔案時絕不補值。
  - `class Settings(StrictModel)`：`schema_version: Literal[1]`、`revision: int`、`pce: PceSettings`、`web: WebSettings`、`display: DisplaySettings`、`logging: LoggingSettings`
  - `PceSettings`：`url: str`（空字串或 http/https、去尾斜線）、`org_id: str`（空字串或數字字串）、`api_key: str`、`api_secret: str`、`deployment_type: DeploymentType`、`console_url: str | None`、`verify_tls: bool | str`（字串＝CA bundle 路徑，**必須接受**；5.x 的模型會拒收，見盤點 a §雜亂 2）、`events_timeout_seconds: int | None = Field(ge=5, le=600)`。`url==""` 代表「尚未設定」。
  - `WebSettings`：`host: str`、`port: int = Field(ge=1, le=65535)`、`username: str`、`password_hash: str`（argon2 雜湊）、`secret_key: str`（≥64 hex）、`allowed_ips: tuple[str, ...]`（用 tuple，避免 frozen 模型內的 list 被就地改寫）、`session_lifetime_seconds: int = Field(ge=60)`、`must_change_password: bool`、`tls: TlsSettings`
  - `TlsSettings`：`enabled: bool`、`mode: Literal["self_signed","provided"]`、`cert_file: str`、`key_file: str`、`auto_renew: bool`、`auto_renew_days: int = Field(ge=1)`、`validity_days: int = Field(ge=1)`、`key_algorithm: Literal["ecdsa-p256","rsa-2048"]`、`min_version: Literal["TLSv1.2","TLSv1.3"]`、`ciphers: str | None`
  - `DisplaySettings`：`language: Language`、`timezone: str`
  - `LoggingSettings`：`level: Literal["DEBUG","INFO","WARNING","ERROR"]`
  - `def default_settings(*, password_hash: str, secret_key: str, port: int = 5001) -> Settings`：`schema_version=1`、`revision=0`；pce 全空字串、`deployment_type=on_prem`、`console_url=None`、`verify_tls=True`、`events_timeout_seconds=None`；web `host="0.0.0.0"`、`username="illumio"`、`allowed_ips=()`、`session_lifetime_seconds=28800`、`must_change_password=False`；tls `enabled=True`、`mode="self_signed"`、cert/key 空字串、`auto_renew=True`、`auto_renew_days=30`、`validity_days=397`、`key_algorithm="ecdsa-p256"`、`min_version="TLSv1.2"`、`ciphers=None`；display `language=en`、`timezone="local"`；logging `level="INFO"`
  - `SECRET_FIELDS: frozenset[str] = {"pce.api_key","pce.api_secret","web.password_hash","web.secret_key"}`；`def redact(s: Settings) -> dict[str, Any]`（秘密欄位非空時換成 `"********"`）；`MASK = "********"`
  - `class SettingsInvalid(Exception)`：`errors: list[tuple[str, str]]`（`(點路徑, 訊息)`，訊息不得含輸入值）
  - `class SettingsConflict(Exception)`：`expected: int`、`actual: int`
  - `class SettingsStore`：`__init__(self, path: Path)`、`load(self) -> Settings`（檔案不存在 → `FileNotFoundError`；JSON 錯或驗證失敗 → `SettingsInvalid`；**不寫檔、不回退預設**）、`current(self) -> Settings`、`update(self, expected_revision: int, mutate: Callable[[dict[str, Any]], None]) -> Settings`（`threading.Lock` 內：比對 `revision`，不符 → `SettingsConflict`；`cand = cur.model_dump(mode="json")`（全新的 dict，與 `cur` 不共用任何物件），`mutate(cand)` 就地改它，`cand["revision"] = cur.revision + 1`，`Settings.model_validate(cand)`；驗證通過才 `mkstemp`（同目錄）→ 寫 → `fsync` → `os.replace`（權限 `0o600`）→ 最後才替換記憶體中的目前設定。`mutate` 拋例外或驗證失敗時，`current()` 與檔案位元組都不變）、`create_initial(self, *, password_hash: str, secret_key: str, port: int = 5001) -> Settings`（以 `default_settings` 建立；檔案已存在 → `FileExistsError`）

- [ ] **Step 1：寫失敗測試**（節錄斷言；每個名稱都是一支測試）

```python
def test_load_missing_file_raises_and_creates_nothing(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    with pytest.raises(FileNotFoundError):
        store.load()
    assert not (tmp_path / "settings.json").exists()

def test_load_invalid_never_writes(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"schema_version": 1, "bogus": 1}')
    before = p.read_bytes()
    with pytest.raises(SettingsInvalid) as e:
        SettingsStore(p).load()
    assert "bogus" in [loc for loc, _ in e.value.errors]
    assert p.read_bytes() == before

def test_load_missing_field_is_invalid_not_defaulted(tmp_path): ... # 刪掉 web.port 與 schema_version → SettingsInvalid，錯誤列出兩個點路徑
def test_load_nested_unknown_key_is_invalid(tmp_path): ...          # web.tls.bogus=1 → SettingsInvalid，loc 為 "web.tls.bogus"
def test_invalid_error_message_never_echoes_secret(tmp_path): ...   # api_secret 設成非字串，訊息不含其值
def test_update_with_stale_revision_conflicts(tmp_path): ...        # 兩次以同一 expected_revision 更新，第二次 SettingsConflict
def test_update_rejects_invalid_and_keeps_file(tmp_path): ...      # mutate 產生 port=0 → SettingsInvalid，檔案位元組不變
def test_failed_update_leaves_current_untouched(tmp_path): ...     # mutate 先清空 allowed_ips 再設 port=0 → 失敗後 current().web.allowed_ips 與檔案皆不變；mutate 自己拋例外亦同
def test_default_settings_roundtrip_is_valid(tmp_path): ...        # create_initial 後 load() 成功且等於 default_settings 的值
def test_saved_file_mode_is_0600(tmp_path): ...
def test_verify_tls_accepts_ca_bundle_path(): ...                   # PceSettings(verify_tls="/etc/pki/ca.pem") 合法
def test_redact_masks_nonempty_secrets_only(): ...
```

- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/settings -q` → FAIL。
- [ ] **Step 3：實作 schema、store、secrets。**
- [ ] **Step 4：跑同一命令 → PASS；跑** `timeout 300 python3.12 -m pytest tests_v6 -q` → PASS。
- [ ] **Step 5：Commit** `git add illumio_ops/settings tests_v6/settings && git commit -m "feat(v6): validated settings store with revisions, fail-closed load and redaction"`

---

### Task 4: 應用狀態庫、遷移與單一寫入者守門

**Files:**
- Create: `illumio_ops/store/db.py`、`illumio_ops/store/ownership.py`、`illumio_ops/store/migrations/__init__.py`、`illumio_ops/store/migrations/0001_job_health.sql`、`tests_v6/store/test_db.py`、`tests_v6/gates/test_single_writer.py`

**Interfaces:**
- Produces:
  - `def connect(path: Path) -> sqlite3.Connection`：建目錄、`journal_mode=WAL`、`foreign_keys=ON`、`busy_timeout=5000`、`row_factory=sqlite3.Row`
  - `def migrate(conn: sqlite3.Connection) -> int`：依序套用 `illumio_ops/store/migrations/NNNN_*.sql`（以 `importlib.resources` 讀），以 `PRAGMA user_version` 記版本，每檔一個 transaction；回傳最終版本；資料庫版本**高於**程式已知最高版本 → `RuntimeError`（拒絕降版）
  - `0001_job_health.sql`：`job_health(job_id TEXT PRIMARY KEY, last_started_at TEXT NOT NULL, last_finished_at TEXT, last_ok INTEGER, last_error TEXT, runs INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0)`；`pce_probe(id INTEGER PRIMARY KEY CHECK (id = 1), checked_at TEXT NOT NULL, results_json TEXT NOT NULL)`
  - `TABLE_OWNERS: dict[str, str] = {"job_health": "illumio_ops.jobs.health", "pce_probe": "illumio_ops.services.pce_health"}`
  - 守門 `find_foreign_writers(modules) -> list[str]`：掃所有字串常數（含相鄰字串串接後的結果），不分大小寫比對這四種寫入形式並取出表名：`INSERT [OR <x>] INTO <t>`、`REPLACE INTO <t>`、`UPDATE [OR <x>] <t> SET`（**表名後必須接 `SET`**，所以 UPSERT 的 `ON CONFLICT ... DO UPDATE SET` 不會把 `SET` 誤當表名）、`DELETE FROM <t>`；表名可帶 `"`／`` ` ``／`[]` 引號。表名在 `TABLE_OWNERS` 而模組不是擁有者 → 違規；表名不在 `TABLE_OWNERS` → 也違規（新表必須登錄）

- [ ] **Step 1：寫失敗測試**：`test_migrate_sets_user_version`、`test_migrate_is_idempotent`、`test_newer_db_version_is_refused`、`test_wal_enabled`；守門 `test_no_foreign_writers` 與自我測試 `test_injected_foreign_write_is_caught`（tmp 模組內 `"INSERT INTO job_health ..."`）、`test_injected_foreign_replace_is_caught`（`"REPLACE INTO job_health ..."`）、`test_unregistered_table_write_is_caught`、`test_owner_upsert_is_clean`（擁有者模組內 `INSERT INTO job_health ... ON CONFLICT(job_id) DO UPDATE SET runs = runs + 1` → 零違規）。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/store tests_v6/gates/test_single_writer.py -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS。**
- [ ] **Step 5：Commit** `git add illumio_ops/store tests_v6/store tests_v6/gates/test_single_writer.py && git commit -m "feat(v6): app sqlite store with migrations and single-writer gate"`

---

### Task 5: PCE client HTTP 核心與健康探測

**Files:**
- Create: `illumio_ops/pce/client.py`、`illumio_ops/pce/rate_limit.py`、`illumio_ops/pce/health.py`、`tests_v6/pce/test_client.py`、`tests_v6/pce/test_rate_limit.py`、`tests_v6/pce/test_health.py`
- 來源（複製後改寫，commit 訊息註明）：`src/api_client.py:122-339`（session／retry／POST 429）、`:341-376`、`:1600-1625`（`health_status_from_body`）、`pce_probe_category`／`_endpoint_probe_category`（`src/api_client.py`、`src/analyzer.py`）、`src/pce_cache/rate_limiter.py`

**Interfaces:**
- Consumes: `PceSettings`（Task 3）、`ProbeName`、`DeploymentType`（Task 2）
- Produces:
  - `@dataclass(frozen=True) class PceResponse: status: int; body: bytes; headers: Mapping[str, str]`，方法 `json(self) -> Any`
  - `class PceTransportError(Exception)`：`path: str`、`kind: Literal["dns","refused","timeout","tls","other"]`（例外訊息不含憑證）
  - `class PceClient`：`__init__(self, cfg: PceSettings, *, rate_limiter: RateLimiter | None = None)`；`request(self, method: str, path: str, *, json: Any = None, timeout: float = 15, org_scoped: bool = True, bounded: bool = False, deadline: float | None = None) -> PceResponse`（`org_scoped=True` → `{url}/api/v2/orgs/{org_id}{path}`，否則 `{url}/api/v2{path}`；連線層失敗一律 `raise PceTransportError`，**不回 `(0, bytes)`**；非 2xx 照常回 `PceResponse`）；`close()`、context manager
  - 5.x 保留值：Basic auth `key:secret`；`Retry(total=3, backoff_factor=1.0, status_forcelist=[429,502,503,504], allowed_methods={"GET","HEAD","PUT","DELETE"}, respect_retry_after_header=True, raise_on_status=False)`；主 pool `pool_connections=10, pool_maxsize=20`；bounded session `max_retries=0, pool 2/4`；POST 收到 429 單次重試，等待 `Retry-After`（非數字或非有限值 → 2.0，夾在 `[0, 30]`），有 rate limiter 時重試前重新取預算、取不到回原 429；`verify_tls` 為字串時當 CA bundle 路徑
  - `class RateLimiter`：`__init__(self, rate_per_minute: int = 400, burst: int | None = None)`（`burst=None` → 容量 `max(rate_per_minute // 6, 1)`；`rate_per_minute < 1` → `ValueError`）、`acquire(self, timeout: float) -> bool`、`set_rate(self, rate_per_minute: int) -> None`（token bucket，照搬 `src/pce_cache/rate_limiter.py:17-` 的 `GlobalRateLimiter`；P1 不做行程級 singleton，由 P2 的收集服務持有）
  - `class PceNotConfigured(Exception)`（同在 `pce/client.py`）；`def client_from_settings(cfg: PceSettings, *, rate_limiter: RateLimiter | None = None) -> PceClient`：`cfg.url == ""` 或 `org_id`／`api_key`／`api_secret` 任一為空 → `raise PceNotConfigured`
  - `@dataclass(frozen=True) class ProbeResult: name: ProbeName; ok: bool; status: int | None; category: str; detail_key: str`
  - `def probe_pce(client: PceClient, deployment: DeploymentType) -> list[ProbeResult]`：順序與停止條件照搬 5.x（`src/analyzer.py:1256-1345`）：先 `GET /noop`（非 org）；失敗即停。`saas` → 只回 noop。`on_prem` → `GET /health` 必須 200 且 `health_status_from_body` 不在 `{"warning","degraded","error","critical"}`，空字串視為未知（不健康）；再 `GET /node_available`，200 或 202 為健康。連線層失敗 → `ok=False, status=None, category=<kind>`。

- [ ] **Step 1：寫失敗測試。** 移植以下 5.x 測試的斷言（行為不變、介面改成新 client）：`tests/test_api_client_request_contract.py`（noop 為已驗證端點、`pce_probe_category`、verify_ssl 三種；**`test_request_returns_zero_status_on_connection_failure` 不移植**，改成下方的 raise 測試）、`tests/test_api_pce_contract.py` 的 `TestRetryExcludesPost` 與 `TestPost429SingleRetry`（POST 不在 `allowed_methods`、POST 429 單次重試、stream 不重試、第二次 429 不再重試、重試帶相同 body 與 headers、Retry-After 夾值、GET 429 不在請求層重試）、`tests/test_api_client_retry_adapter.py`（GET 429／503 重試、400 不重試）、`tests/test_rate_limiter.py`（含 `burst`）。新增：

```python
def test_retry_adapter_parameters_match_5x(): ...                              # total=3、backoff_factor=1.0、status_forcelist、respect_retry_after_header、raise_on_status=False、pool 10/20；bounded session max_retries=0
def test_transport_failure_raises_not_empty(responses_or_unreachable_url): ...   # 連不到 → PceTransportError(kind="refused")
def test_client_from_unconfigured_settings_raises(): ...                       # url="" → PceNotConfigured
def test_post_429_retries_once_with_clamped_wait(): ...                        # Retry-After: "inf" → 等 2.0；"99" → 等 30
def test_probe_categories(): ...                                               # 401 noop → ok False 且停；on_prem health 200+degraded → ok False；node_available 202 → ok True；saas 只有一筆
def test_health_status_from_body_list_picks_worst(): ...
```

- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/pce -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；跑全部** `timeout 600 python3.12 -m pytest tests_v6 -q` → PASS。
- [ ] **Step 5：Commit** `git add illumio_ops/pce tests_v6/pce && git commit -m "feat(v6): PCE client core and health probes ported from 5.x with raising transport errors"`

---

### Task 6: Web 安全機制與登入

**Files:**
- Create: `illumio_ops/web/app.py`、`illumio_ops/web/security.py`、`illumio_ops/web/ipallow.py`、`illumio_ops/web/auth.py`、`illumio_ops/services/context.py`、`tests_v6/web/conftest.py`、`tests_v6/web/test_security.py`、`tests_v6/web/test_auth.py`、`tests_v6/web/test_ipallow.py`
- 來源：`src/gui/__init__.py:154-480`（安全設定順序與數值）、`src/gui/_helpers.py:55-115,227-265`（IP 正規化、允許清單、RST）、`src/config.py:18-31`（argon2）、`src/gui/routes/auth.py`

**Interfaces:**
- Consumes: `SettingsStore`、`InstallPaths`
- Produces:
  - `illumio_ops/services/context.py`（放在 services 層，web 與 jobs 都可 import，不違反分層）：`@dataclass class AppContext: paths: InstallPaths; settings: SettingsStore; pce_factory: Callable[[PceSettings], PceClient]`，方法 `db(self) -> sqlite3.Connection`（`store.db.connect(paths.app_db)`）
  - `def create_app(ctx: AppContext, *, use_https: bool) -> Flask`：
    1. IP 允許清單 `before_request` **第一個註冊**；不在清單 → RST 斷線、不回任何 HTTP（`ipallow.rst_drop()`），對 `/static` 也生效；空清單＝全部允許
    2. Session：`HTTPONLY=True`、`SAMESITE="Strict"`、`SECURE=use_https`、`PERMANENT_SESSION_LIFETIME=web.session_lifetime_seconds`、`secret_key=web.secret_key`；`MAX_CONTENT_LENGTH=25*1024*1024`
    3. flask-login：`session_protection="strong"`，單一管理者 `web.username`
    4. CSRF：`WTF_CSRF_TIME_LIMIT=session_lifetime`、`WTF_CSRF_HEADERS=["X-CSRFToken","X-CSRF-Token"]`；CSRF 錯誤對 `/api/*` 回 400 envelope，`error.code="csrf_error"`，並附新 token
    5. Limiter：`default_limits=["300 per minute"]`、`strategy="fixed-window"`、key＝remote address；儲存＝`file://{paths.limiter_dir}`（照搬 5.x `_JsonFileStorage`），環境變數 `ILLUMIO_OPS_RATELIMIT_URI` 可覆寫（測試用 `memory://`）；429 回 envelope `error.code="rate_limited"`
    6. Talisman：CSP `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'`；`frame_options="DENY"`、`referrer_policy="strict-origin-when-cross-origin"`、permissions policy `camera, microphone, geolocation, interest-cohort, browsing-topics, payment, usb` 全部 `()`；`force_https=use_https`、HSTS 只在 https（`max_age=31536000`、`include_subdomains`、`preload`）；`app.testing` 時不強制 https。另以 `after_request` 照搬 `src/gui/__init__.py:588-606`：`X-Content-Type-Options: nosniff`、`Cross-Origin-Opener-Policy: same-origin`、`Cross-Origin-Resource-Policy: same-site`、移除 `Server` 標頭；`index.html` 回 `Cache-Control: no-store`（`/assets/*` 為雜湊檔名，可長快取）
    7. 未登入的 `/api/*` 一律 401 envelope `error.code="auth_required"`，例外只有 `PUBLIC_OPS = {"auth.login", "auth.csrf", "i18n.dictionary"}`（登入頁在登入前需要字典）；`must_change_password=True` 時除改密碼與登出外一律 423 `error.code="password_change_required"`
    8. 非 `/api/*` 的 GET 一律回 `illumio_ops/web/static/index.html`（SPA）；靜態檔 `/assets/*`
  - `auth.py`：`hash_password(plain: str) -> str`、`verify_password(plain: str, stored: str) -> bool`（argon2 `time_cost=4, memory_cost=131072, parallelism=4`；空或壞雜湊回 False）；路由 `POST /api/auth/login`（`5 per minute`，錯誤一律 `error.code="invalid_credentials"`，不區分帳號或密碼錯）、`POST /api/auth/logout`、`GET /api/auth/csrf`、`GET /api/auth/me`、`POST /api/auth/password`（照搬 `src/gui/routes/config.py:100-125`：`must_change_password=False` 時舊密碼必填且必須正確，`True` 時免填；新密碼長度 **12–512** 且等於 `confirm_password`；成功後清掉 `must_change_password`、**輪替 `web.secret_key`** 讓其他既存 session 立即失效，並以新 key 重簽本請求的 session 使操作者保持登入）。密碼規則常數 `PASSWORD_MIN_LEN = 12`、`PASSWORD_MAX_LEN = 512` 定義在 `auth.py`，Task 12 的 `rescue reset-password` 共用
  - 首次啟動預設帳密沿用 5.x：`illumio`／`illumio`，`must_change_password=False`（使用者先前要求；spec §6.5）

- [ ] **Step 1：寫失敗測試。** 移植斷言：`tests/test_gui_ip_allowlist.py`、`tests/test_static_ip_allowlist.py`（含 RST 斷線、`/static` 也擋、允許清單是第一個 hook）、`tests/test_flask_talisman_headers.py`、`tests/test_limiter_backend.py`、`tests/test_security_headers.py`（CSP 無 nonce、COOP／CORP、無 `Server` 標頭、登入 5/min 第 6 次 429）、`tests/test_security_endpoint_old_password.py`（舊密碼必填與錯誤、`must_change_password` 免舊密碼、11 字元被拒）。新增 `test_password_change_rotates_secret_and_keeps_caller_logged_in`（另一個 client 的舊 session 改密後回 401）、`test_api_requires_login_returns_401_envelope`、`test_spa_fallback_serves_index_for_unknown_paths`、`test_5x_argon2_hash_verifies`（以 5.x 參數產生的雜湊必須能被 v6 驗證——Task 12 遷移依賴此事）。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/web -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；跑全部 `tests_v6` → PASS。**
- [ ] **Step 5：Commit** `git add illumio_ops/web illumio_ops/services/context.py tests_v6/web && git commit -m "feat(v6): web security stack and single-admin auth ported from 5.x"`；commit 後 `git status --porcelain illumio_ops tests_v6` 必須為空（未追蹤的必要檔案會讓本機綠、CI 紅）。

---

### Task 7: API 契約、單一回應信封與前端型別匯出

**Files:**
- Create: `illumio_ops/web/contract.py`、`scripts/v6/export_contracts.py`、`tests_v6/web/test_contract.py`、`tests_v6/gates/test_contract_coverage.py`
- Modify: `illumio_ops/web/auth.py`（改用 `api_route`）

**Interfaces:**
- Produces:
  - `class ApiError(BaseModel): code: str; message_key: str; params: dict[str, str] = {}; field: str | None = None`
  - `class Meta(BaseModel): partial: bool = False; truncated: bool = False; notes: list[str] = []`
  - `class Envelope(BaseModel, Generic[T]): ok: bool; data: T | None = None; error: ApiError | None = None; meta: Meta = Meta()`
  - `@dataclass(frozen=True) class Operation: op_id: str; method: Literal["GET","POST","PUT","DELETE","PATCH"]; path: str; request: type[BaseModel] | None; response: type[BaseModel]`
  - `REGISTRY: dict[str, Operation]`；`def api_route(bp: Blueprint, op: Operation) -> Callable`：登錄 op、註冊路由、把 JSON body 驗證成 `op.request`（失敗 → 400，`error.code="invalid_input"`、`field`＝第一個錯誤的點路徑）、把 handler 回傳的 `op.response` 包進 `Envelope`；例外對應：`SettingsInvalid`→400 `invalid_settings`、`SettingsConflict`→409 `stale_revision`、`PceNotConfigured`→409 `pce_not_configured`、`PceTransportError`→502 `pce_unreachable`（`params.kind`）；其他例外 → 500 `internal_error`，log 完整 traceback，回應不含例外文字
  - `scripts/v6/export_contracts.py`：輸出 `web/src/api/contracts.json`＝`{"operations": {op_id: {"method","path","request_schema","response_schema"}}, "values": export_value_domains()}`；排序穩定（重跑零 diff）
  - `scripts/v6/gen_contracts.sh`：**唯一的產生入口**，依序 `python3.12 scripts/v6/export_contracts.py` → `npm --prefix web run gen:ts`（Task 8 才有；不存在時只做第一步）。本計畫之後所有「產生型別」都指這支腳本，不單獨跑 `npm run gen:ts`。
  - 守門 `test_contract_coverage.py`：(a) `app.url_map` 中每條 `/api/` 規則都對應 `REGISTRY` 內一個 op；(b) 每個 op_id 在 `web/src/**/*.ts(x)` 中**排除 `web/src/api/generated.ts`** 後，至少有一處 `call("<op_id>"`（正規式 `\bcall\(\s*["']<op_id>["']`）——只出現在型別宣告或產生檔不算呼叫者（Task 8 起生效，Task 7 先以 `pytest.mark.xfail(strict=True, reason="web/ arrives in Task 8")` 標記，Task 8 移除）；自我測試：(a) 多註冊一條無契約的路由 → 紅；(b) 在 tmp 複製的 `web/src` 刪掉某 op 唯一的 `call(...)`、但 `generated.ts` 仍列出它 → 紅

- [ ] **Step 1：寫失敗測試**：`test_invalid_body_returns_field_error`、`test_unhandled_exception_hides_message`、`test_transport_error_maps_to_502_with_kind`、`test_export_is_stable`（跑兩次位元組相同）、`test_every_api_rule_has_operation`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/web/test_contract.py tests_v6/gates/test_contract_coverage.py -q` → FAIL。
- [ ] **Step 3：實作，並把 Task 6 的 auth 路由改用 `api_route`。**
- [ ] **Step 4：跑全部 `tests_v6` → PASS（覆蓋守門 (b) 為 xfail）。**
- [ ] **Step 5：Commit** `git add illumio_ops/web scripts/v6/export_contracts.py scripts/v6/gen_contracts.sh tests_v6 && git commit -m "feat(v6): typed API contracts, single envelope and schema export"`

---

### Task 8: 前端骨架（React＋TS＋Vite）

**Files:**
- Create: `web/package.json`、`web/package-lock.json`、`web/tsconfig.json`、`web/vite.config.ts`、`web/index.html`、`web/src/main.tsx`、`web/src/api/client.ts`、`web/src/api/generated.ts`（產生）、`web/src/i18n/index.ts`、`web/src/shell/Shell.tsx`、`web/src/shell/nav.ts`、`web/src/pages/Login.tsx`、`web/src/pages/Home.tsx`、`web/src/styles/tokens.css`、`web/src/styles/base.css`、`web/public/fonts/*`
- Create: `illumio_ops/i18n/en.json`、`illumio_ops/i18n/zh_TW.json`、`illumio_ops/i18n/__init__.py`、`tests_v6/i18n/test_dictionaries.py`
- Modify: `.github/workflows/ci-v6.yml`（加 node 步驟）、`tests_v6/gates/test_contract_coverage.py`（移除 xfail）

**Interfaces:**
- Consumes: `web/src/api/contracts.json`（Task 7）
- Produces:
  - `package.json`：依賴**精確版本**（無 `^`／`~`），React、react-dom、react-router-dom、TypeScript、Vite、@vitejs/plugin-react、json-schema-to-typescript 取執行當下的最新穩定 major；scripts：`gen:ts`（contracts.json → `src/api/generated.ts`；只由 `scripts/v6/gen_contracts.sh` 呼叫）、`typecheck`（`tsc --noEmit`）、`build`（`vite build`，`outDir: ../illumio_ops/web/static`、`emptyOutDir: true`）
  - `client.ts`：`async function call<Op extends OpId>(op: Op, body?: RequestOf<Op>, params?: Record<string,string>): Promise<Envelope<ResponseOf<Op>>>`——從 contracts 取 method／path；自動帶 `X-CSRFToken`（`GET /api/auth/csrf` 取得、401／CSRF 400 時重取一次）；**非 2xx 也回 Envelope，不 throw**；網路失敗回 `{ok:false, error:{code:"network_error", message_key:"err_network"}}`
  - `i18n/index.ts`：`t(key: string, params?: Record<string,string>): string`；字典來源 `GET /api/i18n/{lang}`（Task 8 新增 op `i18n.dictionary`，回 `dict[str,str]`）；缺鍵時顯示鍵名並 `console.error`
  - Shell：左側導覽 224px，區塊依 v3.1：首頁、系統。系統下的項目由各頁面任務註冊（`nav.ts` 的 `registerNav`）：P1 結束時為「PCE 連線」（Task 9）、「背景工作」（Task 10）、「憑證」（Task 11）、「安全」「顯示」（Task 13）；未完成的頁面不出現在導覽，不放 placeholder。使用者選單含登出
  - `tokens.css`：自 `src/static/css/v2/tokens.css` 複製 Direction D token；字型自 `src/static/fonts/` 複製 Montserrat-VF.woff2、NotoSansCJKtc-Regular.otf 及其 LICENSE
  - `illumio_ops/i18n`：`def dictionary(lang: Language) -> dict[str, str]`；只放 v6 用到的鍵；譯文可從 `src/i18n_en.json`／`src/i18n_zh_TW.json` 複製，鍵名自訂、不必沿用 5.x 鍵名
  - 守門 `test_dictionaries.py`：en 與 zh_TW 鍵集合相同；引用的鍵都存在；字典內沒有任何未被引用的鍵（各附注入自我測試）。「引用」的定義（只有這幾種形式算，其他寫法一律不准用來傳 i18n 鍵）：TS 的 `t("<key>"`；Python 中任何名稱以 `_key` 結尾的關鍵字引數或欄位預設值的**字串字面值**（`message_key="..."`、`detail_key="..."`、`reason_key="..."`）。**禁止以 f-string 或串接組出鍵名**——守門對 `*_key=` 後接任何非字串字面值直接報錯；需要變化的部分走 `params`。自我測試：`detail_key="x_unused"` 而字典無此鍵 → 紅；字典有 `y` 但只被 `reason_key="y"` 引用 → 綠；`reason_key=f"a_{n}"` → 紅
- CI 增加：`actions/setup-node`（node 22）、`npm ci --prefix web`、`bash scripts/v6/gen_contracts.sh && git diff --exit-code web/src/api/contracts.json web/src/api/generated.ts`（後端契約與前端型別都必須已提交且最新）、`npm --prefix web run typecheck`、`npm --prefix web run build`——這幾步放在 pytest **之前**（`test_spa_build` 與 e2e 需要建置產物）

- [ ] **Step 1：寫失敗測試** `tests_v6/i18n/test_dictionaries.py`（四支）與 `tests_v6/web/test_spa_build.py::test_built_index_references_hashed_assets`（前端建置後 `illumio_ops/web/static/index.html` 存在且引用 `/assets/*.js`）。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/i18n tests_v6/web/test_spa_build.py -q` → FAIL。
- [ ] **Step 3：建立 web 專案與 i18n 模組；登入頁與首頁（首頁 P1 只顯示「PCE 健康狀態」卡片，資料由 Task 10 提供，此處先顯示「尚未檢查」）。**
- [ ] **Step 4：跑** `npm ci --prefix web && bash scripts/v6/gen_contracts.sh && npm --prefix web run typecheck && npm --prefix web run build`，再跑全部 `timeout 600 python3.12 -m pytest tests_v6 -q` → PASS（含移除 xfail 後的覆蓋守門）。
- [ ] **Step 5：Commit**（`illumio_ops/web/static/` 不入 git，加進 `.gitignore`）

```bash
git add web illumio_ops/i18n tests_v6 .github/workflows/ci-v6.yml .gitignore
git commit -m "feat(v6): React shell, typed API client, login page and i18n dictionaries"
```

---

### Task 9: 垂直切片——系統 › PCE 連線與健康檢查

**Files:**
- Create: `illumio_ops/services/pce_health.py`、`illumio_ops/web/routes/system_pce.py`、`web/src/pages/system/PceConnection.tsx`、`tests_v6/services/test_pce_health.py`、`tests_v6/web/test_system_pce.py`、`tests_v6/e2e/conftest.py`、`tests_v6/e2e/fake_pce.py`、`tests_v6/e2e/test_system_pce_e2e.py`、`tests_v6/gates/test_settings_readers.py`

**Interfaces:**
- Consumes: `SettingsStore.update`、`redact`、`PceClient`、`probe_pce`、`api_route`
- Produces:
  - `services/pce_health.py`（`pce_probe` 表擁有者）：`def run_probe(ctx: AppContext) -> list[ProbeResult]`（以 `ctx.pce_factory(settings.pce)`——預設即 Task 5 的 `client_from_settings`——建 client、跑 `probe_pce`、寫 `pce_probe` 單列）、`def latest(ctx: AppContext) -> tuple[datetime, list[ProbeResult]] | None`；PCE 尚未設定 → `client_from_settings` 拋 `PceNotConfigured`，原樣往上（Task 7 的對應表回 409 `pce_not_configured`）
  - Ops：`system.pce.get`（GET `/api/system/pce` → 遮罩後的 `PceSettings` 與 `revision`）、`system.pce.update`（PUT `/api/system/pce`，body 含 `revision` 與欄位；`api_key`／`api_secret` 為空字串或等於 `MASK` → 保留原值）、`system.pce.probe`（POST `/api/system/pce/probe` → `list[ProbeResult]`）、`system.pce.latest`（GET `/api/system/pce/latest`）
  - 頁面：表單（PCE URL、org ID、API key、API secret、部署型態、主控台 URL、TLS 驗證：開／關／CA 路徑）、主要動作「儲存」、次要動作「測試連線」；每個探測一列，顯示人話結果（例：「無法連線（DNS 解析失敗）」「驗證失敗（HTTP 401）」「PCE 回報 degraded」）；欄位錯誤顯示在欄位旁
  - `tests_v6/e2e/fake_pce.py`：`werkzeug` 啟的假 PCE，可設定 `/api/v2/noop`、`/api/v2/health`、`/api/v2/node_available` 的回應
  - 守門 `test_settings_readers.py`（只比對屬性名稱會被別的物件的同名屬性 `.url`／`.enabled`／`.level` 假綠，所以改成**以完整路徑登錄讀者**）：
    - `SETTINGS_READERS: dict[str, str]`：葉路徑 → 讀它的模組點名稱（例 `"pce.url": "illumio_ops.pce.client"`、`"schema_version": "illumio_ops.settings.store"`、`"revision": "illumio_ops.settings.store"`；`settings/schema.py` 本身不算讀者）
    - `PENDING_READERS: dict[str, str]`：葉路徑 → 到期任務或階段。Task 9 時為：`web.host`、`web.port`、`web.tls.*` 每個葉、`logging.level` → `"P1-T11"`；`display.language` → `"P1-T13"`；`pce.events_timeout_seconds` → `"P2"`；`pce.console_url`、`display.timezone` → `"P3"`。Task 11、13 把各自的項目從 PENDING 搬到 READERS。
    - 斷言：(1) 兩表的鍵不相交，且聯集恰等於 `Settings` 全部葉路徑（schema 增減欄位必須同步登錄）；(2) READERS 每一項的模組存在，且其 AST 同時含有 `.<葉名>` 的屬性讀取與「擁有者證據」——擁有者模型類別名（例 `PceSettings`）或父欄位屬性讀取（例 `.pce`、`.tls`）；根層欄位（`schema_version`、`revision`）的擁有者證據為 `Settings`。
    - 自我測試：schema 多一個未登錄葉 → 紅；登錄的模組只讀了**另一個模型**的同名屬性（例 `.level` 但沒有 `LoggingSettings`／`.logging`）→ 紅；正常登錄 → 綠。

- [ ] **Step 1：寫失敗測試**：`test_get_masks_secrets`、`test_put_masked_secret_keeps_existing`、`test_put_stale_revision_returns_409`、`test_put_invalid_url_returns_field_error`、`test_probe_unconfigured_returns_409`、`test_probe_writes_latest`；e2e `test_save_and_probe_happy_path`、`test_probe_shows_auth_failure_in_words`（假 PCE noop 回 401）、`test_two_tabs_second_save_sees_conflict`。
- [ ] **Step 2：跑** `timeout 600 python3.12 -m pytest tests_v6/services tests_v6/web/test_system_pce.py tests_v6/e2e tests_v6/gates/test_settings_readers.py -q` → FAIL。
- [ ] **Step 3：實作後端、頁面、e2e fixture。**
- [ ] **Step 4：`bash scripts/v6/gen_contracts.sh && npm --prefix web run typecheck && npm --prefix web run build`，再跑同一 pytest 命令 → PASS；跑全部 `tests_v6` → PASS。**
- [ ] **Step 5：Commit** `git add illumio_ops tests_v6 web/src && git commit -m "feat(v6): PCE connection settings and health probe vertical slice"`

---

### Task 10: 排程骨架、job 健康與首頁 PCE 健康卡

**Files:**
- Create: `illumio_ops/jobs/scheduler.py`、`illumio_ops/jobs/health.py`、`illumio_ops/web/routes/system_jobs.py`、`illumio_ops/web/routes/home.py`、`web/src/pages/system/Jobs.tsx`、`tests_v6/jobs/test_scheduler.py`、`tests_v6/jobs/test_health.py`
- Modify: `web/src/pages/Home.tsx`

**Interfaces:**
- Produces:
  - `jobs/health.py`（`job_health` 表擁有者）：`record_start(conn, job_id: str, at: datetime) -> None`、`record_finish(conn, job_id: str, at: datetime, error: str | None) -> None`、`list_health(conn) -> list[JobHealth]`（`JobHealth` 為 pydantic model：`job_id, last_started_at, last_finished_at, last_ok, last_error, runs, failures`）
  - `jobs/scheduler.py`：`def build_scheduler(ctx: AppContext) -> BackgroundScheduler`（`coalesce=True`、`max_instances=1`、UTC）；`def instrument(job_id: str, fn: Callable[[], None], ctx) -> Callable[[], None]`（記錄開始／結束／例外，例外不往上拋但完整寫 log 與 `last_error`）；P1 註冊 `pce_probe`（每 300 秒呼叫 `services.pce_health.run_probe`；PCE 未設定時記為成功並 `last_error=None`、不呼叫 PCE）
  - Ops：`system.jobs.list`（GET `/api/system/jobs`）、`home.summary`（GET `/api/home/summary` → `{pce: {checked_at, results} | null}`）
  - 頁面：系統 › 背景工作（清單：名稱人話、上次執行、結果、失敗次數）；首頁 PCE 健康卡顯示最近一次結果與時間，過期（> 2 × 300 秒）時明說「資料已過期」

- [ ] **Step 1：寫失敗測試**：`test_instrument_records_failure_and_keeps_scheduler_alive`、`test_probe_job_skips_when_unconfigured`、`test_list_health_orders_by_job_id`、`test_home_summary_marks_stale`。
- [ ] **Step 2：跑** `timeout 300 python3.12 -m pytest tests_v6/jobs tests_v6/web -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；`bash scripts/v6/gen_contracts.sh && npm --prefix web run typecheck && npm --prefix web run build`；跑全部 `tests_v6` → PASS。**
- [ ] **Step 5：Commit** `git add illumio_ops tests_v6 web/src && git commit -m "feat(v6): in-process scheduler with job health and home PCE status card"`

---

### Task 11: TLS、cheroot 伺服器與 `python -m illumio_ops serve`

**Files:**
- Create: `illumio_ops/web/tls.py`、`illumio_ops/web/server.py`、`illumio_ops/__main__.py`、`illumio_ops/web/routes/system_tls.py`、`web/src/pages/system/Tls.tsx`（系統 › 憑證）、`tests_v6/web/test_tls.py`、`tests_v6/test_main.py`
- 來源：`src/gui/_helpers.py:495-955`（自簽產生、SAN、續期、CSR、匯入、`_build_ssl_context`）、`src/gui/__init__.py:644-740`（cheroot 與 hardened adapter）、`tests/test_tls.py`、`tests/test_tls_renew_config_passthrough.py`

**Interfaces:**
- Produces:
  - `tls.py`：`build_ssl_context(tls: TlsSettings) -> ssl.SSLContext`（預設 ciphers `ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:!aNULL:!MD5:!DSS:!RC4:!3DES:!EXPORT`；`OP_NO_COMPRESSION | OP_SINGLE_DH_USE | OP_SINGLE_ECDH_USE`）、`ensure_self_signed(tls_dir: Path, tls: TlsSettings) -> tuple[Path, Path]`（缺檔、無 SAN、或 `auto_renew` 且剩餘天數 ≤ `auto_renew_days` 時重產；SAN＝`DNS:localhost`＋本機非 link-local IP；無法判斷 SAN 時**不**重產）、`cert_days_remaining(path: Path) -> int | None`、`generate_csr(...)`、`import_signed_cert(...)`（簽章與 5.x 相同）
  - `server.py`：`serve(app: Flask, host: str, port: int, ssl_ctx: ssl.SSLContext | None, stop: threading.Event) -> None`（cheroot，`numthreads=10`，SIGTERM → 優雅關閉）
  - `__main__.py`：`python -m illumio_ops serve [--root PATH]`：
    1. `resolve_paths` → `paths.ensure_dirs()` → 取得 `paths.service_lock` 的排他 `fcntl.flock`（已被持有 → stderr 一行說明、exit 75）
    2. `SettingsStore.load()`；檔案不存在 → `create_initial`（預設帳密 illumio／illumio、新 secret key）並 log warning；`SettingsInvalid` → stderr 與 log 列出每個欄位、**exit 78**，不寫任何檔案
    3. `connect`＋`migrate` app DB；設定 loguru（`logging.level`，檔案在 `paths.logs_dir`）
    4. TLS：`enabled` 且 `self_signed` → `ensure_self_signed`；`provided` → 檔案不存在則 exit 78
    5. 啟動排程、`serve`
  - 每日 `tls_renew_check` job（僅自簽＋`auto_renew`）：續期後 `last_error=None` 並在 job 健康頁註記「需重新啟動服務才會套用」（5.x 語意：執行中的 listener 不熱換）
  - Ops：`system.tls.status`、`system.tls.renew`、`system.tls.csr`、`system.tls.import`、`system.tls.update`

- [ ] **Step 1：寫失敗測試**：移植 `tests/test_tls.py`、`tests/test_tls_renew_config_passthrough.py` 斷言；新增 `test_serve_refuses_invalid_settings`（以子行程跑 `python -m illumio_ops serve --root tmp`，設定檔壞 → exit 78、stderr 含欄位路徑、檔案位元組不變）、`test_second_instance_refused`（第二個行程 exit 75）、`test_fresh_root_creates_initial_settings_0600`（root 下**沒有** `data/`、`config/`，首次啟動不得 `FileNotFoundError`）。把 `web.host`、`web.port`、`web.tls.*`、`logging.level` 從 `PENDING_READERS` 搬到 `SETTINGS_READERS`（讀者為 `illumio_ops.__main__` 或 `illumio_ops.web.tls`）。
- [ ] **Step 2：跑** `timeout 600 python3.12 -m pytest tests_v6/web/test_tls.py tests_v6/test_main.py -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：跑同一命令 → PASS；跑全部 `tests_v6` → PASS。**
- [ ] **Step 5：Commit** `git add illumio_ops tests_v6 web/src && git commit -m "feat(v6): TLS lifecycle, cheroot server and fail-closed serve entrypoint"`

---

### Task 12: 救援指令與遷移器框架（api／web_gui／tls／settings 四段）

**Files:**
- Create: `illumio_ops/rescue.py`、`illumio_ops/migrate/report.py`、`illumio_ops/migrate/v5.py`、`illumio_ops/migrate/__main__.py`、`tests_v6/migrate/test_v5.py`、`tests_v6/migrate/fixtures/v5_0_0_config.json`、`tests_v6/migrate/fixtures/v5_2_x_config_106_redacted.json`、`tests_v6/test_rescue.py`、`scripts/v6/redact_v5_config.py`、`tests_v6/scripts/test_redact_v5_config.py`

**Interfaces:**
- Produces:
  - `rescue.py`（`python -m illumio_ops.rescue <cmd> [--root PATH]`；先 `paths.ensure_dirs()`，再試取 `service.lock`，取不到 → 「請先停止服務」exit 75）：`init [--port N]`（設定檔不存在時以 `SettingsStore.create_initial` 建立並寫入 port；已存在 → exit 73、不動檔案；供 install.sh 使用，安裝腳本本身不直接寫設定檔）、`reset-password`（`getpass` 兩次，長度規則共用 Task 6 的 `PASSWORD_MIN_LEN`／`PASSWORD_MAX_LEN`（12–512），經 `SettingsStore.update` 寫入，同時輪替 `web.secret_key`）、`check-settings`（合法 exit 0；不合法列欄位 exit 78）
  - `migrate/report.py`：`@dataclass class MigrationItem: source: str; target: str | None; action: Literal["carried","rewritten","dropped","unsupported"]; reason_key: str; params: dict[str, str]`（`reason_key` 一律字面值，變化的部分放 `params`，例 `reason_key="migrate_arrives_in_phase", params={"phase": "P3"}`——Task 8 的 i18n 守門禁止組字串鍵名）；`@dataclass class MigrationReport: items: list[MigrationItem]`，`def render(report, lang: Language) -> str`（只印鍵名與動作，**不印任何值**）
  - `migrate/v5.py`：`def read_v5(v5_root: Path) -> dict[str, Any]`（讀 `config/config.json`；5.x 無版本欄位，以形狀判斷）、`def migrate_v5(raw: dict[str, Any]) -> tuple[Settings, MigrationReport]`：
    - `api.url/org_id/key/secret/deployment_type/console_url/events_timeout_seconds` → `pce.*`；`api.verify_ssl` → `pce.verify_tls`；`api.profile` → dropped（v6 無 profile 概念）
    - `web_gui.username/password/secret_key/allowed_ips/must_change_password` → `web.*`（`password` 為 argon2 雜湊原樣搬；非 `$argon2` 開頭 → 以 v6 hasher 雜湊並記 rewritten）；`web_gui.session_lifetime_seconds` 若存在照搬
    - `web_gui.tls.*` → `web.tls.*`（`self_signed: true` → `mode="self_signed"`；有 cert/key 路徑 → `mode="provided"`）
    - `settings.language` → `display.language`；`settings.timezone` → `display.timezone`
    - spec §7 的 deprecated 鍵（`report.attack_surface`、`web_gui.tls.http_redirect_port`、`pce_profiles`、`active_pce_id`、`pce_cache.archive_review_max_days`）→ dropped，reason `migrate_deprecated_in_5x`
    - **所有其他鍵**（`alerts`、`email`、`smtp`、`rules`、`report*`、`pce_cache`、`siem`、`rule_scheduler`、`scheduler`、`logging`、`rule_backups`、`settings.fleet_*`、`events.*`、`dashboard.*`、`settings.theme`、`settings.enable_health_check`、`settings.dashboard_queries`）→ `unsupported`，reason `migrate_arrives_in_phase`（`params.phase` 依路線圖）或 `migrate_not_in_v6`（`settings.theme`、`dashboard_queries`、`rule_backups`、`scheduler` → `not_in_v6`）。**不得無聲略過任何鍵**：報告的 source 集合必須等於輸入的葉鍵集合。
  - `python -m illumio_ops.migrate --from <v5_root> --report-only [--lang zh_TW]`：只印報告，不寫任何檔案（P6 才接進 install.sh）
  - `scripts/v6/redact_v5_config.py <in> <out>`：把所有秘密欄位、主機名、IP、org id 換成固定假值後輸出（**執行時不得把原檔內容印到終端**）

- [ ] **Step 1：先做去識別化工具（fixture 依賴它）。** 寫 `tests_v6/scripts/test_redact_v5_config.py`：`test_secrets_hosts_ips_org_replaced`（輸入含 api key／secret／密碼雜湊／secret_key／hec_token／smtp 密碼、主機名、IPv4、org id → 輸出不含任何一個原值，結構與鍵集合不變）、`test_prints_nothing_to_stdout`。跑 `timeout 300 python3.12 -m pytest tests_v6/scripts/test_redact_v5_config.py -q` → FAIL；實作 `scripts/v6/redact_v5_config.py`（**只用 stdlib**，才能在 .106 用 5.x venv 的 python 直接跑；秘密欄位以鍵名清單＋「值長得像 token」雙重判斷）→ PASS。
- [ ] **Step 2：準備 fixture。**（a）把 `redact_v5_config.py` 複製到 .106 的暫存目錄，以 `sudo -u illumio-ops PYTHONNOUSERSITE=1 /root/illumio-ops/venv/bin/python <script> /root/illumio-ops/config/config.json <tmp>/out.json` 在遠端去識別化，只把 `out.json` 拷回存成 `v5_2_x_config_106_redacted.json`，刪除遠端暫存檔；以 `grep -cE '<lab 主機名或 IP 片段>'` 確認不含真實值（只印計數）。（b）以 `git show v5.0.0:src/config.py`（`_DEFAULT_CONFIG`）與 `git show v5.0.0:src/config_models.py` 推出 5.0.0 會寫出的完整形狀，填假值，存成 `v5_0_0_config.json`。
- [ ] **Step 3：寫失敗測試**：`test_report_covers_every_input_leaf_key`（兩個 fixture）、`test_migrated_settings_validate`（產出的 `Settings` 以 `default_settings` 為底再覆寫，模型無預設值故必須每欄齊全）、`test_argon2_hash_carried_verbatim`、`test_plaintext_password_is_hashed_and_marked_rewritten`、`test_deprecated_keys_dropped_with_reason`、`test_unsupported_sections_name_their_phase`、`test_render_never_contains_secret_values`、`test_report_only_writes_nothing`；rescue：`test_reset_password_refused_while_service_lock_held`、`test_reset_password_enforces_12_to_512`、`test_check_settings_exit_codes`、`test_init_writes_port_and_refuses_existing`、`test_init_on_fresh_root_without_data_dir`。跑 `timeout 300 python3.12 -m pytest tests_v6/migrate tests_v6/test_rescue.py -q` → FAIL。
- [ ] **Step 4：實作；跑同一命令 → PASS；跑全部 `tests_v6` → PASS。**
- [ ] **Step 5：Commit** `git add illumio_ops scripts/v6/redact_v5_config.py tests_v6 && git commit -m "feat(v6): rescue commands and v5 settings migrator framework with full-coverage report"`

---

### Task 13: 系統 › 安全與顯示頁

**Files:**
- Create: `illumio_ops/web/routes/system_security.py`、`illumio_ops/web/routes/system_display.py`、`web/src/pages/system/Security.tsx`、`web/src/pages/system/Display.tsx`、`tests_v6/web/test_system_security.py`、`tests_v6/e2e/test_security_e2e.py`

**Interfaces:**
- Produces:
  - Ops：`system.security.get`（username、allowed_ips、session_lifetime_seconds、revision）、`system.security.update`（允許清單以 `ipallow.validate_allowed_ips` 正規化，無效項目 → 400 `field="allowed_ips"`；**新清單不含目前請求者 IP 且 body 未帶 `confirm_lockout: true` → 409 `would_lock_out`**）、`system.display.get`／`system.display.update`（language）
  - 改密碼沿用 Task 6 `POST /api/auth/password`
  - 頁面：安全（帳號、改密碼、允許 IP 清單編輯）、顯示（語言切換，切換後整個介面即時換語系）

- [ ] **Step 1：寫失敗測試**：`test_allowlist_excluding_requester_is_refused`、`test_allowlist_with_confirm_is_saved`、`test_invalid_ip_reports_field`、`test_language_change_reflected_in_dictionary_endpoint`；e2e `test_change_language_switches_ui`。把 `display.language` 從 `PENDING_READERS` 搬到 `SETTINGS_READERS`；在 `test_settings_readers.py` 加 `test_no_p1_pending_left`（`PENDING_READERS` 的值不得以 `P1-` 開頭）。
- [ ] **Step 2：跑** `timeout 600 python3.12 -m pytest tests_v6/web/test_system_security.py tests_v6/e2e/test_security_e2e.py -q` → FAIL。
- [ ] **Step 3：實作。**
- [ ] **Step 4：`bash scripts/v6/gen_contracts.sh && npm --prefix web run typecheck && npm --prefix web run build`；跑同一命令 → PASS；跑全部 `tests_v6` → PASS。**
- [ ] **Step 5：Commit** `git add illumio_ops tests_v6 web/src && git commit -m "feat(v6): security and display settings pages with lockout guard"`

---

### Task 14: 離線 bundle、並排安裝與 .106 實機驗收

**Files:**
- Create: `scripts/v6/build_bundle.sh`、`scripts/v6/install.sh`、`scripts/v6/illumio-ops.service.in`、`tests_v6/scripts/test_install_unit.py`、`tests_v6/e2e/test_smoke_remote.py`
- 來源：`scripts/build_offline_bundle.sh`（PBS 下載與 SHA256 釘選 `PBS_TAG="20241016"`、`PBS_PYTHON="3.12.7"`、`PBS_SHA256_LINUX_X86_64`、libpython strip、wheel 下載參數照搬 `scripts/build_offline_bundle.sh:192-205`：`--only-binary=:all: --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 --python-version 3.12 --implementation cp --require-hashes`——只列 2_28 時只發舊標籤的套件（如 cffi）會找不到）、`deploy/illumio-ops.service`（`[Service]` hardening 全部指令）

**Interfaces:**
- Produces:
  - `build_bundle.sh`：產出 `dist/illumio-ops-<version>-offline-linux-x86_64.tar.gz`，解開後目錄樹固定為：
    ```
    illumio-ops-<version>/
      python/                  PBS CPython 3.12.7
      wheels/                  依 requirements-v6.lock 下載
      requirements-v6.lock     install.sh 配 --require-hashes 安裝用
      illumio_ops/             套件本體（含 web/static 建置產物）
      install.sh
      illumio-ops.service.in
    ```
    建置前執行 `npm ci --prefix web` 與前端建置（同 Task 8 的命令），並確認 `illumio_ops/web/static/index.html` 存在
  - **安裝後目錄樹**（`<prefix>` 即 `InstallPaths.root`）：`<prefix>/python/`、`<prefix>/illumio_ops/`、`<prefix>/{config,data,logs,reports}/`。依賴裝進 `<prefix>/python` 的 site-packages；套件本體不安裝，靠 unit 的 `Environment=PYTHONPATH=<prefix>` 匯入（不依賴工作目錄）
  - `install.sh [--prefix DIR] [--service-name NAME] [--port N] [--no-systemd]`（預設 `/opt/illumio-ops`、`illumio-ops`、`5001`；`--no-systemd` 只做複製、pip、`rescue init`，以目前使用者執行，供 Step 2b 驗證）：P1 只支援**全新安裝**——目標目錄已有 5.x（存在 `illumio-ops.py`）或 v6 → 中止並說明（升級在 P6）；建 `illumio-ops` 系統帳號（已存在則沿用）；複製 `python/`、`illumio_ops/` 到 `<prefix>`（root 擁有、他人唯讀）；建立 `<prefix>/{config,data,logs,reports}` 並 `chown illumio-ops`、mode `0700`；以 `<prefix>/python/bin/python3 -m pip install --no-index --require-hashes --find-links <bundle>/wheels -r <bundle>/requirements-v6.lock`；渲染 unit（`Environment=PYTHONPATH=<prefix>`、`Environment=PYTHONNOUSERSITE=1`、`ExecStart=<prefix>/python/bin/python3 -m illumio_ops serve --root <prefix>`、`WorkingDirectory=<prefix>`、`ReadWritePaths=<prefix>/config <prefix>/data <prefix>/logs <prefix>/reports`，其餘 hardening 指令照抄 `deploy/illumio-ops.service`）；以 `sudo -u illumio-ops env PYTHONPATH=<prefix> PYTHONNOUSERSITE=1 <prefix>/python/bin/python3 -m illumio_ops.rescue init --root <prefix> --port <N>` 建立初始設定（安裝腳本不直接寫設定檔）；**不自動啟動**，最後印出啟動指令
  - `test_install_unit.py`：渲染後的 unit 包含 `deploy/illumio-ops.service` 的每一條 hardening 指令（逐行比對清單）、ExecStart 與 ReadWritePaths 正確
  - `test_smoke_remote.py`（`@pytest.mark.requires_pce`，環境變數 `V6_SMOKE_URL` 未設則 skip）：登入 → 存 PCE 連線 → 測試連線全部探測 ok → 首頁健康卡有時間 → 背景工作頁有 `pce_probe`

- [ ] **Step 1：寫失敗測試 `test_install_unit.py`；跑** `timeout 300 python3.12 -m pytest tests_v6/scripts -q` → FAIL；實作 unit 範本與渲染 → PASS。
- [ ] **Step 2：建 bundle**：`bash scripts/v6/build_bundle.sh`（約 25 分鐘，PBS 下載是瓶頸，用 `run_in_background` 並等通知）。
- [ ] **Step 2b：本機乾淨目錄驗證（不經 systemd）。** 把 bundle 解到 scratch 目錄，照 install.sh 的複製與 pip 步驟裝到另一個空的 `<prefix>`（以 `--prefix` 指到 scratch、`--no-systemd` 旗標跳過建帳號與 unit），再以 unit 相同的環境變數跑 `rescue init --root <prefix> --port <空閒埠>` → exit 0，背景啟動 `serve --root <prefix>`，`curl -sk https://127.0.0.1:<埠>/api/auth/csrf` 回 200 envelope 後停掉。任何一步失敗就修 bundle／install.sh，不進 Step 3。（`--no-systemd` 是 install.sh 的正式旗標，`test_install_unit.py` 一併覆蓋。）
- [ ] **Step 3：並排安裝到 .106。** 先確認 `ss -ltn | grep 5443` 無人使用；若 .106 的 VEN 為強制模式導致 5443 不通，停下回報使用者。`scp` bundle → `tar xzf` → `./install.sh --prefix /opt/illumio-ops-v6 --service-name illumio-ops-v6 --port 5443` → `systemctl start illumio-ops-v6` → `systemctl is-active illumio-ops-v6` 為 `active`。**不得觸碰 5.x 的 `/root/illumio-ops` 與其服務**；確認 5.x 服務仍 `active`。
- [ ] **Step 4：實機驗收。** lab PCE 憑證以 1Password `LAB-PCE` 經腳本注入 Playwright（不印出）；跑 `V6_SMOKE_URL=https://172.16.15.106:5443 timeout 900 python3.12 -m pytest tests_v6/e2e/test_smoke_remote.py -q -m requires_pce` → PASS。再以 `python -m illumio_ops.migrate --from /root/illumio-ops --report-only --lang zh_TW`（在 .106 以 `sudo -u illumio-ops` 執行）產出報告，確認每個 5.x 鍵都有一列、無任何值外洩。
- [ ] **Step 5：交付紀錄**寫到 `tmp/v6-p1-verification/report.md`：每個任務的 commit、CI run 連結、.106 驗收輸出、遷移報告摘要、與計畫的偏離。
- [ ] **Step 6：Commit 並開 PR**

```bash
git add scripts/v6 tests_v6/scripts tests_v6/e2e/test_smoke_remote.py
git commit -m "feat(v6): offline bundle and side-by-side installer verified on the test box"
```

---

## P1 完成條件

- `.github/workflows/ci-v6.yml` 在分支上全綠（含 node build 與產生物零 diff）。
- 舊 CI（`ci.yml`）仍全綠——舊程式未被觸碰。
- .106 上 v6（5443）與 5.x（5001）同時 `active`；v6 smoke 通過；遷移報告覆蓋 .106 全部 5.x 鍵且無值外洩。
- 八道全階段守門（路線圖）中 P1 適用者全部存在且各自通過注入自我測試：相依方向、無 print、契約覆蓋（兩支）、設定讀者、單一寫入者、路徑不依賴工作目錄。
