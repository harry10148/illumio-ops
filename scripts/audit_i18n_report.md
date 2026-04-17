# i18n Audit Report (Phase 1)

Run `python scripts/audit_i18n_usage.py` to regenerate.

**Total findings:** 0

| Category | Description | Count |
|---|---|---|
| A | EN placeholder leaks (key resolved to humanize fallback at lang=en) | 0 |
| B | ZH placeholder leaks (key resolved to humanize fallback at lang=zh_TW) | 0 |
| C | Hardcoded CJK in non-i18n Python/JS/HTML source files | 0 |
| D | Auto-translate residue (zh_TW values with suspicious English words) | 0 |
| E | Glossary violations (whitelist terms translated to Chinese in zh_TW) | 0 |
| F | Placeholder English values in i18n_en.json | 0 |
| G | Keys referenced in code but missing from i18n_en.json | 0 |

## [A] EN placeholder leaks (key resolved to humanize fallback at lang=en)

_No findings._

## [B] ZH placeholder leaks (key resolved to humanize fallback at lang=zh_TW)

_No findings._

## [C] Hardcoded CJK in non-i18n Python/JS/HTML source files

_No findings._

## [D] Auto-translate residue (zh_TW values with suspicious English words)

_No findings._

## [E] Glossary violations (whitelist terms translated to Chinese in zh_TW)

_No findings._

## [F] Placeholder English values in i18n_en.json

_No findings._

## [G] Keys referenced in code but missing from i18n_en.json

_No findings._
