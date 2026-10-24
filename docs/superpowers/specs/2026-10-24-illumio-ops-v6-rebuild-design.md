# illumio-ops v6 重建設計

> 狀態：初版**使用者已核可（2026-10-24）**，P1 依初版實作完成（`feat/v6-p1-foundation`，未合併）。
> **修訂版（2026-10-24 下午，以「偵測橫向移動」為核心並重做介面）使用者已核可（2026-10-24）**——修訂處標
> 【使用者 修訂】或【判斷 修訂】，被取代的初版段落直接改寫，不保留兩個版本。
> 性質：**整個專案推倒重做**，回收可用程式碼；舊版（5.x）不再並行維護。
> 依據：2026-10-24 全專案現況盤點（`tmp/rearch-2026-10-24/survey/`，gitignored；
> 彙整見 `99-synthesis.md`，分檔 a–f 為 Claude 盤點、g 為 Codex 獨立判讀）與同日需求對談；
> 修訂版另依同日介面對談、lab／NFR 唯讀實測（§6.6）與畫面草稿（§12）。
> 標記：**【使用者】** 是使用者在對談中的決定；**【判斷】** 是撰寫者的決定，使用者可推翻；
> 未標記的段落是事實或由前兩者直接推得。

---

## 1. 為什麼要做這個產品

Illumio PCE **沒有內建告警機制**，要告警只能把 log 拋到 SIEM 再由 SIEM 處理；**SaaS 版**還必須
另外準備 S3 空間暫存 log，很多客戶沒有這個條件，結果就是收不到任何告警。PCE 的**內建報表也很少**，
微分段收集到的東西向流量沒有被轉成資安或網管看得懂的東西。【使用者】

本產品裝在客戶環境，**透過 PCE REST API 調閱資料**，補上這兩塊：

```
一般做法：  PCE ──syslog / S3──> SIEM ──> 告警          ← SaaS 客戶常卡在 S3
本產品：    PCE <──API 調閱── illumio-ops ──> 依規則告警（email / LINE / Telegram / Teams / webhook）
                                       ├──> 轉送 log 到客戶的 SIEM
                                       └──> 東西向流量報表與潛在風險發現
```

**核心：偵測橫向移動**【使用者 修訂】。掌握了端點之間的流量，最有價值的問題是「環境裡有沒有橫向移動的
可能、有沒有正在發生」。告警、報表、調查都圍繞這個問題組織：

```
                    偵測橫向移動（核心）
     ┌─────────────────────┼──────────────────────┐
  可能性（暴露面）        正在發生（行為→告警）       防堵（下一步，唯讀建議）
  ・可達路徑、樞紐主機     ・扇出、新的管理連線       ・切斷點建議
  ・勒索高風險服務未防護   ・跳板鏈、大量被擋嘗試     ・deny rule 先用流量試算影響
  ・未強制／預計阻擋       ・非管理群組用管理協定
  ・跨環境管理 port        ・前兆：防火牆竄改、VEN 暫停／離線
```

**定位：輔助工具**【使用者 修訂】。資料經 API 輪詢取得，有延遲是正常的；客戶要即時，就請他們把 PCE
用 syslog 送進自己的 SIEM。本產品的本分是：**替沒有 SIEM 的客戶告警**，以及**用流量報表做評估**
（流量的重點在報表，互動調查是輔助告警追查用的）。

## 2. 為什麼要重做

產品從單一 CLI 工具長成「daemon＋SQLite＋Web GUI＋11 型報表＋SIEM」平台（v4.1.0→v5.2.0 三個月內
src +55k／−22k 行）。雜亂的主因不是功能多，而是**同一件事在多處各寫一次、共用狀態沒有擁有者**：

- 同一能力有 6 種入口（argparse 舊旗標、click、互動選單、3 支獨立選單、GUI、排程），跨入口行為差異 18 項。
- 「資料從 cache／live／archive 哪裡拿」寫了 3–4 份；traffic filter 有 3 種以上執行表示；GUI 的
  policy decision 有 6 套值域、其中 3 套整數編碼互相衝突；嚴重度表 7 份、SMTP 實作 3 份。
- `state.json` 23 鍵多方寫入；設定在驗證失敗時 dict 與 typed model 分歧；裸 `ConfigManager()` 40 處。
- 相依倒置（資料層 import GUI 與分析層）、import 環 2 個、分析層經 stdout 把結果交給 GUI。
- 無讀者的路由、功能與資料；永遠不會被清掉的檔案與資料列。

測試機使用痕跡（2026-10-24 唯讀調查）：持續運作且有產出的只有**資料收集、事件告警（LINE＋email）、
SIEM 轉送（22.4 萬筆全數送達）**；GUI 告警收件匣 146 則從未被處理、報表排程只有一筆 demo 且型別不合法、
規則排程的目標都已刪除、VEN 推進從未執行、隔離零紀錄。

## 3. 給誰

- **已購買 Illumio 的客戶**，on-prem PCE 與 SaaS PCE 都要支援。【使用者】
- 操作者是客戶的**資安或網管人員**。【使用者】
- 已有**少數客戶部署了 5.x**（尚未正式交付），**全部是 v5.0.0、離線 bundle 安裝，升級由使用者本人
  執行**；已知沒有用 CLI 建立規則。【使用者】

## 4. 目標、非目標、反目標

### 4.1 目標（依優先序）【使用者】

修訂版順序【使用者 修訂】：

1. **偵測橫向移動**：暴露面分析與行為偵測（§6.5.1），是告警與報表共同的分析核心。
2. **告警**：依設定的規則，從 PCE 事件、流量、PCE 健康狀態，以及橫向移動偵測產生告警並送到通知通道。
3. **評估報表**：把東西向流量轉成「現在該關注什麼、有沒有橫向移動的可能」的報表（§6.5.5）。
4. **log 轉送到客戶 SIEM**：讓沒有 S3 的 SaaS 客戶也能把 audit 事件與流量送進 SIEM。
   （初版目標 2；修訂對談未談及，維持不變。）
5. **調查**：從告警或首頁點進來追查的工作台（§6.5.3），**從 v6.1 提前到 v6.0**【使用者 修訂】；
   規模以「追查一則告警」為準，不做成通用的流量探索平台【判斷 修訂】。**本產品存在的理由之一是做原廠 filter
   做不到的聚合查詢**，例如依 process／使用者分組排名、部分比對（§6.5.7）【使用者 修訂】——這同時服務工作台、
   報表與偵測器。
6. **從 5.x 升級**：已部署客戶的**設定**必須能帶過來。【使用者】

**隔離**屬於 v6.0（橫向移動的「防堵」，§6.5.1）【使用者 修訂】；其他會寫 PCE 的動作仍延到 v6.1（§6.5）。

### 4.2 非目標

- **CLI**：整個拋棄。【使用者】只保留安裝／升級腳本與極少數救援指令（§6.2）。【判斷】
- **資料遷移**：5.x 的 cache、封存、告警紀錄、舊報表不搬。【使用者】
- **舊版並行維護**：不做。【使用者】
- **告警收件匣的處理流程**（new/ack/done 狀態）：不做。（使用者 2026-09-04 v3.1 決策：「不需要收件匣與事件調查
  流程，只要能檢視最近的告警」；測試機 146 則告警從未被處理，佐證。）**修訂：只加「註記」**【使用者 修訂，
  2026-10-24 確認】——每則告警可留文字註記並連到調查時存的查詢條件，方便交接；不做狀態流。
- **即時偵測**：不做。偵測延遲以分鐘到數十分鐘計（§6.6 F7），本產品不是 EDR，也不宣稱即時。
  【使用者 修訂】
- 一台設備對接多個 PCE、多使用者／角色：不做。【判斷，前提見 §5】
- plugger 移植 2–4（app-dependency-intel、vuln-scan-import、workload-isolator）：v6.0 不做，
  原 spec 保留供日後評估。GUI clarity 批次 3：由本設計的前端取代，不另做。

### 4.3 反目標（做出來但違反這些就算失敗）

這些來自 5.x 反覆發生的事故，是本設計的硬性品質規則：

1. **失敗不得看起來像成功或像空結果。** 取資料失敗、部分失敗、截斷、降級，都要在 API 回應與畫面上
   明說；不得吞錯回 `[]`、不得回退成預設值後繼續跑。（5.x：設定驗證失敗回退預設值會無聲關掉 cache
   與 SIEM；`has_draft_changes` 失敗回 False 後照樣 provision；報表排程型別不合法卻每分鐘「執行成功」。）
2. **每份持久資料只有一個寫入模組。** 不得有多方共寫的 JSON 檔。
3. **每個值域只定義一次**，後端與前端共用（前端型別由後端定義產生）。
4. **沒有讀者的東西不出貨**：每條路由有畫面呼叫、每個設定鍵有程式讀、每份產出有清理機制。
5. **截斷要明說**：報表與畫面的長度上限、截斷方式（換行／省略／分頁）必須明確，不可無聲截斷
   （專案 CLAUDE.md 規則）。
