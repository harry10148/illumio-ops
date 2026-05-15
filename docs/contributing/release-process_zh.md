---
title: Release Process
audience: [developer]
last_verified: 2026-05-15
verified_against:
  - CHANGELOG.md
  - deploy/
  - scripts/setup-prod-git.sh
  - README.md
  - commit d9b8389
related_docs:
  - dev-setup.md
  - ../user-guide/getting-started.md
  - i18n-workflow.md
  - ../user-guide/tls-and-certificates.md
---

> **[English](release-process.md)** | **[繁體中文](release-process_zh.md)**
> 📍 [INDEX](../INDEX.md) › 貢獻指引 › 發佈流程
> 🔍 最後驗證日期 **2026-05-15**，對應 commit `d9b8389` — 詳見 frontmatter 來源

# 發佈流程

---

## 版本編號規則

illumio-ops 採用 `<major>.<minor>.<patch>-<topic-slug>` 版本格式，
與 git tag 命名慣例一致。

**`CHANGELOG.md` 中的實際範例：**

| Tag | 說明 |
|-----|------|
| `v3.25.0-tracks-abcd` | 工作負載追蹤功能集 (tracks-abcd) |
| `v3.26.0-i18n-architecture` | i18n 架構大改版 |

**遞增規則：**

- `patch` — 錯誤修復、文件更新、依賴版本釘定；不新增行為。
- `minor` — 新功能或不破壞相容的 API 新增；向後相容。
- `major` — 破壞 config schema、CLI flags 或 API 合約的變更。
- `topic-slug` — 簡短、小寫、以連字號分隔，命名此次發佈主題。
  選擇發佈後不需要重新命名的穩定名稱。

**README 版本徽章格式**（來自 `README.md`）：

```markdown
![Version](https://img.shields.io/badge/Version-v3.25.0--tracks--abcd-blue?style=flat-square)
```

注意雙連字號編碼：shields.io 要求以 `--` 渲染單一 `-`，
因此 `v3.25.0--tracks--abcd` 會顯示為 `v3.25.0-tracks-abcd`。

---

## 發佈前檢查清單

打標籤前，請完整執行以下所有項目。即使變更「看起來很小」也不可跳過
— 每個項目都能攔截不同類型的回歸問題。

- [ ] **測試通過** — `pytest -q` 在目前分支上以 exit 0 結束。
- [ ] **Lint 無誤** — `ruff check .` 或 `flake8` 無錯誤。
- [ ] **型別檢查通過** — `mypy src/` 無新增錯誤。
- [ ] **i18n 審計乾淨** — 執行 i18n 發佈前審計；請參閱
  [i18n 工作流程](i18n-workflow.md) 取得確切指令。
  程式碼中使用的每個 key 都必須出現在 `en` 與 `zh_TW` 兩個語言包中。
- [ ] **CHANGELOG 已更新** — 新增 `## [<version>] — <YYYY-MM-DD>` 段落，
  列出使用者可見的變更，依照現有 "Keep a Changelog" 格式。
- [ ] **README 徽章版本已更新** — 更新 `README.md`（以及 `README_zh.md`）
  中的 `![Version]` shield，改為新標籤。
- [ ] **離線套件已就緒（如適用）** — 若有依賴變更，需重新產生
  `requirements-offline.txt` 與 `wheels/`。
- [ ] **遷移腳本已備妥（如需要）** — 破壞性 config 變更需在
  `scripts/migrate_*.py` 下提供腳本。詳見 CHANGELOG v3.26.0 範例
  （`migrate_rules_to_keys.py`）。

---

## 標籤與版本調升

```bash
# 1. 確認分支乾淨且測試通過
git status
pytest -q

# 2. 提交 CHANGELOG + README 徽章更新
git add CHANGELOG.md README.md README_zh.md
git commit -m "chore: bump version to v<X.Y.Z>-<slug>"

# 3. 建立附注標籤
git tag -a "v<X.Y.Z>-<slug>" -m "Release v<X.Y.Z>-<slug>"

# 4. 推送分支與標籤
git push origin main
git push origin "v<X.Y.Z>-<slug>"
```

> **注意：** 優先使用附注標籤（`-a`）而非輕量標籤，
> 因為附注標籤帶有標記者身份與時間戳記，可在 `git log --tags` 中查看。

