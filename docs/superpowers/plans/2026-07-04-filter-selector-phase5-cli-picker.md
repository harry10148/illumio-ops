# Filter 物件選擇器 Phase 5：CLI questionary picker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 `src/cli/object_picker.py`（questionary 兩段式物件選擇器：類別 → autocomplete 模糊搜尋、迴圈多選、離線/非 TTY 降級手動輸入），落地到 CLI 三個實際觸點（traffic/bandwidth 規則精靈、workload list、pce_cache_cli traffic filter），規則精靈同時升級為 4c flat 物件 key。

**Architecture:** picker 是無狀態函式元件：候選直呼 `ApiClient`（labels=get_all_labels、iplist=get_ip_lists、label_group=get_label_groups、workload=search_workloads），回傳分類 dict；呼叫端負責映射成 filter key。規則精靈每個方向槽（src include / dst include / ex src / ex dst）各呼叫一次 picker，取代 `'=' in x` 啟發式，產出 4c flat key（`src_labels`/`src_iplists`/`src_workloads`/`src_ip_in` list 與 ex 對應）——引擎與端點 4c 已支援；**規則情境 cats 排除 label_group**（4c 結構性不支援，與 Web 端一致）。非 TTY（pipe/CI/測試）與 PCE 離線一律降級為手動輸入，沿用 `_render.py` 的 isatty 慣例。

**Tech Stack:** Python、questionary>=2.0（已在 requirements.txt:24）、pytest（mock questionary 樣式照 tests/test_cli_rule_edit.py）。

**Spec:** `docs/superpowers/specs/2026-07-03-pce-style-filter-object-selector-design.md` §6。

## 設計定案（基於 2026-07-04 Explore 盤點，行號為 HEAD=0cc99e5 現場）

- **現場事實**：
  - `src/cli/object_picker.py` 不存在（新建）。spec 的「workload 列表互動模式」現場不存在互動模式——`src/cli/workload.py:24` `workload list` 只有 click flags（--env/--enforcement，client-side 過濾 :71-81）→ 最小落地：加 `--pick` 選項（TTY 時開 picker 選 label 過濾）。
  - traffic 精靈 `src/cli/menus/traffic.py`：src/dst 收值 :128/:137、ex :221/:232、`'='` 啟發式 :195-200/:238-243、rule dict 組裝 :263-287（**舊純量 key**）、寫入 `cm.add_or_update_rule`（config.py:505，直改 config["rules"] 不走 API）。bandwidth `src/cli/menus/bandwidth.py` 完全平行（:116/:125/:131-136/:213/:224/:230-235/:252-276）。
  - pce_cache_cli `_edit_traffic_filter`（src/pce_cache_cli.py:91，key 迴圈 :104-110）：`workload_label_env`/`exclude_src_ips` 用裸 `input()` comma 拆 list；schema `config_models.py:214/:217`（exclude_src_ips 有 IP field_validator :219）。**注意**：這兩個 key live ingest 未接線消費（jobs.py:119 未傳 traffic_filter）——既有 orphan wiring，**本批不處理**，記 follow-up。
  - questionary 慣例：module-level `questionary.text(...).unsafe_ask()`（cli/rule.py:101）；TTY 判定與樣式 `_render.py:237-240`/`:167 _QUESTIONARY_STYLE`；測試 mock 樣式 `tests/test_cli_rule_edit.py:29-32`（patch `questionary.X` + `.return_value.unsafe_ask.side_effect`）。autocomplete/select 為首次引入。
  - ApiClient 候選方法（CLI 短命行程直呼，不用 GUI module cache）：`get_all_labels()`（:583，錯誤回 []）、`get_ip_lists(pversion="active")`（:793）、`get_label_groups(pversion="active")`（:811）、`search_workloads(params)`（:686）。`ApiClient(cm)` 建構、支援 context manager。
- **picker 介面**（本批契約核心）：

```python
def pick_objects(api, cats, title, preselected=None, lang=None):
    """互動選取 filter 物件。回傳分類 dict：
    {"labels": ["app=erp", ...], "label_groups": ["PG-Prod", ...],
     "iplists": ["/orgs/1/.../ip_lists/7", ...], "workloads": ["/orgs/1/workloads/x", ...],
     "ips": ["10.0.0.1", "10.0.0.0/24", ...]}
    只回傳非空類別。cats 控制可選類別（規則情境不含 'label_group'）。
    preselected 同形 dict（編輯回填：先顯示既有值、可保留/清除）。
    非 TTY 或 PCE 候選載入失敗 → 逐類別降級 questionary/input 手動輸入（comma 拆 list）。"""
```