6. **設定在寫入時驗證**，不合法就拒寫；載入時驗證失敗則拒絕啟動並指出哪一欄。
7. **路徑全部從單一安裝根目錄解析**，不得依賴執行時的工作目錄。
8. **偵測與排名的可信度要明說**【判斷 修訂】：每個偵測、排名、分數都標示資料延遲、觀察期間與欄位覆蓋率
   （例如「傳輸量只有 5% 的 flow 有資料」）；覆蓋不足時照樣顯示結果但附警語，不得讓「沒偵測到」看起來像
   「沒有發生」。
9. **原廠數字照實轉述、附上拆解**【判斷 修訂】：引用 PCE 算的分數或判定（例如勒索防護分數）時，同時顯示
   它的組成；原廠數字自相矛盾時（§6.6 F5）標出矛盾，不照單全收、也不靜默改用自己的算法替代。

## 5. 約束與前提

- 執行環境：Linux x86_64（RHEL／Rocky 系），**可能離線**；以離線 bundle 安裝到 `/opt/illumio-ops`，
  內含 PBS CPython 3.12 與所有 wheel，systemd 服務。Windows 已於 2026-08 移除，不恢復。
- PCE：on-prem 與 SaaS；SaaS `/events` 有 22–60 秒以上的固定延遲，timeout 必須可設定。
- 語系：繁體中文與英文。
- 安全：既有 GUI 安全機制已多輪審查（登入、CSRF、IP 允許清單、限流、Talisman、TLS 自簽／續期／CSR／
  匯入），行為必須保留。憑證只存設定檔（0600），不得出現在 log、畫面或 API 回應。
- **前提（不符請告知）**【判斷】：一台設備只對接一個 PCE；單一管理者帳號。
- **客戶規模：受管 workload 200–1,000 台**【使用者 修訂】（初版「與測試機相當」不成立：測試機接的 lab 只有 21 台；
  測試機 cache 量：events 7.7 萬、raw flows 11 萬、agg 42.5 萬，DB 1.3 GB）。每日 flow 量未知，P2 依 lab 每台平均量
  外推並以合成資料驗證。設計含意【判斷 修訂】：單機 SQLite 仍可行；工作台預設時間範圍要有上限，並保留「依日預先彙總」
  的表供維度欄與報表使用；橫向移動圖在每輪收集後或定時重算並存結果，不在每次請求時算。
- **PCE／VEN 版本：試點客戶大多是新版（25.x–26.x）**【使用者 修訂】。依新版功能設計；更舊的版本走 §6.5.1 的能力偵測
  降級路徑（顯示「此版本不提供」），不另錄舊版 fixture。

## 6. 已定的做法

### 6.1 技術選擇【判斷，使用者授權由撰寫者評估】

| 項目 | 決定 | 理由 |
|---|---|---|
| 後端 | Python 3.12＋SQLite＋離線 bundle | 回收最多；離線安裝已解決 |
| Web | 沿用 Flask 與既有安全機制 | 雜亂來自契約未定義，不是框架 |
| API 契約 | 每個 API 的請求／回應以 pydantic 定義一次；**單一回應信封**；前端 TypeScript 型別由此產生 | 消滅值域漂移（policy decision 6 套編碼）與 6 種回應信封 |
| 前端 | TypeScript＋React，開發時建置，bundle 只帶靜態檔；客戶機器不需要 node | 型別與元件防止重複與值域衝突；React 另可接上使用者既有的設計同步流程 |
| 執行模型 | **單一行程**（Flask＋APScheduler 同行程），每份資料單一寫入者 | CLI 拿掉後沒有第二寫入者；跨行程鎖與 `state.json` 多方寫入可整批消失 |
| CI | 用出貨的 Python 3.12 與**同一份** lock 檔跑測試 | 5.x CI 跑 3.10/3.11，出貨 3.12，兩份 lock 差 28 個套件 |
| 版本 | v6.0.0 | 重大不相容（無 CLI、新設定格式） |

前端多出一套 node 建置工具鏈（目前 repo 沒有任何 node 步驟；Playwright 走 Python 套件）。

### 6.2 介面：只有 GUI【使用者】

- 所有操作都在 GUI。刪除：click 命令樹、argparse 舊旗標、互動選單、`siem_cli`／`pce_cache_cli`／
  `rule_scheduler_cli`。
- 保留安裝面腳本：`build_offline_bundle.sh`、`install.sh`、`preflight.sh`、`uninstall.sh`。
- **救援指令**【判斷】：GUI 進不去時（忘記密碼、TLS 設壞、設定檔損毀拒絕啟動）需要的最小集合——
  重設管理員密碼、驗證設定檔並指出錯誤欄位、（可選）以 HTTP 暫時啟動。**只在服務停止時可執行**，
  不構成第二寫入者。
- **資訊架構重做**【使用者 修訂：可接受介面全面重構】。初版沿用的 v3.1 IA（左側導覽、清單→詳情）由下列
  結構取代；頂層導覽與命名為【判斷 修訂】：

  ```
  首頁（現在該關注什麼）│ 橫向移動 │ 調查（工作台）│ 告警 │ 報表 │ 設定
       §6.5.4               §6.5.1     §6.5.3            §6.5.2   §6.5.5   管理面
  ```
  主機名稱在任何畫面都可點，進入**主機側寫頁**（§6.5.3）。告警、首頁項目、報表裡的數字都帶「在工作台開啟」，
  落點是帶好條件的工作台。
- 保留的 v3.1 原則：每頁一顆主要動作、人話文案、畫面不印路由／設定鍵名／原始 JSON；Direction D 視覺 token
  （白底、細線、Orange 只給動作、Montserrat＋Noto Sans TC，P1 已實作）沿用【判斷 修訂】。

### 6.3 架構分層【判斷】

```
 ┌──────── 前端（TS＋React，建置後的靜態檔）────────┐
 │ 頁面 → 型別化 API client（由後端契約產生）        │
 └──────────────────────┬───────────────────────────┘
 ┌──────── Web 層（Flask）─────────────────────────┐
 │ 認證／CSRF／TLS／限流 │ 路由只做：驗證輸入→呼叫服務→包信封 │
 └──────────────────────┬───────────────────────────┘
 ┌──────── 服務層 ───────────────────────────────────┐
 │ 收集 │ 分析（橫向移動／關注清單）│ 告警 │ 調查 │ 報表 │ SIEM 轉送 │ 管理 │（政策動作：v6.1 位置）│
 └──────────────────────┬───────────────────────────┘
 ┌──────── 領域核心（純函式，無 I/O）─────────────────┐
 │ 值域登錄 │ filter 模型 │ 分析段落 │ 橫向移動圖與偵測器 │ 規則評估 │ 計量（頻寬／量） │
 └──────────────────────┬───────────────────────────┘
 ┌──────── 資料存取 ──────────────────────────────────┐
 │ PCE client │ FlowSource／EventSource（store／live／archive 唯一實作）│ Store │ Settings │
 └───────────────────────────────────────────────────┘
 排程（APScheduler，同行程）只負責「何時呼叫哪個服務」。
```

相依規則：箭頭只能往下；下層不得 import 上層；領域核心不得做 I/O、不得 print、不得讀全域設定。

三個「只准寫一次」的核心，對應 5.x 最大的三處重複：

1. **值域登錄**：policy decision（四值）、draft policy decision（七值軸）、rule 型別
   （allow/deny/override_deny）、告警規則型別、嚴重度、協定、報表型別、SIEM 格式／傳輸、資料來源等，
   全部在此定義一次，前端型別由此產生。編碼只用字串，不用整數。
2. **filter 模型**：一個 filter 定義，編譯成三種執行形式——PCE async query payload、store 查詢、
   DataFrame 篩選；能力限制（某來源不支援某條件）由模型宣告，不由各呼叫端各自白名單。
3. **FlowSource**：「這次查詢的資料從 store、live PCE 還是 archive 拿、缺口怎麼補、結果標示什麼來源與
   完整度」只有一個實作；告警、報表、調查、SIEM 都經由它。
4. **分析段落**【判斷 修訂】：一個分析段落 ＝「filter 條件＋分組（最多兩層）＋指標＋視角」，資料是流量或事件。
   工作台畫面、報表中以流量／事件為資料的節、告警詳情的證據區都是分析段落的呈現。同一份定義在畫面與報表
   算出同一個數字（5.x 的報表分析與 GUI 查詢各寫一套，數字對不起來）。
   **範圍**（builder check 後釐清）：policy_diff、policy_resolver、readiness、ven_status、勒索防護拆解、橫向移動圖
   指標與切斷點是**專用分析模組**，不硬套段落模型；它們的輸出由畫面與報表共用（算一次、兩處呈現），能對應到流量時
   附「在工作台開啟」。**排程**：內建報表存「型別＋參數」（日後改進自動生效，5.x 報表排程照此遷移）；自訂報表存
   段落清單。