---

## 部署到正式環境 / 實驗環境

已安裝部署機器的標準升級流程：

```bash
# 在部署機器上（以服務使用者身份或使用 sudo）
cd /opt/illumio-ops

git pull                                              # 取回 + fast-forward
pip install -r requirements.txt                       # 同步 Python 依賴
sudo systemctl restart illumio-ops.service            # 套用新程式碼
```

若部署環境使用**離線套件**（無法存取網際網路）：

```bash
pip install --no-index --find-links wheels -r requirements-offline.txt
sudo systemctl restart illumio-ops.service
```

關於完整的操作人員升級 SOP（包含 Windows / NSSM 及 config 保存細節），
請參閱[入門指南 — 升級章節](../user-guide/getting-started.md)。

> **TODO：** `scripts/install.sh` 穩定後，對照確認確切的 `pip install` 指令
> — 以上內容依據 UPGRADE.md 模式撰寫。

---

## 正式環境 git 設定

在每台新的部署機器上，初次 clone 之後**執行一次**：

```bash
bash scripts/setup-prod-git.sh
```

**原因：** 部署機器上的 `git pull` 經常因追蹤檔案被就地編輯（如
`deploy/install_service.ps1`、`scripts/install.sh`、
`src/pce_cache/ingestor_events.py` 等）而以
_「would be overwritten by merge」_ 中止。

此腳本在本地 repo 啟用 `merge.autoStash = true` 與 `rebase.autoStash = true`。
啟用 autoStash 後，`git pull` 會先暫存（stash）本地修改 →
執行 fast-forward → 再 pop stash，而不是中止。

此設定**僅限本地** — 不影響上游 repo 或其他 clone。腳本具有冪等性，
重複執行無害。

_來源：commit `2f173d0`，`scripts/setup-prod-git.sh`。_

---

## 回滾

```bash
# 1. 停止服務
sudo systemctl stop illumio-ops.service

# 2. 切換到上一個發佈標籤
git checkout "v<previous-tag>"
# 或從上一版本的離線壓縮包中還原 python/ 和 src/

# 3. 重新安裝上一版本的依賴
pip install --no-index --find-links wheels -r requirements-offline.txt

# 4. 重新啟動服務
sudo systemctl start illumio-ops.service
```

**Config 相容性說明：** `config/config.json` **不需回滾**。
舊版程式碼會安全地忽略新版新增的未知 config key。
除非新版已損毀 config，否則不要從備份還原 `config/`。

**遷移腳本：** 若曾執行遷移腳本（如 `migrate_rules_to_keys.py`），
已修改的 `config/alerts.json` 向前相容 — 舊版程式碼透過備援路徑讀取
`desc_key`/`rec_key`，無需回滾遷移即可繼續運作。

---

## 發佈後驗證

服務重新啟動後，驗證部署是否正常：

1. **健康狀態端點** — `GET /api/status` 應回傳 HTTP 200。
   > 注意：`/health` **不存在**；正確端點為 `/api/status`
   > （B1.3 審計確認）。

   ```bash
   curl -s http://localhost:<port>/api/status | python3 -m json.tool
   ```

2. **儀表板冒煙測試** — 開啟 Web GUI，確認儀表板載入無 JS 控制台錯誤，
   且顯示最新的 PCE 資料。

3. **報告產生** — 觸發至少一種報告類型，確認在 UI 和 `logs/` 中
   均無錯誤地渲染完成。

4. **監控日誌** — 執行 `journalctl -u illumio-ops.service -f`，
   觀察 2–3 分鐘；啟動穩定後不應出現 `ERROR` 或 `CRITICAL` 行。

5. **版本徽章** — 確認 `/api/status` 回應（或 GUI 頁尾）反映新版本字串。

> **TODO：** 新增 `scripts/smoke_test.sh`，將步驟 1 和 3 自動化，
> 供 CI/CD 管線使用。

---

## 相關文件

- [開發環境設定](dev-setup.md) — 打標籤前的本地環境
- [入門指南（操作人員升級）](../user-guide/getting-started.md) — 使用者端操作
- [i18n 工作流程](i18n-workflow.md) — 發佈前 i18n 審計
- [TLS 與憑證](../user-guide/tls-and-certificates.md) — 發佈時的憑證輪換