- **規則精靈 flat key 映射**（Task 2 用，per 槽）：labels→`{ex_}{dir}_labels`、iplists→`{ex_}{dir}_iplists`、workloads→`{ex_}{dir}_workloads`、ips→include `{dir}_ip_in` / exclude `ex_{dir}_ip`（皆 list）。新存規則**不再寫**舊純量 key；編輯舊規則時把舊純量值轉成 preselected 餵 picker（`src_label` scalar → labels:[v]、`src_ip_in` scalar → ips:[v]），存檔時舊 key 移除（與 4c PUT replace 語意一致——實作在 dict 組裝端，`add_or_update_rule` 不改）。
- **手動 key=value / IP 永遠保留**（spec 需求 + 降級路徑）：picker 類別選單含「手動輸入」項；非法 CIDR 不接受（照 exclude_src_ips validator 語意，picker 端做基本格式檢查即可）。
- **CLI i18n**：新 prompt 字串走既有 `t()`（menus 同款），`cli_pick_*` 鍵雙語同步。

## Global Constraints

- 程式內註解繁體中文、commit message 英文 conventional commits、不用 emoji。
- 只動各 Task 列出的檔案；不順手重構（'=' 啟發式僅在精靈接 picker 的兩檔移除；讀取端相容不動）。
- 新字串進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json` 雙語同步（`cli_pick_*` 前綴）。
- 每 Task 結尾跑該 Task 測試 + commit；Task 4 全量（基準以執行時 main 為準，約 2556 passed / 5 skipped）。
- **worktree 紀律**：每個 Bash 命令以絕對 worktree 路徑 `cd` 前綴，commit 前 `git rev-parse --show-toplevel` 驗證；controller 每 task 驗 parent SHA + `git branch --contains`。
- **測試驗真實鏈**：精靈/CLI 測試不 stub picker——非 TTY 降級路徑用 input patch 走完整流程斷言存檔結果；picker questionary 路徑單元測試用 module-level questionary mock（tests/test_cli_rule_edit.py 樣式）+ MagicMock api。
- 規則情境 cats 不含 label_group（4c 一致性）；pce_cache/workload 情境亦不需 label_group（無消費語意）。

---

### Task 1: `src/cli/object_picker.py` 元件 + 單元測試

**Files:**
- Create: `src/cli/object_picker.py`
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（`cli_pick_*` 鍵）
- Test: `tests/test_cli_object_picker.py`（新建）

**Interfaces:**
- Produces: `pick_objects(api, cats, title, preselected=None, lang=None) -> dict`（契約見設計定案）；內部 helper `_load_candidates(api, cat) -> list[tuple[display, value]]`（label→("app=erp","app=erp")、iplist→(name, href)、label_group→(name, name)、workload→(f"{name} ({hostname})", href)）。
- Consumes: `ApiClient.get_all_labels/get_ip_lists/get_label_groups/search_workloads`；`src/cli/_render.py` 的 `_QUESTIONARY_STYLE` 與 TTY 判定慣例（import 或同款邏輯，以現場可 import 性為準）。

- [ ] **Step 1: 寫失敗測試（新檔 tests/test_cli_object_picker.py）**

```python
from unittest.mock import MagicMock, patch


def _api():
    api = MagicMock()
    api.get_all_labels.return_value = [
        {"key": "app", "value": "erp", "href": "/orgs/1/labels/1"},
        {"key": "env", "value": "prod", "href": "/orgs/1/labels/2"},
    ]
    api.get_ip_lists.return_value = [{"name": "corp-vpn", "href": "/orgs/1/sec_policy/active/ip_lists/7"}]
    api.get_label_groups.return_value = [{"name": "PG-Prod", "href": "/orgs/1/sec_policy/active/label_groups/3"}]
    api.search_workloads.return_value = [{"name": "web01", "hostname": "web01.corp", "href": "/orgs/1/workloads/abc"}]
    return api


