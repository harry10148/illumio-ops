# 交接：2026-09-15

給接手的 agent。**先讀這份，再讀你要動的那條線的計畫／spec。**

---

## 1. 現況

| repo | HEAD | 狀態 |
|---|---|---|
| `illumio-ops` | `cc4d9e26` | main 乾淨、已推、CI 綠 |
| `claude-config` | `e5df8af` | 乾淨、已推 |
| `~/.claude-mem` | — | dev 側已推；**Mac 側待人在 Mac 上跑 `mem-sync`** |

`feat/ven-fleet-manager` **已完全併入 main**（領先 0 個 commit），PR #31 MERGED。
worktree `.worktrees/ven-fleet-manager` 還在但已無獨立內容，可刪。

---

## 2. 卡住的兩件事（都不是程式問題）

### 測試機關機中

`illumio-ops-test`（172.16.15.106）**電源關閉**，`No route to host`。因此：

- **部署沒做。** main 上 `2a9d56ae`（fleet 合併）之後的東西都還沒上測試機。
  開機後跑：
  ```
  ssh illumio-ops-test 'cd /root/illumio-ops && git pull --ff-only -q origin main \
    && git rev-parse --short HEAD && systemctl restart illumio-ops \
    && sleep 6 && systemctl is-active illumio-ops'
  ```
- **VEN 報表的真機驗收沒做**（見 §3）。

### Mac 端記憶體同步

拓撲是 Mac → dev（dev 託管 bare repo），dev 沒有到 Mac 的 SSH 入口，所以 Mac 側
只能由操作者在 Mac 上跑 `mem-sync`。跑完之後 dev 這側要再跑一次才算收斂
（規則：Mac 先、dev 最後）。

---

## 3. 唯一的未完成驗收項

**VEN 狀態報表四個新章節的真機視覺驗收。**

計畫（`plans/2026-09-09-ven-fleet-manager.md` Task 5）要求：對 lab 產 en 與 zh
各一份 VEN 報表，用 Playwright 在 **800 與 1280 兩種寬度**逐頁截圖，確認
`fleet-pipeline`／`fleet-compat`／`fleet-score`／`fleet-gaps` 四章沒有截斷或溢出。

**不要把它當成已通過。** 本專案 `CLAUDE.md` 明寫：報表交付前要用實際樣本跑一次
完整輸出並逐頁檢查，而這個 repo 的報表截斷問題重複發生過 5 次。

同一件事也記在 spec 的「未完成」段落
（`specs/2026-09-09-ven-fleet-manager-design.md` 文末）。

---

## 4. 已完成：VEN Fleet Manager（plugger 移植 1／4）

六個 task 全交付，全套 4986 passed、五道閘門綠、CI 綠。

| Task | commit | 內容 |
|---|---|---|
| 1 | `92434242` | `analyze_fleet` 純函式 |
| 2 | `764dce11` | 排程寫快照 ＋ 兩支唯讀 API |
| 3 | `871214d5` | 兩段式推進（**唯一會寫 PCE 的一段**）|
| 4 | `7c541616` | `#/investigate/fleet` ＋ 推進抽屜 |
| 5 | `077d13d6` | 報表四章 ＋ xlsx `Fleet` sheet |
| 6 | `abbc13da` | 文件／CHANGELOG／spec 標記 |

**實作與 spec 的七條偏離全部記在 spec 文末**，包括三條你動到相關程式碼時會撞到的：

1. `visibility_only` **不在** glossary。spec 與計畫都說它是，實查不是。操作者文案
   用 `Visibility only`，API 值域仍是 `visibility_only`。
2. `visibility_ready` / `visibility_not_ready` 在 `workloads_index` 上**分不出來**
   （缺 `security_policy_received_at`），`/api/fleet/list` 對這兩個 bucket 都回整個
   `visibility_only`。摘要 count 仍精確。
3. **`bulk_update` 的 response schema 未經真 PCE 驗證。** Illumio KB 沒有這份
   schema；逐筆 `{href, status, errors}` 的解析是假設。PCE 沒回應到的 href 會被
   賦予整批的結果，不猜生死。**這是整個功能唯一沒有事實基礎的地方。**

---

## 5. 下一條線

`plugger-port-program`：fleet → **app-dep** → vmaps → isolator。

另外三個子專案的 spec 與 plan **都已寫好**：

| 子專案 | spec | plan |
|---|---|---|
| app-dep | `specs/2026-09-09-app-dependency-intel-design.md` | `plans/2026-09-09-app-dependency-intel.md` |
| vmaps | `specs/2026-09-09-vuln-scan-import-design.md` | `plans/2026-09-09-vuln-scan-import.md` |
| isolator | `specs/2026-09-09-workload-isolator-design.md` | `plans/2026-09-09-workload-isolator.md` |
**但它們是同一天寫的，而 fleet 這條線證明了
那批計畫的錨點會過期**——fleet 的計畫裡有四處與原始碼不符（行號漂移之外，還有
欄位根本不存在、端點數算錯、要改的檔其實不用改）。

**動手前逐條核對錨點。** 這是這次省下最多來回的一件事。

另一條未排期：`plans/2026-09-13-gui-operator-clarity.md` 的批次 3（R2/R3/R4/R6
與 R5 剩下那半），計畫寫明**要先寫 spec**。五條的查證結果已寫在該計畫文末，其中
兩條的原始描述是錯的。

---

## 6. 這一輪學到、對你有用的三件事

- **宣布任何守門「有效」之前，注入它該抓的缺陷確認會變紅。** 這輪注入 29 次，
  抓到 **3 支假綠**：版本排序（fixture 的 26/25/23 字串序與數值序恰好一致）、
  xlsx 不截斷（fixture 只有 5 台，截到 50 沒差）、partial 分數說明（那個詞在隔壁
  卡片也有）。三支都「一直綠」而且守不住它宣稱的東西。
- **i18n 稽核連註解都讀。** 在註解裡示範壞寫法（`t("前綴" + 值)`）本身就是一條
  finding。同一種形狀這輪出現兩次。
- **`!` 跑不了需要 sudo 的指令**——沒有互動 tty，會靜默卡在密碼提示，看起來像
  執行了但什麼都沒發生。交指令給操作者時要附一條你自己能查的驗證。

`.claude/projects/-home-harry-rd-illumio-ops/memory/` 底下有完整的教訓索引
（`MEMORY.md`）。
