# 升級路徑：PCE profile 移除之後

> 狀態：設計待使用者審閱。
> 本檔所有對現況的描述皆已對原始碼與真機查證；行號會漂移，以符號為準。

## 1. 要解決什麼

2026-08-21 移除 PCE profile 功能時，只處理了「新版程式讀到舊 config 會怎樣」（`_strip_deprecated_keys`
在載入時丟棄 `pce_profiles` / `active_pce_id`），沒有處理「**既有安裝升級上來時，那台機器可能已經
處於受污染狀態**」。

2026-08-24 在測試機上實際遇到這個情況，並非假想：

```
config.json.pre-profile-removal.bak
  pce_profiles:
    name=lab   url=https://pce.lab.local:8443   有 key
    name=tpce  url=https://tpce.lab.local:8443  有 key
  active_pce_id = tpce
```

該機器於 2026-08-18 把 active profile 從 `lab`（172.16.15.130）切到 `tpce`（172.16.15.131），
**cache 未被沖洗**。結果：

- `pce_traffic_flows_raw` 同時含兩台 PCE 的資料，無任何標記可區分
- 封存日檔同樣跨兩台（07-03～08-18 來自 .130，08-19 之後來自 .131）
- 表面上完全正常——沒有錯誤、沒有警告，只是報表與告警的歷史基準橫跨兩個不同的環境

清理需要人工介入：停服務、沖 cache、VACUUM（5.0 GB → 172 KB）、搬走封存、以有防護的
`config login --pce-target-change flush` 重新指向。升級腳本應該在升級當下就把這件事攤在
操作者面前。

## 2. 現況（查證結果）

### 2.1 `scripts/install.sh` 的既有升級處理

- `IS_UPGRADE` 由 `config/config.json` 是否存在判定（`:127`）
- **有一個「Migrate deprecated config fields on upgrade」區塊（`:229-247`），但只處理
  `web_gui.tls.http_redirect_port` 一個鍵**——`pce_profiles`、`active_pce_id`、
  `pce_cache.archive_review_max_days` 皆未涵蓋
- 有 cache DB 的 `user_version` 前向相容守門（`:165`）：DB 比 bundle 新就拒絕安裝
- 結尾 `chown -R illumio-ops:illumio-ops "$INSTALL_ROOT"`（`:266`）與細緻權限設定——
  **檔案擁有權由安裝腳本負責，這點現況正確**

### 2.2 `scripts/install.ps1` 沒有對應區塊

Windows 端**完全沒有 deprecated 欄位遷移**（`grep http_redirect_port` 零命中）。這是既有的
parity 缺口，不是本案造成的，但本案新增的邏輯若只做 Linux 會把缺口擴大。

### 2.3 應用層的既有行為（不要重複做）

- `_strip_deprecated_keys`（`src/config.py`）在**每次載入**時丟棄已退場的鍵並記 WARNING。
  真機實測：重啟後 log 出現
  `Ignoring deprecated config key(s): pce_profiles, active_pce_id, pce_cache.archive_review_max_days`
- **被丟棄的鍵在磁碟上仍然存在**，直到下一次存檔重寫。這是**刻意的行為**（CHANGELOG 的
  PCE profile 條目明載），因為那是另一個 profile 憑證的**唯一副本**
- `flush_pce_derived_state`（`src/pce_cache/flush.py`）在兩道分析鎖下清空八張表、
  PCE 衍生 state key 與 dashboard 摘要
- `pce_target_changed`（`src/pce_target.py`）是 CLI 與 GUI 共用的「是否換了 PCE」判準

### 2.4 移除功能留下的孤兒檔

`data/archive_review.sqlite` 與 `data/archive_review.sqlite.meta.json` —— 2F-1 Task 7 移除了
唯一會讀寫它們的程式碼，但檔案留在磁碟上。真機上該 DB 有一定體積且永遠不會再被讀取。

## 3. 決策

### 3.1 升級時偵測污染，但**不自動沖洗**

**判準：`pce_profiles` 中存在兩個以上 (url, org_id) 相異的 profile。**

> **初稿的判準是錯的，且錯得剛好會漏掉本案的目標情境**（2026-08-24 Codex 對抗式審查指出，
> 已查證屬實）。初稿寫「active profile 與 `api` 區塊**不一致**才警告」，但舊版
> `ConfigManager.activate_pce_profile()`（`git show dbaa6b5^:src/config.py:679`）在切換時
> 會把 profile 的 `url`/`org_id`/`key`/`secret` **複製進 `api` 後存檔**：
>
> ```python
> for k in ("url", "org_id", "key", "secret", "verify_ssl"):
>     if k in p: api[k] = p[k]
> ```
>
> 因此任何一次正常切換之後，兩者**必然一致**。§1 那台真機的備份正是
> `active_pce_id=tpce` 且 `api.url=tpce.lab.local`——初稿判準在它唯一該觸發的機器上會完全靜默。

