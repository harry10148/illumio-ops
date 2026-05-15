---
title: Developer Setup
audience: [developer]
last_verified: 2026-05-15
verified_against:
  - requirements.txt
  - requirements-dev.txt
  - pytest.ini
  - mypy.ini
  - AGENTS.md
  - .github/workflows/ci.yml
  - commit 926ea42
related_docs:
  - i18n-workflow.md
  - release-process.md
  - ../architecture/overview.md
  - ../INDEX.md
---

> **[English](dev-setup.md)** | **[繁體中文](dev-setup_zh.md)**
> 📍 [INDEX](../INDEX.md) › Contributing › Developer Setup
> 🔍 Last verified **2026-05-15** against commit `926ea42` — see frontmatter for sources

# Developer Setup

This guide gets you from a fresh clone to a running dev environment with tests and
type checking working.

---

## Clone & venv

```bash
git clone <repo-url>
cd illumio-ops

python3 -m venv venv
source venv/bin/activate          # bash / zsh
# source venv/bin/activate.fish   # fish
```

> **Ubuntu 22.04+ / Debian 12+:** `pip install` is blocked outside a venv (PEP 668).
> Install venv support first if needed: `sudo apt install python3-venv`

Re-activate in every new terminal before running anything:

```bash
source venv/bin/activate
```

---

## Install dev deps

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` — production runtime (Flask, pandas, click, loguru, etc.)
`requirements-dev.txt` — test framework + linter + type checker (not bundled into
the production RPM):

| Group | Packages |
|---|---|
| Test framework | `pytest`, `pytest-cov`, `responses`, `freezegun`, `cryptography`, `beautifulsoup4` |
| Lint / type | `ruff`, `mypy` |
| Build / package | offline bundle tooling (see `scripts/build_offline_bundle.sh`) |

---

## Running locally

The entry point is `illumio-ops.py` at the project root.

| Goal | Command |
|---|---|
| Interactive CLI menu | `python3 illumio-ops.py shell` |
| Web GUI only | `python3 illumio-ops.py gui` |
| Headless monitor daemon | `python3 illumio-ops.py monitor` |
| Monitor + GUI together | `python3 illumio-ops.py monitor-gui` |
| Show all subcommands | `python3 illumio-ops.py --help` |

Before starting the GUI or monitor you need a valid config:

```bash
cp config/config.json.example config/config.json
# Edit config/config.json — fill in api.url, api.org_id, api.key, api.secret
```

---

## Lab test machine (optional)

A shared lab test machine is available for end-to-end testing against a real
Illumio PCE. Do **not** store credentials in this file — see `AGENTS.md` or the
current session-handoff document for lab hostname, user, and API key details.

Tests marked `requires_pce` are skipped in CI by default and are intended for
lab runs only.

---

## Tests

```bash
pytest              # run all tests (short traceback)
pytest --tb=long    # verbose tracebacks
pytest -m "not slow"            # skip slow tests for fast iteration
pytest -m "not slow and not integration"  # unit tests only
pytest tests/test_i18n_audit.py tests/test_i18n_quality.py  # i18n gate
```

Test files live flat under `tests/`:

| Category | File pattern | Description |
|---|---|---|
| API client | `test_api_client*.py` | PCE HTTP layer, retry, thread safety |
| Analyzer | `test_analyzer*.py` | Traffic analysis logic |
| CLI | `test_cli_*.py` | Click commands, exit codes, backwards compat |
| GUI / web | `test_gui_*.py` | Flask routes, settings subtab, auth |
| i18n | `test_i18n_*.py`, `test_*_i18n.py` | Key parity, quality, audit |
| Cache | `test_cache_*.py` | PCE cache read/write/wiring |
| Reports | `test_report*.py`, `test_html_*.py` | HTML/XLSX/PDF report structure |
| Scheduler | `test_cron_*.py` | APScheduler time / timezone |
| Integration | `test_integrations_e2e.py`, `test_phase_*_e2e.py` | Multi-subsystem |

**Pytest markers** (defined in `pytest.ini`):

| Marker | Meaning |
|---|---|
| `slow` | Takes > ~1 s; skip with `-m "not slow"` |
| `integration` | Spans more than one subsystem |
| `requires_pce` | Needs live PCE access — skipped in CI |

Coverage report:

```bash
pytest --cov=src --cov-report=term-missing
```

---

## Type checking

mypy is configured in `mypy.ini` targeting Python 3.10.  
The CI hard gate checks only three fully-typed entry modules:

```bash
mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py
```

To check additional modules locally:

```bash
mypy src/<module>.py
```

Strict `disallow_untyped_defs` is enabled for `src/api_client.py`,
`src/analyzer.py`, and `src/reporter.py`. Other modules use
`ignore_missing_imports = True` as the baseline.

---

## Linting / formatting

**Ruff** is the configured linter and formatter (`ruff>=0.4,<1.0` in
`requirements-dev.txt`). No `ruff.toml` / `pyproject.toml` ruff section is
present yet — runs with defaults.

```bash
ruff check .          # lint
ruff format .         # format (replaces black)
ruff check --fix .    # auto-fix lint issues
```

> **TODO:** add `[tool.ruff]` config to `pyproject.toml` (select, line-length,
> target-version). Not yet configured as of 2026-05-15.

---

## CI checks

Workflow: `.github/workflows/ci.yml` — **CI**

Triggers: push or PR targeting `main`. Concurrent runs on the same ref are
cancelled automatically.

Matrix: Python **3.10** and **3.11** on `ubuntu-22.04`.

Steps (in order):

1. **Install dependencies** — `pip install -r requirements.txt -r requirements-dev.txt`
2. **Doc link check** — `python scripts/check_doc_links.py`
3. **i18n audit** (hard gate) — `python scripts/audit_i18n_usage.py`
4. **Type check (strict subset)** — `mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py`
5. **Run tests** — `pytest --tb=short`

All five steps must pass before a PR can merge.

---

## Branch + PR conventions

**Branch naming** (derived from recent branches):

| Type | Pattern | Example |
|---|---|---|
| Feature | `feat/<short-name>` | `feat/phase-3.1-dashboard-story` |
| Bug fix | `fix/<short-name>` | `fix/alert-i18n-and-delivery` |
| Docs | `docs/<short-name>` | `docs/contributing-guide` |

**Commit message style** (from recent history):

```
<type>(<scope>): <subject>

<body — optional, wrap at 72 chars>

Co-Authored-By: ...
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`.

Examples from recent commits:
- `docs(ux-review): session wrap-up — all 9 plans + ADR completed`
- `fix(settings): use explicit i18n key lookup for dirty-section label`
- `test(dashboard): e2e Playwright coverage for story-mode redesign`

**No PR template** is configured in `.github/` — include a checklist manually in
the PR body:

```markdown
## Checklist
- [ ] Tests pass (`pytest`)
- [ ] i18n audit passes (`python scripts/audit_i18n_usage.py`)
- [ ] Type check passes (`mypy --follow-imports=silent src/api_client.py src/analyzer.py src/reporter.py`)
- [ ] i18n keys added to both `src/i18n_en.json` and `src/i18n_zh_TW.json` (if UI/report/alert text changed)
```

---

## Related Docs

- [i18n Workflow](i18n-workflow.md) — adding translation keys (next task)
- [Release Process](release-process.md) — building and shipping a release
- [Architecture Overview](../architecture/overview.md) — understand what you're working on
- [INDEX](../INDEX.md) — full doc map