### 6.4 資料與狀態【判斷】

- **設定**：一個有驗證、帶 `schema_version` 的設定檔（操作者可檢視、可備份、是遷移的對象）。
  寫入時整份驗證，不合法拒寫；所有設定鍵都必須在 schema 宣告。
- **執行期狀態**（watermark、冷卻、throttle、job 健康、報表工作進度、告警紀錄、SIEM 佇列與 DLQ、
  排程狀態、儀表板摘要）：SQLite 資料表，**每張表一個擁有模組**。不再有 `state.json`、
  `dashboard_summary.json`、`job_health.json`、`async_query_jobs.json` 這類共寫檔。
- **大量資料**（events、flows、聚合、封存）與**應用狀態**分開管理，清除、回填、換 PCE 都不碰設定與
  告警紀錄。實體上是兩個 DB 還是同庫分表，由 builder 決定。
- 每種產出（報表檔、封存、快照、log）都有保留期限與清理機制，並列入同一份清單核對。
- 換 PCE（url／org_id 改變）時清除所有衍生資料，清單只有一份。
- **流量資料的形狀**【判斷 修訂】：5.x 的 raw flows 只存 `raw_json`，無法做多維彙整。v6 的 flow store 要把
  分析會用到的維度存成可索引欄位：來源／目的的 workload href、IP、hostname、各 label key 的值、enforcement
  mode；port、協定、發起端與服務端的 process／使用者（§6.5.7）；reported policy decision、方向；`timestamp_range` 的首見／最後見；
  連線數；位元組（可為空）。draft 判定**不入庫**（隨 draft 政策變動，見 §6.6 F1），需要時即時向 PCE 重算。
- **基準期連線表**【判斷 修訂】：記錄每個「來源 → 目的 × port／協定」的首見與最後見時間，供「新出現的連線」
  偵測與報表；保留期不得短於基準期（預設 30 天）。**回填的歷史會寫入基準期連線表與暴露圖**——它們是「看過什麼」
  的紀錄，不是告警評估，與 §7「回填不進告警評估」不衝突；回填深度預設等於基準期，受 PCE 保留期與 async query
  上限限制，不足時偵測器標示實際基準天數（builder check 後釐清）。
- **快照**【判斷 修訂】：每日存一份勒索防護狀態（每台主機的分數、暴露等級、逐服務防護狀態）與橫向移動
  暴露指標，供趨勢與「本期 vs 上期」比較。
- **使用者標註**【判斷 修訂】：竄改的「已知原因」、重要資產與管理群組的 label 選擇，屬於設定或應用狀態，
  各有單一擁有模組。

### 6.5 v6.0 功能範圍

**必做**（§4.1 全部目標與管理面；橫向移動、工作台、首頁、竄改調查、勒索防護、聚合分析見 §6.5.1–§6.5.7）：

- **資料收集**：events 與 traffic flows 經 API 收進 store；聚合、保留、封存、回填；PCE 速率限制；
  延遲與容量監控；截斷與資料遺失偵測（5.x 的看門狗／meta-alert 行為保留）。
  修訂【判斷 修訂】：流量收集預設**每 10 分鐘**一輪（5.x 為每小時；VEN 本身每 10 分鐘回報，再快沒有意義，
  §6.6 F7），可設定；flow store 形狀見 §6.4。另加**資料可見度健康檢查**：讀每台 workload 的
  `visibility_level`，只記錄 blocked 或關閉記錄的主機上，被允許的橫向移動根本看不到——列為首頁與報表的
  資料品質項目（§6.6 F3）。
- **告警**：規則型別 event、traffic、bandwidth、volume、system（PCE 健康），**加上 lateral（橫向移動偵測，
  §6.5.1）**【使用者 修訂】；門檻（立即／計數）、視窗、冷卻、throttle；通道 email（SMTP）、LINE、Telegram、
  Teams、webhook；逐通道測試；最佳實務規則包（加入橫向移動與竄改的預設規則）；告警紀錄保留；GUI 檢視最近
  告警與單筆詳情（含流量對應的政策解釋），詳情的主要動作改為「在工作台開啟」，「在 PCE 主控台開啟」為次要動作
  【判斷 修訂】。
- **SIEM 轉送**：audit 事件與流量；格式 cef、json、syslog_cef、syslog_json、cef_pce、syslog_cef_pce；
  傳輸 udp、tcp、tls、hec；依 policy decision 過濾；PII 遮罩；DLQ 檢視、重送、清除、匯出；狀態頁。
  `cef_pce` 已經 Graylog 實測驗收（2026-09-12），格式行為保留。
- **管理**：PCE 連線（on-prem／SaaS、console_url、verify_ssl、事件 timeout）與手動健康檢查、
  管理者帳號（初始密碼與改密閘沿用 5.x：閘門機制存在，但依使用者先前要求預設不強制首次改密，
  `config.py` `_ensure_web_gui_secret`）、允許 IP、TLS、通知通道、語言／時區、資料保留設定、背景工作健康、模組日誌。
- **升級遷移**（§7）。

**報表**（§4.1 目標 3）：產生、排程、寄信、HTML（report_shell）與 XLSX 輸出。保留的型別：

| 型別 | 回答的問題 | 決定 |
|---|---|---|
| traffic、security_risk、network_inventory | 東西向流量全貌與潛在風險（findings 規則引擎 B/L/R 系列） | 保留（風險主體） |
| readiness | 能不能切強制模式 | 保留 |
| app_summary | 單一應用的依賴與基線 | 保留 |
| policy_diff | 草稿與已佈署政策差在哪 | 保留 |
| audit | PCE 事件稽核 | 保留 |
| ven_status | agent 健康與版本分布 | 保留 |
| policy_usage | **草稿政策**下哪些規則會被流量用到、哪些流量會被草稿擋掉（draft rulesets＋`compute_draft`） | 保留【使用者】 |
| rule_hit_count | **已佈署規則**的實際命中次數（PCE 原生 RHC 報表） | 保留，**含啟用 RHC**：RHC 只能經 API 開啟，**SaaS 與地端都要能在本產品開啟**【使用者，2026-10-24】（見下「RHC 啟用」）。**RHC 只記錄已 provision 的規則**【使用者】：報表必須區分「沒有紀錄」（草稿規則、或期間內尚未佈署）與「有紀錄但 0 次」，不得把前者顯示成 0；草稿規則導向 policy_usage。RHC 是否只從啟用時刻起累計：NFR 尚無法實測，P5 在可啟用的環境驗證 |
| policy_resolver | 把已佈署規則展開成 IP 層級的平面列，供其他工具使用（例如與傳統防火牆規則比對） | 保留，維持 JSON＋CSV 輸出、不做 HTML；列數上限與截斷揭露照舊【使用者】 |

另【判斷】：拿掉所有 CSV 上傳輸入（PCE UI 匯出、workloader、vuln CSV）與獨立的 `draft_policy`
偽型別——產品前提是走 API；draft policy decision 已是 traffic 家族報表的內建欄位。

**報表的組織與呈現**（修訂；細節見 §6.5.5）：上表的型別定義與決定不變，報表目錄改依「要回答的問題」分組，
並新增三型——**橫向移動態勢**（旗艦報表）、**新出現的連線**、**非受管端點**（由 traffic 拆出）。
policy_usage 與 rule_hit_count 在目錄中並列於「規則使用」之下，但**仍是兩個型別**，RHC 的反灰與啟用流程
不受影響【判斷 修訂：草稿中曾畫成合併，因會牽動 RHC 反灰的既有決定而改為並列】。

**RHC 啟用（v6.0 兩種 PCE 寫入之一，另一種是隔離）**【使用者，2026-10-24 定案】：RHC 只能經 API 開啟，**不分 SaaS
或地端**（REST API〈Rule Hit Count〉：PCE 與 VEN 預設都關閉，兩邊都要開）。流程：

1. **狀態檢查**：產品隨時能回答「RHC 開了沒」。判定依兩個讀取：
   `GET /orgs/{org}/report_templates/rule_hit_count_report` 的 `enabled`（PCE 端），以及
   `GET /orgs/{org}/sec_policy/active/firewall_settings` 的 `rule_hit_count_enabled_scopes`（VEN 端，非空才算開；
   `[[]]` 為全部 VEN，否則為指定 scope）。狀態為：已開啟／只開了一半（指出哪一半）／未開啟／無法判定（權限或連線錯誤，
   照實顯示原因，不猜）。
2. **報表反灰**：未完全開啟時，報表頁的 rule_hit_count **反灰、不能產生，也不能排程**，旁邊說明原因並連到設定頁；
   已排程的 RHC 報表在執行時若發現未開啟，記為失敗並寫明原因，不產出空報表。
3. **在設定頁開啟**：開啟動作只放在設定頁（報表前置設定），不放在報表頁。按下後才經 API 執行：
   `PUT /orgs/{org}/report_templates/rule_hit_count_report {"enabled": true}` →
   `PUT /orgs/{org}/sec_policy/draft/firewall_settings`（`rule_hit_count_enabled_scopes`，預設 `[[]]`）→
   `POST /orgs/{org}/sec_policy`，`change_subset` 只含 firewall_settings（不會順帶 provision 客戶其他草稿）。
   已開的那一半不重做。

