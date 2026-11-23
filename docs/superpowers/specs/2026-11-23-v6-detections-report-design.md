# 新報表：特殊分析的偵測與告警（設計草案）

使用者 2026-11-20：「新報表：專列特殊分析告警（異常偵測、告警歷史）」——「好」。2026-11-23 使用者照建議定案（範圍只放偵測類、報表名「偵測與告警」）。

## 1. 要回答的問題

讀者是值班或主管：「這段期間，偵測（橫向移動與異常）抓到了什麼、哪些變成告警、告警有沒有送到、哪些被標為已知」。
事件規則、流量規則、系統檢查的告警在「週總覽」已有總數；本報表只看**偵測類**（告警分類 `lateral`、`anomaly`，來源是 21 種偵測器）。

## 2. 資料來源（全在本機，不查 PCE）

| 資料 | 位置 | 已有的讀法 |
|---|---|---|
| 偵測 | flow store `detections`（detector、subject、severity、first_seen／last_seen、occurrences、critical_asset、summary） | `detection_counts`、`detections_first_seen_between` |
| 標為已知 | app.sqlite `detection_annotations` | `services/alerts/known.py` |
| 告警 | app.sqlite `alerts`（rule、severity、subject、fired_at、grouped_annotation、late） | `period_counts`、`counts_by_category` |
| 送出結果 | `alert_deliveries`（channel、status、attempts、last_error） | `deliveries` |
| 紀錄可信起點 | 告警保留天數與 PCE 綁定時間 | `weekly_overview.alerts_known_from` |

不需要流量查詢，所以不是「按需查詢」型報表；輕量模式下沒有偵測（偵測需要逐輪收集的流量），報表照實說。

## 3. 內容

1. **結論句與 KPI**：期間新偵測數（其中高與嚴重）、偵測告警數、送出失敗數、標為已知數。
2. **偵測，依種類**：21 種各一列——新出現數、其中高／嚴重、涉及主機數、涉及重要資產數；沒有出現的種類合成一行列名稱。
3. **偵測清單**：依嚴重度、重要資產、時間排序，前 N 筆（主機、種類、首次與最後、次數、是否標為已知、連到偵測頁）；超過 N 筆寫明總數。
4. **最常出現的主機**：偵測數最多的前 N 台，各列種類分布。
5. **告警歷史**：偵測類規則逐條——觸發次數、嚴重度分布、標為已知數、送出結果（已送、失敗、不通知）；依日分布。
6. **沒送到的告警**：送出失敗的告警與最後錯誤（已去除密碼與 token）。
7. **資料限制**：期間早於告警紀錄可信起點時寫明；輕量模式寫「偵測需要告警或完整模式」；
   冷卻與頻率限制擋下的次數**沒有依時間記錄**（只有累計），本報表不列，以免寫出算不出來的期間數字。

格式與其他報表相同：HTML、XLSX、郵件摘要；可排程。

## 4. 不做

- 不重算偵測（只讀已存的結果）；不列事件／流量／系統告警（週總覽有）。
- 不改橫向移動報表的「本期偵測」段（那段是暴露面脈絡裡的摘要）。

## 5. 定案

- 範圍：只放偵測類告警（`lateral`、`anomaly`）。
- 報表名：「偵測與告警」／"Detections and alerts"；report_type `detections`。
