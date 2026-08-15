# Phase 2A — 滾動 findings 清單（實作者檢查表）

> **用法**：每次派實作者，把本檔整份貼進 brief 的檢查清單段；每次 review 結束，把新 pattern 追加進來。
>
> **為什麼存在**：T2-T5 累積 15 個 Important findings，**實作者自我審查命中 0 個、reviewer 全抓到**。這個落差代表實作者的 brief 缺了 reviewer 心裡那份清單。這是唯一成本隨任務數遞減的改動——越往後，reviewer 要重複抓的東西越少。
>
> 本檔只收**實際發生過**的缺陷，不收泛用最佳實務。每條都標出處任務。

---

## A. Request／response 處理

**A1. 省略的 key ≠ 空的 key（T4，靜默資料遺失）**
`buildSavePayload` 在 filters 為空時整個省略該 key，後端 `d.get('filters')` 讀到 `None` 就走 legacy 分支、用前端從不送的欄位重建，把已存查詢的每個 filter 清成 `None`——**只改個名字存檔，就把有範圍限制的查詢變成無限制查詢**。生產版 UI 一律送 `filters`（即使是空的）所以沒這問題。
→ 組任何 request body 前，開 `src/gui/routes/` 對應 handler，讀清楚「key 不存在／存在但空／存在有值」三種情況各自的行為。

**A2. 送出的不可以比 UI 承諾的多（T5，未託管工作負載送往 PCE）**
加速 drawer 算出 `managed` 子集、告訴操作者其餘會被略過，實際送出 `selected.slice()`（全部）。後端只驗 href 格式，所以未託管的真的送到 PCE 去了；出貨版 UI 送的是 managed-only 清單。
→ 假設 payload 正確之前，先跟現行出貨 UI 的同一支呼叫比對。

**A3. `{ok:true}` 不等於成功（T5，兩處）**
`{ok:true, success:0, failed:n}` 被 `r.success || hrefs.length` 判成成功並啟動重複計時器；解除隔離則忽略 `results.failed`，把真實失敗誤標成「沒有目標」。
→ 檢查 handler 實際回傳的逐項計數器，不要只看外層 `ok`。

---

## B. 測試誠實度

**B1. 不可能失敗的斷言不是測試（T2、T5 各一）**
T2 交出 `assert isinstance(missing, list)`——任何 JS 陣列都滿足。T5 的 teardown 測試把所有 `destroy()` 刪光照樣會過；「三層 catalog」測試從頭到尾沒選過任何事件類型。
→ 每寫一條斷言就自問：**production 端做什麼改動會讓這條變紅？** 講不出來就是裝飾品。

**B2. 不要把你宣稱在驗的東西 stub 掉（T5）**
load-more 測試用 `page.route(...fulfill...)` 把 Flask 整個繞掉，docstring 卻寫「驗證真後端分頁」。stub 本身沒問題，**名稱或 docstring 誇大了證明的範圍**才是問題。

**B3. 絕不為了讓自己的改動過關而放寬既有測試；真要縮窄，只能縮到剛好涵蓋那個理由（T4）**
T4 把 console-error 閘門改成「訊息含 `502` 三個字就放行」，等於任何無關端點的未來回歸都會被吞掉。
→ 你的改動弄紅了前面任務的斷言，通常是你的碼有問題。真的必須調整，要在報告裡顯著標示。

**B4. 修復後才寫、從沒紅過的測試證明不了任何事（T5）**
每支新增或強化的測試都要出示 RED→GREEN；把檔案還原成修復前狀態（`git show HEAD:<path>`）跑一次即可。

---

## C. 產出物的真實性

**C1. 使用者可見文字一律走 i18n（T5）**
`"F "`／`"L "` 標籤與快選 `"d"` 後綴硬編，中文機會看到英文縮寫。鍵成對進 `src/i18n_en.json` 與 `src/i18n_zh_TW.json`，`gui_` 前綴，禁用 `v2_`／`gui_v2_`。`scripts/audit_i18n_usage.py` 現在會掃 `.mjs` 且認得 `t(` 與 `tf(`，是真閘門。

**C2. 宣稱自己是凍結來源逐條轉錄的檔案，就必須維持逐條轉錄（T5）**
`shadow_compare` 被加進 `GET_MAP`，但 `design/v2/tools/endpoints.yaml` 沒有這條，而 `store-map.mjs` 檔頭自己寫了「加 entry 必須同步改 YAML」。T11 的覆蓋閘門靠這個對應關係才驗得動。

**C3. 註解寫下的宣稱必須成立（T2、T3、T5）**
T2 的註解說殼會在首次繪製前寫入 `data-theme`（實際沒有）；T3 的 `destroy()` 註解誇大了拖曳中的保證；T5 檔頭宣稱列出所有與 mockup 的差異卻漏了兩項，另有註解說「所有 traffic key 的 absent 與 empty 等價」而 `mins` 並非如此。
→ 要嘛驗證後再寫，要嘛不要寫。

---

## D. 風格

**D1. 照周圍的碼寫，不要照自己的預設寫**
`src/static/js/v2/areas/overview.mjs` 與 `investigate.mjs` 是範本：檔頭區塊逐條記錄與 mockup 的差異並標出確切位置、用 `dom.mjs` helper 而非 `innerHTML`、色彩只走 token。
→ 一份取代整個 GUI 的 codebase 裡出現兩種明顯不同的寫法，本身就是缺陷。T2-T5 由 Claude 寫、T6-T9 由 Codex 寫，這條要特別盯。

---

## 追加紀錄

| 日期 | 來源任務 | 新增 pattern |
|---|---|---|
| 2026-08-15 | T2-T5 首次萃取 | A1-A3、B1-B4、C1-C3、D1（共 11 條，涵蓋 15 個 Important findings） |