防護【判斷】：
- 執行前顯示將做的步驟與「會 provision firewall_settings」，操作者確認後才執行；任一步失敗即停，回報已完成到哪一步，
  之後重新檢查狀態並顯示。
- 執行前比對 draft 與 active 的 firewall_settings；若已有客戶自己尚未 provision 的 firewall_settings 變更，
  拒絕執行並說明（否則會被一併 provision）。
- PCE 拒絕（403 等）時照實顯示 PCE 的回應與「需要可寫入、具組織管理權限的 API key」，不得顯示成功。
- 架構上歸在報表服務的「報表前置設定」，不開「政策動作」服務。

**P5 開工時要先釐清的已知風險**：NFR SaaS（26.40.2）以 owner 角色的 user API key 對
`PUT /report_templates/rule_hit_count_report` 回 403（連 `enabled:false` 也是），`optional_features` 沒有相關旗標，
官方文件也未列 SaaS 差異。P5 要在 NFR 找出原因（例如 API key 的類型或角色、租戶設定），在那之前上述流程的第 3 步
在該租戶會走「PCE 拒絕」分支並如實顯示。

**調查提前到 v6.0**【使用者 修訂】：工作台、主機側寫、事件檢視（工作台的事件模式）屬 v6.0（§6.5.3）。

**仍延到 v6.1**【判斷，可推翻】：規則／ruleset 定時啟停並 provision、VEN enforcement 推進、心跳加速、
VEN 車隊總覽。架構保留「政策動作」服務的位置，v6.1 加入時不需改動下層。

**隔離放 v6.0**【使用者 修訂：5.x 規劃隔離標籤的目的，就是讓防堵能落實成隔離；2026-10-24 確認放 v6.0】：歸入橫向移動的
「防堵」一支，設計見 §6.5.1。

因此 v6.0 只有兩種 PCE 寫入：**RHC 啟用**與**隔離（套用／解除 Quarantine label，必要時建立該 label）**。
**目標仍是日常運作只需唯讀 API 角色**；兩種寫入都用同一把選填的「寫入用 key」（見下方 key 決定）。
修訂版新增的讀取端點是否 `read_only` 可用，見 §6.6 的角色表。
讀取路徑仍有三個 POST——
`/traffic_flows/async_queries`（流量查詢）、`/sec_policy/{pversion}/rule_search`（政策解釋）、
`POST /orgs/{org}/reports`（拉 RHC 報表，會在 PCE 建立報表物件）。

**NFR 實測（2026-10-24，SaaS 26.40.2，以 API 臨時建立 `read_only` 角色的 service account，測完即刪）**：
- `POST /traffic_flows/async_queries` → 202、`POST /sec_policy/active/rule_search` → 200：**唯讀角色可用**。
- `POST /reports` → 403（RHC、executive_summary、ransomware_risk 三種範本皆同；同一請求用 owner key → 201）：
  **唯讀角色不能產生任何 PCE 原生報表**。所以只要要拉 RHC 報表，日常 key 就不能是 `read_only`。
- 用 **owner** 角色的 user API key `PUT /report_templates/rule_hit_count_report`（連 `enabled:false` 的 no-op 也一樣）
  → 403 `forbidden_error "Access denied."`；`POST /reports`（RHC）→ 403 `"report template type rule_hit_count_report
  not enabled"`。NFR 上 RHC 範本是停用的，**tenant owner 無法經 API 啟用**；官方文件（REST API 26.1）寫的是
  「organization administrator」可做，與實測不符。依防護規則第一步失敗即停，未動 firewall_settings。
- RHC 啟用的 SaaS 403 見上方「P5 開工時要先釐清的已知風險」。

**API key 角色實測（2026-10-24，lab 地端 26.2.20 與 NFR SaaS 26.40.2 結果相同）**：以 API 為每個角色臨時建立 service account，
跑 v6 會用到的呼叫（寫入類一律送無效 body：403＝無權限、406＝有權限但內容不合法，不改任何資料），測完即刪。

| 呼叫 | read_only | global_object_provisioner | ruleset_* / workload_manager | admin | owner |
|---|---|---|---|---|---|
| labels、workloads、rule_sets、流量查詢、rule_search | ✓ | ✓ | 多數 ✓（workload_manager ✗） | ✓ | ✓ |
| events、active firewall_settings | ✓ | ✓ | ✗ | ✓ | ✓ |
| 讀 RHC 報表範本（狀態檢查） | ✗ | ✗ | ✗ | ✓ | ✓ |
| 產生任何 PCE 原生報表（含 RHC 報表） | ✗ | ✗ | ✗ | **✗** | ✓ |
| 開啟 RHC 報表範本 | ✗ | ✗ | ✗ | ✗ | ✓ |
| 改 draft firewall_settings、provision、建 label／ruleset | ✗ | 部分（provision 全域物件） | 部分 | ✓ | ✓ |

- **只有 owner 能產生 PCE 原生報表與開啟 RHC 範本**，連 admin 都不行；owner 角色可以給 service account。
- 除了 RHC 與隔離以外，v6 的監控、告警、SIEM、資料收集與其他報表（都由本機收集的資料產生）只需要 `read_only`。
- 現況：客戶的 key 都給 owner【使用者，2026-10-24】。
- **決定：拆兩把 key**【使用者，2026-10-24】：PCE 連線的主要 key 建議用 `read_only`（Global Viewer）的 service account，供監控、告警、SIEM、資料收集與 RHC 以外的所有報表；另設一把**選填**的 RHC key（owner 角色的 service account），只用於 RHC 狀態檢查、開啟與 RHC 報表產生。RHC key 沒填時，RHC 報表反灰並說明需要 owner 權限的 key；主要 key 若給了 owner 也能運作（相容現有客戶），設定頁提示建議改用 read_only。RHC key 欄位在 P5 加入（設定 schema 升版並由遷移器處理）。
  **修訂：RHC key 擴大為「寫入用 key」**【使用者 修訂，2026-10-24】：同一把選填 key 同時用於 RHC（狀態、開啟、報表）
  與隔離。沒填時兩者都反灰並說明原因。隔離需要的最小角色未驗（§6.6 角色表），RHC 需要 owner，所以實務上建議給 owner
  角色的 service account。欄位在第一個用到它的階段（P5 或 P6，先到者）加入。

**PCE 健康檢查與網址（依部署型態）**【使用者要求依官方文件，2026-10-24；P1 已實作探測順序】：
- 共同基線：`GET /api/v2/noop`（驗證連線與 API 憑證，Public Stable API）。
- 地端另加：`GET /api/v2/health`（HTTP 200 且 body 狀態為 normal；warning／critical 等為不健康，讀不懂為「未知」）→
  `GET /api/v2/node_available`（200 或 202）。這兩個端點文件註明只適用地端，**SaaS 不呼叫**。
- SaaS 是否健康不能只靠一次 HTTP 探測；P2 起加上事件與流量收集的最新狀態與延遲。
- 網址格式不同：地端 API 網址是 PCE 本身（通常 `https://<pce-fqdn>:8443`），主控台就是同一個網址；SaaS 的 API
  網址是區域 SCP 主機（`https://<scp>.illum.io:443` 這類），人類登入走 Illumio Console（預設 `https://console.illum.io`，
  亦可為自訂的 `*.illumio.ai`），兩者不同。設定頁依部署型態給對應的範例與主控台預設值；`console_url` 留空時，
  SaaS 用 `https://console.illum.io`，地端用 API 網址。
- 部署型態是明確欄位（`on_prem`／`saas`），不從主機名稱推測。

告警詳情頁的主要動作為「在工作台開啟」，次要動作「在 PCE 主控台開啟」（`console_url`）【判斷 修訂】。
規則編輯器需要的 label／IP list 等物件查詢、告警詳情裡的政策解釋仍要做。5.x 的規則排程
（`rule_schedules.json`）與 VEN 推進紀錄不遷移，升級報告列出它們並說明 v6.0 不支援。

#### 6.5.1 橫向移動（核心）【使用者 修訂；細節為判斷】

**共用定義**

- **管理／橫向 port 集合**：值域登錄定義一次。預設為 5.x `_LATERAL_PORTS`（16 個：SMB 445、RPC 135、NetBIOS 139、
  RDP 3389、SSH 22、WinRM 5985/5986、Telnet 23、NFS 2049、RPC portmapper 111、LDAP 389/636、Kerberos 88、
  MSSQL 1433、MySQL 3306、PostgreSQL 5432）與 PCE 勒索高風險服務中 category=admin 者（§6.6 F5）的聯集；
  可在設定頁增減。