改用「profile 清單裡有沒有第二個 PCE」作為判準：有第二個目標，就代表**曾經可以切換**，
而切換不會沖洗 cache。這會涵蓋所有真正有風險的機器，代價是「裝了兩個 profile 但從未切過」
的機器也會收到警告——那是可接受的偽陽性，因為警告本身不具破壞性，且操作者比腳本更清楚
自己切過沒有。

**不自動沖洗**，理由有三：

1. 沖洗會刪掉操作者可能還需要的歷史，而升級腳本沒有立場替他決定
2. 沖洗需要停服務並取得分析鎖；在安裝流程中間做，失敗處理會變得複雜
3. **本案的正確修法本來就包含「重新指向哪一台 PCE」這個決定**——而那是操作者的決定，
   不是升級腳本能推導的

改為：**明確告知 + 給出可照抄的指令**。升級不因此失敗（exit code 不變）。

### 3.2 憑證不由腳本搬移，但要明說去哪裡找

`pce_profiles` 裡的其他 profile 帶著 `key`/`secret`，那是它們的唯一副本。腳本**不得**
把這些鍵從檔案裡刪掉——刪了就沒了。反而要明白告訴操作者：那些憑證還在 `config.json` 裡，
在下一次存檔之前都還救得回來，以及怎麼取出。

這與 2.3 的既有行為一致：應用層丟棄但不改檔，腳本也不改。

### 3.3 `archive_review_max_days` 併入既有的遷移區塊

它與 `http_redirect_port` 同類——純設定鍵、無資料意涵、刪掉沒有副作用。加進
`install.sh:229` 那個區塊，並在 `install.ps1` 補上等價實作。

**`pce_profiles` / `active_pce_id` 不加進去**（見 3.2）。

### 3.4 孤兒檔：提示，不刪

`archive_review.sqlite*` 由腳本偵測並提示可刪與其體積，不自動刪除。理由同 3.1：
那是資料，不是程式碼；而且它可能是操作者查歷史的最後手段。

## 4. 設計

### 4.1 新增升級檢查（`install.sh` 與 `install.ps1` 各一份）

在既有的 deprecated 欄位遷移區塊**之後**、post-install verification **之前**執行。
以 bundle 內的 python 執行，不新增外部相依。

輸出四種情形之一：

| 情形 | 判定 | 輸出 |
|---|---|---|
| 無 `pce_profiles`，且無遷移標記 | 見下方說明 | 一行提示：無法判定，附自查指令 |
| 無 `pce_profiles`，但有本腳本先前留下的遷移標記 | 標記記載當時只有 0–1 個 PCE | 靜默 |
| 有 `pce_profiles`，僅一個 (url, org) | 只有一個目標，切不了 | 一行提示：profile 已移除、憑證仍在檔案裡 |
| 有 `pce_profiles`，兩個以上相異 (url, org) | 曾可切換 | **顯著警告**（見 4.2） |

**「鍵不存在」不等於安全。** 移除版跑過之後，任何一次 `ConfigManager.save()` 都會把載入時
剝除的 `pce_profiles` 從磁碟上抹掉，但**不會**清理已經混合的 cache；下一次升級就只看到一個
沒有舊鍵的 config，完全靜默。因此本檢查在首次執行時必須寫下一份**遷移標記**
（`config/.pce-profile-migration.json`，記錄檢查當下看到幾個相異 PCE 目標與時間戳），
後續升級以標記為準。標記不存在且無舊鍵時，只能誠實說「判定不了」並附上自查方式，
不得靜默放行。

URL 與 org_id 的比較必須沿用 `src/pce_target.py` 的 `normalize_pce_url` /
`normalize_org_id`，不得自行實作字串比對——否則 `https://host:8443` 與 `https://host:8443/`
會被判成不同的 PCE，把每一次升級都變成假警報。

### 4.2 警告的輸出內容

必須包含四件事，缺一不可：

1. **發生了什麼**：這台機器的 cache 可能同時含有多台 PCE 的資料，沒有標記可以區分
2. **影響**：建立在 cache 上的報表、告警與查詢，其歷史基準橫跨多個環境
3. **涉及哪些 PCE**：`pce_profiles` 裡每個相異的 url/org 逐條列出，並標明 `api` 目前指向哪一個
4. **可照抄的處理指令**，且順序正確（兩種情境分開給，見下）

**必須用安裝的 wrapper `illumio-ops`，不得寫裸的 `python -c`。**
初稿寫 `<INSTALL_ROOT>/python/bin/python3 -c "from src.cli import cli; cli()"`，那條指令
從家目錄或解壓目錄貼上會直接 `ModuleNotFoundError: No module named 'src'`——絕對的 python
路徑不會把 `INSTALL_ROOT` 加進 import path。更糟的是 `db_path`、state 路徑預設是相對的
`data/...`/`logs/...`，即使補了 `PYTHONPATH` 也會操作到**錯誤位置的檔案**。
`scripts/install.sh:284` 裝的 `/usr/local/bin/illumio-ops` wrapper 已經處理好 `cd`
與環境，用它。（2026-08-24 Codex 對抗式審查指出，已查證屬實。）