def test_pick_labels_via_questionary(monkeypatch):
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    with patch("questionary.select") as msel, patch("questionary.autocomplete") as mauto:
        # 第一輪選 Labels 類別、autocomplete 選 app=erp；第二輪選「完成」
        msel.return_value.unsafe_ask.side_effect = ["label", "__done__"]
        mauto.return_value.unsafe_ask.side_effect = ["app=erp"]
        out = op.pick_objects(_api(), cats=("label", "iplist", "workload", "ip"), title="src")
    assert out == {"labels": ["app=erp"]}


def test_pick_iplist_returns_href(monkeypatch):
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    with patch("questionary.select") as msel, patch("questionary.autocomplete") as mauto:
        msel.return_value.unsafe_ask.side_effect = ["iplist", "__done__"]
        mauto.return_value.unsafe_ask.side_effect = ["corp-vpn"]
        out = op.pick_objects(_api(), cats=("label", "iplist"), title="src")
    assert out == {"iplists": ["/orgs/1/sec_policy/active/ip_lists/7"]}


def test_cats_excludes_label_group(monkeypatch):
    # 規則情境：cats 不含 label_group → 類別選單不得出現該項
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    with patch("questionary.select") as msel:
        msel.return_value.unsafe_ask.side_effect = ["__done__"]
        op.pick_objects(_api(), cats=("label", "iplist", "workload", "ip"), title="src")
        choices = msel.call_args.kwargs.get("choices") or msel.call_args.args[1]
        assert not any("label_group" == getattr(c, "value", c) for c in choices)


def test_offline_falls_back_to_manual(monkeypatch):
    # 候選載入丟例外 → 該類別降級手動輸入（questionary.text），仍可完成
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: True)
    api = _api()
    api.get_all_labels.side_effect = Exception("pce down")
    with patch("questionary.select") as msel, patch("questionary.text") as mtext:
        msel.return_value.unsafe_ask.side_effect = ["label", "__done__"]
        mtext.return_value.unsafe_ask.side_effect = ["env=dev"]
        out = op.pick_objects(api, cats=("label",), title="src")
    assert out == {"labels": ["env=dev"]}