- **重要資產**與**管理群組**：在設定頁以 label 選定（例：`app=Finance`、`role=DB` 為重要資產；`role=Jump`、
  `app=IT-Admin` 為管理群組）。未設定時：暴露面以「可觸及的主機數」排序所有主機，依賴重要資產的項目不出現，
  首頁顯示一項「尚未設定重要資產／管理群組」引導設定。不做猜測式預設【判斷 修訂】。

**可能性（暴露面）**

- **圖**：節點是主機（受管 workload；非受管以 IP 表示），可切換成 app／env label 彙總檢視；邊是觀察期間
  （預設 30 天）內**實際觀察到**的管理 port 連線。v6.0 用觀察到的連線，不從政策推算可達性
  （政策推算延後，5.x 的 policy_resolver 可作為日後基礎）【判斷 修訂】。
- **兩種狀態並排**：「現在」＝ reported 為 allowed 或 potentially_blocked 的邊（未強制所以會通）；
  「全部強制後」＝只剩 allowed 的邊。差距就是強制的價值。
- **指標**：每台主機在 k 跳內（預設 3；5.x 用 4）可觸及的主機數、可觸及每個重要資產的來源數與最短路徑、
  樞紐主機（5.x 的 articulation points 演算法可回收）、跨環境的管理 port 連線（5.x L010）。
- **勒索防護疊加**：PCE 判定「未防護且 listening」的高風險服務，在圖上標成可落腳點（§6.5.6）。

**正在發生（偵測器 → `lateral` 告警）**

每輪收集（預設 10 分鐘）後在新資料上評估；門檻與視窗可調，以下為預設方向，數值由 builder 依實測定：

| 偵測器 | 判斷 | 5.x 現況 |
|---|---|---|
| 扇出 | 一台主機在視窗內對 ≥ N 台主機發起管理 port 連線 | 報表規則 B006（N=10），無告警 |
| 新的管理連線 | 基準期（預設 30 天）未出現過的「來源 → 目的 × 管理 port」；指向重要資產時加重 | 無 |
| 跳板鏈 | A→B 之後在時間 T 內出現 B→C，兩段都是管理 port | 只有報表的可達性，不看時序 |
| 大量被擋嘗試 | 一台主機對多個目標的 reported `blocked` 連線突增 | 無 |
| 非管理群組用管理協定 | 來源不在管理群組卻使用管理 port；未設定管理群組時此偵測器停用並說明 | 無 |
| 跨環境管理 port | 不同 env label 之間有 allowed／potentially_blocked 的管理 port 連線 | 報表規則 L010，無告警 |
| 帳號扇出 | 同一個發起端使用者在視窗內對 ≥ N 台主機發起管理 port 連線（§6.5.7；依賴使用者欄位覆蓋，覆蓋不足時標示） | 報表 mod06 只做排名，無告警 |
| 非預期的發起 process | 管理 port 連線的發起端 process 不在該協定的常見清單（例：SMB 由 powershell／rundll32 發起、RDP 不是由 mstsc 發起）；清單可調 | 無 |

- **前兆加權**：同一台主機在前 24 小時內出現 `agent.tampering`（尤其 signal 型）、`agent.suspend`、VEN 離線時，
  該主機發起的偵測嚴重度上調一級，告警裡寫明前兆。
- **時序精度**：flow 的時間是 VEN 回報的 `timestamp_range`（首見／最後見），粒度受 10 分鐘回報與 snapshot 語意
  限制；跳板鏈只能判「時間上接得起來」，告警文字要這樣寫，不得寫成確定的攻擊鏈。
- **冷啟動**：基準期（含回填）未滿時，「新的管理連線」標示「基準期累積中（已 N 天）」，不發告警。
- **版本能力偵測**【判斷 修訂，builder check 後補】：PCE／VEN 版本不提供某端點或欄位時（例：沒有 `risk_summary`、
  沒有 signal 型竄改、沒有 `visibility_level`），該功能顯示「此 PCE／VEN 版本不提供」並說明需要的版本，不得顯示成
  空結果或 0（反目標 1）。實作上每項依賴集中宣告一次，由 PCE client 偵測。

**防堵（下一步）**

- **切斷點建議**（唯讀）：在通往重要資產的最短路徑上，找出移除後最能降低可觸及數的邊或主機，寫成
  「只切 bak-01 → fin-db-01 的 RDP，可觸及 fin-db-01 的主機從 41 降到 9」。
- **deny rule 試算**（唯讀）：任何建議的 deny rule，先用已收集的流量算出會擋掉哪些連線、影響哪些來源。
  只輸出建議與清單（可匯出），**不寫 PCE**。
- **隔離**（PCE 寫入，v6.0）：沿用 5.x 的 Quarantine label 機制（label key `Quarantine`，值 Mild／Moderate／
  Severe，套用到 workload），在 5.x 之上補足：
  - 執行前檢查 PCE 上**有沒有引用 Quarantine label 的政策**；沒有時明說「label 套上了也不會真的隔離」，
    不得顯示成功（反目標 1；5.x 的 `check_and_create_quarantine_labels` 建立失敗是靜默的）。
  - 執行前用流量試算隔離後會斷掉哪些連線，操作者確認後才執行；保留原本的 labels 以便解除時還原。
  - 套用與解除都寫入操作紀錄（誰、何時、哪台、哪個等級、原 labels）。
  - 使用「寫入用 key」（與 RHC 共用，§6.5 key 決定）；沒填時隔離按鈕反灰並說明。
  - 入口：主機側寫頁、工作台的主機列、橫向移動頁的樞紐主機；批次隔離沿用 5.x 能力，但試算與確認以整批為單位。

#### 6.5.2 告警補充【判斷 修訂】

- `lateral` 型規則的條件就是 §6.5.1 的偵測器與門檻；最佳實務規則包預設開啟扇出、新的管理連線（基準期滿後）、
  跨環境管理 port。
- 竄改相關事件（`agent.tampering` 的兩種分類、`agent.suspend`）的預設事件規則保留，告警內容帶入 §6.5.4 的判讀
  （規律類型、是否已標記原因）；已標記原因的同模式事件歸成一組計數，不逐筆通知。
- 告警詳情的證據區是一個分析段落（§6.3），可一鍵在工作台開啟。
- **註記**【使用者 修訂】：每則告警可留文字註記（誰、何時），並附上調查時存的工作台條件；不做 new／ack／done 狀態。

#### 6.5.3 調查工作台與主機側寫【使用者 修訂；版面為判斷】

規模以「追查一則告警」為準【判斷 修訂，依使用者「流量重點在報表」】。畫面草稿：`workbench-v2.html`（§12）。

- **骨架**：上方條件列（時間、帶入的告警條件可一鍵移除、部分比對搜尋 hostname／IP／process／使用者），
  **左側維度欄**：每個維度直接列出前幾名與數字，點一下加進條件。維度：來源／目的主機、各 label key、
  port／服務、**發起端 process／使用者、服務端 process／使用者**（兩組分開，§6.5.7）、reported 判定、方向。
  指標可切換 flow 數、連線數、不重複目的／來源數、位元組（附覆蓋率）。
- **三個視角**：明細、排名（分組最多兩層，例：來源主機 → 使用者）、**預計阻擋**（依 draft 政策向 PCE 重算，
  約一分鐘，明確按鈕觸發，不隨點選即時更新；顯示會擋下每筆連線的 deny rule，§6.6 F1）。
- **事件模式**：同一畫面切換到事件，維度改為事件類型、主機、嚴重度、操作者。
- **主機側寫頁**：誰連它、常用 port、事件時間線、竄改紀錄、目前模式、勒索防護拆解、切換模式後會被擋的流量。
- **成本取捨**：維度欄每換一次條件要同時算 6–7 個維度的前幾名。預設觀察期間 7 天；若 store 撐不住即時計算，
  允許改為「展開某個維度時才算」，但不得無聲截斷（結果是前 N 名時要寫明）。這是 P2 store 設計的主要負載來源，
  P2 計畫要先量測。
- 「存成排程報表」：把目前的分析段落存成自訂報表的一節（§6.5.5）。

#### 6.5.4 首頁「現在該關注什麼」與竄改調查【使用者 修訂；細節為判斷】

**關注清單**（首頁，也是每封報表信件的第一段）

- 來源：橫向移動暴露與偵測、竄改、勒索防護 ① 類（§6.5.6）、切換模式的阻礙、資料品質（覆蓋率、可見度、收集缺口）、
  未處理的系統健康問題。
- 排序：嚴重度 × 是否涉及重要資產 × 是否本期新出現 × 資料可信度。每項一句話說明「為什麼重要」與下一步連結；
  標示「本週新出現」或「持續 N 週」。清單是推導出來的檢視，不是收件匣（告警只有註記，§6.5.2）。

**竄改調查**（主機側寫與告警詳情內）

1. **判讀**：signal 型事件寫出 process、PID、動作（新增／刪除規則或 chain，§6.6 F4）；confirmed 型照實說明
   「這類事件不帶 process 資訊」。
