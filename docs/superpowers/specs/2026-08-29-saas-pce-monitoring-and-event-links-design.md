# SaaS PCE 監控與事件連結設計

> 狀態：已完成現況、真機與原廠文件查證，依實作計畫執行中。
>
> 查證基準：`main` @ `80e0274d43d4cb9730ee2fc00d01e8aa46b8139d`，2026-08-29。

## 1. 問題與已確認事實

目前產品把三種不同用途的 URL 混在一起：

```text
api.url ──┬── REST API 呼叫
          ├── PCE health probe
          └── 告警內的人類操作連結（錯誤）
```

這在 on-prem PCE 偶爾可行，到了 SaaS 就不成立：SaaS REST API 位於區域 SCP
host，人類登入則走 Illumio Console。現有 `_console_base()` 又只辨識
`*.illumio.com` 且含 `scp` 的 hostname，但 SaaS API hostname 不一定符合，
因此事件連結可能仍指回 API host。

健康檢查也有相同的部署型態混用：

- `GET /api/v2/noop` 是 Public Stable API；原廠用途就是驗證 PCE 連線與 API
  credentials，適合所有部署型態的共同基線。
- `GET /api/v2/health` 只適用 on-prem PCE，不適用 Illumio Cloud。
- `GET /api/v2/node_available` 是 on-prem core node／load balancer probe，不是
  SaaS 健康契約。
- SaaS 是否「可用」不能只靠一次 HTTP probe；實際事件與 traffic ingestion 的
  `last_status` 與 lag 才能證明產品所依賴的資料管線仍在前進。現行 Dashboard
  `_overview_pipeline()` 會丟掉 `last_status`，而失敗 ingest 仍更新 `last_sync_at`，
  因此只看 lag 可能把持續失敗畫成綠色；本案必須一起封住。
- Illumio 官方 SaaS status page 適合事故關聯與人工確認，不應被 scrape 成主要
  探針。

原廠依據：

