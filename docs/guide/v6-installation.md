---
title: v6 安裝、升級與回退
last_verified: 2026-11-06
verified_against:
  - scripts/install.sh
  - scripts/rollback.sh
  - scripts/restore-previous.sh
  - scripts/preflight.sh
  - scripts/uninstall.sh
  - illumio_ops/migrate/v6.py
  - illumio_ops/rescue.py
  - illumio_ops/migrate/v5_write.py
  - illumio_ops/migrate/v5_handover.py
---

# v6 安裝、升級與回退

illumio-ops v6 以離線安裝包安裝，可以離線執行。安裝包內含 CPython 3.12 和所有相依套件，安裝在 Linux x86_64（RHEL、Rocky 系）上，以 systemd 服務執行。v6 只有網頁介面，沒有命令列工具。

## 1. 硬體建議

| 收集模式 | 受管 Workload | vCPU | RAM | 資料磁碟 |
|---|---|---|---|---|
| 完整 | ≤ 300 | 2（推估） | 4 GB | 25 GB |
| 完整 | ≤ 1,000 | 4 | 4 GB（建議 8 GB） | 60 GB |
| 告警 | ≤ 1,000 | 2（推估） | 4 GB | 25 GB |
| 輕量（預設） | ≤ 1,000 | 2 | 2 GB（按需查詢時，每個查詢窗另需數百 MB） | 20 GB |

- 磁碟用量以預設保留天數計算：流量 35 天、彙總 90 天、基準期 30 天、事件 90 天。告警模式的流量與彙總只保留 8 天。
- 開啟封存另外計算：每 1,000 台每天約 80 MB；預設永久保留，一年約 29 GB。
- 1,000 台時建議用 8 GB 記憶體，因為每小時的橫向移動分析會多用約 0.8 GB。
- 數字來自 1,000 台的合成資料，在 4 vCPU 的機器上量測。量測細節見設計文件 §5。

## 2. 全新安裝

```
tar xzf illumio-ops-<版本>-offline-linux-x86_64.tar.gz
cd illumio-ops-<版本>
./preflight.sh                        # 先檢查主機與安裝包（只讀，不改任何東西）
sudo ./install.sh                     # 預設 /opt/illumio-ops、服務 illumio-ops、port 5001
sudo systemctl enable --now illumio-ops
```

- `preflight.sh` 會說明 `install.sh` 在這個目錄會做什麼（全新安裝、從 5.x 升級、升級已安裝的 v6），並檢查架構、glibc、
  systemd、磁碟空間、安裝包是否完整與 port。有 FAIL 時先處理再安裝；`--prefix`、`--port` 與 `install.sh` 相同。
- 安裝程式只安裝，不會啟動服務。
- 啟動後開 `https://<主機>:5001/`，以預設帳號登入並立刻改密碼，接著到「系統 › PCE 連線」填入 PCE。
- 可用的選項：
  - `--prefix`、`--service-name`、`--port`：改安裝位置、服務名稱與 port。
  - `--no-systemd`：以目前使用者安裝，只供驗證。

## 3. 從 5.x 升級

5.x 的設定會帶過來，資料不帶。v6 從空的資料庫開始，PCE 上還保留的期間會自動回填，供報表與檢視使用。

```
sudo ./install.sh --prefix /opt/illumio-ops --report-only    # 先看報告，不改任何東西
sudo ./install.sh --prefix /opt/illumio-ops                  # 顯示報告，輸入 yes 才升級
sudo systemctl enable --now illumio-ops
```

- 前綴目錄裡有 5.x（`illumio-ops.py`）時，安裝程式會自動判定這是升級。5.x 裝在別處時，用 `--upgrade-from <5.x 目錄>` 指定。
- 非互動執行要加 `--accept-report`。報告語言用 `--lang zh_TW` 指定。
- 報告會列出 5.x 的每一個設定鍵：帶過去、改寫、不支援、捨棄，各附原因。有無法轉換的值時，升級不會進行。

### 升級時會做的事

```
看報告 ─> 確認 ─> 停止並停用 5.x 服務 ─> 備份 5.x 的 unit 與 /usr/local/bin/illumio-ops
       ─> （v6 要用同一個目錄時）把 5.x 目錄改名為 <目錄>.5x-<時間>
       ─> 安裝 v6 ─> 寫入設定、TLS 憑證，並記下 5.x 停在哪裡 ─> 留下 rollback.sh
```

- 5.x 的目錄和資料不會被修改。只有在 v6 要用同一個目錄時，5.x 目錄才會被改名。
- 5.x 的 systemd unit 由 `WorkingDirectory` 找出。找不到時用 `--old-service` 指定。
- 升級程式不會跟隨 5.x 目錄裡的連結。設定檔、資料庫或 TLS 檔若是連結，升級會停下，或在報告中列為「沒有複製」。

### 不重送、不漏送

升級程式先停掉 5.x，再讀它最後的進度。v6 啟動後從那裡接續：

| 項目 | 接續點 | 說明 |
|---|---|---|
| SIEM audit 事件（每個目的地） | 5.x 最後送出的事件時間；有較早但仍在排隊的事件時，從那筆開始 | 至少送達一次：仍在排隊的較舊事件會重送，可用 `externalId` 去重；5.x 已放棄的事件（它的 DLQ）不重送，數量列在報告裡 |
| 事件告警 | 5.x 最後評估到的事件 | 停機期間的事件會照常告警 |
| 收集 | 從上述最早的時間點開始，最多往回 7 天 | 停機期間的資料以即時資料收進來，所以會送出、也會告警；超過 7 天的缺口寫在報告裡 |

