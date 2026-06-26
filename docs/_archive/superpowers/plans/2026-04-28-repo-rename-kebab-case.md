# Repo Rename: Kebab-Case Standardisation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename 6 Illumio project repos to lowercase kebab-case — local directories, entry-point filenames, GitHub repo names, and git remote URLs.

**Architecture:** Process each repo in sequence (方案 A). Repos with an entry-point file rename do `git mv → commit → push` first, then GitHub rename, then remote URL update, then local directory rename. Repos without a file rename skip straight to GitHub rename.

**Tech Stack:** bash, git, GitHub CLI (`gh`)

---

## Task 1: illumio_Backup → illumio-backup

**Files:**
- Rename: `illumio_Backup/illumio_backup.sh` → `illumio_Backup/illumio-backup.sh`
- Directory: `/home/harry/dev/illumio_Backup` → `/home/harry/dev/illumio-backup`

- [ ] **Step 1: git mv 入口腳本**

```bash
git -C /home/harry/dev/illumio_Backup mv illumio_backup.sh illumio-backup.sh
```

- [ ] **Step 2: 確認 staged**

```bash
git -C /home/harry/dev/illumio_Backup status
```

Expected output 包含：`renamed: illumio_backup.sh -> illumio-backup.sh`

- [ ] **Step 3: Commit**

```bash
git -C /home/harry/dev/illumio_Backup commit -m "$(cat <<'EOF'
chore: rename entry-point to kebab-case (illumio-backup.sh)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Push**

```bash
git -C /home/harry/dev/illumio_Backup push origin
```

Expected: `master -> master` 推送成功

- [ ] **Step 5: GitHub rename**

```bash
gh repo rename illumio-backup --repo harry10148/illumio_Backup
```

Expected: `✓ Renamed repository harry10148/illumio-backup`

- [ ] **Step 6: 更新 remote URL**

```bash
git -C /home/harry/dev/illumio_Backup remote set-url origin git@github.com:harry10148/illumio-backup.git
```

- [ ] **Step 7: 驗證 remote**

```bash
git -C /home/harry/dev/illumio_Backup remote -v
```

Expected: 兩行皆顯示 `git@github.com:harry10148/illumio-backup.git`

- [ ] **Step 8: 本地目錄改名**

```bash
mv /home/harry/dev/illumio_Backup /home/harry/dev/illumio-backup
```

- [ ] **Step 9: 驗證**

```bash
ls /home/harry/dev/illumio-backup/illumio-backup.sh
gh repo view harry10148/illumio-backup --json name -q .name
```

Expected: 檔案存在，輸出 `illumio-backup`

---

## Task 2: illumio_vensim → illumio-vensim

**Files:**
- Rename: `illumio_vensim/illumio_vensim.py` → `illumio_vensim/illumio-vensim.py`
- Directory: `/home/harry/dev/illumio_vensim` → `/home/harry/dev/illumio-vensim`

- [ ] **Step 1: git mv 入口腳本**

```bash
git -C /home/harry/dev/illumio_vensim mv illumio_vensim.py illumio-vensim.py
```

- [ ] **Step 2: 確認 staged**

```bash
git -C /home/harry/dev/illumio_vensim status
```

Expected output 包含：`renamed: illumio_vensim.py -> illumio-vensim.py`

- [ ] **Step 3: Commit**

```bash
git -C /home/harry/dev/illumio_vensim commit -m "$(cat <<'EOF'
chore: rename entry-point to kebab-case (illumio-vensim.py)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Push**

```bash
git -C /home/harry/dev/illumio_vensim push origin
```

Expected: `master -> master` 推送成功

- [ ] **Step 5: GitHub rename**

```bash
gh repo rename illumio-vensim --repo harry10148/illumio_vensim
```

Expected: `✓ Renamed repository harry10148/illumio-vensim`

- [ ] **Step 6: 更新 remote URL**

```bash
git -C /home/harry/dev/illumio_vensim remote set-url origin git@github.com:harry10148/illumio-vensim.git
```

- [ ] **Step 7: 驗證 remote**

```bash
git -C /home/harry/dev/illumio_vensim remote -v
```

Expected: 兩行皆顯示 `git@github.com:harry10148/illumio-vensim.git`

- [ ] **Step 8: 本地目錄改名**

```bash
mv /home/harry/dev/illumio_vensim /home/harry/dev/illumio-vensim
```

- [ ] **Step 9: 驗證**

```bash
ls /home/harry/dev/illumio-vensim/illumio-vensim.py
gh repo view harry10148/illumio-vensim --json name -q .name
```

Expected: 檔案存在，輸出 `illumio-vensim`

---

## Task 3: illumio_Deploy → illumio-deploy

**Files:**
- Directory: `/home/harry/dev/illumio_Deploy` → `/home/harry/dev/illumio-deploy`
- 無入口腳本需改名

- [ ] **Step 1: GitHub rename**

```bash
gh repo rename illumio-deploy --repo harry10148/illumio_Deploy
```

Expected: `✓ Renamed repository harry10148/illumio-deploy`

- [ ] **Step 2: 更新 remote URL**

```bash
git -C /home/harry/dev/illumio_Deploy remote set-url origin https://github.com/harry10148/illumio-deploy.git
```

- [ ] **Step 3: 驗證 remote**

```bash
git -C /home/harry/dev/illumio_Deploy remote -v
```

Expected: 兩行皆顯示 `https://github.com/harry10148/illumio-deploy.git`

- [ ] **Step 4: 本地目錄改名**

```bash
mv /home/harry/dev/illumio_Deploy /home/harry/dev/illumio-deploy
```

- [ ] **Step 5: 驗證**

```bash
ls /home/harry/dev/illumio-deploy/
gh repo view harry10148/illumio-deploy --json name -q .name
```

