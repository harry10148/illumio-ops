# Observability Residuals Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收清 2026-07-16 Phase A 觀測性交付的 8 項殘債、補 docs_check 的 verified_against 存在性檢查，並移除 traffic-workload 分頁的「過去 7 天流量趨勢」圖（使用者裁決：無價值）。

**Architecture:** 全部是既有子系統的小型修復：job_health 儲存層（prune）、rule_scheduler tick 持久化（寫入節流）、GUI 前端（stale 判定、錯誤透傳、間隔顯示、API 失敗處理）、gui/_helpers openssl 呼叫（timeout）、docs_check 腳本（新檢查）、趨勢圖全鏈移除（HTML/JS/CSS/路由/測試/i18n）。

**Tech Stack:** Python 3.10+（Flask、APScheduler、pytest）、vanilla JS（CSP 嚴格、無 inline handler）、i18n 雙 JSON。

## Global Constraints

- Commit message 用英文 conventional commits（repo 慣例），內文與 UI 文案繁體中文、一律無 emoji。
- JS 檔**禁止行尾 CJK 註解**（Cat C 教訓：行尾中文註解曾令壓縮/審查工具誤判）；註解獨立成行。
- 測試只用 `tmp_path`，不落地 repo 目錄。
- 四個 CI 硬閘不得紅：`scripts/check_no_naive_datetime.py`、`scripts/check_doc_links.py`、`scripts/audit_i18n_usage.py`、`mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py`。
- i18n 鍵：新增/刪除必須 en 與 zh_TW 兩檔同步，且與使用點同一 commit（audit_i18n_usage 會抓孤兒）。
- 全套 pytest 數字必須本人親跑確認（不可只信 subagent 回報）。
- 工作在獨立 worktree 分支 `hardening-residuals` 進行（superpowers:using-git-worktrees）。

---

### Task 1: job_health 孤兒條目 prune

`logs/job_health.json` 只增不減：job 改名或條件性 job（如 tls_renew_check）停用後，舊條目永遠留在檔內且被 `_overview_job_health` 判為 warn（逾期），面板累積假警報。修法：scheduler 完成全部註冊後，以「本次實際註冊的 job id 集合」修剪儲存。

**Files:**
- Modify: `src/job_health.py`（新增 `prune_job_health`）
- Modify: `src/scheduler/__init__.py`（所有 `add_job` 完成後、`return sched` 前呼叫）
- Test: `tests/test_job_health.py`

**Interfaces:**
- Produces: `prune_job_health(active_job_ids: Iterable[str]) -> None`

- [ ] **Step 1: 寫失敗測試**（沿用 `tests/test_job_health.py` 既有的 `_job_health_file` monkeypatch 慣例——先讀該檔開頭 fixture，照抄同款寫法）

```python
def test_prune_job_health_removes_orphans(tmp_path, monkeypatch):
    monkeypatch.setattr(job_health, "_job_health_file",
                        lambda: str(tmp_path / "job_health.json"))
    job_health.record_job_registered("keep_me", 60)
    job_health.record_job_run("keep_me", "ok")
    job_health.record_job_registered("orphan", 60)
    job_health.prune_job_health(["keep_me"])
    data = job_health.load_job_health()
    assert "keep_me" in data
    assert "orphan" not in data
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_job_health.py -v -k prune`
Expected: FAIL（`AttributeError: ... no attribute 'prune_job_health'`）

- [ ] **Step 3: 實作 `prune_job_health`**（加在 `record_job_run` 之後）

```python
def prune_job_health(active_job_ids) -> None:
    """移除不在本次註冊清單中的孤兒條目。

    job 改名或條件性 job 停用後，殘留條目會被 overview 永久判 warn
    （2026-07-16 Phase A 殘債）。每次 scheduler 建立時以實際註冊
    集合修剪一次。
    """
    active = set(active_job_ids)

    def _merge(data: dict) -> dict:
        return {k: v for k, v in data.items() if k in active}

    _safe_update(_merge)
```

