# 待執行計畫合併執行說明（2026-07-10）

## 結論

四個待執行計畫**不合併成單一大案**；Alert 可靠性與容量 7/24 兩案**合併為同一分支串行執行**，其餘獨立平行。

## Stream A：`feat/ops-reliability`（容量 7/24 → Alert 可靠性，串行）

- 執行順序：`2026-07-04-capacity-and-24x7-hardening.md` 先行（其中 ingest 碰頂漏資料、PCE 失敗不告警兩項最優先），完成後接 `2026-07-04-alert-reliability-and-event-catalog-audit.md`。
- 合併理由：兩案共同修改 `src/analyzer.py` 與 `src/api_client.py`；告警語意重疊（容量案的 lag/失敗告警 vs Alert 案的 watchdog/overflow/DLQ 告警）。
- **對帳規則**：執行 Alert 案各 task 前，先檢查容量案已落地的告警機制（lag_monitor 告警、capacity 告警）；同語意的告警不得重建第二條路徑，改為擴充既有機制。盤點時已知「DLQ 清理與查詢截斷已存在勿重做」同樣適用。

## Stream B：`feat/port-service-filter`（平行 worktree）

- `2026-07-10-port-service-filter-and-browse.md`，13 tasks，子系統封閉（filter/query 層＋FilterBar＋CLI picker）。
- 與 Stream A 交集僅 i18n JSON 與 `quarantine.js`/`index.html` 不相鄰區段；後合併者 rebase 處理。

## Stream C：Rule Hit Count（殿後）

- `2026-07-05-rule-hit-count-report.md`，12 tasks。待 Stream A 或 B 其一收斂後再開，控制平行度。

## 不動

- Readiness 獨立報表 backlog：等客戶回饋，不排程。
