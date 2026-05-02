# Changelog

All notable changes to illumio-ops are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to a `<major>.<minor>.<patch>-<topic-slug>` versioning
scheme aligned with the git tag conventions.

## [3.22.0-h4-i18n] — 2026-05-02

H4 sub-plan from Batch 4 of the code review: convert `src/i18n.py`
(2275 lines, dominated by ~2000 lines of literal Chinese-translation
data) into the package `src/i18n/` with engine code in `engine.py`
(~340 lines) and data in `data/*.json` (~78 KB across four JSON files).
Public API (`t`, `get_messages`, `set_language`, `get_language`)
unchanged; 59 importers continue to use `from src.i18n import …`
without modification.

### Added
- `src/i18n/__init__.py` — re-exports the public API plus 5 engine
  internals (`EN_MESSAGES`, `ZH_MESSAGES`, `_ZH_EXPLICIT`,
  `_humanize_key_en`, `_humanize_key_zh`) needed by
  `scripts/audit_i18n_usage.py` and `tests/test_i18n_quality.py`.
- `src/i18n/engine.py` — pure engine code (state, humanize, translate,
  build_messages, public API).
- `src/i18n/data/zh_explicit.json` — 1432 keys, merged from a
  four-stage in-code merge (initial literal + 3 individual patches +
  2 `.update()` blocks).
- `src/i18n/data/token_map_en.json` (115 entries),
  `src/i18n/data/token_map_zh.json` (306 entries).
- `src/i18n/data/phrase_overrides.json` (32 entries).
- `src/i18n/.gitignore` — un-ignores `data/` against the root
  `.gitignore`'s blanket exclusion.

### Changed
- `tests/test_reader_guide_render.py` — monkeypatch target updated to
  `src.i18n.engine` (the test patches private symbols `_build_messages`,
  `EN_MESSAGES`, `_normalized_en_messages`).
- `scripts/audit_i18n_usage.py` — `I18N_SOURCE_FILES` entry updated
  from `SRC / "i18n.py"` to `SRC / "i18n" / "engine.py"`.

### Verified
- Tests: 824 passed, 1 skipped (back to pre-H4 baseline).
- i18n audit: 0 findings.
- mypy strict on the typed core: 0 errors.

## [3.21.0-code-review-fixes] — 2026-05-02

Resolves 24 of 27 findings from the 2026-05-01 全面 code review (H1–H3,
M1–M11, L1–L10). The remaining three high-impact items (H4 i18n extraction,
H5 GUI Blueprint split, H6 settings rename) are deferred to dedicated
sub-plans. Final test count: 824 passed, 1 skipped; mypy strict-clean on
the typed core; matplotlib glyph-missing warnings reduced from 20 to 0.

### Added
- `src/cli/_render.py` — TUI / terminal helpers relocated from `utils.py`
  (`Colors`, `safe_input`, `draw_panel`, `draw_table`, `Spinner`,
  `format_unit`, `get_terminal_width`, …).
- `src/cli/_runtime.py` — shared `run_daemon_loop`, `run_gui_only`,
  `run_daemon_with_gui` so the legacy argparse path and the click
  subcommands stop duplicating daemon-startup logic.
- `src/report/rules/` — per-rule subpackage (`_base` + `r01`–`r05`).
- `src/static/fonts/NotoSansCJKtc-Regular.otf` — bundled CJK font
  (SIL OFL 1.1, see `src/static/fonts/LICENSE-NotoSansCJK.txt`) so
  matplotlib chart PNGs render Chinese without OS-level font installs.
- `src/py.typed` (PEP 561 marker) and `mypy.ini` (lenient defaults,
  `disallow_untyped_defs` on `api_client`, `analyzer`, `reporter`).
- `POST /api/cache/retention/run` — manual retention sweep endpoint.
- `tests/conftest.py` shared fixtures (`header_client`, `temp_config_file`,
  `app_persistent`, `client`).