- [ ] **Step 4: 接線 scheduler** — 在 `src/scheduler/__init__.py` 中找到 `return sched` 前（全部 `add_job` 之後），加：

```python
    # 修剪孤兒 job_health 條目：改名/停用的 job 不得永久佔據 warn
    from src.job_health import prune_job_health
    prune_job_health([j.id for j in sched.get_jobs()])
```

注意：`_instrument` 傳入的 job_id 字串與 `add_job(id=...)` 一致（逐一核對六處以上呼叫點），故 `sched.get_jobs()` 的 id 集合即有效集合。

- [ ] **Step 5: 跑測試確認通過＋相關套件不紅**

Run: `pytest tests/test_job_health.py tests/test_gui_job_health_panel.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit** — `fix(job-health): prune orphaned entries at scheduler startup`

---

### Task 2: posture stale 判定改錨定 source_date（前端）

`dashboard.js:1489` 以 `generated_at`＋30 分鐘門檻判 stale，但 `generated_at` 是 posture_summary job 的重算時戳（每 600s 刷新）；真正的資料日期是 `source_date`（日更 traffic snapshot 的 generated_at，見 `src/scheduler/jobs.py:386`）。現行判定既測不到「快照停更」（job 活著就永遠新鮮），又會在 job 間隔調大時誤報。job 停跑一節已由 Job Health 表涵蓋，前端 stale 應反映**資料**新鮮度。

**Files:**
- Modify: `src/static/js/dashboard.js:1489`（stale 判定）與 `:1532-1535`（stale 標示行的時戳）

**Interfaces:**
- Consumes: overview API 的 `posture.source_date`（已存在，格式 ISO 字串，可能為空字串）

- [ ] **Step 1: 修改 `_renderPostureHero`**

1489 行改為（26h = 日更節奏 + 2h 寬限；source_date 缺失時退回 generated_at 舊行為）：

```js
  // posture 資料源是日更 traffic snapshot：新鮮度看 source_date（26h）。
  // generated_at 只是 10 分鐘級重算時戳；job 停跑由 Job Health 表涵蓋。
  var postureTs = posture.source_date || posture.generated_at;
  var postureStale = _ovStale(postureTs, 26 * 60 * 60 * 1000);
```

1532-1535 的 stale 標示行把 `posture.generated_at` 兩處改用 `postureTs`：

```js
    if (postureStale) {
      html += '<div style="font-size:11px;color:var(--dim);width:100%;">' + (postureTs
            ? T('gui_ov_stale_since', 'stale') + ' ' + _fmtAge((Date.now() - Date.parse(postureTs)) / 1000)
            : T('gui_jh_never_ran', 'never ran')) + '</div>';
    }
```

- [ ] **Step 2: 語法檢查**

Run: `node --check src/static/js/dashboard.js`
Expected: 無輸出（通過）

- [ ] **Step 3: Commit** — `fix(gui): posture stale indicator anchors to snapshot source_date, not recompute timestamp`

---

### Task 3: rule tick 純心跳不再全量重寫 state.json

`rule_scheduler.py:248` 每個 tick（預設 300s）替每條 schedule 記 `last_checked`，`:356-375` 因此每 tick 全量重寫共享的 `logs/state.json`（report scheduler、watermark 等同檔）。修法：純 `last_checked` 心跳至多每 900s 落盤一次；有動作/錯誤/新增/待修剪條目照舊立即寫。

**Files:**
- Modify: `src/rule_scheduler.py`（模組常數＋`check` 尾端持久化區塊）
- Test: `tests/test_rule_scheduler.py`

**Interfaces:**
- Produces: 模組常數 `_CHECK_PERSIST_GAP_S = 900`（測試會 monkeypatch）

- [ ] **Step 1: 寫失敗測試**（沿用 `tests/test_rule_scheduler.py` 既有 ScheduleDB/engine harness 慣例：mock api 的 `get_live_item` 回 (200, {"enabled": <target>}) 使 tick 無動作、`has_draft_changes` 回 False；state 檔以既有慣例導向 tmp_path——先讀該檔確認 `_resolve_rule_state_file` 的 monkeypatch 寫法）

```python
def test_pure_heartbeat_tick_skips_state_rewrite(tmp_path, monkeypatch):
    # arrange: 一條 recurring schedule、PCE 已在目標態（無動作）
    # state file 導向 tmp_path
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(rule_scheduler, "_resolve_rule_state_file",
                        lambda: str(state_file))
    engine = _make_engine_with_one_noop_schedule()  # 依該檔既有 helper 組裝
    engine.check(silent=True, tz_str="UTC")
    first = state_file.read_bytes()
    engine.check(silent=True, tz_str="UTC")
    assert state_file.read_bytes() == first  # 900s 內純心跳不重寫

