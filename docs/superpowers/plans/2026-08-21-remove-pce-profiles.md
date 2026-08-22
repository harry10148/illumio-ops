# PCE Profile 移除 + 連線目標變更防護 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 拿掉從未實作到憑證層以外的 PCE profile 功能，並在連線目標真的改變時強制操作者做出明示選擇，讓「這台設備服務一台 PCE」成為程式碼保證而不是口頭約定。

**Architecture:** 兩段。第一段（Task 1-4）純移除：`pce_profiles` / `active_pce_id` 走既有的 deprecated-key 機制退場，ConfigManager 的五個 profile 方法、`/api/pce-profiles` 兩個端點、System 頁的 SY-01 面板與新增抽屜、27 個 i18n 鍵一併拿掉；`config.api` 成為「這台設備連哪台 PCE」的唯一真相。第二段（Task 5-7）補洞：`POST /api/settings` 偵測 `api.url` 或 `api.org_id` 改變時拒絕儲存並要求操作者在「清除快取」與「同一台 PCE 換位址」之間擇一，前者會實際清乾淨所有 PCE 衍生狀態。Task 8 是真機驗證。

**Tech Stack:** Python 3.12 / Flask / SQLAlchemy 2.x / pydantic v2 / 原生 ES modules（`src/static/js/v2/`）/ pytest + Playwright

**Spec:** `docs/superpowers/specs/2026-08-21-pce-profile-isolation-assessment.md`（§4.5 是本計畫的依據）

## Global Constraints

- **Commit 訊息用英文 conventional-commits**；計畫與說明文件用繁體中文。
- **`src/config_models.py` 的 `_Base` 是 `extra="forbid"`**：任何從 `ConfigSchema` 移除的欄位，若既有 `config.json` 仍帶著它，載入會直接失敗。移除欄位前必須先讓 `_strip_deprecated_keys()` 認得它（Task 1 先於 Task 2，順序不可調換）。
- **i18n 三份字典要同步**：`src/i18n_zh_TW.json`、`src/i18n_en.json`、`src/i18n/data/zh_explicit.json`。`scripts/precompute_zh_translations.py` 以 `zh_explicit` 為優先來源重算 `zh_TW`，漏改 `zh_explicit` 會在下次 precompute 被機器翻譯覆蓋。三個檔都以 `json.dumps(d, indent=2, ensure_ascii=False) + "\n"` 寫回，可精確 round-trip。
- **每個任務結束前這三個閘門必須是 0 / 綠**：
  - `./venv/bin/python scripts/audit_i18n_usage.py` → `Total: 0 finding(s)`
  - `./venv/bin/python -m pytest tests/test_i18n_no_reviewer_copy.py -q`
  - `./venv/bin/python -m pytest tests/test_i18n_zh_explicit_sync.py -q`
- **新增的 i18n 文案不得帶工程敘述**：不寫 HTTP 端點、狀態碼、「後端／前端」、內部欄位名。守門測試 `tests/test_i18n_no_reviewer_copy.py` 會擋。
- **虛擬環境是 `./venv`**（不是 `.venv`）。
- **測試一律前景執行並帶 timeout**，例：`timeout 900 ./venv/bin/python -m pytest tests/test_config_deprecated_keys.py -q`
- 每個任務自己的覆蓋測試綠了才 commit；全套由 orchestrator 在任務之間跑。

---

### Task 1: 讓帶著 profile 鍵的舊 config 仍能載入

**Files:**
- Modify: `src/config.py`（`_DEPRECATED_KEY_PATHS`，約 line 127-130）
- Test: `tests/test_config_deprecated_keys.py`

**Interfaces:**
- Consumes: 既有的 `_strip_deprecated_keys(merged: dict) -> list[str]`
- Produces: 無新介面。Task 2 依賴本任務已讓 `pce_profiles` / `active_pce_id` 在載入時被丟棄。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_config_deprecated_keys.py` 末尾加：

```python
def test_strip_removes_pce_profile_keys_in_place():
    """設備曾支援多組 PCE profile；欄位已移除，舊 config.json 仍須能載入。"""
    merged = {
        "api": {"url": "https://pce.example.com:8443"},
        "pce_profiles": [{"id": 1, "name": "lab", "url": "https://a:8443"}],
        "active_pce_id": 1,
    }
    dropped = _strip_deprecated_keys(merged)
    assert sorted(dropped) == ["active_pce_id", "pce_profiles"]
    assert "pce_profiles" not in merged
    assert "active_pce_id" not in merged
    assert merged["api"]["url"] == "https://pce.example.com:8443"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 300 ./venv/bin/python -m pytest tests/test_config_deprecated_keys.py::test_strip_removes_pce_profile_keys_in_place -q`
Expected: FAIL —`assert [] == ['active_pce_id', 'pce_profiles']`

- [ ] **Step 3: 實作**

`src/config.py`：

```python
_DEPRECATED_KEY_PATHS: tuple[str, ...] = (
    "report.attack_surface",
    "web_gui.tls.http_redirect_port",
    # PCE profiles were only ever a credential switcher: nothing downstream of
    # config["api"] knew they existed, and switching one silently re-pointed
    # the appliance at a second PCE while keeping the first one's cache.
    "pce_profiles",
    "active_pce_id",
)
```

- [ ] **Step 4: 測試通過**

Run: `timeout 300 ./venv/bin/python -m pytest tests/test_config_deprecated_keys.py -q`
Expected: PASS（全檔）

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config_deprecated_keys.py
git commit -m "chore(config): retire the pce_profiles keys ahead of removing the field"
```

---

### Task 2: 移除 ConfigManager 的 profile CRUD 與 schema 欄位

**Files:**
- Modify: `src/config.py`（`DEFAULT_CONFIG` 的 `"pce_profiles"` / `"active_pce_id"` 兩行；`get_pce_profiles` / `get_active_pce_id` / `add_pce_profile` / `update_pce_profile` / `remove_pce_profile` / `activate_pce_profile` / **`sync_api_to_active_profile`** 七個方法）
- Modify: `src/gui/routes/config.py`（`cm.sync_api_to_active_profile()` 呼叫，約 line 272）
- Modify: `src/cli/menus/_root.py`（兩處 `cm.sync_api_to_active_profile()` 呼叫與其上方註解，約 line 92-93 與 105）
- Modify: `src/config_models.py`（`class PceProfile`；`ConfigSchema` 的 `pce_profiles` 與 `active_pce_id` 兩個欄位）
- Test: `tests/test_config_models.py`

