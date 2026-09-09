# Workload Isolator（EDR／SOAR 整合）設計（子專案 4／4，借鑒 illumio-plugger workload-isolator）

日期：2026-09-09　狀態：草案待使用者審閱　分支：feat/ven-fleet-manager（執行時各自開分支）

## 0. 背景與範圍

使用者定位：既有 quarantine（換 `Quarantine` label，`/api/quarantine/*`）＝**手動隔離**，維持不動。
新 isolator 是**獨立一套給 EDR／SOAR 整合**：對外 webhook、多把可撤銷 API key、TTL 自動釋放、
可還原紀錄、告警通知。

plugger 的實作只做 `enforcement_mode=full`、deny rule 是空殼、無持久化（重啟後 workload 卡在 full）、
`GET /api/state` 未驗證、MAX 檢查與插入分鎖。本案逐項修正。

使用者決定：
- 隔離手段每次可選 `method ∈ {label, full, both}`，系統設定預設值（出廠 `label`）。
  `label`＝加既有 `Quarantine` label（值由設定 `isolation.label_level` 決定，預設 `Severe`），依賴操作者
  已在 PCE 佈建的 deny ruleset；`full`＝`enforcement_mode=full`（不需 provision，下次 heartbeat 生效；
  **已有 allow 規則的 workload 不會被擋**）；`both`＝兩者。
- 認證：多把 API key，只存 argon2 hash，可個別撤銷，稽核寫 key 名稱。

不在範圍：deny ruleset 的自動建立（維持「操作者預佈建」，但本案加一個**檢查**）、bulk isolate。

## 1. 架構

```
EDR/SOAR ── POST /api/isolation/webhook/isolate   Authorization: Bearer iok_<id>.<secret>
         ── POST /api/isolation/webhook/release
                    │  verify key (argon2 by id) ─ rate limit ─ IP allowlist（既有閘門仍生效）
                    ▼
            src/isolation/service.py  isolate()/release()
                    ├─ find_workload(target)  href | hostname | ip
                    ├─ method label: update_workload_labels(+Quarantine)   既有 api_client
                    ├─ method full : set_workload_enforcement_mode(href,"full")  新 api_client 方法
                    ├─ IsolationStore  config/isolations.json（ScheduleDB 模式，可還原）
                    └─ notify: Reporter.send_alerts(type=system, channels=None)
scheduler tick_isolation_ttl (60s) ── 到期 release(reason="ttl")
GUI #/investigate/isolation  清單／手動隔離／釋放／紀錄        （session auth）
GUI #/system/security  API keys 卡（建立→只顯示一次、撤銷、最後使用時間）
```

## 2. API key

- 格式 `iok_<id8>.<secret32>`；儲存 `config.json["isolation"]["api_keys"]`：
  `[{"id","name","hash","created_at","created_by","revoked_at"|null,"last_used_at"|null}]`。
  `hash` 命中 `_SECRET_PATTERN`（以 `hash` 結尾不命中，故欄位名用 `secret_hash`），`_redact_secrets` 自動遮。
- 驗證：由 `id` 找紀錄，`verify_password(secret, secret_hash)`；revoked→401；每次成功更新 `last_used_at`
  （節流：同 key 60 秒內不重寫檔）。
- 建立：`POST /api/security/api-keys {name}` → 回明文一次；撤銷 `DELETE /api/security/api-keys/<id>`；
  列表 `GET /api/security/api-keys`（不含 hash）。都走 session auth＋既有 `/api/security` 的
  `cm.write_lock`＋scratch 模式，`@limiter.limit("10 per hour")`。

## 3. Webhook 端點（API key auth）

- `security_check` 公開清單加 `/api/isolation/webhook/isolate`、`/release`；`@csrf.exempt`；
  `@limiter.limit("30 per minute")`；423 gate 豁免 endpoint。IP allowlist 不豁免（EDR 來源 IP 須在允許清單，文件說明）。
- `POST /api/isolation/webhook/isolate`
  ```
  in : {target: str（href|hostname|ip）, reason: str（必填 ≤500）, source?: str, ttl_seconds?: int(0–604800),
        method?: "label"|"full"|"both", dry_run?: bool}
  out 200: {ok, status: "isolated"|"already_isolated"|"dry_run", record: {...}}
  out 404: workload not found ； 409: 已達上限 或 該 workload 正在處理 ； 422: 參數錯 ； 401: key 無效
  ```
- `POST /api/isolation/webhook/release` `{target, reason?}` → 200 `{ok, status:"released"|"not_isolated", record}`。
- 回應永不含 key、不含 PCE 憑證；錯誤訊息用 `t()`，另附機器碼 `code`。

## 4. 服務層 `src/isolation/service.py`

- `find_workload(api, target)`：`/orgs/` 開頭→`api.get_workload(href)`；否則 `api.search_workloads`
  依 hostname（大小寫不分）→ name → ip_address 精確；多筆命中→409 `ambiguous_target` 列出候選。