def test_heartbeat_persists_after_gap(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(rule_scheduler, "_resolve_rule_state_file",
                        lambda: str(state_file))
    monkeypatch.setattr(rule_scheduler, "_CHECK_PERSIST_GAP_S", 0)
    engine = _make_engine_with_one_noop_schedule()
    engine.check(silent=True, tz_str="UTC")
    first = state_file.read_bytes()
    engine.check(silent=True, tz_str="UTC")
    assert state_file.read_bytes() != first  # gap 歸零則每次都寫
```

（若該檔沒有現成可複用的 helper，就在測試檔內建一個最小 `_make_engine_with_one_noop_schedule`：dict-backed ScheduleDB stub＋Mock api，照該檔 767 行附近既有測試的組法。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_rule_scheduler.py -v -k heartbeat`
Expected: 第一個測試 FAIL（目前每 tick 都重寫）

- [ ] **Step 3: 實作** — `rule_scheduler.py` 模組層加常數：

```python
# 純 last_checked 心跳的落盤節流（秒）：有動作/錯誤/成員變動照舊立即寫
_CHECK_PERSIST_GAP_S = 900
```

`check()` 尾端持久化區塊（356-375 行）改為：

```python
        if tick_states:
            try:
                from src.state_store import load_state_file, update_state_file

                state_file = _resolve_rule_state_file()
                prev_states = (load_state_file(state_file) or {}).get(_RULE_STATE_KEY) or {}
                live_hrefs = set(self.db.get_all())
                # 「有料」= 任一條目帶動作/結果/錯誤、成員新增、或有待修剪殘留
                meaningful = (
                    any(set(st) - {"last_checked"} for st in tick_states.values())
                    or any(h not in prev_states for h in tick_states)
                    or any(h not in live_hrefs and h not in tick_states for h in prev_states)
                )
                skip = False
                if not meaningful:
                    # 純心跳：至多每 _CHECK_PERSIST_GAP_S 落盤一次，避免每個
                    # tick 全量重寫共享 state.json（2026-07-23 觀測性殘債）
                    newest = max((str(st.get("last_checked") or "")
                                  for st in prev_states.values()), default="")
                    try:
                        newest_dt = datetime.datetime.strptime(
                            newest, "%Y-%m-%dT%H:%M:%SZ").replace(
                            tzinfo=datetime.timezone.utc)
                        age = (datetime.datetime.now(datetime.timezone.utc)
                               - newest_dt).total_seconds()
                        skip = age < _CHECK_PERSIST_GAP_S
                    except ValueError:
                        skip = False  # 無法解析（含空檔）一律落盤修復
                if not skip:
                    def _merge(data):
                        states = dict(data.get(_RULE_STATE_KEY) or {})
                        for h in list(states):
                            if h not in live_hrefs and h not in tick_states:
                                states.pop(h)
                        for h, st in tick_states.items():
                            cur = dict(states.get(h) or {})
                            cur.update(st)
                            states[h] = cur
                        data[_RULE_STATE_KEY] = states
                        return data

                    update_state_file(state_file, _merge)
            except Exception:
                logger.opt(exception=True).debug("rule schedule state persist failed")

        return logs
```

（`_merge` 內容與現行相同，只是外面包了 skip 判斷；`live_hrefs` 提到外層共用。）

- [ ] **Step 4: 跑測試確認通過＋整檔不紅**

Run: `pytest tests/test_rule_scheduler.py tests/test_rule_scheduler_cli.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit** — `fix(rule-scheduler): throttle pure-heartbeat state.json rewrites to 15min`

---

### Task 4: rule 排程錯誤欄位透傳前端

engine 已把錯誤記進 state（`rule_scheduler.py:331/343/348` 的 `error` 欄位），但 `gui/routes/rule_scheduler.py:253-256` 只透傳 last_checked/last_action/last_result，前端只顯示「 !」尾綴，操作者看不到錯誤內容。

**Files:**
- Modify: `src/gui/routes/rule_scheduler.py:256` 後加一行
- Modify: `src/static/js/rule-scheduler.js:538-546`
- Test: 先 `grep -rn "rs_schedules_list\|/api/rule_scheduler/schedules" tests/` 找既有路由測試；有就擴充斷言，沒有就只做前端＋路由手動驗證（本 task 不新建路由測試 harness）

**Interfaces:**
- Produces: schedules API 條目新欄位 `last_error: str | None`

- [ ] **Step 1: 路由透傳** — `rs_schedules_list` 中 `entry['last_result'] = st.get('last_result')` 之後加：

```python
                entry['last_error'] = st.get('error')
```

- [ ] **Step 2: 前端顯示** — `rule-scheduler.js` 538-546 行改為（title 屬性帶完整錯誤，滑過可見；先確認該檔的 `h()` helper 支援 `title` 一般屬性——grep `function h(` 看實作，若 attrs 是 setAttribute 泛用即可直接用）：

```js
      // Last run cell: last_checked timestamp plus optional action/result suffix.
      // On error, tint the cell and surface the recorded error text via title.
      let lastTd;
      if (s.last_checked) {
        const resTxt = s.last_result === 'error' ? ' !' : '';
        const text = s.last_checked + (s.last_action ? (' (' + s.last_action + resTxt + ')') : '');
        const attrs = s.last_result === 'error'
          ? { style: { color: 'var(--danger)' }, title: s.last_error || '' }
          : null;
        lastTd = h('td', attrs, text);
      } else {
        lastTd = h('td', null, _t('gui_jh_never_ran'));
      }
```

- [ ] **Step 3: 驗證**

Run: `node --check src/static/js/rule-scheduler.js && pytest tests/test_rule_scheduler.py -v`（若 Step 0 grep 有找到路由測試，一併跑）
Expected: 通過

- [ ] **Step 4: Commit** — `fix(rule-scheduler): surface per-schedule engine error text to GUI`

---

### Task 5: gui/_helpers openssl subprocess 全面加 timeout

`_helpers.py` 內 6 處 `subprocess.run`（`grep -n 'subprocess.run' src/gui/_helpers.py` → 496、646、779、828、841、847 行）全部無 timeout；openssl 卡住會吊死呼叫者（含 TLS 日更 job 與 dashboard overview）。類不點：六處一次修。

**Files:**
- Modify: `src/gui/_helpers.py`（6 處）
- Test: `tests/` 中先 `grep -rln '_cert_days_remaining\|_get_cert_info' tests/` 找既有測試檔（觀測記錄顯示這些函式已有 monkeypatch 慣例）；擴充其一

**Interfaces:** 無簽名變更；行為變更 = openssl 逾時視同「不可得」（回 None／略過），不再無限等。

- [ ] **Step 1: 寫失敗測試**（放進既有 cert 測試檔；若無則新建 `tests/test_cert_helpers_timeout.py`）

```python
import subprocess
from src.gui import _helpers


def test_cert_days_remaining_survives_openssl_hang(tmp_path, monkeypatch):
    cert = tmp_path / "x.pem"
    cert.write_text("dummy")

    def _hang(*a, **kw):
        assert kw.get("timeout"), "openssl calls must carry a timeout"
        raise subprocess.TimeoutExpired(cmd="openssl", timeout=kw["timeout"])

    monkeypatch.setattr(subprocess, "run", _hang)
    assert _helpers._cert_days_remaining(str(cert)) is None


def test_get_cert_info_survives_openssl_hang(tmp_path, monkeypatch):
    cert = tmp_path / "x.pem"
    cert.write_text("dummy")

    def _hang(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="openssl", timeout=kw.get("timeout", 0))

    monkeypatch.setattr(subprocess, "run", _hang)
    info = _helpers._get_cert_info(str(cert))
    assert info["exists"] is True  # 不炸、回可用 dict
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/ -v -k openssl_hang`
Expected: FAIL（TimeoutExpired 未被接住往外炸）

- [ ] **Step 3: 實作** — 六處 `subprocess.run([...openssl...])` 逐一加 `timeout=15`，並把各自的 `except` 子句補上 `subprocess.TimeoutExpired`：
  - `_cert_days_remaining`（779）：`except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired): return None`
  - `_get_cert_info`（828、841、847）：逐呼叫檢視——維持函式契約「失敗回已知欄位的 dict」；哪裡原本捕 `CalledProcessError` 就併捕 `TimeoutExpired`
  - 496、646 兩處：先讀上下文（各是哪個 openssl 操作），同樣加 `timeout=15` 並把 TimeoutExpired 併入該處既有錯誤路徑（不可新增未定義行為；若該處以 raise RuntimeError 收斂，就讓 TimeoutExpired 也轉成同款 RuntimeError）

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/ -v -k "openssl_hang or cert"`
Expected: 全 PASS

- [ ] **Step 5: Commit** — `fix(gui): add timeouts to all openssl subprocess calls`

---

### Task 6: actions API 失敗/429 前端如實呈現＋test-alert 限流放寬

後端 429 已回 JSON `{ok:false, error:"rate_limit_exceeded", description:"..."}`（`gui/__init__.py:374-381`），但 `actions.js` 各 runner 拿到 `ok:false` 仍走成功路徑：`alog(r.output || done)` 印「done」、toast「completed」——429 訊息近空白＋永遠 completed 是同一類 bug。另 test-alert `10 per hour` 對逐通道測試太緊（5 通道測兩輪即打滿），放寬到 30。

**Files:**
- Modify: `src/static/js/actions.js`（新 helper＋各 runner）
- Modify: `src/gui/routes/actions.py:493`（limit 字串）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（新增 2 鍵）
- Test: `grep -rn '10 per hour' tests/` 若有斷言 test-alert 限流值的測試同步改

**Interfaces:**
- Produces: `_apiFailed(r) -> boolean`（actions.js 內部）；i18n 鍵 `gui_err_rate_limited`、`gui_action_failed`

- [ ] **Step 1: i18n 鍵**（兩檔同步、字母序插入）

`i18n_en.json`：

```json
  "gui_action_failed": "Action failed",
  "gui_err_rate_limited": "Rate limit hit ({description}) - please retry later",
```

`i18n_zh_TW.json`：

```json
  "gui_action_failed": "操作失敗",
  "gui_err_rate_limited": "操作過於頻繁，已被限流（{description}），請稍後再試",
```

- [ ] **Step 2: actions.js 加 helper**（放在 `runAction` 前）

```js
// API responses use {ok:false, error, description} on failure (incl. 429
// rate_limit_exceeded from gui/__init__.py). Runners must not toast
// "completed" for these.
function _apiFailed(r) {
  if (!r || r.ok !== false) return false;
  const msg = r.error === 'rate_limit_exceeded'
    ? _t('gui_err_rate_limited').replace('{description}', r.description || '')
    : (r.error || r.description || _t('gui_action_failed'));
  alog(msg);
  toast(msg, 'err');
  return true;
}
```

- [ ] **Step 3: 套用到全部 runner** — `grep -n "await post('/api/" src/static/js/actions.js` 列出所有呼叫點（至少 runAction、runPluginTestAlert、runDebug、resetWatermark、stopGui——stopGui 已有 try/catch 豁免可跳過），在每個 `const r = await post(...)` 後緊接：

```js
  if (_apiFailed(r)) return;
```

（`runAction`/`runPluginTestAlert` 中此行放在 `alog(r.output ...)` 之前。）

- [ ] **Step 4: 限流放寬** — `actions.py:493` `@limiter.limit("10 per hour")`（僅 test-alert 這個）改 `@limiter.limit("30 per hour")`。reset-watermark 的 10/hour 不動。

- [ ] **Step 5: 驗證**

Run: `node --check src/static/js/actions.js && python scripts/audit_i18n_usage.py && pytest tests/ -k "test_alert or actions" -v`
Expected: 全綠

- [ ] **Step 6: Commit** — `fix(gui): surface action API failures and 429s honestly; relax test-alert limit to 30/hour`

---

### Task 7: Job Health 表間隔顯示秒級

`integrations.js:1503-1505` 間隔一律換算成 m/h，秒級 job（siem_dispatch 30s）顯示錯誤；缺值顯示 0m。

**Files:**
- Modify: `src/static/js/integrations.js:1503-1505`

- [ ] **Step 1: 改寫**

```js
    var ivs = Number(e.interval_seconds) || 0;
    var mins = !ivs ? '-'
      : ivs >= 3600 ? (Math.round(ivs / 3600) + 'h')
      : ivs >= 60 ? (Math.round(ivs / 60) + 'm')
      : (ivs + 's');
```

- [ ] **Step 2: 驗證** — `node --check src/static/js/integrations.js`

- [ ] **Step 3: Commit** — `fix(gui): job health interval renders sub-minute values as seconds`

---

### Task 8: 移除「過去 7 天流量趨勢」圖（全鏈）

使用者裁決此圖無價值。移除鏈：模板區塊＋樣式 → JS 載入/渲染 → 掛鉤 → API 路由 → 測試 → i18n 鍵 → 文件/CHANGELOG。教訓對照 filter-key-chain-checklist：刪除也要逐層核對，不留懸空引用。

**Files:**
- Modify: `src/templates/index.html`（840-863 一帶 `tw-trend-panel` 區塊；另 grep 檔內 `tw-trend` 樣式規則一併刪）
- Modify: `src/static/js/quarantine.js`（`switchQTab` 內 11-15 行掛鉤；766 行起的 R4k 區段到檔尾 `renderTrafficTrend` 結束，含 `_trendFetching/_trendFlaggedOnly/_trendBuckets`、change listener、`loadTrafficTrend`、`renderTrafficTrend`；若 `_svgEl` 只被 trend 用到一併刪——先 grep）
- Modify: `src/static/js/tabs.js:39-41`（掛鉤）
- Modify: `src/static/js/utils.js:61`（註解提及 loadTrafficTrend——改寫該行註解，勿留懸空引用）
- Modify: `src/gui/routes/actions.py:576-650`（`api_traffic_trend` 整個路由）
- Delete: `tests/test_traffic_trend_decisions.py`
- Modify: `tests/test_actions_archive_source.py`（僅移除 `test_traffic_trend_archive_source_shows_loaded_days`；其餘測試保留）
- Modify: `src/i18n_en.json`、`src/i18n_zh_TW.json`（刪 `gui_tw_trend_allowed/blocked/flagged_only/potential/title` 5 鍵×2 檔）
- Modify: `docs/`（`grep -rn 'trend\|趨勢' docs/guide docs/reference` 命中處同步刪改；`gui-tour.md` 初查無命中，仍要全掃）

- [ ] **Step 1: 模板** — 刪 `<!-- R4k: 7-day traffic trend SVG chart — additive, below KPI strip -->` 起的整個 `tw-trend-panel` div；刪後 `grep -c 'tw-trend' src/templates/index.html` 必須為 0。`sw-allowed/sw-potential/sw-blocked` 樣式先 `grep -rn 'sw-allowed'` 全 repo——若僅 legend 使用則連樣式刪，否則保留。

- [ ] **Step 2: JS** — 依序刪 quarantine.js 掛鉤與 R4k 區段、tabs.js 掛鉤、utils.js 註解改寫。刪後：

Run: `grep -rn 'TrafficTrend\|tw-trend\|_trendF\|_trendB' src/static/js/` 
Expected: 無命中

Run: `node --check src/static/js/quarantine.js && node --check src/static/js/tabs.js && node --check src/static/js/utils.js`
Expected: 通過

- [ ] **Step 3: 路由與測試** — 刪 `api_traffic_trend`；刪/改兩個測試檔。

Run: `grep -rn 'traffic/trend' src/ tests/ --include='*.py' --include='*.js'`
Expected: 無命中

- [ ] **Step 4: i18n** — 兩檔各刪 5 鍵。

Run: `python scripts/audit_i18n_usage.py`
Expected: 0 findings

- [ ] **Step 5: 文件** — 全掃 docs 命中處修訂；CHANGELOG `### Removed` 加一條（英文，說明 GUI trend chart 與 `/api/traffic/trend` 移除）。

Run: `python scripts/check_doc_links.py && python scripts/docs_check.py --all --exclude 'superpowers/**' --exclude '_archive/**' --exclude 'ux-review-*/**'`（以 repo 既有 gate 呼叫參數為準——先看 `scripts/check_doc_coverage.sh` 怎麼呼叫）
Expected: 通過

- [ ] **Step 6: 全套測試**

Run: `pytest --tb=short -q`
Expected: 全 PASS（張數比基準少 2±，因刪了 trend 測試）

- [ ] **Step 7: Commit** — `feat(gui)!: remove 7-day traffic trend chart and /api/traffic/trend`（CHANGELOG 同 commit）

---

### Task 9: docs_check 補 verified_against 路徑存在性檢查

7/17 事故：`preview.py` 刪除後 `verified_against` 懸空引用靠人工才抓到。在 `--frontmatter` 檢查內加「引用路徑必須存在」。

**Files:**
- Modify: `scripts/docs_check.py`（`check_frontmatter` 內或其後新函式）
- Test: `tests/test_docs_check.py`

**Interfaces:**
- Produces: issue 類別字串 `verified_against`

- [ ] **Step 1: 寫失敗測試**（照 `tests/test_docs_check.py` 既有 tmp docs 組裝慣例——先讀該檔）

```python
def test_verified_against_missing_path_flagged(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text(
        "---\ntitle: t\nlast_verified: 2026-07-23\n"
        "verified_against:\n  - src/definitely_missing_xyz.py\n---\nbody\n",
        encoding="utf-8")
    issues = []
    docs_check.check_verified_against_paths([doc], issues,
                                            repo_root=tmp_path)
    assert issues and issues[0][1] == "verified_against"


def test_verified_against_existing_path_clean(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.py").write_text("x")
    doc = tmp_path / "a.md"
    doc.write_text(
        "---\ntitle: t\nlast_verified: 2026-07-23\n"
        "verified_against:\n  - src/ok.py\n---\nbody\n",
        encoding="utf-8")
    issues = []
    docs_check.check_verified_against_paths([doc], issues,
                                            repo_root=tmp_path)
    assert issues == []
```

- [ ] **Step 2: 跑測試確認失敗** — `pytest tests/test_docs_check.py -v -k verified_against` → FAIL（函式不存在）

- [ ] **Step 3: 實作**

```python
def check_verified_against_paths(
    md: list[Path], issues: list[tuple[str, str, str]],
    repo_root: Path | None = None,
) -> None:
    """verified_against 裡「長得像 repo 路徑」的條目必須存在。

    只檢查含 '/' 的條目（如 src/foo.py）；不含 '/' 的版本字樣
    （如 "PCE 25.2.40"）跳過。2026-07-17 preview.py 懸空引用事故的防門。
    """
    root = repo_root or Path(__file__).resolve().parent.parent
    for path in md:
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        if not fm:
            continue
        va = fm.get("verified_against")
        entries = va if isinstance(va, list) else ([va] if isinstance(va, str) else [])
        for item in entries:
            item = (item or "").strip()
            if not item or "/" not in item or item.startswith(("http://", "https://")):
                continue
            if not (root / item).exists():
                issues.append((str(path), "verified_against", f"path not found: {item}"))
```

`main()` 內接在 frontmatter gate：

```python
    if args.all or args.frontmatter:
        check_frontmatter(md, issues)
        check_verified_against_paths(md, issues)
```

- [ ] **Step 4: 對真 docs 跑一次確認零誤報**

Run: `pytest tests/test_docs_check.py -v && python scripts/docs_check.py --frontmatter`（帶 repo 既有 gate 的 exclude 參數）
Expected: 測試全過；真 docs 零 verified_against issue（若有命中，先逐條判定是真懸空還是格式外例——真懸空就修文件，格式外例就收斂判定規則，不得放寬到漏掉真路徑）

- [ ] **Step 5: Commit** — `feat(docs-check): flag dangling verified_against path references`

---

### Task 10: 收尾——CHANGELOG、全套驗證、合併、部署、真機驗證

- [ ] **Step 1: CHANGELOG** — `## [Unreleased]` 補齊本批全部條目（Fixed：Task 1-7、9；Removed：Task 8）。

- [ ] **Step 2: 全套 gate 親跑**

```bash
pytest --tb=short -q
python scripts/check_no_naive_datetime.py
python scripts/check_doc_links.py
python scripts/audit_i18n_usage.py
mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py
for f in src/static/js/*.js; do node --check "$f"; done
```

Expected: 全綠；記下 pytest 總數與基準（3190 - 移除 2 + 新增 ~7）核對。

- [ ] **Step 3: 合併 main＋push＋CI** — merge（non-ff）、`git push`、`gh run watch` 盯到綠（教訓：subagent-full-suite-verification）。

- [ ] **Step 4: 部署測試機** — `ssh illumio-ops-test`（172.16.15.106，`/root/illumio-ops`）：`git pull --ff-only && systemctl restart illumio-ops`，確認 `systemctl is-active` 與 journal 無新錯誤。

- [ ] **Step 5: 真機驗證（Playwright，教訓：真機 e2e 是 DOM/CSS bug 唯一閘門）**
  - traffic-workload 分頁：趨勢圖區塊消失、console 無錯誤、KPI 條與查詢區正常。
  - Integrations overview：Job Health 表 siem_dispatch 間隔顯示 `30s`；無孤兒 job 條目。
  - Overview：posture 卡依 source_date 呈現（日更資料未逾 26h 應為正常色）。
  - Actions：送一次單通道 test-alert，toast 反映實際結果；用 curl 對 `/api/actions/reset-watermark` 打滿 10 次驗 429 JSON 契約（不動 test-alert 免得洗告警通道）。
  - journal 觀察一輪 rule tick（300s）：無動作時 `logs/state.json` mtime 不應每 tick 變動。

- [ ] **Step 6: 驗證結果回報＋記憶更新** — 逐項證據寫回報；更新 memory（temporal-bug-class-sweep 的殘債清單標記完成）。