2. **找規律**：依間隔把主機分成規律循環（中位數約 10 分鐘：多半是另一套防火牆程式與 VEN 搶表）、短時間密集
   （人或腳本手動改）、零星。
3. **對時間線**：列出第一次竄改前後同一主機的事件（模式變更、VEN 升級、政策 provision）。
4. **主機端指引**：依作業系統給可直接複製的單行指令（nftables：`nft -s list ruleset`、帶時間戳的
   `nft monitor ruleset`、bpftrace 掛 `nf_tables_newrule`；iptables-legacy：auditd；Windows：platform.log），
   以及 VEN 留存的竄改證據檔位置。
5. **標記已知原因**：使用者可對主機或模式標註原因（例：「NetBird，已知」），之後同模式事件歸組、持續計數、不逐筆吵。

#### 6.5.5 報表的組織與呈現【使用者：報表呈現與內容可自由發想；細節為判斷】

畫面草稿：`reports.html`、`focus-lateral.html`（§12）。

| 分組 | 報表 |
|---|---|
| 橫向移動 | **橫向移動態勢**（新，旗艦）：暴露面指標與趨勢、本期偵測、重要資產可觸及數、切斷點建議 |
| 盤點 | network_inventory（應用相依）、app_summary、**非受管端點**（新，由 traffic 拆出） |
| 分析 | security_risk、traffic、**新出現的連線**（新） |
| 評估 | readiness（含預計阻擋）、policy_usage／rule_hit_count（並列）、policy_diff、policy_resolver、勒索防護（§6.5.6） |
| 營運 | ven_status（加入竄改與已知原因）、audit |
| 自訂 | 由工作台存下的分析段落組成 |

- **信件正文就是摘要**：4 個關鍵指標（附上期比較）、3–5 條取自關注清單且屬於該報表範圍的發現（各附「為什麼
  重要＋建議動作」）、資料品質一行。附件為自足 HTML 完整報表＋XLSX 原始資料；不做 PDF。
- **以流量／事件為資料的節是分析段落**（其餘為專用分析模組，§6.3 第 4 點），能對應到流量的節都帶「在工作台開啟」連結；需要一個「GUI 對外網址」設定，未設定時信件不放連結並說明。
- **本期 vs 上期**：排程報表的每個指標都附上期比較（取自快照，§6.4）。
- 截斷與資料品質揭露依反目標 5、8。

#### 6.5.6 勒索防護【使用者 修訂；細節為判斷】

- **改用 PCE 的判定**：高風險服務清單、嚴重度、逐服務防護狀態、listening／inactive、主機暴露等級，取自 PCE
  （§6.6 F5）；取代 5.x 報表自訂的勒索 port 清單（`report_config.yaml`，與主控台數字對不起來）。
- **分數照原廠算法呈現並附拆解**（§6.6 F6）：每台主機列出「服務、嚴重度權重、覆蓋率、貢獻」；allow 規則造成的
  扣分要指出是哪條規則，並說明「被允許的來源仍算攻擊面，這是原廠刻意的設計」。逐主機逐服務的精確覆蓋率 API 不提供
  （只有 `protection_state`）；app group 逐服務覆蓋率的端點位置未知（§6.6 角色表），找到前一律以 `protection_state` 呈現並寫明是近似。
- **矛盾要標出來**：例如「全部服務已防護，但分數 0%」（lab 實況），標為「原廠數字與明細不一致」，不拿來排序。
- **疊加流量**：「未防護＋listening」再依近 30 天有無流量分成「最優先（有人在用）」與「可直接封（零影響）」；
  「未防護＋inactive 卻有連線嘗試」標為可疑。
- **更新成本**：逐主機的 `risk_details` 是一台一呼叫；依 `risk_summary.last_updated_at` 有變才重抓，並受速率限制。

#### 6.5.7 聚合分析：原廠 filter 做不到的【使用者 修訂；細節為判斷】

**為什麼**：PCE 的流量查詢只能「篩」不能「聚」——沒有分組、排名、不重複計數；process 只能依
`process_name`／`windows_service_name` 篩，比對方式文件未說明；**使用者完全不能當查詢條件**（async query 的
services 條目只有 port、to_port、proto、process_name、windows_service_name 五欄）。所以「哪個帳號用 RDP 連最多台」
「哪個 process 對外連最多目的地」這類問題只能在本產品裡回答。

**語意（實測，§6.6 F10）**：flow 上的 process／使用者屬於**回報那一端**——outbound flow 是發起端（例：
`LAB\Administrator` 的 `onedrive.exe` 往外連），inbound flow 是服務端（例：`dns.exe`、`haproxy`）。因此：

- 資料模型存成兩組維度：**發起端 process／使用者**（來自 outbound）與**服務端 process／使用者**（來自 inbound），
  畫面與報表都分開顯示，不混成一欄。
- **去重**：兩端都受管時同一條連線可能被兩邊各回報一次（lab 有 258 筆兩端皆受管的 flow 帶 process／使用者）。
  聚合以「一條連線」為單位，兩邊的屬性合併到同一筆；配對規則依實測（§6.6 F11）：來源 IP、目的 IP、port、協定相同，方向相反，且時間區間重疊或相距 ≤ 600 秒；
  不得用 `first_detected` 相等配對。配對不確定時寧可分開計並標示，不得默默重複計數。
- **正規化**：process 名稱去路徑、Windows 不分大小寫；使用者拆成網域與帳號，系統帳號（`NT AUTHORITY\*`、`root`、
  服務帳號）可一鍵排除。
- **比對**：部分比對與萬用字元（`*`），不分大小寫；不做正規表示式【判斷 修訂】。

**能做的聚合**：任何已存維度都可當分組（最多兩層）；指標含 flow 數、連線數、不重複目的／來源／port 數、位元組。
**針對橫向移動的預設分析**（工作台的預設排名、報表「分析」組的「使用者與 process」節）：管理 port 的發起端使用者
排名（依不重複目的主機數）、發起端 process 排名、服務帳號出現在管理連線、使用者 × 主機的新組合（對照基準期）。

**覆蓋率**：lab 上 process 只有 3.8%、使用者 12.3% 的 flow 有值（F2）；Linux 的 outbound 常只有使用者沒有 process。
每個以 process／使用者分組的結果都附「此分析只涵蓋 N% 的 flow」（反目標 8）。

### 6.6 修訂版依據的實測事實（2026-10-24，唯讀；lab＝地端 26.2.20，NFR＝SaaS 26.40.2）

標「實測」的是量到的；標「假設」的是推測，不得當成已知。探測腳本在 session scratchpad，未入庫。

- **F1 預計阻擋拿得到（實測，lab）**：7 天 19,098 筆 flow，async query 完成後 `PUT {query}/update_rules`，
  目的端為 visibility_only 的 flow 有 170 筆 `draft_policy_decision = blocked_by_boundary`，每筆的
  `enforcement_boundaries` 帶 `[{href: /orgs/N/sec_policy/draft/rule_sets/<id>/deny_rules/<id>}]`，即「會擋下它的
  deny rule」。觀察到的 draft 值：allowed、potentially_blocked、blocked_by_boundary；`boundary_decision` 全為 null；
  `override_deny_rules` 欄位存在（此資料中為空）；`rules` 在 78 筆含 `essential_service_rule`。
- **F2 欄位覆蓋低（實測，lab）**：位元組（`dst_bi`／`dst_bo`）1,008／19,098（5.3%），process 733（3.8%），
  使用者 2,356（12.3%）。lab 21 台中 20 台 `visibility_level = enhanced_data_collection`，**所以不是沒開 EDC**，
  原因未明。假設：位元組只出現在 `state` 為 active／closed 的 flow（778＋192＝970，接近 1,008），未驗證。
- **F3 可見度可讀（實測）**：workload 的 `visibility_level`（lab：EDC 20、flow_summary 1；NFR：flow_summary 130）。
- **F4 竄改事件有兩種（實測，lab 60 天 335 筆、6 台）**：`notifications[].info.event_classification` 為
  `confirmed`（322 筆，severity info，只有 beginning／ending_timestamp、num_events、tampering_revert_succeeded）或
  `signal`（13 筆，severity warning，`info.events[]` 帶 process_name〔iptables／ip6tables／nft〕、process_id、
  kernel_functions〔nf_tables_newrule／delrule／newchain／delchain〕、tamper_type、timestamp；原廠文件稱 VEN 26.2.20 起）。
  3 台主機的竄改間隔中位數 10.1 分鐘，另兩台 0.6 與 26.9 分鐘。
