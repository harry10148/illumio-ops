# Documentation Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild illumio-ops documentation as 22 verified bilingual doc pairs (44 `.md` files) replacing 14 outdated pairs, with 5-layer cross-linking and per-page freshness frontmatter.

**Architecture:** 4-batch rollout, each batch shippable as its own PR. B1 establishes skeleton + Operator-facing docs. B2 adds Reference + Architecture. B3 adds Contributing +縮版 README. B4 builds the audit tool, completes migration-audit, and `git rm` the 26 old `.md` files. Each doc-creation task follows a 7-step SOP (Research → Outline → Author EN → Translate zh_TW → Frontmatter → docs_check → Commit).

**Tech Stack:** GitHub-flavored Markdown, YAML frontmatter, Python 3.10+ (stdlib only) for `scripts/docs_check.py`. No new build tooling. Translation references: `src/i18n/data/zh_explicit.json` + existing `*_zh.md` files (until B4 deletion).

**Spec reference:** `docs/superpowers/specs/2026-05-15-docs-refactor-design.md`

---

## Pre-flight

### Branch & worktree

This is a large multi-batch refactor. Recommend a dedicated branch `feat/docs-refactor-2026-05` (or worktree-isolated). Current branch `feat/phase-2.2-component-abstraction` has unrelated work in flight.

```bash
git -C /home/harry/rd/illumio-ops switch -c feat/docs-refactor-2026-05
```

Or via `using-git-worktrees` skill.

---

## Conventions (read once; applies to every doc task)

### C1. Frontmatter format (every `.md` in `docs/`)

```yaml
---
title: <Title in English>
audience: [operator|developer|api|security]   # 1+ values
last_verified: 2026-05-15                      # YYYY-MM-DD of authoring
verified_against:
  - src/<module>/<file>.py                     # path read
  - <command>                                  # CLI/API run
  - commit <sha>                               # SHA at verify time
related_docs:
  - <relative-path>.md                         # 3-5 entries
---
```

### C2. Page header (after frontmatter, before `# Title`)

```markdown
> 🌐 **[English](<file>.md)** | **[繁體中文](<file>_zh.md)**
> 📍 [INDEX](<rel-path>/INDEX.md) › <Section> › <This Page>
> 🔍 Last verified **<date>** against commit `<sha>` — see frontmatter for sources
```

zh_TW 版本：語言切換指向 `<file>.md`（去 `_zh`）；breadcrumb / verified 行改中文。

### C3. Page footer (last section)

```markdown
---
## Related Docs
- [<Title>](<rel-path>.md) — 一句中/英描述為何讀這篇
- [<Title>](<rel-path>.md) — ...
- [<Title>](<rel-path>.md) — ...
```

3–5 條，與 frontmatter `related_docs` 一致。

### C4. Per-doc 7-step SOP

Every doc-creation task uses these 7 steps:

1. **Research** — open the listed `src/` files in $EDITOR or via `Read` tool; run the listed CLI/API commands; note current behavior in working notes.
2. **Outline** — write the doc skeleton (sections + bullet stubs) per the spec in this task. Verify spec mention matches reality from Step 1.
3. **Author EN** — fill prose into the outline. Hard line limit per spec §10: user-guide ≤ 800, architecture ≤ 1200, reference ≤ 2000.
4. **Translate zh_TW** — produce `<file>_zh.md` with identical structure. Use `src/i18n/data/zh_explicit.json` for Illumio terminology; fall back to existing `*_zh.md` files.
5. **Frontmatter + Related Docs** — fill `last_verified`, `verified_against` (Step 1 evidence + current commit SHA via `git rev-parse --short HEAD`), and append Related Docs section per C3.
6. **docs_check** — run `python scripts/docs_check.py --files docs/<path>.md docs/<path>_zh.md` and resolve any reported issues. (Skip in B1.1–B1.2 since the script doesn't exist yet; first usable in B1.3 onward.)
7. **Commit** — single commit with both EN + zh_TW + any consequential INDEX update.

### C5. Commit message format

```
docs(<area>): add <topic> (EN + zh_TW)

- verified_against: <main src paths>
- closes: B<n>.<m>
```

Where `<area>` ∈ `getting-started`, `user-guide`, `reference`, `architecture`, `contributing`, `index`, `meta`.

### C6. Translation lookup precedence

When translating an Illumio/PCE term:
1. Check `src/i18n/data/zh_explicit.json` first (source-of-truth glossary)
2. Then `src/i18n/data/zh_TW.json` (general translations)
3. Then existing `docs/*_zh.md` for consistency
4. If still unsure, leave EN inline + add to `docs/_meta/glossary-terms.json` skeleton for B2 glossary task

### C7. INDEX update pattern

Every batch finale task updates `docs/INDEX.md` and `docs/INDEX_zh.md` `<!-- BEGIN:doc-map ... END:doc-map -->` block to include newly added pairs.

### C8. Spec drift policy

If during research (Step 1) any spec assumption is found to be wrong (e.g., spec claims a CLI subcommand exists but `--help` doesn't show it), STOP and ask user before continuing. Do not invent. Mark unknowns as `> [!TODO] @harry: confirm <question>` in the EN draft.

---

## Batch B1 — Skeleton + Operator-facing docs (11 pairs)

**B1 deliverable:** `docs/INDEX{,_zh}.md`, `docs/getting-started{,_zh}.md`, 9 `user-guide/*` pairs. **22 new `.md` files.** Old docs stay for now.

### Task B1.1: Create `scripts/docs_check.py` (audit script)

**Why first:** Steps 6 of all subsequent doc tasks call this script. Build minimal version now; extend in B4.

**Files:**
- Create: `scripts/docs_check.py`
- Create: `tests/test_docs_check.py`

**Spec source:** §3 (Page Template), §9 (Success Criteria)

- [ ] **Step 1: Write failing test**

```python
# tests/test_docs_check.py
"""Tests for scripts/docs_check.py audit tool."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "docs_check.py"


def run_check(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    p = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=cwd or Path.cwd(),
    )
    return p.returncode, p.stdout, p.stderr


def test_bilingual_check_passes_when_paired(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text("# Alpha\n")
    (docs / "alpha_zh.md").write_text("# Alpha\n")
    rc, out, _ = run_check("--bilingual", "--root", str(docs))
    assert rc == 0, out


def test_bilingual_check_fails_on_orphan(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text("# Alpha\n")
    # missing alpha_zh.md
    rc, out, _ = run_check("--bilingual", "--root", str(docs))
    assert rc != 0
    assert "alpha_zh.md" in out


def test_freshness_check_flags_stale(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "alpha.md").write_text(
        "---\ntitle: Alpha\nlast_verified: 2020-01-01\n---\n# Alpha\n"
    )
    (docs / "alpha_zh.md").write_text(
        "---\ntitle: Alpha\nlast_verified: 2020-01-01\n---\n# Alpha\n"
    )
    rc, out, _ = run_check("--freshness", "30", "--root", str(docs))
    assert rc != 0
    assert "alpha.md" in out
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
pytest tests/test_docs_check.py -v
```

Expected: 3 tests fail with `FileNotFoundError` / `ModuleNotFoundError` (script doesn't exist).

- [ ] **Step 3: Implement minimal `scripts/docs_check.py`**

```python
#!/usr/bin/env python3
"""docs_check.py — illumio-ops documentation audit.

Modes (compose freely):
  --bilingual           every EN .md has a sibling _zh.md (and vice-versa)
  --freshness N         flag .md files with last_verified older than N days
  --links               flag broken relative links in .md files
  --frontmatter         flag missing/invalid frontmatter keys
  --all                 enable all checks
  --root PATH           docs root (default: ./docs)
  --files FILE [FILE]   only check these files
  --json                emit JSON instead of human text

Exit 0 on clean, non-zero on issues found.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n", re.DOTALL)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


@dataclass
class Issue:
    file: str
    rule: str
    detail: str


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    def add(self, file: str, rule: str, detail: str) -> None:
        self.issues.append(Issue(file, rule, detail))

    @property
    def ok(self) -> bool:
        return not self.issues


def parse_frontmatter(text: str) -> dict[str, str] | None:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def iter_md(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md") if "_meta" not in p.parts)


def check_bilingual(root: Path, report: Report) -> None:
    files = {p.name: p for p in iter_md(root)}
    for name, path in files.items():
        if name.endswith("_zh.md"):
            counterpart = name[: -len("_zh.md")] + ".md"
        else:
            counterpart = name[: -len(".md")] + "_zh.md"
        if counterpart not in files:
            report.add(str(path), "bilingual", f"missing counterpart: {counterpart}")


def check_freshness(root: Path, days: int, report: Report) -> None:
    cutoff = date.today().toordinal() - days
    for path in iter_md(root):
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        if not fm or "last_verified" not in fm:
            continue  # frontmatter check handles missing
        try:
            d = datetime.strptime(fm["last_verified"], "%Y-%m-%d").date()
        except ValueError:
            report.add(str(path), "freshness", f"invalid last_verified: {fm['last_verified']}")
            continue
        if d.toordinal() < cutoff:
            report.add(str(path), "freshness", f"last_verified {d} older than {days}d")


def check_frontmatter(root: Path, report: Report) -> None:
    required = {"title", "last_verified", "verified_against"}
    for path in iter_md(root):
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        if fm is None:
            report.add(str(path), "frontmatter", "missing or malformed frontmatter block")
            continue
        for key in required:
            if key not in fm:
                report.add(str(path), "frontmatter", f"missing key: {key}")


def check_links(root: Path, report: Report) -> None:
    md_files = {p.resolve() for p in iter_md(root)}
    for path in iter_md(root):
        text = path.read_text(encoding="utf-8")
        for link in LINK_RE.findall(text):
            target = link.split("#", 1)[0].split(" ", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if target.endswith(".md"):
                resolved = (path.parent / target).resolve()
                if resolved not in md_files:
                    report.add(str(path), "links", f"broken: {target}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--bilingual", action="store_true")
    p.add_argument("--freshness", type=int, default=None)
    p.add_argument("--links", action="store_true")
    p.add_argument("--frontmatter", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--root", default="docs")
    p.add_argument("--files", nargs="*", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"error: root not found: {root}", file=sys.stderr)
        return 2

    report = Report()
    if args.all or args.bilingual:
        check_bilingual(root, report)
    if args.all or args.freshness is not None:
        check_freshness(root, args.freshness if args.freshness is not None else 30, report)
    if args.all or args.frontmatter:
        check_frontmatter(root, report)
    if args.all or args.links:
        check_links(root, report)

    if args.json:
        print(json.dumps([i.__dict__ for i in report.issues], indent=2, ensure_ascii=False))
    else:
        for i in report.issues:
            print(f"[{i.rule}] {i.file}: {i.detail}")
        if report.ok:
            print("OK — no issues")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
pytest tests/test_docs_check.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Smoke-test against existing docs**

```bash
python scripts/docs_check.py --bilingual --root docs
```

Expected: exit 0 (existing 14 pairs are paired) — or surface real orphans. Note: this hits the OLD docs/ which will get cleaned up in B4; informational only.

- [ ] **Step 6: Commit**

```bash
git add scripts/docs_check.py tests/test_docs_check.py
git commit -m "docs(tooling): add scripts/docs_check.py (bilingual/freshness/links/frontmatter)

Audit script for new doc structure. 4 checks: bilingual coverage,
last_verified freshness, broken internal links, frontmatter completeness.
- closes: B1.1"
```

---

### Task B1.2: Create `docs/INDEX.md` + `docs/INDEX_zh.md` (skeleton)

**Why second:** All later docs link back to INDEX in their Breadcrumb (C2). Need the file to exist (even sparse) before other tasks can link to it without breaking `docs_check --links`.

**Files:**
- Create: `docs/INDEX.md`
- Create: `docs/INDEX_zh.md`

**Spec source:** §5 (INDEX structure)

**Research (Step 1):** Read `README.md` lines 1–50 for current doc-map structure; read spec §1 for audience entry points.

**Outline (Step 2) — EN sections:**
1. `# illumio-ops Documentation` + language switch
2. `## Where to start` with 4 reader-role subsections (Operator / Developer / Integrator / Auditor) — see spec §1
3. `## Full document map` with `<!-- BEGIN:doc-map ... END:doc-map -->` table (initially listing only `getting-started` + INDEX entries; later tasks will append rows)
4. `## How docs are kept fresh` (one paragraph + reference to `scripts/docs_check.py`)

- [ ] **Step 1: Research** — read sources above.

- [ ] **Step 2: Write skeleton `docs/INDEX.md`**

```markdown
---
title: illumio-ops Documentation
audience: [operator, developer, api, security]
last_verified: 2026-05-15
verified_against:
  - docs/superpowers/specs/2026-05-15-docs-refactor-design.md
  - commit <fill-with-git-rev-parse-short-HEAD>
related_docs:
  - getting-started.md
  - reference/glossary.md
---

> 🌐 **[English](INDEX.md)** | **[繁體中文](INDEX_zh.md)**
> 📍 You are here.
> 🔍 Last verified **2026-05-15** — see frontmatter for sources

# illumio-ops Documentation

## Where to start

### 👤 Operator — using the dashboard / CLI to monitor PCE
1. [Getting Started](getting-started.md)
2. [Dashboard](user-guide/dashboard.md)
3. [Reports](user-guide/reports.md)
4. [Alerts & Quarantine](user-guide/alerts-and-quarantine.md)

### 🧰 Developer / Contributor
1. [Dev Setup](contributing/dev-setup.md)
2. [Architecture Overview](architecture/overview.md)
3. [i18n Contract](architecture/i18n-contract.md)

### 🔌 API user / Integrator
1. [REST API](reference/rest-api.md)
2. [SIEM Integration](user-guide/siem-integration.md)
3. [SIEM Pipeline (event schema)](architecture/siem-pipeline.md)

### 🛡️ Security / Compliance Auditor
1. [TLS & Certificates](user-guide/tls-and-certificates.md)
2. [SIEM Integration (audit forwarding)](user-guide/siem-integration.md)
3. [Multi-PCE](user-guide/multi-pce.md)
4. [Architecture Overview — Data flow](architecture/overview.md#data-flow)

## Full document map

<!-- BEGIN:doc-map -->
| Area | Topic | EN | 中文 |
|------|-------|----|----|
| Index | Entry point | [INDEX.md](INDEX.md) | [INDEX_zh.md](INDEX_zh.md) |
| Onboarding | Install + first run + upgrade | [getting-started.md](getting-started.md) | [getting-started_zh.md](getting-started_zh.md) |
<!-- END:doc-map -->

> _Additional rows are appended at the end of each batch (B1 → B2 → B3)._

## How docs are kept fresh

Every doc carries `last_verified` and `verified_against` frontmatter. Run `python scripts/docs_check.py --all` to audit:
- bilingual coverage (every EN `.md` has a `_zh.md` sibling)
- `last_verified` ≤ 30 days
- no broken internal links
- frontmatter completeness

---
## Related Docs
- [Getting Started](getting-started.md) — first install and connection
- [Glossary](reference/glossary.md) — Illumio terminology (added in B2)
```

- [ ] **Step 3: Write `docs/INDEX_zh.md`** — same structure, sections in zh_TW. Use the existing `README_zh.md` doc-map block as translation reference.

- [ ] **Step 4: Fill `verified_against` commit SHA**

```bash
SHA=$(git rev-parse --short HEAD)
# Edit docs/INDEX.md and docs/INDEX_zh.md, replace <fill-with-...> with $SHA
```

- [ ] **Step 5: Run docs_check**

```bash
python scripts/docs_check.py --bilingual --frontmatter --root docs
```

Expected: clean on `INDEX{,_zh}.md`. Existing old docs may show frontmatter-missing — those are pre-existing, ignore until B4.

- [ ] **Step 6: Commit**

```bash
git add docs/INDEX.md docs/INDEX_zh.md
git commit -m "docs(index): add docs/INDEX{,_zh}.md skeleton (4 reader entries, doc-map block)

INDEX is the linchpin all later docs link back to in their breadcrumb.
- closes: B1.2"
```

---

### Task B1.3: Create `docs/getting-started.md` + `_zh.md`

**Files:**
- Create: `docs/getting-started.md`
- Create: `docs/getting-started_zh.md`
- Modify: `docs/INDEX.md` (no-op; entry already in doc-map)

**Spec source:** §2 IA, §6.1 (consolidates Installation + UPGRADE)

**Source-of-truth references (Step 1):**
- `docs/Installation.md` (EXISTING; treat as **reference, may be stale** per spec)
- `docs/UPGRADE.md` (EXISTING; same)
- `requirements.txt`, `requirements-offline.txt`
- `illumio-ops.py` (root entry script)
- `deploy/` directory (systemd unit, install script)
- `scripts/setup-prod-git.sh` (per recent commit `2f173d0`)
- Run `python illumio-ops.py --help` for current commands

**Outline (Step 2):**
1. `# Getting Started`
2. `## What is illumio-ops` (3-line elevator pitch — agentless monitoring/automation for Illumio PCE via REST API)
3. `## Prerequisites` (Python 3.10+, PCE access, OS support matrix)
4. `## Installation` — 3 sub-sections:
   - `### From source (development)` — venv + `pip install -r requirements.txt` + run via `python illumio-ops.py`
   - `### Offline bundle (RHEL/Ubuntu/Windows)` — using `requirements-offline.txt` + bundle from `dist/`
   - `### systemd / NSSM service` — from `deploy/`
5. `## First PCE Connection` (where credentials live, first `illumio-ops sync` or equivalent)
6. `## First Login (security)` (initial admin password, password change requirement)
7. `## Upgrade` (`git pull`, `pip install -r requirements.txt`, `systemctl restart illumio-ops.service`; reference `scripts/setup-prod-git.sh`)
8. `## Verify it worked` (check `/health`, check dashboard, expected log lines)
9. `## Where to go next` — links to dashboard / reports / alerts user-guide pages

- [ ] **Step 1: Research** — read sources above; run `python illumio-ops.py --help`; capture output.
- [ ] **Step 2: Author EN** with section structure above, prose ≤ 800 lines, evidence-based content only.
- [ ] **Step 3: Translate zh_TW** — same structure, query `src/i18n/data/zh_explicit.json` for terms like "Pairing Profile", "Workload", "Ruleset".
- [ ] **Step 4: Frontmatter** —
  ```yaml
  ---
  title: Getting Started
  audience: [operator]
  last_verified: 2026-05-15
  verified_against:
    - docs/Installation.md (legacy, audited)
    - docs/UPGRADE.md (legacy, audited)
    - requirements.txt
    - illumio-ops.py
    - deploy/
    - scripts/setup-prod-git.sh
    - python illumio-ops.py --help
    - commit <sha>
  related_docs:
    - INDEX.md
    - user-guide/dashboard.md
    - user-guide/multi-pce.md
    - user-guide/troubleshooting.md
  ---
  ```
- [ ] **Step 5: Related Docs section** at footer:
  - `[INDEX](INDEX.md) — full doc map`
  - `[Dashboard](user-guide/dashboard.md) — first place to look after install`
  - `[Multi-PCE](user-guide/multi-pce.md) — connecting more than one PCE`
  - `[Troubleshooting](user-guide/troubleshooting.md) — when first run goes wrong`
- [ ] **Step 6: docs_check** —
  ```bash
  python scripts/docs_check.py --bilingual --frontmatter --files docs/getting-started.md docs/getting-started_zh.md
  ```
  Expected: clean. Links check disabled because user-guide targets don't exist yet (will be checked in B1.13 final).
- [ ] **Step 7: Commit**
  ```bash
  git add docs/getting-started.md docs/getting-started_zh.md
  git commit -m "docs(getting-started): add getting-started{,_zh}.md (install + first connection + upgrade)

  Consolidates legacy Installation + UPGRADE docs into a single onboarding doc.
  - verified_against: requirements.txt, illumio-ops.py, deploy/, scripts/setup-prod-git.sh
  - closes: B1.3"
  ```

---

### Task B1.4: Create `docs/user-guide/dashboard.md` + `_zh.md`

**Files:**
- Create: `docs/user-guide/dashboard.md`
- Create: `docs/user-guide/dashboard_zh.md`

**Spec source:** §2 IA (user-guide), §2.1 (`gui` 13 files map here)

**Source-of-truth references:**
- `src/gui/routes/` (Flask routes for `/`, `/api/dashboard/snapshot`, `/audit_summary`, `/policy_usage_summary`)
- `src/gui/__init__.py` (Flask app init)
- `src/templates/index.html` (current dashboard template)
- `src/static/js/dashboard.js`, `src/static/js/dashboard_v2.js`
- `data/latest_snapshot.json` (KPI snapshot format — per mem0 entry, uses `label_key` for i18n)
- Recent commits affecting dashboard: `28105c0`, `b9d88de`, `f970d39`, `682de09` (i18n dashboard fixes), `f679f3a` (Operations dropdown), `753b753` (status chip)
- Run: open `https://172.16.15.106:5001` (lab) — note current UI sections

**Outline (Step 2):**
1. `# Dashboard`
2. `## Overview` — what the dashboard shows, refresh model
3. `## KPI cards` — the `.kpi-card` component grid (健康摘要, 事件查詢, 規則使用, 工作負載, 流量採樣, etc.), what each metric means
4. `## Mini-KPI tiles` — per the i18n `pd_*` keys (re-translation at request-time per mem0)
5. `## Action Matrix recommendations` — per recent fix `f970d39`
6. `## Operations menu (header)` — Density / Logs / Stop entries per `f679f3a`
7. `## Status chip & health dot` — per `753b753`
8. `## Multi-PCE switcher` (if applicable; cross-reference `multi-pce.md`)
9. `## Language switching` — runtime EN ↔ zh_TW; reference `architecture/i18n-contract.md`

- [ ] **Step 1: Research** — open referenced src files; capture current KPI label keys; visit lab dashboard if reachable.
- [ ] **Step 2: Author EN** — sections above.
- [ ] **Step 3: Translate zh_TW** — Use existing `User_Manual_zh.md` § Dashboard sections as translation reference; cross-check `src/i18n/data/zh_explicit.json` for KPI label translations.
- [ ] **Step 4: Frontmatter**
  ```yaml
  ---
  title: Dashboard
  audience: [operator]
  last_verified: 2026-05-15
  verified_against:
    - src/gui/routes/
    - src/templates/index.html
    - src/static/js/dashboard.js
    - src/static/js/dashboard_v2.js
    - data/latest_snapshot.json
    - commit <sha>
  related_docs:
    - reports.md
    - alerts-and-quarantine.md
    - multi-pce.md
    - ../architecture/i18n-contract.md
  ---
  ```
- [ ] **Step 5: Related Docs**
- [ ] **Step 6: docs_check**
- [ ] **Step 7: Commit**
  ```
  docs(user-guide): add dashboard{,_zh}.md (KPI cards, mini-KPI, action matrix, operations menu)
  - closes: B1.4
  ```

---

### Task B1.5: Create `docs/user-guide/reports.md` + `_zh.md`

**Files:**
- Create: `docs/user-guide/reports.md`
- Create: `docs/user-guide/reports_zh.md`

**Spec source:** §2 IA, §6.1 (取代 Report_Modules + Security_Rules_Reference 使用者層)

**Source-of-truth references:**
- `src/report/` (71 files — biggest module)
- `src/report/rules/` (security rules definitions)
- `src/report/exporters/` (HTML / PDF / CSV exporters)
- `src/report/parsers/` (data ingestion)
- `src/report/analysis/` (business logic)
- Existing `docs/Report_Modules.md`, `docs/Security_Rules_Reference.md` (treat as **stale reference**)
- Recent: `f935717` (split wide tables), `92143a6` (ReportLab removal / HTML print CSS), `2026-05-12 print-layout` plan
- Run: `python illumio-ops.py report --help` and `python illumio-ops.py report run --help`

**Outline:**
1. `# Reports`
2. `## Report types overview` — table of report names + purpose + outputs
3. `## Running a report` — CLI usage (cross-reference `reference/cli.md`)
4. `## Report modules` — for each module: input, what it shows, output format, link to architecture/report-engine.md for internals
5. `## Security rules` — list of all rules (≤ 800 line cap means abbreviated; full reference is in `reference/cli.md`)
6. `## Print layout & HTML export` — per `92143a6`
7. `## Email delivery` — quick overview, cross-reference Operator workflow
8. `## Multi-channel delivery` (if exists; check src)

- [ ] **Step 1: Research** — exhaustive read of `src/report/__init__.py`, list of all modules, run CLI.
- [ ] **Step 2: Author EN**
- [ ] **Step 3: Translate zh_TW** — Report_Modules_zh.md is large (28K) but stale — use as terminology source only.
- [ ] **Step 4: Frontmatter**
  ```yaml
  verified_against:
    - src/report/
    - src/report/rules/
    - src/report/exporters/
    - python illumio-ops.py report --help
    - python illumio-ops.py report run --help
    - commit <sha>
  related_docs:
    - ../architecture/report-engine.md
    - ../reference/cli.md
    - alerts-and-quarantine.md
    - siem-integration.md
  ```
- [ ] **Step 5: Related Docs**
- [ ] **Step 6: docs_check**
- [ ] **Step 7: Commit** — `docs(user-guide): add reports{,_zh}.md (closes B1.5)`

---

### Task B1.6: Create `docs/user-guide/alerts-and-quarantine.md` + `_zh.md`

**Files:**
- Create: `docs/user-guide/alerts-and-quarantine.md`
- Create: `docs/user-guide/alerts-and-quarantine_zh.md`

**Spec source:** §2 IA, §2.1 (`alerts` + `events` map here)

**Source-of-truth references:**
- `src/alerts/` (5 files; alerts.json structure)
- `src/alerts/templates/` (alert email/notification templates)
- `src/events/` (8 files; event processing)
- `config/alerts.json` (current rules definition; per mem0 uses `name_key`/`desc_key`/`rec_key`)
- `src/settings/manager.py` `ConfigManager._resolve_rule_keys` / `_write_alerts_file` (per mem0)
- Run: `python illumio-ops.py alerts --help`

**Outline:**
1. `# Alerts & Quarantine`
2. `## Alert types` — what each name_key in alerts.json represents
3. `## Configuring alert rules` — via UI Settings → Alerts vs editing alerts.json
4. `## Notification channels` — email, SIEM forwarding (cross-ref siem-integration), webhook
5. `## Quarantine workflow` — manual quarantine, auto-quarantine triggers
6. `## Accelerate Workload button` — per `9d2c0f3` design + `51707a8` plan
7. `## Migration of legacy rules` — `[MISSING:rule_*]` markers + `_LEGACY_FILTER_TO_NAME_KEY` (per mem0)
8. `## i18n behavior` — alerts re-render on language switch (per mem0); cross-ref architecture/i18n-contract.md

- [ ] **Step 1: Research**
- [ ] **Step 2: Author EN**
- [ ] **Step 3: Translate zh_TW**
- [ ] **Step 4: Frontmatter**
  ```yaml
  verified_against:
    - src/alerts/
    - src/events/
    - config/alerts.json
    - src/settings/manager.py
    - python illumio-ops.py alerts --help
    - commit <sha>
  related_docs:
    - dashboard.md
    - siem-integration.md
    - rule-scheduler.md
    - ../architecture/i18n-contract.md
  ```
- [ ] **Step 5–7:** Related Docs, docs_check, commit (`closes B1.6`)

---

### Task B1.7: Create `docs/user-guide/rule-scheduler.md` + `_zh.md`

**Files:**
- Create: `docs/user-guide/rule-scheduler.md`
- Create: `docs/user-guide/rule-scheduler_zh.md`

**Spec source:** §2 IA, §2.1 (`scheduler` maps here)

**Source-of-truth references:**
- `src/scheduler/` (APScheduler integration)
- `src/gui/routes/rule_scheduler.py` (per mem0)
- `src/rule_scheduler_cli.py` (per mem0)
- Per mem0: `t(key, lang='en')` for stored descriptions to prevent language leakage into audit reports
- Run: `python illumio-ops.py rule-scheduler --help`

**Outline:**
1. `# Rule Scheduler`
2. `## What it does` — schedule temporary PCE rules (allow / quarantine / etc.) with auto-expire
3. `## Creating a scheduled rule` — UI + CLI workflow
4. `## Recurring vs one-shot`
5. `## Why descriptions are always English` — explain `t(key, lang='en')` rationale (audit/policy-usage report stability)
6. `## Listing & cancelling scheduled rules`
7. `## Audit trail` — where the records go

- [ ] **Step 1–7:** SOP. Commit `closes B1.7`.

```yaml
verified_against:
  - src/scheduler/
  - src/gui/routes/rule_scheduler.py
  - src/rule_scheduler_cli.py
  - python illumio-ops.py rule-scheduler --help
  - commit <sha>
related_docs:
  - alerts-and-quarantine.md
  - ../architecture/i18n-contract.md
  - ../reference/cli.md
```

---

### Task B1.8: Create `docs/user-guide/siem-integration.md` + `_zh.md`

**Files:**
- Create: `docs/user-guide/siem-integration.md`
- Create: `docs/user-guide/siem-integration_zh.md`

**Spec source:** §2 IA, §6.1 (split with `architecture/siem-pipeline.md`)

**Source-of-truth references:**
- `src/siem/` (19 files)
- `src/siem/formatters/` (CEF, syslog_cef, syslog_json, NormalizedJSON)
- `src/siem/transports/` (syslog, HEC, etc.)
- Recent commits: `7035f50` (destination UX redesign spec), `4ceb5bd` (implementation plan), `edda47b` (NormalizedJSONFormatter), `b91b1e1` (RFC5424), `304fd9b`/`ccebc77` (CEF missing fields), `d217646` (CLI siem status), `4577c7b` (empty-state)
- Run: `python illumio-ops.py siem --help`, `siem status --help`

**Outline:**
1. `# SIEM Integration`
2. `## Supported destinations` — syslog (TCP/UDP/TLS), HEC, normalized JSON
3. `## Configuring a destination` — UI (post `7035f50` host/port split + modal redesign) + CLI
4. `## Event types forwarded` — audit, alerts, quarantine actions (link to siem-pipeline.md for schema)
5. `## Formatter choices` — CEF / syslog_cef / syslog_json / NormalizedJSON — when to use which
6. `## TLS configuration for syslog`
7. `## Testing & status` — `siem status` empty-state, dedup behavior
8. `## Compliance & audit forwarding` (Auditor entry-point)

- [ ] **Step 1–7:** SOP. Commit `closes B1.8`.

```yaml
verified_against:
  - src/siem/
  - src/siem/formatters/
  - src/siem/transports/
  - python illumio-ops.py siem --help
  - python illumio-ops.py siem status --help
  - commit <sha>
related_docs:
  - ../architecture/siem-pipeline.md
  - alerts-and-quarantine.md
  - tls-and-certificates.md
  - ../reference/rest-api.md
```

---

### Task B1.9: Create `docs/user-guide/multi-pce.md` + `_zh.md`

**Files:**
- Create: `docs/user-guide/multi-pce.md`
- Create: `docs/user-guide/multi-pce_zh.md`

**Source-of-truth references:**
- `src/settings/manager.py` (multi-PCE configuration)
- `config/` (multi-PCE config file format)
- `src/gui/routes/` (PCE switcher route)
- Existing `User_Manual.md` § "Multi-PCE" (legacy reference)

**Outline:**
1. `# Multi-PCE`
2. `## When to use multiple PCEs` — federated deployment scenarios
3. `## Adding a PCE`
4. `## PCE switcher in the dashboard`
5. `## Per-PCE settings vs shared`
6. `## Authentication & TLS per PCE` (cross-ref tls-and-certificates.md)
7. `## Reports across PCEs`

- [ ] **Step 1–7:** SOP. Commit `closes B1.9`.

```yaml
verified_against:
  - src/settings/manager.py
  - config/
  - src/gui/routes/
  - commit <sha>
related_docs:
  - tls-and-certificates.md
  - dashboard.md
  - settings-and-pce-cache.md
  - ../reference/cli.md
```

---

### Task B1.10: Create `docs/user-guide/tls-and-certificates.md` + `_zh.md`

**Files:**
- Create: `docs/user-guide/tls-and-certificates.md`
- Create: `docs/user-guide/tls-and-certificates_zh.md`

**Source-of-truth references:**
- `src/gui/routes/` (TLS settings UI)
- Recent commits: `86d550e` (CSR generation + signed cert import workflow), `c089e58` (auto-expand import panel), `7baf6de` (humanize Days Remaining)
- TLS cert path (varies by deployment)
- Run: `python illumio-ops.py tls --help` (if exists; otherwise UI-only)

**Outline:**
1. `# TLS & Certificates`
2. `## Default self-signed cert`
3. `## Generating a CSR` (per `86d550e`)
4. `## Importing a signed cert`
5. `## Cert rotation`
6. `## Days remaining display` (per `7baf6de`)
7. `## PCE-side TLS verification`
8. `## Troubleshooting cert errors`

- [ ] **Step 1–7:** SOP. Commit `closes B1.10`.

```yaml
verified_against:
  - src/gui/routes/
  - commit 86d550e
  - commit <sha>
related_docs:
  - multi-pce.md
  - troubleshooting.md
  - siem-integration.md
  - ../contributing/release-process.md
```

---

### Task B1.11: Create `docs/user-guide/settings-and-pce-cache.md` + `_zh.md`

**Files:**
- Create: `docs/user-guide/settings-and-pce-cache.md`
- Create: `docs/user-guide/settings-and-pce-cache_zh.md`

**Spec source:** §6.1 (取代 PCE_Cache + 部分 User_Manual 設定章節)

**Source-of-truth references:**
- `src/pce_cache/` (15 files)
- `src/settings/` (1 file)
- `data/pce_cache.sqlite` (per `a88e823`)
- Existing `docs/PCE_Cache.md` (legacy reference)
- Recent: `abe112d` (help text in settings), `6c3382e` (traffic sampling help text), `2d99dc5` (confirm-password field)

**Outline:**
1. `# Settings & PCE Cache`
2. `## Settings overview` — UI Settings tabs
3. `## Password / credentials` — `2d99dc5` confirm-password
4. `## PCE connection settings`
5. `## Traffic sampling settings` (per `6c3382e`)
6. `## PCE cache — what it is` — `data/pce_cache.sqlite`
7. `## Cache refresh modes` — incremental, full
8. `## Cache management CLI` — `python illumio-ops.py cache --help` (verify exists)
9. `## Cache schema overview` (brief; full in architecture/overview.md)
10. `## Backup & migration`

- [ ] **Step 1–7:** SOP. Commit `closes B1.11`.

```yaml
verified_against:
  - src/pce_cache/
  - src/settings/
  - data/pce_cache.sqlite (path)
  - python illumio-ops.py cache --help
  - commit <sha>
related_docs:
  - getting-started.md
  - multi-pce.md
  - ../architecture/overview.md
  - troubleshooting.md
```

---

### Task B1.12: Create `docs/user-guide/troubleshooting.md` + `_zh.md`

**Files:**
- Create: `docs/user-guide/troubleshooting.md`
- Create: `docs/user-guide/troubleshooting_zh.md`

**Source-of-truth references:**
- Existing `docs/Troubleshooting.md` (legacy reference)
- `logs/` directory layout
- Loguru config (per phase-7 plan)
- Recent fixes that suggest common pitfalls: TLS, i18n, PCE cache path, multi-PCE config

**Outline:**
1. `# Troubleshooting`
2. `## Logs — where to look` — `logs/` layout
3. `## Common install issues`
4. `## PCE connection failures`
5. `## TLS / cert mismatches` (cross-ref tls-and-certificates.md)
6. `## Report fails to generate`
7. `## SIEM destination not receiving events`
8. `## Dashboard shows stale data` — cache refresh
9. `## i18n / language switching issues`
10. `## Service won't start (systemd)`
11. `## Upgrade aborted by pull conflict` (per `2f173d0`)
12. `## How to file a useful bug report`

- [ ] **Step 1–7:** SOP. Commit `closes B1.12`.

```yaml
verified_against:
  - docs/Troubleshooting.md (legacy, audited)
  - logs/
  - scripts/setup-prod-git.sh
  - commit <sha>
related_docs:
  - getting-started.md
  - tls-and-certificates.md
  - siem-integration.md
  - reports.md
```

---

### Task B1.13: Update `docs/INDEX.md` + `_zh.md` doc-map; run full B1 docs_check

**Files:**
- Modify: `docs/INDEX.md`
- Modify: `docs/INDEX_zh.md`

- [ ] **Step 1: Append doc-map rows for B1 (11 new pairs)**

Append inside `<!-- BEGIN:doc-map -->` block:

```markdown
| User Guide | Dashboard | [user-guide/dashboard.md](user-guide/dashboard.md) | [user-guide/dashboard_zh.md](user-guide/dashboard_zh.md) |
| User Guide | Reports | [user-guide/reports.md](user-guide/reports.md) | [user-guide/reports_zh.md](user-guide/reports_zh.md) |
| User Guide | Alerts & Quarantine | [user-guide/alerts-and-quarantine.md](user-guide/alerts-and-quarantine.md) | [user-guide/alerts-and-quarantine_zh.md](user-guide/alerts-and-quarantine_zh.md) |
| User Guide | Rule Scheduler | [user-guide/rule-scheduler.md](user-guide/rule-scheduler.md) | [user-guide/rule-scheduler_zh.md](user-guide/rule-scheduler_zh.md) |
| User Guide | SIEM Integration | [user-guide/siem-integration.md](user-guide/siem-integration.md) | [user-guide/siem-integration_zh.md](user-guide/siem-integration_zh.md) |
| User Guide | Multi-PCE | [user-guide/multi-pce.md](user-guide/multi-pce.md) | [user-guide/multi-pce_zh.md](user-guide/multi-pce_zh.md) |
| User Guide | TLS & Certificates | [user-guide/tls-and-certificates.md](user-guide/tls-and-certificates.md) | [user-guide/tls-and-certificates_zh.md](user-guide/tls-and-certificates_zh.md) |
| User Guide | Settings & PCE Cache | [user-guide/settings-and-pce-cache.md](user-guide/settings-and-pce-cache.md) | [user-guide/settings-and-pce-cache_zh.md](user-guide/settings-and-pce-cache_zh.md) |
| User Guide | Troubleshooting | [user-guide/troubleshooting.md](user-guide/troubleshooting.md) | [user-guide/troubleshooting_zh.md](user-guide/troubleshooting_zh.md) |
```

Mirror the same in `INDEX_zh.md` with Chinese labels (User Guide → 使用者指引).

- [ ] **Step 2: Bump INDEX `last_verified` to today + add new SHA**

- [ ] **Step 3: Run full B1 docs_check**

```bash
python scripts/docs_check.py --all --root docs/
```

Expected: some link warnings for files not yet created (B2/B3 targets like `reference/cli.md`, `architecture/*`, `contributing/*`). Acceptable for now; will resolve in B2/B3. The current B1 deliverables must all be clean.

Specifically B1 should have 0 issues among:
- `docs/INDEX{,_zh}.md`
- `docs/getting-started{,_zh}.md`
- `docs/user-guide/*{,_zh}.md`

Filter the report:

```bash
python scripts/docs_check.py --all --root docs/ 2>&1 | grep -E "INDEX|getting-started|user-guide/" | grep -v "links" || echo "B1 clean"
```

(Skip link check since B2/B3 targets are still missing.)

- [ ] **Step 4: Commit**

```bash
git add docs/INDEX.md docs/INDEX_zh.md
git commit -m "docs(index): append B1 doc-map rows (9 user-guide entries)

- closes: B1.13"
```

---

### Task B1.14: Open PR for B1

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin feat/docs-refactor-2026-05
gh pr create --title "docs: refactor B1 — skeleton + Operator user-guide (11 pairs)" --body "$(cat <<'EOF'
## Summary
- Adds new doc tree: INDEX + getting-started + 9 user-guide/* pairs (22 .md)
- Adds `scripts/docs_check.py` audit script
- Old docs (Installation.md, etc.) **still in place** — removal deferred to B4 per plan

Each new doc carries:
- `last_verified` + `verified_against` frontmatter
- 5-layer cross-linking (lang switch / breadcrumb / Related Docs / inline / INDEX entry)
- EN-SoT + zh_TW sibling

## Test plan
- [ ] `pytest tests/test_docs_check.py -v` (passes)
- [ ] `python scripts/docs_check.py --bilingual --frontmatter --root docs/` clean on new files
- [ ] Render `docs/INDEX.md` on GitHub — verify doc-map table & 4 reader entries
- [ ] Click through a couple Related Docs links — verify resolution
- [ ] Run `docs/INDEX_zh.md` through same checks

Related spec: `docs/superpowers/specs/2026-05-15-docs-refactor-design.md`
Plan: `docs/superpowers/plans/2026-05-15-docs-refactor.md` (B1 closes B1.1–B1.13)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Address review, merge.**

---

## Batch B2 — Reference + Architecture (7 pairs)

**B2 deliverable:** 3 `reference/*` pairs + 4 `architecture/*` pairs = **14 new `.md`.**

### Task B2.1: Create `docs/reference/glossary.md` + `_zh.md`

**Why first in B2:** All later docs (especially architecture) lean on terminology. Build glossary early so B2.2–B2.7 can link into it.

**Files:**
- Create: `docs/reference/glossary.md`
- Create: `docs/reference/glossary_zh.md`

**Source-of-truth references:**
- `src/i18n/data/zh_explicit.json` (primary glossary)
- `src/i18n/data/zh_TW.json`
- Existing `docs/Glossary.md` (legacy reference)
- Illumio public glossary terms: Workload, Label, Pairing Profile, Ruleset, Rule, Service, Service Account, PCE, VEN, Enforcement Mode, etc.

**Outline:**
1. `# Glossary`
2. `## Illumio core terms` — Workload, Label, Scope, Ruleset, Rule, Service, etc. (one definition each, link to Illumio docs when relevant)
3. `## illumio-ops-specific terms` — Pairing Profile, PCE Cache, Alert Rule, Rule Scheduler, etc.
4. `## i18n terms` — label_key, name_key, zh_explicit, etc.
5. `## Compliance / audit terms` — Audit log, SIEM forwarding event types
6. `## Acronyms` — PCE, VEN, REST, CEF, HEC, NSSM

- [ ] **Step 1: Research** — read `src/i18n/data/zh_explicit.json`; extract canonical translations.
- [ ] **Step 2: Author EN** — alphabetical or grouped by category (see outline).
- [ ] **Step 3: Translate zh_TW** — for each entry, EN term + zh translation + 1-line definition in both languages.
- [ ] **Step 4: Frontmatter**
  ```yaml
  verified_against:
    - src/i18n/data/zh_explicit.json
    - src/i18n/data/zh_TW.json
    - docs/Glossary.md (legacy, audited)
    - commit <sha>
  related_docs:
    - ../INDEX.md
    - ../architecture/i18n-contract.md
    - ../user-guide/dashboard.md
    - ../contributing/i18n-workflow.md
  ```
- [ ] **Step 5–7:** Related Docs, docs_check, commit (`closes B2.1`).

---

### Task B2.2: Create `docs/reference/cli.md` + `_zh.md`

**Files:**
- Create: `docs/reference/cli.md`
- Create: `docs/reference/cli_zh.md`

**Source-of-truth references:**
- `src/cli/` (30 files)
- `src/cli/menus/` (interactive menus)
- Existing `docs/cli-command-map.md` (alias map; **fold in** per spec §6.1)
- Existing `docs/API_Cookbook.md` § CLI sections (legacy reference)
- Recent: `0074f65` (subcommand aliases annotated), `dc64b75` (click global flags), `4577c7b` (siem status fix), `28b3a91` (cli-command-map.md)
- Run: `python illumio-ops.py --help`, then `<each-subcommand> --help`

**Outline:**
1. `# CLI Reference`
2. `## Global flags` — `--json`, `--quiet`, `--verbose`, `--lang` (verify)
3. `## Commands` — for each subcommand: synopsis, flags, examples
   - `report` (run, list, show, delete)
   - `siem` (list, add, status, test, delete)
   - `alerts` (list, ack, mute)
   - `rule-scheduler` (list, add, cancel)
   - `cache` (status, refresh, clear)
   - `tls` (status, csr, import)
   - `config` (show, set, get)
   - `serve` (start GUI)
4. `## Subcommand aliases` — table from `cli-command-map.md` (per `0074f65` annotation)
5. `## Exit codes`
6. `## Environment variables`

Hard cap 2000 lines (per spec §10).

- [ ] **Step 1–7:** SOP. Commit `closes B2.2`.

```yaml
verified_against:
  - src/cli/
  - src/cli/menus/
  - docs/cli-command-map.md (legacy, folded in)
  - python illumio-ops.py --help (and per-subcommand)
  - commit <sha>
related_docs:
  - rest-api.md
  - glossary.md
  - ../user-guide/reports.md
  - ../user-guide/siem-integration.md
```

---

### Task B2.3: Create `docs/reference/rest-api.md` + `_zh.md`

**Files:**
- Create: `docs/reference/rest-api.md`
- Create: `docs/reference/rest-api_zh.md`

**Source-of-truth references:**
- `src/api/` (4 files; auth, route registration)
- `src/gui/routes/` (all Flask routes; identify which are JSON API vs HTML)
- Existing `docs/API_Cookbook.md` (legacy reference)
- Recent: `c9d8500` (pd_ keys in UI translation dict — UI side, not API), `f90572f` (default dialog language)

**Outline:**
1. `# REST API`
2. `## Auth model` — session cookie, CSRF, API key (verify)
3. `## Endpoints by area` — for each endpoint: method, path, request body, response body, example curl
   - Dashboard snapshot endpoints (`/api/dashboard/snapshot`, `/audit_summary`, `/policy_usage_summary`)
   - Reports
   - SIEM destinations
   - Alerts
   - Cache
   - Settings
4. `## Pagination`
5. `## Error model`
6. `## Versioning`

- [ ] **Step 1–7:** SOP. Commit `closes B2.3`.

```yaml
verified_against:
  - src/api/
  - src/gui/routes/
  - docs/API_Cookbook.md (legacy, audited)
  - commit <sha>
related_docs:
  - cli.md
  - ../user-guide/siem-integration.md
  - ../architecture/overview.md
  - glossary.md
```

---

### Task B2.4: Create `docs/architecture/overview.md` + `_zh.md`

**Files:**
- Create: `docs/architecture/overview.md`
- Create: `docs/architecture/overview_zh.md`

**Spec source:** §6.1 marks original `Architecture.md` as **least trustworthy — complete rewrite**.

**Source-of-truth references:**
- `src/` whole tree
- `illumio-ops.py` (entry script)
- `requirements.txt` for runtime deps
- Recent: i18n R1–R4 refactor (`ee363ee` plan, `5dfe4a9` contributor guide, `45595b7` changelog)
- `data/`, `config/`, `deploy/`, `vendor/` directory roles
- Existing `docs/Architecture.md` and `docs/fonts-vendoring.md` (treat as **stale reference**)

**Outline:**
1. `# Architecture Overview`
2. `## High-level diagram` — text-based / ASCII (PCE → illumio-ops core → exporters → Flask/CLI → users; SIEM/Alert side-paths)
3. `## Module tour (`src/`)`
   - `gui/` — Flask app + routes
   - `cli/` — Click commands
   - `report/` (71 files) — analysis / parsers / exporters / rules
   - `siem/` — formatters + transports
   - `pce_cache/` — SQLite-backed cache
   - `alerts/` + `events/`
   - `scheduler/` — APScheduler
   - `i18n/` — JSON dictionaries
   - `api/` — REST routes
   - `settings/` — ConfigManager
4. `## Data flow` — PCE → cache → reports/dashboards/SIEM
5. `## Configuration` — `config/`, `data/`
6. `## Logging` — loguru config, log files in `logs/`
7. `## Vendor & static assets` — `vendor/`, `src/static/` (fold in fonts-vendoring content)
8. `## Process model` — single Flask process, APScheduler thread, etc.
9. `## Sensitive data & where it lives` (Auditor section — cross-cut from spec §1)
10. `## Deployment topology` — systemd / NSSM / Docker (if any)

Hard cap 1200 lines.

- [ ] **Step 1–7:** SOP. Commit `closes B2.4`.

```yaml
verified_against:
  - src/ (whole tree)
  - illumio-ops.py
  - deploy/
  - data/
  - vendor/
  - docs/Architecture.md (legacy, fully audited)
  - docs/fonts-vendoring.md (legacy, folded in)
  - commit <sha>
related_docs:
  - report-engine.md
  - siem-pipeline.md
  - i18n-contract.md
  - ../user-guide/settings-and-pce-cache.md
```

---

### Task B2.5: Create `docs/architecture/report-engine.md` + `_zh.md`

**Files:**
- Create: `docs/architecture/report-engine.md`
- Create: `docs/architecture/report-engine_zh.md`

**Source-of-truth references:**
- `src/report/` (71 files — biggest module)
- `src/report/analysis/`, `parsers/`, `exporters/`, `rules/`
- Recent: ReportLab removal (`92143a6`), HTML print CSS, print layout (`4727992` spec, `f233294` plan), table layout fixes (`f935717`, `caa1349`, `9db21d5`, `0eabc30`, `ac0ae02`, `36f46d8`)

**Outline:**
1. `# Report Engine Architecture`
2. `## Pipeline stages` — fetch → parse → analyze → render → export
3. `## Parsers` — `src/report/parsers/`
4. `## Analysis modules` — `src/report/analysis/`
5. `## Rules engine` — `src/report/rules/`
6. `## Exporters` — HTML, PDF (HTML+CSS via WeasyPrint or similar; ReportLab removed), CSV, XLSX
7. `## Print layout & wide-table handling` (per recent fixes)
8. `## Caching of intermediate results`
9. `## How to add a new report module`

Hard cap 1200 lines.

- [ ] **Step 1–7:** SOP. Commit `closes B2.5`.

```yaml
verified_against:
  - src/report/
  - commit <sha>
related_docs:
  - overview.md
  - ../user-guide/reports.md
  - ../reference/cli.md
  - i18n-contract.md
```

---

### Task B2.6: Create `docs/architecture/siem-pipeline.md` + `_zh.md`

**Files:**
- Create: `docs/architecture/siem-pipeline.md`
- Create: `docs/architecture/siem-pipeline_zh.md`

**Source-of-truth references:**
- `src/siem/` (19 files)
- `src/siem/formatters/` (CEF, syslog_*, NormalizedJSON)
- `src/siem/transports/`
- Recent: `edda47b` NormalizedJSONFormatter, `b91b1e1` RFC5424, `304fd9b`/`ccebc77` CEF additions

**Outline:**
1. `# SIEM Pipeline Architecture`
2. `## Event sources` — what generates events (audit, alerts, quarantine)
3. `## Event normalization` — internal event model
4. `## Formatters`
   - CEF
   - syslog_cef (CEF wrapped in RFC5424)
   - syslog_json
   - NormalizedJSON
5. `## Transports` — TCP / UDP / TLS syslog, HEC
6. `## Retry & backpressure model`
7. `## Event schema` — full reference (this is the canonical schema; user-guide/siem-integration.md links here)
8. `## Adding a new formatter`
9. `## Adding a new transport`

Hard cap 1200 lines.

- [ ] **Step 1–7:** SOP. Commit `closes B2.6`.

```yaml
verified_against:
  - src/siem/
  - src/siem/formatters/
  - src/siem/transports/
  - commit <sha>
related_docs:
  - overview.md
  - ../user-guide/siem-integration.md
  - ../reference/rest-api.md
  - ../user-guide/alerts-and-quarantine.md
```

---

### Task B2.7: Create `docs/architecture/i18n-contract.md` + `_zh.md`

**Files:**
- Create: `docs/architecture/i18n-contract.md`
- Create: `docs/architecture/i18n-contract_zh.md`

**Source-of-truth references:**
- `src/i18n/` (2 files)
- `src/i18n/data/` (zh_explicit.json, zh_TW.json, possibly others)
- Existing `docs/i18n-architecture.md` if present (search)
- Per mem0: dashboard snapshot retranslation, rule_scheduler English-only descriptions, alerts.json key resolution
- Recent: R1–R4 refactor (`ee363ee`), `5dfe4a9` (post-refactor contributor guide), `45595b7` (3.26.0 changelog), `055faf9` (test xfail), category J zh_TW gate (`b9d88de`)

**Outline:**
1. `# i18n Contract`
2. `## Languages supported` — EN (en) + zh_TW
3. `## Storage` — `src/i18n/data/*.json`; `zh_explicit.json` as authoritative for Illumio terms
4. `## API` — `t(key, lang=...)` signature; default lang resolution
5. `## UI vs stored data distinction` — UI labels re-translate on lang switch; stored data (rule descriptions, audit logs) frozen in English at write time (per mem0)
6. `## Snapshot retranslation pattern` — `_retranslate_kpi_labels(data, lang)` for dashboard endpoints
7. `## alerts.json key resolution` — `_resolve_rule_keys` / `_write_alerts_file` / `_LEGACY_FILTER_TO_NAME_KEY`
8. `## label_key vs resolved label` — frontend `pd_*` keys, `gui_*` keys
9. `## How to add a new key` (link to `contributing/i18n-workflow.md`)
10. `## Audit tests` — `tests/i18n_*`, Category J zh_TW gate

Hard cap 1200 lines.

- [ ] **Step 1–7:** SOP. Commit `closes B2.7`.

```yaml
verified_against:
  - src/i18n/
  - src/i18n/data/
  - tests/i18n_*
  - commit <sha>
related_docs:
  - overview.md
  - ../contributing/i18n-workflow.md
  - ../reference/glossary.md
  - ../user-guide/dashboard.md
```

---

### Task B2.8: Update INDEX doc-map for B2; run docs_check; PR

- [ ] **Step 1: Append doc-map rows** for `reference/*` (3) and `architecture/*` (4) — same pattern as B1.13.

- [ ] **Step 2: Bump INDEX `last_verified`.**

- [ ] **Step 3: Run full docs_check (links should now mostly resolve except `contributing/*`)**

```bash
python scripts/docs_check.py --all --root docs/
```

Filter out contributing/* link warnings (will resolve in B3).

- [ ] **Step 4: Commit + Push + PR**

```bash
git add docs/INDEX.md docs/INDEX_zh.md
git commit -m "docs(index): append B2 doc-map rows (reference + architecture)

- closes: B2.8"
git push
gh pr create --title "docs: refactor B2 — reference + architecture (7 pairs)" --body "$(cat <<'EOF'
## Summary
- Adds 3 reference/* pairs (glossary, cli, rest-api) + 4 architecture/* pairs (overview, report-engine, siem-pipeline, i18n-contract)
- 14 new .md files; each carries last_verified + verified_against frontmatter
- INDEX doc-map appended

## Test plan
- [ ] \`python scripts/docs_check.py --bilingual --frontmatter --root docs/\` clean on new B2 files
- [ ] Render \`docs/architecture/overview.md\` on GitHub — check ASCII diagram readability
- [ ] Click Glossary inline links from a B1 user-guide doc — verify resolution
- [ ] Verify cli.md alias section covers all entries from legacy cli-command-map.md

Related spec: \`docs/superpowers/specs/2026-05-15-docs-refactor-design.md\`
Plan: \`docs/superpowers/plans/2026-05-15-docs-refactor.md\` (B2 closes B2.1–B2.8)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Batch B3 — Contributing + README (4 pairs)

**B3 deliverable:** 3 `contributing/*` pairs +縮版 root README pair.

### Task B3.1: Create `docs/contributing/dev-setup.md` + `_zh.md`

**Files:**
- Create: `docs/contributing/dev-setup.md`
- Create: `docs/contributing/dev-setup_zh.md`

**Source-of-truth references:**
- `requirements-dev.txt`
- `pyproject.toml` (if present)
- `pytest.ini`
- `mypy.ini`
- `AGENTS.md` (root; check for dev guidance)
- Existing dev hints in `docs/User_Manual.md`

**Outline:**
1. `# Developer Setup`
2. `## Clone & venv`
3. `## Install dev deps` — `pip install -r requirements.txt -r requirements-dev.txt`
4. `## Running locally` — `python illumio-ops.py serve` (verify)
5. `## Lab test machine` — referenced indirectly (don't dump credentials; cross-ref `.session-handoff-*` style or AGENTS.md)
6. `## Tests` — `pytest`, layout of `tests/`
7. `## Type checking` — `mypy` config
8. `## Linting / formatting` (if configured)
9. `## Branch + PR conventions`

- [ ] **Step 1–7:** SOP. Commit `closes B3.1`.

```yaml
verified_against:
  - requirements-dev.txt
  - pytest.ini
  - mypy.ini
  - AGENTS.md
  - commit <sha>
related_docs:
  - i18n-workflow.md
  - release-process.md
  - ../architecture/overview.md
  - ../INDEX.md
```

---

### Task B3.2: Create `docs/contributing/i18n-workflow.md` + `_zh.md`

**Files:**
- Create: `docs/contributing/i18n-workflow.md`
- Create: `docs/contributing/i18n-workflow_zh.md`

**Source-of-truth references:**
- `src/i18n/data/zh_explicit.json`, `zh_TW.json`
- `tests/i18n_*` (audit tests)
- `scripts/audit_i18n_report.md`
- Per mem0: dashboard zh_TW i18n audit script (`1a481f1`)
- CI Category J approved-translation gate (`b9d88de`)

**Outline:**
1. `# i18n Workflow`
2. `## When to add a new i18n key`
3. `## Where keys live` (link to architecture/i18n-contract.md)
4. `## Adding a key — step-by-step`
5. `## Glossary alignment` — link to reference/glossary.md
6. `## Approved translations gate` (CI Category J)
7. `## Running i18n audit locally`
8. `## Common pitfalls` — language leakage into stored data, missing zh_TW counterpart

- [ ] **Step 1–7:** SOP. Commit `closes B3.2`.

```yaml
verified_against:
  - src/i18n/data/
  - tests/i18n_*
  - scripts/audit_i18n_report.md
  - commit <sha>
related_docs:
  - ../architecture/i18n-contract.md
  - ../reference/glossary.md
  - dev-setup.md
  - release-process.md
```

---

### Task B3.3: Create `docs/contributing/release-process.md` + `_zh.md`

**Files:**
- Create: `docs/contributing/release-process.md`
- Create: `docs/contributing/release-process_zh.md`

**Source-of-truth references:**
- `CHANGELOG.md` (read recent entries for release pattern)
- `deploy/` (systemd unit, install script)
- `scripts/setup-prod-git.sh`
- README version badge update flow
- Recent: `1491d0d` ZH translations + UPGRADE guide; `6a22ef5` sync to v3.25.0-tracks-abcd

**Outline:**
1. `# Release Process`
2. `## Versioning scheme` — semver + suffix tags (e.g., `tracks-abcd`, `i18n-architecture`)
3. `## Pre-release checklist` — tests pass, lint clean, CHANGELOG updated
4. `## Tagging & version bump`
5. `## Deployment to prod / lab` — `git pull` + `pip install -r requirements.txt` + `systemctl restart illumio-ops.service` (cross-ref getting-started.md upgrade)
6. `## Production git setup` — `scripts/setup-prod-git.sh` to prevent pull-abort
7. `## Rollback`
8. `## Post-release verification`

- [ ] **Step 1–7:** SOP. Commit `closes B3.3`.

```yaml
verified_against:
  - CHANGELOG.md
  - deploy/
  - scripts/setup-prod-git.sh
  - commit <sha>
related_docs:
  - dev-setup.md
  - ../user-guide/getting-started.md
  - i18n-workflow.md
  - ../user-guide/tls-and-certificates.md
```

---

### Task B3.4: Rewrite root `README.md` + `README_zh.md` to ≤ 100 lines

**Files:**
- Modify: `README.md`
- Modify: `README_zh.md`

**Spec source:** §6.1, §9 row 9

**Source-of-truth references:**
- Existing `README.md` (audit, retain only essential framing)
- `docs/INDEX.md` (the new entry point)

**Outline (≤ 100 lines):**
1. `# illumio-ops` + version badges (keep)
2. 1-paragraph elevator pitch (what it does)
3. `## Quick start` — 5 lines max, point to `docs/getting-started.md`
4. `## Documentation` — link to `docs/INDEX.md` (EN) and `docs/INDEX_zh.md` (zh_TW)
5. `## Highlights` — 5-bullet quick feature list
6. `## License` (if applicable)

Delete everything else (no doc-map duplication — that lives in INDEX now).

- [ ] **Step 1: Audit current README.md** — note line count, identify content to keep vs move to INDEX/getting-started.

- [ ] **Step 2: Rewrite README.md** to skeleton above.

- [ ] **Step 3: Rewrite README_zh.md** mirrored.

- [ ] **Step 4: Verify line count**

```bash
wc -l README.md README_zh.md
```

Expected: both ≤ 100.

- [ ] **Step 5: Commit**

```bash
git add README.md README_zh.md
git commit -m "docs(readme): slim to ≤100 lines; point to docs/INDEX.md

Doc-map and detailed content moved to docs/INDEX{,_zh}.md and the new
docs/ tree. README is now a GitHub-first-glance entry only.
- closes: B3.4"
```

---

### Task B3.5: Update INDEX doc-map for B3; full docs_check; PR

- [ ] **Step 1: Append `contributing/*` rows + README rows** to `docs/INDEX{,_zh}.md` doc-map.

- [ ] **Step 2: Bump INDEX `last_verified`.**

- [ ] **Step 3: Run full docs_check — now ALL targets should resolve.**

```bash
python scripts/docs_check.py --all --root docs/
```

Expected: 0 issues across NEW tree (`INDEX*`, `getting-started*`, `user-guide/`, `reference/`, `architecture/`, `contributing/`). Old docs in `docs/` may still show frontmatter-missing — accept; cleaned in B4.

- [ ] **Step 4: Commit + PR**

```bash
git add docs/INDEX.md docs/INDEX_zh.md
git commit -m "docs(index): append B3 doc-map rows (contributing + README)

- closes: B3.5"
git push
gh pr create --title "docs: refactor B3 — contributing + slim README (4 pairs)" --body "$(cat <<'EOF'
## Summary
- Adds 3 contributing/* pairs (dev-setup, i18n-workflow, release-process)
- Slims root README.md / README_zh.md to ≤100 lines, points to docs/INDEX.md
- INDEX doc-map appended; full new tree now resolvable

## Test plan
- [ ] \`python scripts/docs_check.py --all --root docs/\` — 0 issues across the new tree
- [ ] \`wc -l README.md README_zh.md\` — both ≤ 100
- [ ] Render new README on GitHub — verify it points to docs/INDEX.md as primary entry
- [ ] From contributing/dev-setup.md, verify venv + pip install instructions reproduce

Related spec: \`docs/superpowers/specs/2026-05-15-docs-refactor-design.md\`
Plan: \`docs/superpowers/plans/2026-05-15-docs-refactor.md\` (B3 closes B3.1–B3.5)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Batch B4 — Polish + Cleanup

**B4 deliverable:** `migration-audit.json` complete; `_meta/glossary-terms.json` skeleton; inline-link polishing; `git rm` 26 old `.md`; CHANGELOG entry.

### Task B4.1: Build `docs/_meta/migration-audit.json`

**Files:**
- Create: `docs/_meta/migration-audit.json`
- Create: `docs/_meta/glossary-terms.json` (empty skeleton)

**Spec source:** §6.2 schema

**Per spec, the audit must cover the 14 old doc pairs (28 .md files): README + Installation + UPGRADE + User_Manual + Report_Modules + Security_Rules_Reference + SIEM_Integration + Architecture + PCE_Cache + API_Cookbook + Glossary + Troubleshooting + cli-command-map + fonts-vendoring.**

- [ ] **Step 1: Draft `migration-audit.json`** — one object per logical doc (14 entries). For each, walk the old EN file and extract material claims; classify each as `verified` / `stale` / `unknown` / `obsolete`; record `action`.

Template entry:

```json
{
  "source": "docs/Architecture.md",
  "target": "docs/architecture/overview.md",
  "audited_at": "2026-05-15",
  "auditor_commit": "<sha>",
  "claims": [
    {
      "claim": "<paraphrased claim from old doc>",
      "verdict": "stale",
      "actual_source": "<src path or doc that shows the truth>",
      "action": "rewrite"
    }
  ]
}
```

Aim for 3–10 claims per source doc — focus on **material** claims (architectural assertions, config paths, command names, behavior), not prose flavor.

- [ ] **Step 2: Create empty `glossary-terms.json` skeleton**

```json
{
  "_comment": "Reserved for future automated glossary linking (out of scope this refactor). Populate from reference/glossary.md when needed.",
  "terms": []
}
```

- [ ] **Step 3: Validate JSON**

```bash
python -m json.tool docs/_meta/migration-audit.json > /dev/null && echo OK
python -m json.tool docs/_meta/glossary-terms.json > /dev/null && echo OK
```

- [ ] **Step 4: Commit**

```bash
git add docs/_meta/migration-audit.json docs/_meta/glossary-terms.json
git commit -m "docs(meta): add migration-audit.json (14 old docs audited) + glossary-terms skeleton

Captures claim → verdict → action for each legacy doc before deletion.
Preserves reasoning trail per spec §6.2.
- closes: B4.1"
```

---

### Task B4.2: Inline-link polishing across new docs

**Files:**
- Modify: any of the 22 new pairs that lack inline Glossary / architecture links.

**Goal:** add L4 inline cross-links where natural (first mention of a term that has a Glossary entry; first mention of a module that has an architecture page).

- [ ] **Step 1: Grep for missed terms**

```bash
# For each glossary term, find files that mention it without linking
python scripts/docs_check.py --links --root docs/  # just to confirm 0 broken
```

(No automated inline-link injection in this refactor; do it manually for the top 10 terms.)

Top terms to inline-link in user-guide docs (manual pass):
- "PCE" → `glossary.md#pce` on first mention
- "Workload" → `glossary.md#workload`
- "Ruleset" → `glossary.md#ruleset`
- "Pairing Profile" → `glossary.md#pairing-profile`
- "SIEM" → `glossary.md#siem`

For architecture docs:
- "i18n contract" → `i18n-contract.md` on first mention in `overview.md` and `report-engine.md`

- [ ] **Step 2: Verify with docs_check** — no link breakage introduced.

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs(polish): inline Glossary + cross-arch links in new docs

- closes: B4.2"
```

---

### Task B4.3: Run full audit and freeze last_verified

**Files:**
- Modify: any new doc that has fallen out of `--freshness 30`.

- [ ] **Step 1: Full sweep**

```bash
python scripts/docs_check.py --all --root docs/
```

Expected on the NEW tree (`INDEX*`, `getting-started*`, `user-guide/`, `reference/`, `architecture/`, `contributing/`): 0 issues. Old docs will still report — that's expected; cleared in B4.4.

- [ ] **Step 2: If any new doc fails `--freshness 30`** (because B1 work was done >30 days ago by the time you reach B4), re-verify those files against current src and bump `last_verified` + commit SHA. **Do not blindly bump**: re-run Step 1 of that doc's original task to ensure the claims still hold.

- [ ] **Step 3: Commit any bumps**

```bash
git add docs/
git commit -m "docs(meta): refresh last_verified for stale-after-B1 docs

- closes: B4.3"
```

(If no docs needed refresh, skip the commit — keep history clean.)

---

### Task B4.4: `git rm` the 26 old `.md` files

**Files (delete):**
```
docs/Installation.md           docs/Installation_zh.md
docs/UPGRADE.md                docs/UPGRADE_zh.md
docs/User_Manual.md            docs/User_Manual_zh.md
docs/Report_Modules.md         docs/Report_Modules_zh.md
docs/Security_Rules_Reference.md  docs/Security_Rules_Reference_zh.md
docs/SIEM_Integration.md       docs/SIEM_Integration_zh.md
docs/Architecture.md           docs/Architecture_zh.md
docs/PCE_Cache.md              docs/PCE_Cache_zh.md
docs/API_Cookbook.md           docs/API_Cookbook_zh.md
docs/Glossary.md               docs/Glossary_zh.md
docs/Troubleshooting.md        docs/Troubleshooting_zh.md
docs/cli-command-map.md        docs/cli-command-map_zh.md
docs/fonts-vendoring.md        docs/fonts-vendoring_zh.md
```

Note: README{,_zh}.md are MODIFIED, not deleted.

- [ ] **Step 1: Confirm migration-audit.json is committed** (precondition).

```bash
git log --oneline -- docs/_meta/migration-audit.json | head -1
```

Expected: at least one commit exists.

- [ ] **Step 2: `git rm` the 26 files**

```bash
git rm docs/Installation.md docs/Installation_zh.md \
       docs/UPGRADE.md docs/UPGRADE_zh.md \
       docs/User_Manual.md docs/User_Manual_zh.md \
       docs/Report_Modules.md docs/Report_Modules_zh.md \
       docs/Security_Rules_Reference.md docs/Security_Rules_Reference_zh.md \
       docs/SIEM_Integration.md docs/SIEM_Integration_zh.md \
       docs/Architecture.md docs/Architecture_zh.md \
       docs/PCE_Cache.md docs/PCE_Cache_zh.md \
       docs/API_Cookbook.md docs/API_Cookbook_zh.md \
       docs/Glossary.md docs/Glossary_zh.md \
       docs/Troubleshooting.md docs/Troubleshooting_zh.md \
       docs/cli-command-map.md docs/cli-command-map_zh.md \
       docs/fonts-vendoring.md docs/fonts-vendoring_zh.md
```

- [ ] **Step 3: Verify count**

```bash
git status --short docs/ | grep '^D ' | wc -l
```

Expected: `26`.

- [ ] **Step 4: Run full docs_check (should be totally clean now)**

```bash
python scripts/docs_check.py --all --root docs/
```

Expected: `OK — no issues`.

- [ ] **Step 5: Commit**

```bash
git commit -m "docs(legacy): remove 26 outdated .md files (13 pairs)

Replaced by the new 22-pair doc tree under docs/{INDEX,getting-started,
user-guide,reference,architecture,contributing}. Audit trail preserved
in docs/_meta/migration-audit.json.

Refs:
- spec: docs/superpowers/specs/2026-05-15-docs-refactor-design.md §6
- plan: docs/superpowers/plans/2026-05-15-docs-refactor.md B4.4
- closes: B4.4"
```

---

### Task B4.5: Update CHANGELOG.md

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add CHANGELOG entry**

Prepend a new section near the top (preserve existing format).

The version label depends on release sequencing — pick by reading the latest `## v...` header in `CHANGELOG.md` and incrementing per the project's semver+suffix convention (e.g., previous header `v3.26.0-i18n-architecture` → this entry might be `v3.27.0-docs-refactor`). Ask user if uncertain.

```markdown
## v3.27.0-docs-refactor — Documentation Refactor

### Documentation
- Restructured `docs/` to a 22-pair bilingual tree mapped to `src/` modules
- New entry point: `docs/INDEX.md` / `docs/INDEX_zh.md` with 4 reader-role entries
- All docs now carry `last_verified` + `verified_against` frontmatter
- Added `scripts/docs_check.py` audit tool (bilingual / freshness / links / frontmatter)
- 14 legacy doc pairs replaced; audit trail at `docs/_meta/migration-audit.json`
- `README.md` slimmed to ≤100 lines, points to `docs/INDEX.md`

### Breaking
- Removed: `docs/Installation.md`, `docs/UPGRADE.md`, `docs/User_Manual.md`, `docs/Report_Modules.md`, `docs/Security_Rules_Reference.md`, `docs/SIEM_Integration.md`, `docs/Architecture.md`, `docs/PCE_Cache.md`, `docs/API_Cookbook.md`, `docs/Glossary.md`, `docs/Troubleshooting.md`, `docs/cli-command-map.md`, `docs/fonts-vendoring.md` (each + `_zh.md`). Old links to these paths will 404 — use `docs/INDEX.md` to find the new location.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): document docs refactor (22-pair tree, frontmatter, docs_check)

- closes: B4.5"
```

---

### Task B4.6: Final PR for B4

- [ ] **Step 1: Push + PR**

```bash
git push
gh pr create --title "docs: refactor B4 — migration audit + delete 26 old .md + CHANGELOG" --body "$(cat <<'EOF'
## Summary
- Adds `docs/_meta/migration-audit.json` covering 14 legacy doc pairs
- Adds `docs/_meta/glossary-terms.json` skeleton (future hook)
- Inline-links Glossary + architecture pages across new docs (L4 cross-links)
- Removes 26 legacy `.md` files (13 pairs) — all content migrated or audited as obsolete
- CHANGELOG entry documenting the refactor

## Post-merge verification
- [ ] `python scripts/docs_check.py --all --root docs/` returns 0 issues
- [ ] `git ls-files docs/` shows only the new tree + `_meta/`
- [ ] `wc -l README.md` ≤ 100
- [ ] Render `docs/INDEX.md` on GitHub — all 4 reader-role links resolve
- [ ] Spot-check a Related Docs link in 3 random user-guide pages

## Breaking
External links to deleted paths (`docs/Installation.md`, etc.) will 404.
See CHANGELOG for the full removal list and migration map.

Spec: `docs/superpowers/specs/2026-05-15-docs-refactor-design.md`
Plan: `docs/superpowers/plans/2026-05-15-docs-refactor.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Address review, merge.**

---

## Self-Review Checklist (run after plan execution)

This is what the implementer (or final reviewer) checks before declaring the refactor done.

- [ ] Run `python scripts/docs_check.py --all --root docs/` — exit 0
- [ ] Run `pytest tests/test_docs_check.py -v` — all pass
- [ ] `git ls-files docs/` shows: `INDEX{,_zh}.md`, `getting-started{,_zh}.md`, 9 `user-guide/*.md` pairs, 3 `reference/*.md` pairs, 4 `architecture/*.md` pairs, 3 `contributing/*.md` pairs, `_meta/*.json` — no other `*.md` in `docs/` root.
- [ ] `wc -l README.md README_zh.md` — both ≤ 100
- [ ] `grep -l 'audience:' docs/**/*.md | wc -l` — 44 (or 43 if a file legitimately omits audience)
- [ ] `grep -L 'last_verified:' docs/**/*.md` — empty (every file has it)
- [ ] `docs/INDEX.md` has 4 reader subsections (`Operator`, `Developer`, `Integrator`, `Auditor`) each with ≥ 3 entries
- [ ] Each `user-guide/*.md` has a `## Related Docs` section with ≥ 3 entries
- [ ] `docs/_meta/migration-audit.json` parses as JSON, has entries for all 14 legacy logical docs
- [ ] CHANGELOG updated
- [ ] All 4 PRs (B1, B2, B3, B4) merged to main

---

## Notes on parallelism (for subagent-driven-development)

Within a batch, doc-creation tasks have **no inter-task dependencies** (except B1.1 which builds the audit tool used by later docs, and B1.2 which creates INDEX that later docs breadcrumb to).

Suggested parallel groupings if using `dispatching-parallel-agents`:

- **B1 parallel group α:** B1.3 (getting-started)
- **B1 parallel group β:** B1.4–B1.12 (9 user-guide docs) — all can run concurrently after B1.1+B1.2
- **B1 sequential finale:** B1.13 (INDEX doc-map update; must wait for β to finish)
- **B2 parallel group γ:** B2.1 (glossary), B2.2–B2.3 (reference) — can run concurrently
- **B2 parallel group δ:** B2.4–B2.7 (architecture) — can run concurrently after γ's glossary lands
- **B2 sequential finale:** B2.8
- **B3 parallel group ε:** B3.1–B3.3 (contributing) + B3.4 (README) — all concurrent
- **B3 sequential finale:** B3.5
- **B4 sequential:** B4.1 → B4.2 → B4.3 → B4.4 → B4.5 → B4.6 (each depends on previous)

Each parallel agent gets a single task spec from this plan (the section under `### Task X.Y`); they should treat the SOP in §Conventions as binding.