**Interfaces:**
- Consumes: Task 1 的 deprecated-key 退場
- Produces: `ConfigSchema` 不再有 `pce_profiles` / `active_pce_id`；`ConfigManager` 不再有任何 `*_pce_profile*` 方法。Task 3 依賴這一點。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_config_models.py` 末尾加：

```python
def test_config_schema_has_no_pce_profile_fields():
    """Profile 概念已移除：schema 不得再宣告它，否則舊資料會被當成合法設定留著。"""
    from src.config_models import ConfigSchema
    fields = set(ConfigSchema.model_fields)
    assert "pce_profiles" not in fields
    assert "active_pce_id" not in fields


def test_config_manager_has_no_profile_methods():
    """`sync_api_to_active_profile` 也要被抓到——它的名字裡沒有 `pce_profile`，
    第一版盤點就是這樣把它整個漏掉的。"""
    from src.config import ConfigManager
    leftovers = [n for n in dir(ConfigManager)
                 if "pce_profile" in n or "active_profile" in n]
    assert leftovers == [], f"still present: {leftovers}"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 300 ./venv/bin/python -m pytest tests/test_config_models.py -q -k "pce_profile"`
Expected: FAIL 兩條

- [ ] **Step 3: 實作**

1. `src/config_models.py`：整段刪除 `class PceProfile`（約 line 191-198），並從 `ConfigSchema` 刪掉這兩行：

```python
    pce_profiles: list[PceProfile] = Field(default_factory=list)
    active_pce_id: Optional[int] = None
```

2. `src/config.py`：從 `DEFAULT_CONFIG` 刪掉 `"pce_profiles": [],` 與 `"active_pce_id": None,` 兩行；刪除 `get_pce_profiles` / `get_active_pce_id` / `add_pce_profile` / `update_pce_profile` / `remove_pce_profile` / `activate_pce_profile` 六個方法（整段連同其間的註解）。

2b. **第七個方法：`sync_api_to_active_profile()`（約 line 709-720）也要刪，連同它的三個呼叫端。**（orchestrator 預檢補入：初稿的盤點用 `grep "def .*pce_profile"`，這個方法名裡沒有 `pce_profile` 所以整個漏掉。）它把 `config.api` 的值抄回作用中的 profile——沒有 profile 之後就沒有抄的對象。三個呼叫端都是「改完 `config.api` 之後、`cm.save()` 之前」呼叫它，刪掉呼叫即可，周圍的邏輯完全不動：

   - `src/gui/routes/config.py` 約 line 272：刪掉 `cm.sync_api_to_active_profile()` 一行。
   - `src/cli/menus/_root.py` 約 line 92-93：刪掉 `# Sync changes back to active PCE profile (if any)` 註解與其下的呼叫，兩行一起。
   - `src/cli/menus/_root.py` 約 line 105：刪掉 `cm.sync_api_to_active_profile()` 一行。

   刪完用 `grep -rn "sync_api_to_active_profile" src/ tests/` 確認為空。

3. 若 `import time` 只被 `add_pce_profile` 用到，一併移除；用 `grep -n "time\." src/config.py` 確認後再動。既有的 dead code 不要順手清。

- [ ] **Step 4: 測試通過**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_config_models.py tests/test_config_deprecated_keys.py tests/test_config_backwards_compat.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/config.py src/config_models.py tests/test_config_models.py
git commit -m "refactor(config): drop the PCE profile store and its CRUD"
```

---

> **執行順序裁決（orchestrator，預檢）**：本任務在 Task 2 **之前**執行。Task 2 移除
> `ConfigManager` 的 profile 方法，而本任務的 `api_get_settings` 仍在呼叫它們——先做 2
> 會留下一段 `AttributeError` 的破碎狀態。先移除呼叫端再移除方法就沒有這個窗口。

### Task 3: 移除 REST 端點與設定回應中的 profile 欄位

**Files:**
- Modify: `src/gui/routes/config.py`（`/api/pce-profiles` 的 GET 與 POST 兩個 handler，約 line 424-495；`api_get_settings` 回應中的 `"pce_profiles"` / `"active_pce_id"` 兩鍵，約 line 144-145；`known_roots` 集合，約 line 264）
- Modify: `src/gui/_helpers.py`（`_get_active_pce_url`，約 line 460-467）
- Modify: `src/reporter.py`（`_active_pce_url`，約 line 177-183）
- Delete: `tests/test_gui_pce_profiles.py`
- Test: `tests/test_api_settings.py`

**Interfaces:**
- Consumes: Task 2 移除後的 `ConfigManager`
- Produces: `_get_active_pce_url(cm) -> str` 與 `Reporter._active_pce_url() -> str` 簽章不變、行為改為只讀 `config["api"]["url"]`。Task 5 會在 `api_save_settings` 內新增邏輯，不動這兩者。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_api_settings.py` 末尾加：

```python
def test_settings_response_has_no_profile_fields(authed_client):
    """Profile 概念已移除：設定回應不得再帶 profile 清單或 active id。"""
    client, _csrf = authed_client
    body = client.get("/api/settings").get_json()
    assert "pce_profiles" not in body
    assert "active_pce_id" not in body


def test_pce_profiles_endpoint_is_gone(authed_client):
    client, _csrf = authed_client
    assert client.get("/api/pce-profiles").status_code == 404
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_api_settings.py -q -k "profile"`
Expected: FAIL 兩條（回應仍帶欄位、端點仍回 200）

- [ ] **Step 3: 實作**

1. `src/gui/routes/config.py`：刪除 `# ── API: PCE Profiles ──` 整段（`api_list_pce_profiles` 與 `api_pce_profiles_action` 兩個 handler，含其上方的區塊註解）。

2. 同檔 `api_get_settings` 的回應 dict 刪掉：

```python
            "pce_profiles":   cm.get_pce_profiles(),
            "active_pce_id":  cm.get_active_pce_id(),
```

3. 同檔 `known_roots` 刪掉 `'pce_profiles', 'active_pce_id'` 兩個元素。

4. `src/gui/_helpers.py` 整個函式改成：