Expected: 目錄存在且可列出內容，輸出 `illumio-deploy`

---

## Task 4: illumio_ops → illumio-ops

**Files:**
- Rename: `illumio_ops/illumio_ops.py` → `illumio_ops/illumio-ops.py`
- Directory: `/home/harry/dev/illumio_ops` → `/home/harry/dev/illumio-ops`

注意：此 repo 包含本計畫文件，目錄改名後路徑變為 `/home/harry/dev/illumio-ops/docs/...`，屬正常。

- [ ] **Step 1: git mv 入口腳本**

```bash
git -C /home/harry/dev/illumio_ops mv illumio_ops.py illumio-ops.py
```

- [ ] **Step 2: 確認 staged**

```bash
git -C /home/harry/dev/illumio_ops status
```

Expected output 包含：`renamed: illumio_ops.py -> illumio-ops.py`

- [ ] **Step 3: Commit**

```bash
git -C /home/harry/dev/illumio_ops commit -m "$(cat <<'EOF'
chore: rename entry-point to kebab-case (illumio-ops.py)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Push**

```bash
git -C /home/harry/dev/illumio_ops push origin
```

Expected: `main -> main` 推送成功

- [ ] **Step 5: GitHub rename**

```bash
gh repo rename illumio-ops --repo harry10148/illumio_ops
```

Expected: `✓ Renamed repository harry10148/illumio-ops`

- [ ] **Step 6: 更新 remote URL**

```bash
git -C /home/harry/dev/illumio_ops remote set-url origin https://github.com/harry10148/illumio-ops.git
```

- [ ] **Step 7: 驗證 remote**

```bash
git -C /home/harry/dev/illumio_ops remote -v
```

Expected: 兩行皆顯示 `https://github.com/harry10148/illumio-ops.git`

- [ ] **Step 8: 本地目錄改名**

```bash
mv /home/harry/dev/illumio_ops /home/harry/dev/illumio-ops
```

- [ ] **Step 9: 驗證**

```bash
ls /home/harry/dev/illumio-ops/illumio-ops.py
gh repo view harry10148/illumio-ops --json name -q .name
```

Expected: 檔案存在，輸出 `illumio-ops`

---

## Task 5: illumio_Quarantine → illumio-quarantine

**Files:**
- Directory: `/home/harry/dev/illumio_Quarantine` → `/home/harry/dev/illumio-quarantine`
- 無入口腳本需改名（`illumio-quarantine.sh` 已是 kebab-case）

- [ ] **Step 1: GitHub rename**

```bash
gh repo rename illumio-quarantine --repo harry10148/illumio_Quarantine
```

Expected: `✓ Renamed repository harry10148/illumio-quarantine`

- [ ] **Step 2: 更新 remote URL**

```bash
git -C /home/harry/dev/illumio_Quarantine remote set-url origin https://github.com/harry10148/illumio-quarantine.git
```

- [ ] **Step 3: 驗證 remote**

```bash
git -C /home/harry/dev/illumio_Quarantine remote -v
```

Expected: 兩行皆顯示 `https://github.com/harry10148/illumio-quarantine.git`

- [ ] **Step 4: 本地目錄改名**

```bash
mv /home/harry/dev/illumio_Quarantine /home/harry/dev/illumio-quarantine
```

- [ ] **Step 5: 驗證**

```bash
ls /home/harry/dev/illumio-quarantine/
gh repo view harry10148/illumio-quarantine --json name -q .name
```

Expected: 目錄存在且可列出內容，輸出 `illumio-quarantine`

---

## Task 6: illumio_flowlink_formatter → illumio-flowlink-formatter

**Files:**
- Directory: `/home/harry/dev/illumio_flowlink_formatter` → `/home/harry/dev/illumio-flowlink-formatter`
- 無入口腳本需改名

- [ ] **Step 1: GitHub rename**

```bash
gh repo rename illumio-flowlink-formatter --repo harry10148/illumio_flowlink_formatter
```

Expected: `✓ Renamed repository harry10148/illumio-flowlink-formatter`

- [ ] **Step 2: 更新 remote URL**

```bash
git -C /home/harry/dev/illumio_flowlink_formatter remote set-url origin git@github.com:harry10148/illumio-flowlink-formatter.git
```

- [ ] **Step 3: 驗證 remote**

```bash
git -C /home/harry/dev/illumio_flowlink_formatter remote -v
```

Expected: 兩行皆顯示 `git@github.com:harry10148/illumio-flowlink-formatter.git`

- [ ] **Step 4: 本地目錄改名**

```bash
mv /home/harry/dev/illumio_flowlink_formatter /home/harry/dev/illumio-flowlink-formatter
```

- [ ] **Step 5: 驗證**

```bash
ls /home/harry/dev/illumio-flowlink-formatter/
gh repo view harry10148/illumio-flowlink-formatter --json name -q .name
```

Expected: 目錄存在且可列出內容，輸出 `illumio-flowlink-formatter`

---

## 最終驗證

- [ ] **全局驗證**

```bash
# 確認所有新目錄存在，舊目錄已消失
ls /home/harry/dev/ | grep illumio

# 確認所有 remote URL 已更新
for repo in illumio-backup illumio-vensim illumio-deploy illumio-ops illumio-quarantine illumio-flowlink-formatter; do
  echo "=== $repo ==="
  git -C /home/harry/dev/$repo remote -v 2>/dev/null | head -1
done

# 確認 GitHub repos 已改名
for repo in illumio-backup illumio-vensim illumio-deploy illumio-ops illumio-quarantine illumio-flowlink-formatter; do
  gh repo view harry10148/$repo --json name -q .name
done
```

Expected: 6 個新目錄存在，remote URL 全部指向新名稱，GitHub 回傳 6 個新名稱
