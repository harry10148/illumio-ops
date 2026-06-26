# Repo Rename: Kebab-Case Standardisation

**Feature Name:** Rename all Illumio project repos to lowercase kebab-case  
**Goal:** Unified naming — replace underscores and mixed-case with lowercase hyphens across all repo names, local directories, and entry-point filenames  
**Architecture:** Cross-repo, filesystem + GitHub rename, no code-content changes  
**Tech Stack:** bash, git, GitHub CLI (`gh`)

---

## Scope

### Repos to rename (6)

`illumio-s3-siem-collector` is already correct — excluded.

| # | Old name | New name | Entry-point rename | Remote type |
|---|----------|----------|--------------------|-------------|
| 1 | `illumio_Backup` | `illumio-backup` | `illumio_backup.sh` → `illumio-backup.sh` | SSH |
| 2 | `illumio_vensim` | `illumio-vensim` | `illumio_vensim.py` → `illumio-vensim.py` | SSH |
| 3 | `illumio_Deploy` | `illumio-deploy` | — | HTTPS |
| 4 | `illumio_ops` | `illumio-ops` | `illumio_ops.py` → `illumio-ops.py` | HTTPS |
| 5 | `illumio_Quarantine` | `illumio-quarantine` | — | HTTPS |
| 6 | `illumio_flowlink_formatter` | `illumio-flowlink-formatter` | — | SSH |

### Out of scope
- File contents — not modified
- Internal Python modules (`src/`, `tests/`, `scripts/*.py`) — kept as snake_case (Python convention)
- `scripts/` shell scripts that do not contain the project name in their filename

---

## Per-repo Steps (applied in order 1–6)

```
1. git mv <old-entry-point> <new-entry-point>   # only for repos with an entry-point rename
2. git commit "chore: rename entry-point to kebab-case"
3. git push origin
4. gh repo rename <new-name> --repo harry10148/<old-name>
5. git remote set-url origin <new-url>          # preserve SSH or HTTPS scheme
6. mv /home/harry/dev/<old-name> /home/harry/dev/<new-name>
```

Repos without an entry-point rename skip steps 1–3 and go straight to step 4.

---

## Remote URL mapping

| Repo | Old remote | New remote |
|------|-----------|------------|
| `illumio_Backup` | `git@github.com:harry10148/illumio_Backup.git` | `git@github.com:harry10148/illumio-backup.git` |
| `illumio_vensim` | `git@github.com:harry10148/illumio_vensim.git` | `git@github.com:harry10148/illumio-vensim.git` |
| `illumio_Deploy` | `https://github.com/harry10148/illumio_Deploy.git` | `https://github.com/harry10148/illumio-deploy.git` |
| `illumio_ops` | `https://github.com/harry10148/illumio_ops.git` | `https://github.com/harry10148/illumio-ops.git` |
| `illumio_Quarantine` | `https://github.com/harry10148/illumio_Quarantine.git` | `https://github.com/harry10148/illumio-quarantine.git` |
| `illumio_flowlink_formatter` | `git@github.com:harry10148/illumio_flowlink_formatter.git` | `git@github.com:harry10148/illumio-flowlink-formatter.git` |

---

## Success Criteria

- All 6 local directories exist under the new kebab-case names
- All 6 GitHub repos are renamed (verifiable via `gh repo view`)
- All local `origin` remotes point to the new URLs (`git remote -v` shows new names)
- Entry-point files renamed and tracked by git (`git log --follow` shows rename)
- No other file contents modified