```python
def _get_active_pce_url(cm: 'ConfigManager') -> str:
    """Return the PCE URL this appliance is configured against."""
    return cm.config.get('api', {}).get('url', '')
```

5. `src/reporter.py` 整個方法改成：

```python
    def _active_pce_url(self) -> str:
        return str(self.cm.config.get("api", {}).get("url", "")).strip()
```

6. `git rm tests/test_gui_pce_profiles.py`

7. 檢查 `tests/test_d2_misc_hardening.py` 與 `tests/test_cli_rule_list.py` 對 profile 的引用：兩者只是在 fixture 的 config 裡塞了 `pce_profiles` 鍵。移除該鍵即可，不要改動這兩檔的斷言。用 `grep -n "pce_profile" tests/test_d2_misc_hardening.py tests/test_cli_rule_list.py` 定位。

- [ ] **Step 4: 測試通過**

Run: `timeout 900 ./venv/bin/python -m pytest tests/test_api_settings.py tests/test_d2_misc_hardening.py tests/test_cli_rule_list.py tests/test_gui_auth.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(gui): remove the PCE profile endpoints and payload fields"
```

---

### Task 4: 移除前端 profile UI、i18n 鍵與文件段落

**Files:**
- Modify: `src/static/js/v2/areas/system.mjs`（`pceDrawer()` 整個函式；`mountPce` 內的 `PCE_SNAPS`、`handles.activate`、SY-01 面板與表格、`drawer.registerAudit("sy-pce-add", …)`、`modal.registerAudit("sy-pce-activate", …)`、`palette.registerFor(R_PCE, cmdSpec("sy:pce-add", …))`）
- Modify: `src/static/js/v2/core/store-map.mjs`（`pce_profiles: "/api/pce-profiles",`，約 line 125）
- Modify: `src/i18n_zh_TW.json`、`src/i18n_en.json`、`src/i18n/data/zh_explicit.json`
- Modify: `docs/guide/gui-tour.md`、`docs/guide/configuration.md`、`docs/reference/rest-api.md`
- Test: `tests/test_v2_system_e2e.py`、`tests/test_v2_shell_flows_e2e.py`、`tests/test_v2_coverage_live.py`

**Interfaces:**
- Consumes: Task 3 移除後的端點
- Produces: `PCE_SNAPS` 變成 `["settings", "status"]`；System → PCE 頁只剩連線設定表單。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_v2_system_e2e.py` 末尾加（沿用該檔既有的 `v2_page` fixture 用法，照抄鄰近測試的 fixture 參數名）：

```python
def test_pce_page_has_no_profile_ui(v2_page):
    """Profile 概念已移除：PCE 頁不得再出現清單、新增或切換的入口。"""
    v2_page.goto_route("#/system/pce")
    html = v2_page.content()
    for gone in ("sy-pce-add", "sy-pce-activate", "SY-01"):
        assert gone not in html, f"{gone} still rendered"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 900 ./venv/bin/python -m pytest tests/test_v2_system_e2e.py::test_pce_page_has_no_profile_ui -q`
Expected: FAIL —`sy-pce-add still rendered`

- [ ] **Step 3: 實作**

1. `system.mjs`：刪除 `pceDrawer()` 整個函式（含其上方引用舊 `settings.js` 的區塊註解）。

2. `system.mjs` `mountPce` 開頭三行註冊全部刪除：

```javascript
  drawer.registerAudit("sy-pce-add", function () { return drawer.open(pceDrawer()); });
  modal.registerAudit("sy-pce-activate", function () { return handles.activate ? handles.activate() : null; });
  palette.registerFor(R_PCE, cmdSpec("sy:pce-add", t("gui_pce_add"), function () { drawer.open(pceDrawer()); }));
```

3. `system.mjs`：`const PCE_SNAPS = ["settings", "pce_profiles", "status"];` → `const PCE_SNAPS = ["settings", "status"];`

4. `system.mjs`：刪除 `const profiles = …` 與 `const activeId = …` 兩行、整個 `// ── SY-01 profiles ──` 區塊（`profPanel` 到 `board.appendChild(profPanel);`）、以及 `handles.activate = function (p) {…};` 整段。

5. `system.mjs`：`activeId` 在連線區的 `roField(t("gui_sy_pce_active"), activeId, …)` 也要一起刪——那一列與 `gui_sy_pce_profile_name` 一列都是 profile 概念的殘留。該 `roList` 只剩空陣列時，連同上方的 `sectionHead(t("gui_sy_secret_state"))` 與 `roList` 一起刪除。

6. `store-map.mjs`：刪除 `pce_profiles: "/api/pce-profiles",` 一行。

7. 刪除這些 i18n 鍵（三份字典都要，`zh_explicit` 有才刪）：

```
gui_pce_activate  gui_pce_active  gui_pce_add  gui_pce_delete_profile
gui_pce_name  gui_pce_profiles  gui_pce_save_profile  gui_pce_switched
gui_sy_pce_active  gui_sy_pce_active_field  gui_sy_pce_i_cache
gui_sy_pce_i_del  gui_sy_pce_i_queries  gui_sy_pce_i_switch
gui_sy_pce_meta  gui_sy_pce_none  gui_sy_pce_none_body
gui_sy_pce_profile_field  gui_sy_pce_profile_name  gui_sy_pce_save_note
gui_sy_secret_state
gui_err_pce_id_required  gui_err_pce_name_url_required  gui_err_pce_profile_not_found
```

保留 `gui_sy_pce_url_rule`（連線表單仍在用）、`gui_err_pce_event_fetch*`、`gui_err_pce_health_use_system_form`（與 profile 無關）。

用這段腳本刪，不要手改 JSON：