- **F5 勒索防護 API（實測）**：workload `risk_summary.ransomware` = {workload_exposure_severity（critical／high／medium／
  low／fully_protected）, ransomware_protection_percent, last_updated_at}；`GET {workload}/risk_details` →
  `risk_details.ransomware.details[]` = {name, port, proto, severity, category（admin／legacy）, protection_state
  （觀察到 unprotected、protected_closed）, port_status（listening／inactive）, active_policy, draft_policy,
  recommendation, os_platforms}；`GET /orgs/{org}/reports/risk_summary`（組織摘要，含 coverage 百分比、
  依嚴重度與類別的已防護／未防護 port 數、top risky apps／services）；`GET /orgs/{org}/app_groups/risk_summary`。
  高風險服務清單（NFR）30 項，RDP 3389 TCP 與 UDP 各一項、皆 critical。時間序列端點**路徑未知**（猜了兩個都 404，
  不代表不存在）。**矛盾**：lab 13 台 fully_protected 主機（24 項全為 protected_closed）的
  `ransomware_protection_percent` 皆為 0.0，組織 coverage 也是 0.0；NFR 90 台全未防護、0%（合理）。lab 的矛盾值得開原廠支援單。
- **F6 分數算法有公開（文件）**：Visualization Guide 24.2〈Ransomware Protection for Servers Dashboard〉——逐服務覆蓋率
  ＝ 被擋掉的 address space ÷ 全部 address space（Selective：無規則或只有 allow 0%、deny 100%、deny＋allow 部分；
  Full：無 allow 100%、有 allow 部分；Idle／Visibility 0%）；嚴重度權重 Critical 40、High 30、Medium 20、Low 10；
  主機分數為加權平均；組織分數只計 protection-ready 主機；port 是否 listening 不影響判定。文件**未定義** address space
  如何切分、組織分數如何彙總、暴露等級門檻。
- **F7 延遲底線（文件）**：VEN 每 10 分鐘回報 flow；地端 PCE 可在收到後立即以 syslog／Fluentd 匯出
  （`runtime_env.yml` `export_flow_summaries_to_syslog`，Public Experimental）；SaaS 改寫到客戶 S3。
- **F8**：async query 上限 200,000 筆（文件）。deny rule 在 ruleset 內（`rule_sets[].deny_rules`）；組織層
  `/sec_policy/{p}/deny_rules` 在 lab 回 404（實測）。
- **F9 5.x 可回收的分析**：`mod15_lateral_movement`（BFS 可達、articulation points）、`attack_posture`
  （攻擊階段排序）、rules_engine B006（扇出）與 L010（跨環境管理 port）。
- **F11 雙端回報（實測，lab 7 天）**：兩端都受管的 1,882 筆 flow 依（來源 IP、目的 IP、port、協定）分成 1,707 組；只有 outbound 的
  1,515 組、只有 inbound 的 73 組、**inbound 與 outbound 都有的約 75 組**（約 4%）。154 對 outbound×inbound 配對中，150 對時間區間重疊、
  3 對相距 10 分鐘內、1 對超過 10 分鐘；只有 12 對 `first_detected` 完全相同，所以不能用相同首見時間配對。
- **F10 process／使用者屬於回報端（實測，lab 7 天）**：2,412 筆帶 process 或使用者的 flow 中，outbound 2,184、
  inbound 228；兩端受管情形（來源受管, 目的受管）＝(是, 否) 2,099、(是, 是) 258、(否, 是) 55。outbound 的值是
  發起端（`harry`／`root` 的 443、`LAB\Administrator` 的 `onedrive.exe`），inbound 的值是服務端（`dns.exe`、
  `haproxy`／`ilo-pce`）。Linux 的 outbound 多半只有使用者沒有 process。同一連線被兩端各回報的比例未量（假設存在，
  P2 驗證）。async query 的 services 條目可用欄位只有 port／to_port／proto／process_name／windows_service_name
  （2026-07 經官方 API guide 查證），使用者不能當條件。

**修訂版新增呼叫的角色需求**（2026-10-24 P2 計畫撰寫時實測，lab 與 NFR 結果相同；方法同 P1 Task 0：以 API 臨時建立各角色
service account、寫入類送無效 body——403＝無權限、406＝有權限——測完即刪）：

| 呼叫 | 用途 | owner | `read_only` | workload_manager | global_object_provisioner | admin |
|---|---|---|---|---|---|---|
| `PUT {query}/update_rules` | 預計阻擋重算 | ✓ | ✓ | ✗（連流量查詢都不能送） | ✓ | ✓ |
| `GET /workloads`（`risk_summary`、`visibility_level` 欄位） | 可見度、勒索 | ✓ | ✓ | ✓ | ✓ | ✓ |
| `GET {workload}/risk_details` | 勒索明細 | ✓ | ✓ | ✓ | ✓ | ✓ |
| `GET /reports/risk_summary` | 組織勒索摘要 | ✓ | ✓ | ✗ | ✓ | ✓ |
| `GET /app_groups/risk_summary` | app group 勒索 | ✓ | ✓ | ✓ | ✓ | ✓ |
| `GET {app_group href}/risk_details` | app group 逐服務覆蓋率 | 404（各角色皆同：路徑或 href 形式不對，**端點位置未知**） | | | | |
| `GET /events?event_type=agent.tampering` | 竄改、前兆 | ✓ | ✓ | ✗ | ✓ | ✓ |
| `POST /labels`（建立 Quarantine label） | 隔離 | ✓ | ✗ | ✗ | ✗ | ✓ |
| `PUT {workload}`（labels） | 隔離 | ✓ | ✗ | ✓ | ✗ | ✓ |

結論：**橫向移動、勒索、竄改的所有讀取在 `read_only` 下可用，雙 key 設計不需重議**。隔離需要能建 label（owner 或 admin；
label 已存在時 workload_manager 也能套用）；RHC 需要 owner，所以寫入用 key 建議 owner。app group 逐服務覆蓋率的端點位置未知，
§6.5.6 的「可用 app group 逐服務平均覆蓋率」在找到正確端點前不成立，拆解先以 `protection_state` 呈現並標為近似。

## 7. 從 5.x 升級【使用者：設定必須帶過去，資料不必】

- **搬什麼**：PCE 連線（含憑證）、告警規則（`config/alerts.json`）、通知通道與 SMTP、SIEM 轉送與
  目的地、資料收集與保留設定、報表排程與輸出設定、語言／時區、GUI 管理者帳號（密碼雜湊）與允許 IP、
  TLS 設定與 `config/tls/` 憑證。規則排程（`config/rule_schedules.json`）v6.0 不支援，只列入報告
  （§6.5）；v6.1 加回時再補遷移。
- **不搬**：pce_cache DB、封存、`alerts.sqlite`、`state.json`、報表與趨勢歷史。v6 從空的 store 開始，
  在 PCE 仍保留的期間內自動回填。
- **格式容忍**：5.x 設定檔**沒有版本欄位**，遷移器必須吃下所有 5.x 形狀，至少包括：deprecated 鍵
  （`report.attack_surface`、`web_gui.tls.http_redirect_port`、`pce_profiles`、`active_pce_id`、
  `pce_cache.archive_review_max_days`）、`line_token` 別名、SIEM 舊 `endpoint` 欄、舊版 `alerts.json`
  為通道設定的形狀、traffic 規則的 legacy 純量鍵與 FilterBar 物件鍵兩種寫法、`pd` 整數編碼
  （0 allowed／1 potentially_blocked／2 blocked／-1 全部）、CLI `rule edit` 誤寫的 `threshold` 鍵
  （引擎實際讀 `threshold_count`）、未宣告在 schema 的鍵（`settings.fleet_*`、`events.overlap_seconds`、
  `dashboard.*`）、最佳實務規則的 `*_key` 欄位。
- **不無聲丟棄**：遷移器先產出報告（搬了什麼、改寫了什麼、丟掉了什麼、為什麼），操作者確認後才寫入；
  任何無法對應的鍵或規則都要列在報告裡。
- **確認發生在安裝時**【判斷】：`install.sh` 偵測到 5.x 安裝時執行遷移器，在 shell 顯示報告並互動確認；
  另提供非互動旗標（接受報告、或只產生報告不寫入）。這樣管理者帳號、允許 IP、TLS 在 v6 第一次啟動前
  就已就位，不需要 GUI 引導模式。遷移器屬於安裝面，不構成 CLI。
- **切換時的連續性**【判斷】：v6 回填的歷史資料**只供報表與檢視**，不送 SIEM、不進告警評估。
  SIEM 與事件告警的起點：遷移器盡力從 5.x 讀出各 SIEM 目的地／各來源已送到哪裡、事件告警的
  watermark（只讀這幾個高水位時間點，不搬資料），v6 從那裡接續，達成不重送也不漏送；讀不到時
  從 v6 安裝時刻開始，報告中明說停機期間的缺口。回退到 5.x 時，5.x 從它自己停下的地方接續，
  可能重送升級期間的資料，回退文件要寫明。
- VEN 推進紀錄（`config/fleet_progressions.json`，5.x 寫在執行目錄相對路徑）同上：v6.0 只列入報告。
  客戶為 v5.0.0，該檔要到 5.2.0 才存在，實務上應不會出現。