- `isolate(api, store, target, *, reason, source, ttl, method, actor, dry_run)`：
  1. 讀 workload，取 `enforcement_mode`、`labels`、`online`、`managed`。unmanaged→422（label 可加但無意義，full 無效）。
  2. 鎖內：已有 active 紀錄→`already_isolated`；`len(active) >= isolation.max_isolated`（預設 100）→409；
     **同一鎖內先寫入 `status:"pending"` 紀錄**再釋放鎖（修 plugger TOCTOU）。
  3. 依 method 執行；`label`：`check_and_create_quarantine_labels`＋整組替換加目標 level（照 actions.py:530-572）；
     `full`：新 `ApiClient.set_workload_enforcement_mode(href, mode) -> bool`（PUT `{href}` `{"enforcement_mode": mode}`）。
     任一步失敗→紀錄 `status:"failed"`＋已完成步驟，並回滾已完成的另一步（both 時）。
  4. 成功→`status:"active"`，`release_at = now+ttl`（ttl 0＝不自動釋放）。
  5. 通知：`Reporter(cm).send_alerts(channels=None)` 前先把一筆 `type="system"` 的告警物件放入 health bucket
     （summary「Isolated <hostname>（<method>）— <reason>」）；失敗不影響隔離結果。
- `release(api, store, target_or_record_id, *, reason, actor)`：依紀錄還原：`label`→過濾掉 q_hrefs
  （照 actions.py:637-690）；`full`→`set_workload_enforcement_mode(href, previous_mode)`；
  `previous_mode` 缺→**不還原、標 `needs_manual_review`**（不採 plugger 的預設 visibility_only）。
  紀錄 `status:"released"`、`released_at`、`released_by`、`release_reason`。
- 紀錄 schema：
  `{"id","href","hostname","ips":[],"method","label_level","previous_mode","previous_labels":[hrefs],
    "isolated_at","release_at"|null,"reason","source","actor"（key 名或使用者）,"status",
    "steps":[{"kind","ok","http","error"}],"released_at","released_by","release_reason"}`。
- `IsolationStore(config/isolations.json)`：複製 `ScheduleDB` 鎖內重讀單筆寫入；`active()`、`get()`、`put()`、`recent(limit)`。

## 5. TTL 與檢查

- `scheduler/jobs.py` 新 `tick_isolation_ttl(cm)`，`isolation.ttl_check_interval_seconds` 預設 60，
  `_instrument` 包；到期者逐一 `release(reason="ttl")`，失敗保留 active 並累加 `release_attempts`，
  超過 5 次→`needs_manual_review`＋告警。
- 啟動檢查（job 首跑）：`isolation.label_level` 的 Quarantine label 是否存在，且是否有任一 active
  ruleset 的 scope/consumer 引用該 label；缺→寫 `dashboard_summary.isolation.ruleset_warning`，
  GUI 頁首 warn 條「隔離 label 未被任何規則集引用，label 方法不會斷網」。

## 6. GUI `#/investigate/isolation`

- 清單（active／history 切換）、每列：hostname、method、來源、原因、isolated_at、release_at 倒數、狀態 chip。
- 動作：手動隔離抽屜（target、reason、method、TTL）、釋放（確認 modal）、延長 TTL。
- 頁首：ruleset_warning、max 使用量。
- coverage.yaml IV-21..IV-24；i18n `gui_iso_*`；`#/system/security` 新 panel SY-17 API keys。

## 7. 安全

- key 明文只在建立回應出現一次；log 經 `loguru_config` 遮罩（`authorization`／`secret` 已在規則）。
- webhook body 大小上限 8 KB；`target` 長度 ≤255；拒絕含控制字元。
- 稽核：`_audit_action("isolation_isolate", actor=key_name|user, target, method, record_id)`。

## 8. 測試

- keys：建立→驗證通過、撤銷→401、錯 id／錯 secret→401 且回應時間不因錯誤型別而洩漏（同一路徑）。
- service：三種 method 各自的 PCE 呼叫序列（fake api）、both 半途失敗回滾、already_isolated、max、
  previous_mode 缺→needs_manual_review、dry_run 不寫。
- TTL job：到期釋放、失敗計數與 5 次升級。
- webhook：未帶 key 401、CSRF 不擋、限流 31 次→429、404／409／422 碼。
- 注入測試：把 `/api/isolation/webhook/isolate` 從公開清單移除應變 401（確認閘門在看）。
- GUI e2e：route mount、四個 anchor、API keys panel 建立後明文只顯示一次。
- 真機（lab）：對一台 selective workload 跑 `both`＋TTL 120 秒，驗 label 加上、mode=full、到期還原。

## 9. 已知限制

- `label` 方法的斷網效果取決於操作者的 deny ruleset；本案只檢查引用、不建立。
- `full` 對已有 allow 規則的 workload 不斷網（已在 GUI method 選項旁註明）。