```python
import json, pathlib
KEYS = """gui_pce_activate gui_pce_active gui_pce_add gui_pce_delete_profile
gui_pce_name gui_pce_profiles gui_pce_save_profile gui_pce_switched
gui_sy_pce_active gui_sy_pce_active_field gui_sy_pce_i_cache gui_sy_pce_i_del
gui_sy_pce_i_queries gui_sy_pce_i_switch gui_sy_pce_meta gui_sy_pce_none
gui_sy_pce_none_body gui_sy_pce_profile_field gui_sy_pce_profile_name
gui_sy_pce_save_note gui_sy_secret_state gui_err_pce_id_required
gui_err_pce_name_url_required gui_err_pce_profile_not_found""".split()
for p in ("src/i18n_zh_TW.json", "src/i18n_en.json", "src/i18n/data/zh_explicit.json"):
    f = pathlib.Path(p); d = json.loads(f.read_text(encoding="utf-8"))
    for k in KEYS:
        d.pop(k, None)
    f.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

8. 文件：`docs/guide/gui-tour.md` 的 PCE profile 段落、`docs/guide/configuration.md` 的 `pce_profiles` 設定說明、`docs/reference/rest-api.md` 的 `/api/pce-profiles` 兩個端點條目全部刪除。用 `grep -n "pce.profile\|pce-profiles" docs/guide/*.md docs/reference/*.md` 逐處定位。`docs/superpowers/` 底下的舊計畫與 spec **不要改**——那是歷史紀錄。

9. **覆蓋率錨點 SY-01 必須一起退場**（orchestrator 預檢補入，計畫初稿漏了這一段）。
   `tests/test_v2_coverage_live.py` 斷言 `covered == total == 102`、且 app 不得渲染
   `coverage.yaml` 沒列的錨點、也不得少列。移除 SY-01 面板會同時打破這三條。要動的是：

   - `design/v2/coverage.yaml`：刪除 `SY-01: {item: PCE profiles CRUD/切換, route: "#/system/pce"}` 一行。
   - `tests/test_v2_coverage_live.py`：`102` 出現在**三個地方**——檔案 docstring 第 1 行、`:81` 的 `assert gate_result["covered"] == gate_result["total"] == 102`、`:88` 的註解——全部改成 `101`。（`design/v2/coverage.yaml` 目前正好 102 個錨點，刪一個後是 101。）
   - `tests/test_v2_shell_flows_e2e.py`（orchestrator 二次盤點補入，brief 初稿沒列這個檔）：`test_system_subroutes_switch` 用 `SY-01` 當「`#/system/pce` 這個區確實掛上了／離開後確實卸載」的標記，`:294` 是 `count() >= 1`、`:298` 是 `count() == 0`。兩處都改成 `SY-18`（該路由移除 SY-01 後唯一剩下的錨點），語意不變。
   - `tests/test_v2_system_e2e.py`：
     - `test_pce_coverage_and_i18n`：`_goto(page, base_url, R_PCE, "SY-01")` 的錨點參數改為 `"SY-18"`；`assert {"SY-01", "SY-18"} - _covs(page) == set()` 改為 `assert {"SY-18"} - _covs(page) == set()`。
     - 整個 `test_pce_profile_crud_add_then_delete` 刪除。
     - 「PCE activate」那段守衛（建立 throwaway profile → 開 confirm → 按取消）整段刪除，含其 `_api_post("/api/pce-profiles", …)` 呼叫與清理程式碼。刪除後檢查外層測試函式是否還有其他區段；若只剩這一段，連函式一起刪。
     - 其餘所有 `_goto(page, base_url, R_PCE, "SY-01")` 與 `page.wait_for_selector('[data-cov="SY-01"]')` 改成 `"SY-18"` / `'[data-cov="SY-18"]'`。最後 `grep -n 'SY-01' tests/test_v2_system_e2e.py` 必須為空。

   `#/system/pce` 移除後只剩 SY-18 一個錨點，`test_every_route_contributed_something`（該路由至少貢獻一個錨點）仍會通過。

- [ ] **Step 4: 測試與閘門通過**

```bash
timeout 1800 ./venv/bin/python -m pytest tests/test_v2_system_e2e.py tests/test_v2_coverage_live.py -q
timeout 300 ./venv/bin/python scripts/audit_i18n_usage.py
timeout 300 ./venv/bin/python -m pytest tests/test_i18n_no_reviewer_copy.py tests/test_i18n_zh_explicit_sync.py -q
```
Expected: pytest 全綠；audit `Total: 0 finding(s)`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(gui-v2): remove the PCE profile page, its keys and its docs"
```

---

### Task 5: 偵測連線目標改變並要求明示選擇

**Files:**
- Modify: `src/gui/routes/config.py`（`api_save_settings`，`if 'api' in d:` 區塊內，url scheme 驗證之後、`for k in api_allowlist` 之前）
- Modify: `src/i18n_zh_TW.json`、`src/i18n_en.json`、`src/i18n/data/zh_explicit.json`
- Test: `tests/test_api_settings.py`（**加在既有檔案末尾，不要新建檔案**——見下方說明）

**Interfaces:**
- Consumes: Task 3 之後的 `api_save_settings`
- Produces: `POST /api/settings` 在 `api.url` 或 `api.org_id` 改變且請求未帶 `pce_target_change` 時，回 `409` 與 `{"ok": false, "pce_target_changed": true, "old": {...}, "new": {...}, "error": "<localised>"}`。接受的 `pce_target_change` 值為 `"flush"` 與 `"same-pce"`。Task 6 提供 `flush_pce_derived_state()`，Task 7 是前端。

- [ ] **Step 1: 寫失敗測試**

**測試加在 `tests/test_api_settings.py` 的末尾，不要新建測試檔。** 原因（orchestrator 預檢查證）：`authed_client` 是 `tests/test_api_settings.py:66` 的**檔案內** fixture，它依賴同檔 `:61` 的 `client` 與 `:40` 附近的 `app`——`tests/conftest.py:192` 的同名 `client` 是不同的東西（走 `app_persistent`）。新建檔案會拿不到這條 fixture 鏈，或拿到錯的那條。這些測試的主題本來就是 `POST /api/settings` 的行為，放在這個檔案是對的位置。

在 `tests/test_api_settings.py` 末尾加入（`import pytest`、`_csrf` 該檔已有，不要重複 import）：

```python
# ── PCE 連線目標變更必須是明示的決定 ──────────────────────────────────────────
# 這台設備的快取、擷取位置、封存與排程都沒有 PCE 維度（見
# docs/superpowers/specs/2026-08-21-pce-profile-isolation-assessment.md）。把
# api.url 或 api.org_id 指向另一台 PCE 而不處理既有資料，兩台的資料會靜默混合，
# 而且沒有任何徵兆。所以這裡不猜、也不自動清——直接擋下來要求操作者選。

def _save(client, csrf, api_block, choice=None):
    body = {"api": api_block}
    if choice is not None:
        body["pce_target_change"] = choice
    return client.post("/api/settings", json=body,
                       headers={"X-CSRFToken": csrf},
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})


def test_changing_url_without_a_choice_is_refused(authed_client):
    client, csrf = authed_client
    res = _save(client, csrf, {"url": "https://other-pce.example.com:8443"})
    assert res.status_code == 409
    body = res.get_json()
    assert body["ok"] is False
    assert body["pce_target_changed"] is True
    assert body["old"]["url"] == "https://pce.example.com:8443"
    assert body["new"]["url"] == "https://other-pce.example.com:8443"


def test_changing_org_id_without_a_choice_is_refused(authed_client):
    client, csrf = authed_client
    res = _save(client, csrf, {"org_id": "7"})
    assert res.status_code == 409
    assert res.get_json()["pce_target_changed"] is True


def test_rotating_credentials_is_not_a_target_change(authed_client):
    """換 key/secret 只是輪替憑證，不該擋。"""
    client, csrf = authed_client
    res = _save(client, csrf, {"key": "newkey", "secret": "newsecret"})
    assert res.status_code == 200
    assert res.get_json()["ok"] is True


def test_same_pce_choice_saves_without_touching_data(authed_client):
    client, csrf = authed_client
    res = _save(client, csrf, {"url": "https://renamed.example.com:8443"},
                choice="same-pce")
    assert res.status_code == 200
    assert res.get_json()["ok"] is True


def test_unknown_choice_is_rejected(authed_client):
    client, csrf = authed_client
    res = _save(client, csrf, {"url": "https://other.example.com:8443"},
                choice="whatever")
    assert res.status_code == 400
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_api_settings.py -q -k "choice or target_change"`（orchestrator 已用 `--collect-only` 驗證此 filter 恰好選中五條新測試）
Expected: 除 `test_rotating_credentials_is_not_a_target_change` 外全部 FAIL（目前一律 200）

- [ ] **Step 3: 實作**

`src/gui/routes/config.py`，在 `api_save_settings` 的 url scheme 驗證之後插入：

```python
                # Changing which PCE this appliance talks to is not an edit —
                # the cache, the ingestion positions, the archive files and the
                # schedules all carry the previous PCE's data with no marker
                # saying so. Make the operator say what should happen to it.
                _old_api = scratch.get('api', {})
                _target_changed = (
                    ('url' in api_in and str(api_in['url']).strip() != str(_old_api.get('url', '')).strip())
                    or ('org_id' in api_in and str(api_in['org_id']).strip() != str(_old_api.get('org_id', '')).strip())
                )
                _choice = d.get('pce_target_change')
                if _target_changed:
                    if _choice is None:
                        return jsonify({
                            "ok": False,
                            "pce_target_changed": True,
                            "old": {"url": _old_api.get('url', ''), "org_id": _old_api.get('org_id', '')},
                            "new": {"url": str(api_in.get('url', _old_api.get('url', ''))).strip(),
                                    "org_id": str(api_in.get('org_id', _old_api.get('org_id', ''))).strip()},
                            "error": t("gui_err_pce_target_needs_choice", lang=lang),
                        }), 409
                    if _choice not in ("flush", "same-pce"):
                        return jsonify({"ok": False,
                                        "error": t("gui_err_pce_target_bad_choice", lang=lang)}), 400
```

新增 i18n 鍵（三份字典）：

| key | zh_TW | en |
|---|---|---|
| `gui_err_pce_target_needs_choice` | 這會把設備指向另一台 PCE。請先選擇如何處理現有的快取與歷史資料。 | This points the appliance at a different PCE. Choose what happens to the existing cache and history first. |
| `gui_err_pce_target_bad_choice` | 無法識別的處理方式。 | Unrecognised choice. |

- [ ] **Step 4: 測試通過**

Run: `timeout 900 ./venv/bin/python -m pytest tests/test_api_settings.py -q`
Expected: PASS（`flush` 此時只是被接受，尚未真的清——Task 6 補）

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(gui): refuse a silent PCE re-point, ask what happens to the data"
```

---

### Task 6: 實作 PCE 衍生狀態的清除

**Files:**
- Create: `src/pce_cache/flush.py`
- Modify: `src/gui/routes/config.py`（Task 5 插入的區塊，`_choice == "flush"` 時呼叫）
- Test: `tests/test_pce_flush.py`（新建）

**Interfaces:**
- Consumes: `src/pce_cache/models.py` 的七個模型、`src/analyzer.py` 的 state 檔慣例
- Produces: `flush_pce_derived_state(db_path: str, state_path: str) -> dict[str, int]`，回傳每個被清項目的筆數，鍵為 `pce_events` / `pce_traffic_flows_raw` / `pce_traffic_flow_obs` / `pce_traffic_flows_agg` / `ingestion_cursors` / `ingestion_watermarks` / `siem_dispatch` / `dead_letter` / `state_keys`。

- [ ] **Step 1: 寫失敗測試**

新建 `tests/test_pce_flush.py`：

```python
"""清除必須清乾淨：只刪主資料表會讓新 PCE 沿用舊的擷取位置。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    Base, PceEvent, IngestionWatermark, SiemDispatch,
)
from src.pce_cache.flush import flush_pce_derived_state


def _seed(db_path):
    """欄位取自 src/pce_cache/models.py：PceEvent 與 SiemDispatch 幾乎全欄位
    NOT NULL，少一個就是 IntegrityError 而不是測試失敗。"""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine)
    with sf() as s:
        s.add(PceEvent(pce_href="/orgs/1/events/a", pce_event_id="a",
                       timestamp=now, event_type="x", severity="info",
                       status="success", pce_fqdn="pce.example.com",
                       raw_json="{}", ingested_at=now))
        s.add(IngestionWatermark(source="events", last_href="/orgs/1/events/a"))
        s.add(SiemDispatch(source_table="pce_events", source_id=1,
                           destination="splunk", status="pending",
                           queued_at=now))
        s.commit()
    return engine, sf


def test_flush_empties_every_table_including_watermarks(tmp_path):
    db = tmp_path / "cache.db"
    engine, sf = _seed(str(db))
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "event_watermark": "2026-01-01T00:00:00Z",
        "alert_history": {"r1": "2026-01-01T00:00:00Z"},
        "event_seen": ["a"],
        "event_parser_stats": {"n": 1},
        "posture_summary": {"x": 1},
        "rule_schedule_states": {"s1": "keep"},
        "settings_backup": {"keep": "me"},
    }), encoding="utf-8")

    counts = flush_pce_derived_state(str(db), str(state))

    with sf() as s:
        assert s.execute(select(PceEvent)).all() == []
        assert s.execute(select(IngestionWatermark)).all() == []
        assert s.execute(select(SiemDispatch)).all() == []
    assert counts["pce_events"] == 1
    assert counts["ingestion_watermarks"] == 1

    left = json.loads(state.read_text(encoding="utf-8"))
    for gone in ("event_watermark", "alert_history", "event_seen",
                 "event_parser_stats", "posture_summary"):
        assert gone not in left, gone
    # 排程是操作者自己建的，不隨 PCE 的資料一起清掉。
    assert left["rule_schedule_states"] == {"s1": "keep"}
    assert left["settings_backup"] == {"keep": "me"}, "非 PCE 衍生的鍵不可被動到"


def test_flush_on_a_missing_db_is_not_an_error(tmp_path):
    counts = flush_pce_derived_state(str(tmp_path / "nope.db"), str(tmp_path / "nope.json"))
    assert counts == {}
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 600 ./venv/bin/python -m pytest tests/test_pce_flush.py -q`
Expected: FAIL —`ModuleNotFoundError: src.pce_cache.flush`

- [ ] **Step 3: 實作**

新建 `src/pce_cache/flush.py`：

```python
"""Drop every row this appliance derived from one PCE.

The cache carries no tenant dimension: `flow_hash` is globally unique and the
ingestion watermark's primary key is `source` alone. So re-pointing the
appliance at a second PCE without clearing this leaves the two mixed, and the
new PCE inherits the old one's fetch position. Everything here is deleted
together or the state is worse than before the flush.
"""
from __future__ import annotations

import json
import os

from loguru import logger
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    Base, DeadLetter, IngestionCursor, IngestionWatermark, PceEvent,
    PceTrafficFlowAgg, PceTrafficFlowObs, PceTrafficFlowRaw, SiemDispatch,
)

# Order matters: SiemDispatch and DeadLetter reference rows in the data tables
# by (source_table, source_id), so they go first.
_MODELS = (
    SiemDispatch, DeadLetter,
    PceTrafficFlowAgg, PceTrafficFlowObs, PceTrafficFlowRaw, PceEvent,
    IngestionCursor, IngestionWatermark,
)

# The state.json keys that describe one PCE's history. Everything else in that
# file (schedules, GUI state, backups) survives.
#
# The analyzer already owns an authoritative list of the keys it writes, so
# take it from there rather than restating it — a restated copy drifts, and a
# key this misses is a key the next PCE inherits.
from src.analyzer import _ANALYZER_OWNED_STATE_KEYS

# Written by other subsystems but derived from the same PCE all the same.
# Deliberately NOT here: rule_schedule_states / report_schedule_states, which
# belong to schedules the operator authored, not to the PCE's data.
_EXTRA_PCE_DERIVED = ("event_timeline", "pce_stats", "posture_summary")

_STATE_KEYS = tuple(_ANALYZER_OWNED_STATE_KEYS) + _EXTRA_PCE_DERIVED


def flush_pce_derived_state(db_path: str, state_path: str) -> dict[str, int]:
    """Empty the cache tables and the PCE-derived keys of the state file.

    Returns a count per item cleared. A missing DB or state file is not an
    error: there is simply nothing of the old PCE left to remove.
    """
    counts: dict[str, int] = {}

    if os.path.exists(db_path):
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        with session_factory() as session:
            for model in _MODELS:
                n = session.execute(select(func.count()).select_from(model)).scalar_one()
                session.execute(delete(model))
                counts[model.__tablename__] = int(n)
            session.commit()
        engine.dispose()
        logger.warning("PCE cache flushed: {}", counts)

    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        removed = [k for k in _STATE_KEYS if k in state]
        for k in removed:
            state.pop(k, None)
        if removed:
            with open(state_path, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
            logger.warning("PCE-derived state keys cleared: {}", removed)
        counts["state_keys"] = len(removed)

    return counts
```

`src/gui/routes/config.py`，在 Task 5 的 `if _choice not in (...)` 檢查之後補上實際執行（仍在 `with cm.write_lock:` 內）：

```python
                    if _choice == "flush":
                        from src.pce_cache.flush import flush_pce_derived_state
                        _cache_cfg = cm.models.pce_cache
                        flush_pce_derived_state(_cache_cfg.db_path, _resolve_state_file())
```

`_resolve_state_file` 已存在於 `src/gui/_helpers.py`，確認 `src/gui/routes/config.py` 的 import 區有帶它；沒有就加進既有的 `from src.gui._helpers import (...)` 清單。

- [ ] **Step 4: 測試通過**

Run: `timeout 900 ./venv/bin/python -m pytest tests/test_pce_flush.py tests/test_api_settings.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(pce-cache): clear every PCE-derived row when the target changes"
```

---

### Task 7: 前端的明示選擇流程

**Files:**
- Modify: `src/static/js/v2/areas/system.mjs`（PCE 連線表單的 `form.afterSave` / 儲存流程）
- Modify: `src/i18n_zh_TW.json`、`src/i18n_en.json`、`src/i18n/data/zh_explicit.json`
- Test: `tests/test_v2_system_e2e.py`、`tests/test_v2_shell_flows_e2e.py`、`tests/test_v2_coverage_live.py`

**Interfaces:**
- Consumes: Task 5 的 409 回應形狀 `{ok:false, pce_target_changed:true, old:{url,org_id}, new:{url,org_id}, error}`
- Produces: 無新導出。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_v2_system_e2e.py` 末尾加：

```python
def test_pce_target_change_asks_before_saving(v2_page):
    """改掉 URL 後按儲存，必須先跳出選擇，而不是直接存下去。"""
    page, base_url = v2_page
    _goto(page, base_url, R_PCE, "SY-18")

    url = page.locator('.board input[data-field="url"]')
    url.fill("https://another-pce.example.com:8443")
    assert url.input_value() == "https://another-pce.example.com:8443"

    page.get_by_role("button", name=_labels(page)["gui_save"], exact=True).first.click()

    modal = page.locator(".modal").first
    modal.wait_for(state="visible")
    text = modal.inner_text()
    assert "another-pce.example.com" in text, text
    assert "pce.example.com:8443" in text, text

    # 取消不得留下任何已儲存的痕跡：關掉後表單仍是改過但未存的狀態。
    modal.get_by_role("button", name=_labels(page)["gui_cancel"], exact=True).click()
    assert page.locator(".modal").count() == 0
```

> 以下四點 orchestrator 已在原始碼查證，照抄即可，**不要再自行探索**：
> `v2_page` fixture 產出的是 tuple `(page, base_url)`（`tests/v2_e2e_utils.py:290`），不是帶方法的物件；
> 導航用 `_goto(page, base_url, route, cov)`（`tests/test_v2_system_e2e.py:125`）；
> 按鈕名稱查表用 `_labels(page)`（`:150`），**`gui_save` 已在該表的 keys 清單裡**，新的按鈕文案若要在測試裡點，必須把鍵加進那份清單；
> 表單欄位定位用 `page.locator('.board input[data-field="url"]')`（既有測試 `:805` 就是這樣抓 key/secret 的）。

- [ ] **Step 2: 跑測試確認失敗**

Run: `timeout 900 ./venv/bin/python -m pytest tests/test_v2_system_e2e.py::test_pce_target_change_asks_before_saving -q`
Expected: FAIL（沒有 modal）

- [ ] **Step 3: 實作**

> 以下三個介面 orchestrator 已查證，照抄即可，不必再自行探索：
> `modal.confirm({title, impact, onOk})` 只有確定／取消兩顆按鈕（`components/modal.mjs`）；
> `confirmSpec(title, impact, onOk)` 是每個 area 各自複製的三參數小工具（`system.mjs:351`）；
> `makeForm()` 回傳的 `fapi.save()` 在 `res.ok !== true` 時只會 `toast.crit` 後回 false（`system.mjs` 約 690-706）。

**(a) `components/modal.mjs`：`confirm()` 增加選用的次要動作。** 這個決定是三向的（清除／同一台／取消），兩顆按鈕表達不了；`alt` 未給時行為與現在完全相同，既有呼叫端不受影響。

`confirm()` 沒有 `foot` 或 `okBtn` 這種區域變數（orchestrator 已讀過 `src/static/js/v2/components/modal.mjs:55-81` 查證）：OK 鈕是 `const ok`（`:59`），footer 是在 `box.appendChild(el("footer", …))` 的呼叫裡就地建構（`:77-81`），子節點依序是 `spacer()`、cancel 鈕、`ok`。所以次要動作要插進那個就地建構的參數串裡，位置在 cancel 與 `ok` 之間。

把 footer 那段改成：

```javascript
  /* Optional third choice, built before the footer so it can be dropped into
   * the same call. Omitted by every existing caller, and absent from the DOM
   * when omitted — a confirm stays two buttons unless the decision genuinely
   * has a third answer. */
  const alt = o.alt && o.alt.label
    ? el("button", { class: "btn", type: "button", text: o.alt.label })
    : null;
  if (alt) {
    alt.addEventListener("click", async function () {
      alt.disabled = true;
      try {
        const r = o.alt.onAlt ? await o.alt.onAlt() : undefined;
        if (r !== false) close();
      } finally { alt.disabled = false; }
    });
  }

  box.appendChild(el("footer", { class: "modal-f" },
    spacer(),
    el("button", { class: "btn ghost", type: "button", text: t("gui_cancel"), onClick: close }),
    alt,
    ok
  ));
