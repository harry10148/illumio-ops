# Project AGENTS Rules

## i18n Guardrails (Required)

- Any user-visible text must use i18n keys. Do not hardcode text in:
  - Web UI templates/JS
  - CLI output
  - Reports
  - Mail alert / message alert
- Any new i18n key must be added to both:
  - `src/i18n_en.json`
  - `src/i18n_zh_TW.json`
- Domain terms in project glossary are intentionally not translated.
  - Use `src/i18n.py` (`_ZH_EXPLICIT`) as the source of truth unless explicitly changed.
- Before merge, i18n checks must pass:
  - `python3 scripts/audit_i18n_usage.py`
  - `python3 -m pytest tests/test_i18n_audit.py tests/test_i18n_quality.py`
- If a PR changes UI/report/alert text, include i18n coverage in the PR checklist.