- **可回退**：升級保留 5.x 安裝目錄與資料原樣，提供文件化的回退步驟。
- **新預設規則對升級客戶的行為**【判斷 修訂，builder check 後補】：升級的安裝會建立新的橫向移動與竄改預設規則並開始
  評估，結果出現在首頁、橫向移動頁與報表，但**不送通知**，直到操作者在規則頁逐條開啟——避免升級當天把長期存在的
  Dev→Prod 管理連線一次灌進客戶的 LINE／email。新安裝則預設開啟通知。升級報告列出這些規則與開啟方式。
- **測試資料**：客戶設定檔拿不到，只能參考測試環境。【使用者】fixture 兩個來源：(1) 測試機 .106 的
  真實設定（去識別化，5.2.x 形狀）；(2) 由 git tag `v5.0.0` 的 `config_models.py`／`_DEFAULT_CONFIG`／
  GUI 寫入端推出的 5.0.0 形狀（客戶實際版本）。遷移器至少要涵蓋 5.0.0 到 5.2.x。
- **`pd` 對調風險**：5.1.0 以前 CLI 精靈存的 `pd` 0／1 對調；已知客戶沒有用 CLI 建規則，所以照現行
  序數轉換（0 allowed／1 potentially_blocked／2 blocked／-1 全部），不另做人工確認。【使用者】

## 8. 回收、重寫、刪除【判斷】

回收是「搬進新結構並保留其行為測試」，不是原地保留。依盤點的自足程度與契約測試覆蓋判定：

| 處置 | 項目 |
|---|---|
| **回收** | `api_client` 的 HTTP 核心（重試、TLS、auth、速率限制）與**經真 PCE 驗證的行為及其測試**（X-Total-Count 為未過濾總數、500 上限＋async 回補、label 同 key 為 OR、ip_address 只接受純字串否則 406、裸日期 406、POST 429 只重試一次、Rule Search 6 份錄製 fixture）；`events/matcher`、`events/normalizer`、事件目錄；`pce_cache/traffic_filter`；`pce_target`；SIEM formatters／transports／DLQ／mask；報表 `analysis/*` 純模組（policy_resolver、policy_diff 四核心、posture／advisor、estate_inventory 等）、`df_filter`、`port_token`、`report_shell` 與 exporters；`rule_hit_count_enablement` 的三步啟用流程；i18n 字典（去掉 CLI 鍵）；安裝／預檢／移除腳本與 systemd hardening；Direction D 設計 token；`calculate_mbps` 三態計量 |
| **重寫** | 所有 GUI 路由與整個前端；`analyzer.py`／`reporter.py` 拆成收集→評估→通知；設定與狀態的所有權；報表產生入口（單一函式、單一參數結構）；cache／live／archive 取數（§6.3 FlowSource）；filter 執行（§6.3 filter 模型）；async job 生命週期（5.x 兩套、7 個輪詢迴圈）；SMTP（5.x 三份） |
| **刪除** | `src/cli/`、`src/main.py` 的選單與 argparse、三支 `*_cli.py`、`settings/`、所有相容 wrapper、無讀者的路由與功能（`shadow` 比對器、`alert_dlq`、`rule_backups`、`_rs_background_scheduler` 等） |

修訂版補充【判斷 修訂】：**回收** `report/analysis/mod15_lateral_movement.py`（可達性與 articulation points，含已修的
BFS 爆炸問題）、`attack_posture.py`、rules_engine 的 B006／L010 判斷（改寫成偵測器）、5.x 竄改調查的擷取方法
（memory／runbook 的單行指令）；**重寫** 5.x 的隔離（label 建立失敗靜默、未檢查政策是否引用）；**刪除** 5.x
`report_config.yaml` 的勒索 port 清單（改用 PCE 判定）。

已知的 5.x 缺陷在新程式中不得重現，清單見 `tmp/rearch-2026-10-24/survey/99-synthesis.md` §6 與各分檔
「雜亂證據」節；builder 應把它們轉成新程式的守門測試。

## 9. 驗證方式

- 回收模組的行為測試隨模組搬移並持續通過。
- 告警、SIEM、報表、遷移各有對真實測試機（.106，lab PCE，on-prem）的端到端驗收；SaaS 另在
  **NFR SaaS 租戶**驗收，可自由使用，包括會觸發告警的臨時變更。【使用者】報表依專案規則以實際樣本
  資料完整產出、逐頁檢查截斷與溢出。
- GUI 以 Playwright（Python）做端到端測試；斷言使用者可見行為與不變量，不綁 DOM 結構。
- 守門測試在宣稱有效前，先注入它該抓的缺陷確認會變紅。
- 遷移器以 §7 的兩類 fixture（測試機真實設定、v5.0.0 形狀）驗證，並在測試機做一次 5.x→v6 實際升級
  與回退。注意 .106 目前持續以 5.x 運作（SIEM→Graylog、告警），切換驗收會中斷它，排程時要考慮。
- 修訂版新增【判斷 修訂】：
  - **橫向移動**：在 lab 以一台受管主機對多台主機做 SSH／SMB 連線，驗證扇出與新的管理連線偵測在收集週期內
    （約 10–20 分鐘）產生 `lateral` 告警並送達；NFR 做一次。偵測器的單元測試用錄製的 flow fixture，含基準期未滿、
    時序接不起來、覆蓋率為零等邊界。
  - **勒索防護**：本產品顯示的每台主機分數與拆解，與 PCE 主控台同一台主機的數字逐台比對；不一致時要能指出原因
    （例：lab 的 0% 矛盾），不得默默顯示另一個數字。
  - **竄改**：用 lab 60 天的真實事件驗證兩種分類的判讀、規律分類（三台 10 分鐘循環必須被分成「規律循環」）。
  - **預計阻擋**：lab 上 visibility_only 主機的 `blocked_by_boundary` flow，在工作台顯示出對應的 deny rule 名稱。
  - **報表信件**：以實際 lab 資料寄出橫向移動態勢報表，信件正文不開附件即可讀，連結落點正確；依專案規則逐頁檢查截斷。

## 10. 留給 builder 的

函式庫選擇（OpenAPI／型別產生工具、React 周邊套件）、DB 實體切分與 schema、模組與目錄命名、
頁面版面細節（在 §6.2 修訂 IA 與 Direction D 內）、程式碼放置方式（建議同 repo、新套件目錄、長期分支，
切換時刪除舊碼）、工作切分與順序。修訂版另交給 builder：偵測器門檻的預設數值（依 lab 實測定）、圖的跳數與
觀察期間預設、關注清單排序的權重、維度欄的計算策略（即時或展開時算）、圖的畫法與套件、主機端單行指令的完整清單。

## 11. 待使用者決定

（2026-10-24 builder check 後整理；使用者回答後改寫成決定並移到對應章節。）

初版：全部已回答：試點客戶事實（§3、§7）、SaaS 驗收環境（§9）、policy_usage 保留、policy_resolver 維持
現狀（§6.5）。遷移器對指向已移除型別或功能的報表排程，列入報告並略過。（初版「調查延到 v6.1」已被修訂取代。）

修訂版（builder check 後於 2026-10-24 回答，已寫入對應章節）：隔離放 v6.0、與 RHC 共用一把寫入用 key（§6.5）；
告警只加註記、不做狀態流（§4.2）；客戶規模受管 200–1,000 台、PCE／VEN 大多新版（§5）。
builder check 另外的三題由撰寫者裁定並標【判斷 修訂】：分析段落的範圍與排程存法（§6.3）、回填寫入基準期（§6.4）、
升級客戶的新預設規則先不送通知（§7）；舊版 PCE 走能力偵測降級（§6.5.1）。尚未回答：v6 是否有交付期限（影響
P5／P6 哪些可延到 6.0.x）。

## 12. 參考

- 現況盤點：`tmp/rearch-2026-10-24/survey/`（00 合約、a PCE 存取、b 快取與狀態、c 監控告警 SIEM、
  d 報表、e CLI 設定 i18n 部署、f GUI、g Codex 判讀、99 彙整）。
- v3.1 工作台設計：`docs/superpowers/specs/2026-09-04-ui-redesign-v3-1-workbench-design.md`。
- cef_pce 格式：`docs/superpowers/specs/2026-09-11-cef-pce-native-format-design.md`。
- 部署目標：測試機 .106（git checkout）、內部機 .135（離線 bundle）。
- 修訂版畫面草稿（gitignored，brainstorm session）：`.superpowers/brainstorm/3221625-1792825707/content/`——
  `workbench-layout.html`（三種查法比較）、`workbench-v2.html`（定案的工作台）、`reports.html`（報表目錄與信件正文）、
  `focus-lateral.html`（首頁關注清單與橫向移動）、`ransomware.html`（勒索防護 × 流量）。草稿裡的主機名稱與數字是示意，
  覆蓋率比例是 lab 實測。
- 原廠文件：Visualization Guide 24.2〈Ransomware Protection for Servers Dashboard〉
  （https://product-docs-repo.illumio.com/Tech-Docs/Core/24.2/Visualization/out/en/visualization-tools/dashboards/ransomware-protection-for-servers-dashboard.html）。