```

> `el()` 忽略 null 子節點——orchestrator 已查證（`src/static/js/v2/core/dom.mjs:12,58`：`children: … | null (nullish skipped)`），所以 `alt` 為 null 時 footer 就是原本的兩顆按鈕，DOM 完全不變。

同時更新 `confirm()` 上方的 JSDoc，把 `alt` 列進去。

**(b) `system.mjs` 的 `confirmSpec()` 加第四個選用參數**：

```javascript
function confirmSpec(title, impact, onOk, alt) {
  return { title: title, impact: impact, onOk: onOk, alt: alt };
}
```

> 只改 `system.mjs` 這一份。其他 area 的同名複本不在本任務範圍，不要順手改。

**(c) `makeForm()` 增加兩個掛勾**（`system.mjs`）：

在 `fapi.save` 內，取得 `body` 之後、送出之前：

```javascript
    if (fapi.extraBody) { Object.assign(body, fapi.extraBody); fapi.extraBody = null; }
```

在同一個函式的失敗分支，把

```javascript
      if (!res || res.ok !== true) {
        toast.crit(errorText(res));
        return false;
      }
```

改成

```javascript
      if (!res || res.ok !== true) {
        /* A refusal the caller knows how to turn into a question is not an
         * error to shout about — it asks, then re-sends the same body with
         * the answer. Anything else still surfaces as a toast. */
        if (fapi.onRefused) {
          const handled = fapi.onRefused(res, body);
          if (handled) return Promise.resolve(handled);
        }
        toast.crit(errorText(res));
        return false;
      }