**情境 A — 要改指向另一台 PCE：**

```
sudo systemctl stop illumio-ops
sudo -u illumio-ops illumio-ops config login --url <要用的 PCE> --org-id <org> \
    --pce-target-change flush
sudo systemctl start illumio-ops
```

**情境 B — 維持目前 `api` 指向的 PCE，只清掉混進來的舊資料：**

```
sudo systemctl stop illumio-ops
sudo -u illumio-ops illumio-ops cache flush --confirm
sudo systemctl start illumio-ops
```

> **`cache flush` 目前不存在，本案必須新增**（2026-08-24 Codex 對抗式審查指出，已查證屬實）。
> `flush_pce_derived_state` 只有三個呼叫端：互動選單（`src/cli/menus/_root.py:120`）、
> `config login`（`src/cli/config.py:335`）、GUI 設定（`src/gui/routes/config.py:332`）。
> 而 `login_cmd` 只在 `target_changed and pce_target_change == "flush"` 時才沖洗——
> **操作者若選擇留在同一台 PCE，情境 A 的指令會成功存檔卻完全不清快取**，
> 而那正是本案最常見的選擇（污染來自過去的切換，現在的指向通常是對的）。
> 新命令掛在既有的 `cache` 群組下（`src/cli/cache.py:58`，已有 backfill/status/retention），
> 必須要求明示確認旗標，且沿用 `flush_pce_derived_state` 的兩道分析鎖，不另建路徑。

**指令必須以 `sudo -u illumio-ops` 執行。** 2026-08-24 真機事故：以 root 執行
`config login` 會把 `config.json` 重寫成 root 所有，服務（跑在 `illumio-ops` 身分）
隨即 crash 迴圈，且錯誤訊息只說 Permission denied、不會指出是擁有者被改。
連帶被改到的還有 `alerts.json`、`logs/state.json`、`logs/dashboard_summary.json`。

**不得在提示裡寫 `--secret`**：`config login` 自己會警告該參數會出現在 process listing。
提示應引導操作者用互動式輸入。

### 4.3 封存目錄的提示

若 4.1 判定為警告情形，額外提示：封存日檔同樣可能跨兩台 PCE，沖 cache 不會動到它們，
處理方式是把現有 `archive_dir` 整個搬開讓新的重新累積（附上指令）。**搬移不是刪除**——
PCE 只保留約三個月，超過的部分封存是唯一副本。

### 4.4 孤兒檔提示

偵測 `data/archive_review.sqlite`，存在則印出路徑與體積，說明 2F-1 之後已無任何程式讀取它，
可安全刪除。不自動刪。

### 4.5 Windows parity

`install.ps1` 需要 4.1–4.4 的等價實作（含 `cache flush` 的 PowerShell 版指令範例），以及 2.2 指出的既有缺口（`http_redirect_port`
遷移）一併補上。指令範例改為 PowerShell 與 NSSM 形式，服務身分的等價要求同樣適用。

## 5. 測試

- 升級檢查的單元測試（以暫存 config 檔驅動）：四種情形各一，斷言輸出**包含**必要元素
  而非逐字比對（文案會變）
- **URL 正規化**：`https://h:8443` 與 `https://h:8443/` 判為同一台；不同 host 或不同 org
  判為不同。**不得測 `https://h:8443/api` 與 `https://h:8443` 等價**——`normalize_pce_url`
  只去尾端斜線、**刻意保留 path**，該案例與「必須沿用該函式」互相矛盾。要改變這個語意
  就得連 CLI 與 GUI 的 target-change guard 一起重新設計，不在本案範圍。
  （2026-08-24 Codex 對抗式審查指出，已查證屬實。）
- `cache flush` 的測試：拒絕未帶確認旗標的呼叫；帶旗標時確實清空八張表與 state key；
  與 `config login --pce-target-change flush` 走同一個 `flush_pce_derived_state`（不得有第二套）
- **守門測試**：`install.sh` 與 `install.ps1` 的 deprecated 遷移鍵集合必須相等（集合相等，
  非子字串），否則 parity 會再次漂移
- 既有 `tests/test_offline_bundle*.py` 需涵蓋新增區塊不破壞既有升級流程
- **提示指令的可執行性**：4.2 的指令字串以 `--help` 層級驗證其選項確實存在
  （比照本專案「brief 裡的每一條命令派工前自己先跑過」的紀律）

## 6. 本設計不處理

- **自動沖洗**：見 3.1
- **憑證搬移**：見 3.2
- **封存檔的跨 PCE 標記**：讓封存檔自帶來源 PCE 識別是更根本的修法，但那要改產生端格式
  與既有檔案的相容處理，範圍遠大於本案
- **cache 列的 PCE 來源欄位**：同上，且會動到 `flow_hash` 的組成
- 已安裝機器的既有污染：本案只保證「升級時會被告知」，清理仍由操作者依提示執行