def test_non_tty_manual_path(monkeypatch):
    # 非 TTY：逐類別 input() comma 拆 list，跳過 questionary
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: False)
    inputs = iter(["app=erp, env=prod", "", "", "10.0.0.0/24"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    out = op.pick_objects(_api(), cats=("label", "iplist", "workload", "ip"), title="src")
    assert out == {"labels": ["app=erp", "env=prod"], "ips": ["10.0.0.0/24"]}


def test_invalid_cidr_rejected(monkeypatch):
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: False)
    inputs = iter(["", "999.1.1.1, 10.0.0.1"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    out = op.pick_objects(_api(), cats=("label", "ip"), title="src")
    assert out == {"ips": ["10.0.0.1"]}


def test_preselected_backfill(monkeypatch):
    # 編輯回填：preselected 直接帶入結果（非 TTY 空輸入=保留）
    from src.cli import object_picker as op
    monkeypatch.setattr(op, "_interactive_ok", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    out = op.pick_objects(_api(), cats=("label", "ip"), title="src",
                          preselected={"labels": ["app=old"], "ips": ["1.2.3.4"]})
    assert out == {"labels": ["app=old"], "ips": ["1.2.3.4"]}
```

註：`_interactive_ok` 為 picker 內 TTY 判定 helper（測試以 monkeypatch 切換）；questionary mock 形狀（select 的 choices 取用方式）以實作為準微調，但**斷言語意不可弱化**。

Run: `python3 -m pytest tests/test_cli_object_picker.py -v`
Expected: FAIL（模組不存在）。

- [ ] **Step 2: 實作 src/cli/object_picker.py**

結構（完整實作由 implementer 依測試與下列骨架完成；prompt 字串全走 `t()` 新鍵 `cli_pick_category`/`cli_pick_search`/`cli_pick_manual`/`cli_pick_done`/`cli_pick_offline_hint`/`cli_pick_selected`/`cli_pick_manual_input`）：

```python
"""CLI 物件選擇器：questionary 兩段式（類別 → autocomplete），與 Web FilterBar 同語意。
候選直呼 ApiClient（cached 三類 + workload 即時）；PCE 離線或非 TTY 降級手動輸入。"""
import ipaddress
import sys

import questionary

from src.i18n import t

_CAT_ORDER = ("label", "label_group", "iplist", "workload", "ip")


def _interactive_ok():
    # 與 _render.py 同慣例：非 TTY（pipe/CI/測試）不走 questionary
    return sys.stdin.isatty() and sys.stdout.isatty()


def _valid_ip_or_cidr(text):
    try:
        if "/" in text:
            ipaddress.ip_network(text, strict=False)
        else:
            ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _load_candidates(api, cat):
    # 回傳 [(display, value)]；value 是要存進 filter 的字串（label 用 key=value、物件用 href、label_group 用名稱）
    if cat == "label":
        return [(f"{l['key']}={l['value']}", f"{l['key']}={l['value']}") for l in api.get_all_labels()]
    if cat == "iplist":
        return [(ipl["name"], ipl["href"]) for ipl in api.get_ip_lists()]
    if cat == "label_group":
        return [(g["name"], g["name"]) for g in api.get_label_groups()]
    if cat == "workload":
        return [(f"{w.get('name') or w.get('hostname')} ({w.get('hostname', '')})", w["href"])
                for w in api.search_workloads({"max_results": 200})]
    return []


_CAT_RESULT_KEY = {"label": "labels", "label_group": "label_groups",
                   "iplist": "iplists", "workload": "workloads", "ip": "ips"}
```

主函式 `pick_objects`：
1. 結果初始化為 `dict(preselected or {})`（淺拷貝、只留非空）。
2. 非 TTY：對 cats 逐類別 `input()`（prompt 顯示既有值），空輸入=保留 preselected，comma 拆 list；`ip` 類逐值 `_valid_ip_or_cidr` 過濾（無效值略過並印提示）。回傳非空類別。
3. TTY：迴圈 `questionary.select`（choices=cats 內類別 + 手動 IP/CIDR + 完成 `__done__`，style 沿 `_QUESTIONARY_STYLE` 可 import 則用）→ 選類別後 `_load_candidates` try/except（失敗印 `cli_pick_offline_hint` 後 `questionary.text` 手動輸入）→ 成功則 `questionary.autocomplete`（choices=display 清單，選定後映射 value）→ append 進結果對應 key（去重）→ 顯示已選清單（`cli_pick_selected`）→ 迴圈直到 `__done__`。
4. 回傳只含非空類別的 dict。

- [ ] **Step 3: 跑測試** `python3 -m pytest tests/test_cli_object_picker.py -v` → 全 PASS；`python3 scripts/audit_i18n_usage.py` → 0 findings。

- [ ] **Step 4: Commit**

```bash
git add src/cli/object_picker.py tests/test_cli_object_picker.py src/i18n_en.json src/i18n_zh_TW.json
git commit -m "feat(cli): questionary object picker with offline and non-tty fallback"
```

---

### Task 2: traffic + bandwidth 規則精靈接 picker（flat key 化）

**Files:**
- Modify: `src/cli/menus/traffic.py`（收值 :128/:137/:221/:232、啟發式 :195-200/:238-243、dict 組裝 :263-287）
- Modify: `src/cli/menus/bandwidth.py`（對應段）
- Test: `tests/test_manage_rules_menu.py`（追加/調整）

**Interfaces:**
- Consumes: `pick_objects(api, cats=("label", "iplist", "workload", "ip"), title, preselected)`（**無 label_group**——4c 規則不支援）；`ApiClient(cm)`。
- Produces: rule dict 用 4c flat key：`src_labels`/`dst_labels`/`ex_src_labels`/`ex_dst_labels`/`src_iplists`/.../`src_workloads`/.../`src_ip_in`/`dst_ip_in`/`ex_src_ip`/`ex_dst_ip`（list）。新存規則不寫舊純量 key；編輯舊規則時舊純量值轉 preselected、存檔時移除舊 key（pop 舊 8 key）。

- [ ] **Step 1: 寫失敗測試（非 TTY 手動路徑走真實鏈，不 stub picker）**

沿 tests/test_manage_rules_menu.py 既有樣式（patch input 序列 + 假 cm），新增：

```python
def test_traffic_wizard_saves_flat_object_keys(...):
    # input 序列走完精靈：name/pd/... src 槽輸入 "app=erp, app=web"（label 類）
    # 與 "10.0.0.1"（ip 類）、dst 槽空、ex 槽空 ...
    # 斷言 cm.config["rules"][-1]：
    assert rule["src_labels"] == ["app=erp", "app=web"]
    assert rule["src_ip_in"] == ["10.0.0.1"]
    assert "src_label" not in rule          # 不再寫舊純量 key


def test_traffic_wizard_edit_legacy_rule_migrates_keys(...):
    # edit_rule 帶舊純量 key（src_label="app=old", src_ip_in="1.2.3.4"）
    # 非 TTY 空輸入=保留 → 存檔後：
    assert rule["src_labels"] == ["app=old"]
    assert rule["src_ip_in"] == ["1.2.3.4"]  # scalar → list
    assert "src_label" not in rule           # 舊 key 已移除
```

（bandwidth 對應各一；input 序列以現場精靈實際 prompt 順序為準——實作者先走讀兩精靈流程再寫序列，測試需能在無 questionary 下執行=非 TTY 降級路徑。）

Run: `python3 -m pytest tests/test_manage_rules_menu.py -v -k "flat or migrates"`
Expected: FAIL。

- [ ] **Step 2: 實作**

兩精靈各自：
1. src/dst/ex_src/ex_dst 四個收值點改為 `pick_objects(api, cats=("label", "iplist", "workload", "ip"), title=<i18n>, preselected=<編輯時由舊 rule 轉換>)`——`api` 用 `with ApiClient(cm) as api:` 包住精靈 filter 段（或每槽建構，以現場資源管理慣例為準）。
2. 刪除 `'=' in x` 啟發式段。
3. dict 組裝：picker 結果映射 flat key（labels→`{dir}_labels`、iplists→`{dir}_iplists`、workloads→`{dir}_workloads`、ips→include `{dir}_ip_in`/exclude `ex_{dir}_ip`）；只放非空 key；編輯時 pop 舊 8 純量 key（`src_label`/`dst_label`/`src_ip_in` scalar 判斷——注意 `src_ip_in` 新舊同名不同型：舊 scalar 已轉 preselected，組裝時一律寫 list）。
4. preselected 轉換 helper（放精靈檔或 object_picker.py，二精靈共用則放後者）：`legacy_rule_to_preselected(rule, dir_prefix, exclude) -> dict`。

- [ ] **Step 3: 跑測試** `python3 -m pytest tests/test_manage_rules_menu.py tests/test_cli_object_picker.py tests/test_analyzer_object_filters.py -q` → 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add src/cli/menus/traffic.py src/cli/menus/bandwidth.py tests/test_manage_rules_menu.py src/cli/object_picker.py
git commit -m "feat(cli): rule wizards use object picker and emit flat filter keys"
```

---

### Task 3: workload list --pick + pce_cache_cli 接 picker

**Files:**
- Modify: `src/cli/workload.py`（`list_workloads` :24 加 `--pick` flag）
- Modify: `src/pce_cache_cli.py`（`_edit_traffic_filter` :91 的 `workload_label_env`/`exclude_src_ips` 兩 key）
- Test: `tests/test_cli_workload_list.py`、`tests/test_pce_cache_menu.py`（追加）

**Interfaces:**
- Consumes: `pick_objects`。
- Produces: `workload list --pick`：TTY 時開 picker（cats=("label",)），選出的 labels 轉 env/label client-side 過濾條件（與既有 --env 過濾同語意：任一選中 label 命中即保留；非 TTY + --pick → 提示並忽略）。pce_cache：`workload_label_env` 用 picker（cats=("label",)，候選過濾 env dimension——`get_labels("env")` 或 get_all_labels 篩 key=="env"，**存 value 字串**與既有格式一致）；`exclude_src_ips` 用 picker（cats=("ip",)，沿用 schema validator 語意）；`actions`/`protocols` 兩 key 維持原 input 不動。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_cli_workload_list.py 追加
def test_workload_list_pick_filters_by_selected_label(...):
    # patch pick_objects 回 {"labels": ["env=Production"]}？——不 stub 真實鏈：
    # 非 TTY 模式 --pick 走 input 降級（monkeypatch _interactive_ok True + questionary mock 亦可，
    # 擇一但斷言結果=只列 env=Production 的 workload）
    ...

# tests/test_pce_cache_menu.py 追加
def test_traffic_filter_env_and_ips_via_picker(...):
    # 非 TTY input 序列：actions 空、protocols 空、env 槽 "Production"、ips 槽 "10.0.0.0/24"
    # 斷言 config pce_cache.traffic_filter.workload_label_env == ["Production"]
    #      exclude_src_ips == ["10.0.0.0/24"]
```

（實作細節以現場測試檔樣式為準；pce_cache 測試沿既有 patch input 樣式，走 picker 非 TTY 降級=真實鏈。）

- [ ] **Step 2: 實作**（workload --pick 在 TTY 開 picker 後把 labels 併入既有 client-side 過濾；pce_cache 兩 key 換 `pick_objects` 呼叫、env 候選=get_all_labels 篩 `key == "env"` 的 value、存 value 字串 list；其他 key 原樣。）

- [ ] **Step 3: 跑測試** `python3 -m pytest tests/test_cli_workload_list.py tests/test_pce_cache_menu.py tests/test_cli_object_picker.py -q` → 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add src/cli/workload.py src/pce_cache_cli.py tests/test_cli_workload_list.py tests/test_pce_cache_menu.py
git commit -m "feat(cli): object picker for workload list and pce-cache traffic filter"
```

---

### Task 4: 全量回歸 + i18n + 實機煙霧（controller）

- [ ] **Step 1: 全量** `python3 -m pytest tests/ -q`（基準約 2556 passed）。
- [ ] **Step 2: i18n 稽核** `python3 scripts/audit_i18n_usage.py` → 0 findings。
- [ ] **Step 3: 實機煙霧（CLI 無瀏覽器——雙軌）**：
  1. **真實 PCE 候選載入**：python 直呼 `_load_candidates(ApiClient(cm), cat)` 四類各一次，驗回傳非空且形狀正確（真實 label/iplist href）。
  2. **非 TTY 端到端**：echo input 序列 | 跑 traffic 精靈（或 pytest 已覆蓋——跑一次真 CLI 進程驗非 TTY 降級不掛）；`illumio-ops rule ...` 精靈產出的規則以 `python3 -c` 讀 alerts.json 驗 flat key。
  3. TTY questionary 路徑：測試已用 mock 覆蓋；實機 TTY 互動無法自動化——記錄限制，靠 Task 1 單元測試 + 使用者日後手動體驗。
- [ ] **Step 4: 回報 + 收尾**：final whole-branch review → --no-ff merge（merge-tree 預檢）→ push。**明列**：pce_cache traffic_filter live ingest 未接線消費（既有 orphan，非本批）；規則精靈 label_group 不提供（4c 一致）；TTY 互動路徑無自動化 E2E（mock 覆蓋）。

---

## Self-Review 紀錄

- **Spec §6 覆蓋**：兩段式 questionary + autocomplete → Task 1；候選 ApiClient 四類 → Task 1 `_load_candidates`；離線降級 → Task 1（例外→手動 + 提示）；四落點 → Task 2（traffic/bandwidth）+ Task 3（workload list 以 --pick 最小落地、pce_cache 兩 key）；手動輸入永遠保留 → 類別選單含手動項 + 非 TTY 全手動。
- **與 4c 一致性**：規則情境 cats 無 label_group；flat key 映射 = `_RULE_FB_KEYS` 子集（CLI 不產 any_* ——精靈無任一側槽，spec 未要求，YAGNI）；編輯遷移 pop 舊 key = 4c PUT replace 語意。
- **型別一致性**：`pick_objects` 回傳 dict 鍵（labels/label_groups/iplists/workloads/ips）Task 1 定義、Task 2/3 消費；`_interactive_ok` 測試切換點三個 Task 測試共用。
- **已知不確定點（任務內標註）**：精靈 input 序列的實際 prompt 順序（Task 2 現場走讀）；`_QUESTIONARY_STYLE` 可否直接 import（Task 1 現場）；workload --pick 的過濾合併語意細節（Task 3 與既有 --env 過濾對齊）；questionary mock 的 choices 取用形狀（Task 1 微調不弱化斷言）。
- **Placeholder 掃描**：picker 骨架含完整 helper 與非 TTY 邏輯描述、測試給可執行碼；Task 2/3 測試給斷言核心 + 現場樣式對位點（input 序列本質上必須現場走讀，已明標）。
