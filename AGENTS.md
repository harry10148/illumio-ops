# Project AGENTS Rules

## i18n Guardrails (Required)

- Any user-visible text (web UI, reports, mail and message alerts, server-side reports such as the migration
  report) must use i18n keys; never hard-code it.
- Every new key goes into both `illumio_ops/i18n/en.json` and `illumio_ops/i18n/zh_TW.json`.
- Glossary terms are not translated (zh_TW writes "Workload", "Label", …); `tests/i18n/test_terminology.py` checks.
- Before merge: `python -m pytest tests/i18n`.