```

**(d) PCE 連線表單掛上處理**（`system.mjs` 的 `mountPce`，`form.setBody(...)` 之後）：

```javascript
    /* 409 + pce_target_changed is the appliance refusing to guess what should
     * happen to a previous PCE's cache. Ask, then re-send with the answer. */
    form.onRefused = function (res) {
      if (!res || res.pce_target_changed !== true) return false;
      return new Promise(function (resolve) {
        const m = modal.confirm(confirmSpec(t("gui_sy_pce_target_title"), [
          tf("gui_sy_pce_target_from", { url: res.old.url, org: res.old.org_id }),
          tf("gui_sy_pce_target_to", { url: res.new.url, org: res.new.org_id }),
          t("gui_sy_pce_target_flush_body"),
        ], function () {
          form.extraBody = { pce_target_change: "flush" };
          return form.save().then(resolve);
        }, {
          label: t("gui_sy_pce_target_same"),
          onAlt: function () {
            form.extraBody = { pce_target_change: "same-pce" };
            return form.save().then(resolve);
          },
        }));
        m.onClose(function () { resolve(false); });
      });
    };
```

新增 i18n 鍵（三份字典）：

| key | zh_TW | en |
|---|---|---|
| `gui_sy_pce_target_title` | 這會指向另一台 PCE | This points at a different PCE |
| `gui_sy_pce_target_from` | 目前：{url}（org {org}） | Now: {url} (org {org}) |
| `gui_sy_pce_target_to` | 改為：{url}（org {org}） | Changing to: {url} (org {org}) |
| `gui_sy_pce_target_flush_body` | 現有的快取、擷取位置與告警冷卻都是前一台 PCE 的資料，沒有任何標記說明這件事。清除後會從新的 PCE 重新擷取。 | The existing cache, fetch positions and alert cooldowns all hold the previous PCE's data, with nothing marking them as such. Clearing starts a fresh fetch from the new PCE. |
| `gui_sy_pce_target_same` | 同一台 PCE，只是換了位址 | Same PCE, new address |

- [ ] **Step 4: 測試與閘門通過**

```bash
timeout 900 ./venv/bin/python -m pytest tests/test_v2_system_e2e.py -q
timeout 300 ./venv/bin/python scripts/audit_i18n_usage.py
timeout 300 ./venv/bin/python -m pytest tests/test_i18n_no_reviewer_copy.py tests/test_i18n_zh_explicit_sync.py -q
```
Expected: 全綠 / `Total: 0 finding(s)`

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(gui-v2): ask before re-pointing the appliance at another PCE"
```