- 8 split GUI-test files (`test_gui_auth`, `test_gui_event_viewer`,
  `test_gui_quarantine`, `test_gui_ip_allowlist`, `test_gui_alert_plugins`,
  `test_gui_dashboard`, `test_gui_rules`, `test_gui_misc`) replacing the
  1325-line `test_gui_security.py`.

### Changed
- **Authentication**: an authenticated session is now sufficient for
  credential / settings changes; `old_password` is no longer required.
  `PasswordChangeForm` removed; the CLI `web_gui_security_menu` (option 1)
  is the canonical forgot-password recovery path.
- **First-run UX**: default admin password is `illumio` with a
  must-change banner and a forced inline change on first login.
- Configuration split: `alerts` payload moves to
  `config/alerts.json` (auto-derived sibling of `config.json`),
  added to `.gitignore`.
- CSP relaxed: `style-src 'unsafe-inline'` enabled (no nonce, since
  any nonce in CSP Level 3 suppresses `unsafe-inline`); Montserrat
  font bundled locally.
- `src/main.py` daemon branches now delegate to `src.cli._runtime`.
- `src/utils.py` shrunk from 525 lines to a thin re-export shim.
- `src/report/rules_engine.py` shrunk from 1076 lines (rules moved
  to `src/report/rules/`); kept as a backwards-compat re-export shim.
- `setup_logger` moved to `src/loguru_config.py`.
- `print()` calls in `src/analyzer.py` and `src/reporter.py` replaced
  with the `loguru` logger.
- Type hints added across `src/api_client.py` (49 defs),
  `src/analyzer.py` (17), and `src/reporter.py` (23) — every `def`
  passes `disallow_untyped_defs`.

### Fixed
- **H1** Constant-time login (no username enumeration).
- **H3** Stop leaking exception strings to API clients.
- **L1** `secret_key` empty-string fallback now uses `or` to keep a
  generated default.
- **L4** Loguru sink-level secret redaction.
- **M1** Inline `onclick` handlers replaced with delegated
  dispatcher (CSP cleanup, change/input/keydown follow-up).
- **M2** `rule-scheduler.js` now uses the DOM API; `jsStr` removed.
- **M3** `BuiltinSSLAdapter` receives the hardened SSL context at
  construction time.
- **M7** Bare `except Exception: pass` blocks in `src/gui/__init__.py`
  now log silenced exceptions.
- **M8** `/api/logout` requires a CSRF token.
- **L2** Initial password banner shown once at startup, then erased.
- **L3** Graceful shutdown via SIGINT (replaces `os._exit`).
- **L6** Mark SIEM `TestResult` dataclass as not-a-test for pytest
  collection.
- **L5** Alert templates (`line_digest`, `mail_wrapper`) honour i18n.
- SIEM forwarder promoted to GA with inline-enqueue ingest path.
- GUI re-POST of masked secrets no longer overwrites the real value.
- Integrations Overview auto-renders; TLS-warn spam suppressed.
- `tests/test_api_client.py` — `update_label_cache` stubbed in
  `setUp` so cache-miss tests stay offline (pre-existing flaky on
  `main`, fixed as a hot-fix during the Batch 5 run).

### Deferred
- **H2** A previous attempt that re-introduced `old_password`
  enforcement was reversed once the simpler authenticated-session
  policy was adopted.
- **H4** `src/i18n.py` JSON extraction (~2300 lines) — sub-plan needed.
- **H5** `src/gui/__init__.py` Blueprint split (~3700 lines) — sub-plan
  needed.
- **H6** `src/settings.py` → `src/cli/menus/*` rename (~2200 lines)
  — sub-plan needed.

### Out-of-plan items completed on this branch
SIEM forwarder GA, Montserrat local bundling, CSP `style-src` policy
adjustments, Integrations Overview auto-render, `alerts.json` split
+ gitignore, default-admin first-run UX, cache-retention endpoint.