- 5.x 的流量轉送在 v6 改為「新連線」事件，沒有接續點。這個來源需要告警或完整模式，並且要等基準期滿才會開始送。
- 接續的結果寫在 `<前綴>/logs/migration-report.txt`。

### 升級客戶的新預設規則

橫向移動與異常偵測的預設規則會開始評估，結果出現在告警頁、偵測頁與報表，但不送通知。要通知就到「告警規則與通知」頁逐條開啟。這是為了避免長期存在的管理連線在升級當天一次湧進 LINE 或 email。

### 5.x 的規則排程

`config/rule_schedules.json` 裡的每筆排程遷移為**暫停**，名稱、星期、起訖時間、時區照搬（`local` 換成主機時區；
`UTC+5.5` 這類寫法保留為 `UTC+05:30`）。讀不懂的項目寫在遷移報告，不會遷移。到「規則排程」頁逐筆確認後按「繼續」；
排程要動 PCE 需要「系統 › PCE 連線」的寫入用 API key。目標在 PCE 上已刪除的，第一次檢查時會標為「PCE 上已刪除」。

## 4. 回退到 5.x

```
sudo /opt/illumio-ops/rollback.sh
```

- 回退會做這些事：
  - 停止並停用 v6。
  - 把 v6 目錄改名為 `<前綴>.v6-rolled-back-<時間>` 保留下來，裡面有設定、資料與遷移報告。
  - 把 5.x 放回原位，還原它的 unit 與命令列包裝。
  - 啟動 5.x。
- 5.x 會從它自己停下的地方繼續，所以 v6 運作期間送過的 SIEM 事件與告警，可能會再送一次。
- 回退後要再升級，重新執行 `install.sh` 即可。被保留的 v6 目錄不影響新的升級。

## 5. 升級已安裝的 v6

解開新版安裝包後，在同一個前綴再執行一次 `install.sh`：

```
sudo ./install.sh                  # 先顯示升級計畫，輸入 yes 才動手
sudo ./install.sh --report-only    # 只看計畫，什麼都不改
sudo ./install.sh --accept-report  # 不詢問（非互動）
```

```
讀取既有安裝（不改任何東西）
  ├─ 已安裝的版本比安裝包新 ──────────> 拒絕（不會把舊版裝到新版上）
  ├─ 設定檔或資料庫比安裝包新、或新版無法啟動 ─> 拒絕，並指出原因
  └─ 可以升級：顯示「從 X 升到 Y」與首次啟動會改結構的資料庫
停止服務 ─> 舊版程式、設定檔，以及新版首次啟動會遷移的資料庫，複製到 <前綴>/previous
        ─> 安裝新版程式與相依套件、更新 systemd unit
        ─> 原本在執行就重新啟動，並確認服務起得來
```

- 設定、資料、報表、日誌與憑證都留在原處，不會重新初始化。
- 需要複製資料庫時，會先確認磁碟空間足夠，不夠就不動手。
- 相同版本也可以重新安裝（修復被改壞的程式檔）。
- 服務的 unit 名稱會自動找出（執行這個前綴的那個 unit）；找不到時用 `--service-name` 指定。

### 回到升級前的版本

```
sudo /opt/illumio-ops/restore-previous.sh
```

- 停止服務，把 `previous/` 裡的舊版程式、設定檔與資料庫副本放回，原本在執行就重新啟動。
- 新版改過的設定檔與資料庫不刪除，改名為 `*.from-<新版版本>-<時間>` 留在 `config/`、`data/`。
- 升級後在介面改的設定、以及寫進被還原資料庫的資料，會回到升級前的狀態；其他資料照舊。
- 只保留前一版：再升級一次，`previous/` 就換成那次被取代的版本。回到 5.x 仍用第 4 節的 `rollback.sh`。

## 6. 進不了網頁介面時（救援指令）

先停止服務，再以服務帳號執行（指令會拒絕在服務執行中或以其他帳號改設定）：

```
sudo systemctl stop illumio-ops
sudo runuser -u illumio-ops -- env PYTHONPATH=/opt/illumio-ops \
    /opt/illumio-ops/python/bin/python3 -P -m illumio_ops.rescue <指令> --root /opt/illumio-ops
sudo systemctl start illumio-ops
```

| 指令 | 用在 |
|---|---|
| `reset-password` | 忘記管理者密碼。改完後所有已登入的人都會被登出。 |
| `clear-allowed-ips` | 允許 IP 清單把自己擋在外面。清單清空（任何位址都能登入），並印出原本的清單，登入後到「系統 › 安全」重設。 |
| `reset-tls` | 匯入的憑證不見了、與私鑰不合或加密套件設錯，服務起不來。改回自簽憑證（下次啟動時產生），不刪除原本的憑證檔；之後到「系統 › 憑證」重新匯入。 |
| `check-settings` | 服務起不來時，檢查設定檔並指出哪一欄有問題。 |

## 7. 解除安裝

```
sudo /opt/illumio-ops/uninstall.sh          # 移除服務與程式，保留 config/、data/、reports/
sudo /opt/illumio-ops/uninstall.sh --purge  # 連設定、資料與報表整個目錄一起刪除
```

- 動手前會先說明要刪什麼，輸入 yes 才執行；非互動時加 `--yes`。
- 保留下來的 `config/`、`data/`、`reports/` 改由 root 擁有、權限 0700：服務帳號 `illumio-ops` 會一併刪除（同一台主機上
  還有其他 illumio-ops 服務時保留），它的 user id 之後可能分給別的程式。
- 之後在同一個目錄再執行 `install.sh`，會沿用保留的設定與資料重新安裝（登入帳密、PCE 連線、規則都還在）；
  保留的設定或資料庫若比安裝包新，會拒絕安裝。