- [No Op Public Stable API](https://product-docs-repo.illumio.com/Tech-Docs/Core/24.5/REST-APIs/out/en/pce-management/no-op-public-stable-api.html)
- [PCE Health API（文件註明只限 on-prem）](https://product-docs-repo.illumio.com/Tech-Docs/Core/PDFs/REST_APIs_22_2.pdf)
- [Node Availability（只限 data center software deployment）](https://product-docs-repo.illumio.com/Tech-Docs/Core/22.2/REST-APIs/out/en/22-2-rest-apis/pce-management/node-availability.html)
- [Illumio Console 預設與 custom subdomain](https://product-docs-repo.illumio.com/Tech-Docs/Platform/out/en/introducing-the-illumio-console/accessing-illumio-console.html)
- [Illumio SaaS Services status page](https://status.illumio.com/posts/dashboard)

## 2. 設定模型

新增兩個 `api` 欄位：

```json
{
  "api": {
    "deployment_type": "saas",
    "url": "https://saas-api.example.invalid",
    "console_url": "https://console.illum.io",
    "org_id": "1"
  },
  "web_gui": {
    "public_url": "https://illumio-ops.example.com"
  }
}
```

責任固定如下：

| 設定 | 責任 | 是否可省略 |
|---|---|---|
| `api.deployment_type` | 選擇支援的 health probe 組合 | 舊設定缺少時以 `on_prem` 載入 |
| `api.url` | 機器對機器 REST API base | 否 |
| `api.console_url` | 告警內的 PCE Console 人類操作連結 | 可；SaaS 預設 `https://console.illum.io`，on-prem 預設 API origin |
| `web_gui.public_url` | illumio-ops 自己的 dashboard／報表 CTA | 可；不得再拿它代替 PCE Console URL |

`deployment_type` 必須是 `saas | on_prem` 列舉，不用布林值，也不從 hostname
推測。`console_url` 允許 v26.10+ 的 custom `*.illumio.ai` Console URL。

為保留既有 on-prem 安裝相容性，舊設定缺少欄位時採 `on_prem`。所有新安裝範本、
GUI 與 CLI 都必須把部署型態顯示為明確欄位，避免新使用者依賴隱含預設。

只改 `deployment_type` 或 `console_url` 不代表換了一台 PCE，不觸發 cache flush；但
CLI 修改後仍須提醒重啟長駐服務，讓新的 probe 與連結設定生效。

## 3. 健康判定

### 3.1 Probe flow

```text
所有部署
   |
   +-- GET /api/v2/noop (authenticated)
          |
          +-- 非 2xx ──> 分類並告警，不再做後續 probe
          |
          +-- 2xx
                |
                +-- SaaS ─────> API access OK
                |
                +-- on-prem ──> GET /health
                                  |
                                  +-- body degraded -> degraded
                                  +-- healthy -> GET /node_available

資料面（獨立、兩種部署都要）
   +-- events ingestion watermark: last_status + lag
   +-- traffic ingestion watermark: last_status + lag
```

### 3.2 狀態分類

| HTTP／錯誤 | 分類 | `reachable` | 整體整合狀態 |
|---|---|---:|---|
| 2xx | `ok` | true | healthy（仍須看 ingestion freshness） |
| 401 | `auth_failed` | true | critical：平台有回應但 credentials 無效 |
| 403 | `authorization_failed` | true | critical：credentials 權限不足 |
| 429 | `rate_limited` | true | degraded，不得誤報為平台死亡 |
| 5xx | `server_error` | true | critical／provider-side error |
| DNS/TCP/TLS/timeout（status 0） | `transport_error` | false | critical／unreachable |
| 其他 HTTP | `http_error` | true | degraded 或 critical，保留狀態碼 |

健康告警、測試連線 API、Overview／Health bar 使用同一分類，不各自重新解讀；
`pce_stats.health_category` 保存最近一次 health probe 的分類，成功時覆寫為 `ok`，
避免 recovery 後仍用 sticky `last_error` 當成目前狀態。
回應 body 只保留安全截斷內容；不得把 API key、secret 或完整 exception 回到 client。

### 3.3 SaaS provider status

產品在 `deployment_type=saas` 時顯示官方 status page 連結供人工關聯。這是輔助訊號，
不 scrape HTML、不把 status page 可達性算入 PCE watchdog，也不讓第三方 status page
故障反過來製造 PCE 告警。

### 3.4 SaaS events latency tolerance

Prod 真機補驗顯示 `/noop` 為 204、org endpoint 為 200，但 events endpoint 即使只取
1 筆也約需 20 秒；冷啟動實際使用的 24 小時／10,000 筆查詢約需 21 秒。現行
`fetch_events_strict()` 固定 30 秒 timeout，SaaS backend 或網路只要短暫再慢約 9 秒，
urllib3 的 GET retry 就會耗盡並產生截圖中的 `Max retries exceeded`。失敗時 watermark
不前進，下一輪會持續重查同一個大視窗。

本案不重做 async ingestion，但要移除已實測的 30 秒臨界點：SaaS events pull 使用
60 秒 read timeout；legacy/on-prem 保留 30 秒。此差異只由明示 `deployment_type`
選擇，不由 hostname 推測。timeout 後仍按 `transport_error`／ingestion watermark error
處理，不把延長 timeout 當成健康成功。

## 4. 事件連結

事件 alert payload 仍只產生一個共同的 `pce_link`，所有 LINE、Telegram、email、
Teams／plugin renderer 都消費它；修正必須發生在共同 URL resolver，不在各通道個別
補丁。

```text
event.href + api.console_url
              |
              +-- on-prem: https://pce.example:8443/#/events/<id>
              +-- SaaS:    https://console.illum.io/#/events/<id>
              +-- custom:  https://acme.illumio.ai/#/events/<id>
```

不再根據 `api.url` 的 domain suffix 判斷 SaaS。若沒有 event href，回傳 Console landing
URL；若連 Console URL 都無法解析，省略 CTA，不產生空或 javascript URL。

Illumio 公開文件沒有承諾 `/#/events/<id>` 是穩定 deep-link contract，因此正式交付前
必須使用可登入的 SaaS 帳號，實際驗證 alert 產出的連結能落到正確事件。若當時仍無
有效 SaaS credentials，該部分不得宣稱真機驗證完成；保守 fallback 是只開 Console
landing page，而不是交付未驗證的精準連結。

## 5. 不在本案範圍

- 不自動從 API hostname 推導 `deployment_type` 或 custom Console URL。
- 不 scrape `status.illumio.com`，也不建立外部 status API 相依。
- 不重做 cache lag／watchdog 架構；沿用既有 ingestion watermark 與
  `pce_stats.consecutive_failures`。
- 不改 PCE profile／cache isolation 模型。
- 不新增可自由插入字串的 event URL template，避免設定注入與不必要複雜度。

## 6. 驗收條件

1. SaaS 不再呼叫 `/health` 或 `/node_available`；on-prem 仍保留完整三層檢查。
2. `/noop` 的 401 明確顯示為 credentials 問題，而不是 PCE offline。
3. GUI、互動 CLI、`config login` 均可設定 deployment type 與 Console URL。
4. 舊設定無新欄位仍能載入，行為維持 on-prem。
5. SaaS API hostname 不再被拿來產生 Console event URL。
6. 四種告警輸出從同一 payload 取得同一個正確 `pce_link`。
7. Health Dashboard 同時能看出 API probe 結果與 ingestion lag／last status；任一
   ingestion source 的 `last_status=error` 時，即使 lag 很小也不得顯示綠色。
8. i18n、mypy strict subset、完整 pytest 與文件檢查全部通過。
9. SaaS events pull 不再使用 30 秒 timeout；on-prem timeout 行為維持不變，兩條分支都有
   request-contract regression test。
