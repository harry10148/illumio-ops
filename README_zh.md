# illumio-ops

> **[English](README.md)** | **[繁體中文](README_zh.md)**

**illumio-ops** 是 **Illumio Core** 的無代理輔助工具，核心在偵測**橫向移動**。它只透過 REST API 讀取 PCE，不部署代理程式。除非操作者隔離某台主機，否則不會變更任何 Workload。整個產品是單一服務，只有網頁介面。v6 是 5.x 的重建版，沒有命令列。

- **偵測**：
  - 橫向移動：扇出、新的管理連線、樞紐鏈、跨環境等。
  - 允許流量中的異常。
  - 結果出現在首頁關注清單與橫向移動頁。
- **告警**：
  - 對象：PCE 事件、流量、偵測，以及產品自身的健康狀況。
  - 送達：email、LINE、Telegram、Teams、webhook。
  - 規則可以排除 Label、Workload、位址、PCE IP List 與公網位址。
- **報表**：
  - 格式：HTML、CSV、XLSX、JSON。
  - 可以排程或隨時產生；寄出的信件正文就讀得懂。
- **調查工作台**、主機側寫、隔離、Rule Hit Count。
- **SIEM 轉送**：
  - 內容：audit 事件、偵測、告警、新連線。
  - 傳輸：syslog、TLS、Splunk HEC。
  - 格式：CEF 或 JSON。
- **三種收集模式**：輕量（預設，按需向 PCE 查詢）、告警、完整。

## 安裝、從 5.x 升級、回退

見 [docs/guide/v6-installation.md](docs/guide/v6-installation.md)。重點如下：

- 安裝方式：Linux x86_64（RHEL、Rocky）的離線安裝包。
- `install.sh`：全新安裝，或升級 5.x。升級時設定會帶過來，SIEM 與事件告警從 5.x 停下的地方接續。
- `rollback.sh`：回退到 5.x。
- 5.x 的文件保留在 [docs/legacy-5.x](docs/legacy-5.x/)。