---

### Task 8: 全套測試、CHANGELOG 與真機驗證

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/guide/configuration.md`（升級說明段落）

- [ ] **Step 1: 全套測試**

Run: `timeout 5400 ./venv/bin/python -m pytest -q`（**背景執行並掛回叫等待器**；`ps` 顯示 pytest 存活後再繼續）
Expected: 0 failed。任何失敗都要修到綠，不得標記 xfail。

- [ ] **Step 2: 寫 CHANGELOG**

在 `CHANGELOG.md` 的 Unreleased 段落加入：

```markdown
### Removed
- PCE profiles. They were only ever a credential switcher — nothing downstream
  of `config.api` knew they existed — while the cache, ingestion watermarks,
  archive files and schedules carried one PCE's data with no marker saying so.
  Existing `pce_profiles` / `active_pce_id` entries in `config.json` are
  dropped on load; the appliance keeps using the connection settings under
  `api`, which already held the active profile's values. **A second profile's
  stored credentials are not migrated anywhere — copy them out before
  upgrading if you need them.**

### Changed
- Changing `api.url` or `api.org_id` now requires an explicit choice: clear the
  PCE-derived cache, watermarks, alert cooldowns and SIEM queue, or declare it
  the same PCE at a new address. Rotating the key/secret is unaffected.
```

- [ ] **Step 3: 升級說明**

`docs/guide/configuration.md` 加一段，講清楚：舊 config 的 profile 鍵會被丟棄、第二組以後的憑證不會遷移、要先自行抄出來。

- [ ] **Step 4: 部署測試機並真機驗證**

```bash
ssh root@172.16.15.106 'cd /root/illumio-ops && git pull --ff-only && systemctl restart illumio-ops'
```

逐項在 `https://172.16.15.106:5001` 上實看並記錄結果：

1. `#/system/pce` 沒有 profile 清單、沒有「新增 PCE」、沒有「切換至此 PCE」
2. 連線表單仍可正常儲存（只改 `verify_ssl` 或輪替 key/secret → 直接成功，不跳選擇）
3. 改掉 URL 按儲存 → 跳出選擇；選「同一台 PCE，只是換了位址」→ 存檔成功且快取筆數不變（`#/system/cache` 的事件／流量筆數）
4. 再改一次 URL → 選「清除」→ 快取筆數歸零、`#/investigate/traffic` 顯示空態而非舊資料
5. 用一份帶 `pce_profiles` 的舊 `config.json` 啟動 → 服務正常起來，log 出現 `Ignoring deprecated config key(s)`

**第 5 項要真的做**：在測試機上備份 `config/config.json`，手動塞回 `"pce_profiles": [{"id":1,"name":"old","url":"https://x:8443"}], "active_pce_id": 1`，重啟，確認服務起得來，再還原備份。

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md docs/guide/configuration.md
git commit -m "docs(changelog): record the PCE profile removal and the re-point guard"
```

---

## 自我檢查（撰寫時已執行）

- **Spec 覆蓋**：spec §4.5 的方案 A 有兩個構成要素——「profile 降級／移除」由 Task 1-4 覆蓋，「切換改成明示的破壞性操作」由 Task 5-7 覆蓋。§2.3 表列的全域狀態中，cache 七張表、watermark、cursor、SIEM queue／DLQ、state.json 的 PCE 衍生鍵由 Task 6 清除。**刻意不清**：archive 檔案（磁碟上的歷史資料，刪掉不可逆且未必是操作者的意思）、報表輸出與 history、`dashboard_summary.json`、`async_query_jobs.json`——這四項列在下方遺留事項，不在本計畫範圍。
- **佔位字掃描**：無 TBD／TODO；每個程式碼步驟都有可照抄的內容。Task 7 的 e2e helper 名稱與 `confirmSpec` 第四參數標記為「實作前先讀該檔確認」，而不是假裝知道——這是刻意的，因為那兩處的當下形狀我沒有查證。
- **型別一致性**：`flush_pce_derived_state(db_path: str, state_path: str) -> dict[str, int]` 在 Task 6 定義、Task 6 步驟 3 的路由呼叫端一致。`pce_target_change` 的兩個值 `"flush"` / `"same-pce"` 在 Task 5 定義、Task 7 使用，字面一致。

## 本計畫不處理（遺留事項）

- archive 目錄、報表輸出與 KPI history、`dashboard_summary.json`、`async_query_jobs.json` 的跨 PCE 殘留——移除 profile 之後這些只會在「操作者手動改連線目標」時被觸及，且刪除不可逆，需另案決定保留政策。
- 背景工作與連線變更的競態：目前沒有屏障阻止「清除當下正在跑的 ingest 把舊 PCE 的資料寫回去」。實務上視窗很短（清除是同步的、下一輪 ingest 才會重讀設定），但這是已知缺口，spec §2.2 有記錄。
