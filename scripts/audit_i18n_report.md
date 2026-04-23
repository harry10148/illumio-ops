# i18n Audit Report (Phase 1)

Run `python scripts/audit_i18n_usage.py` to regenerate.

**Total findings:** 3

| Category | Description | Count |
|---|---|---|
| A | EN placeholder leaks (key resolved to humanize fallback at lang=en) | 0 |
| B | ZH placeholder leaks (key resolved to humanize fallback at lang=zh_TW) | 0 |
| C | Hardcoded CJK in non-i18n Python/JS/HTML source files | 0 |
| D | Auto-translate residue (zh_TW values with suspicious English words) | 1 |
| E | Glossary violations (whitelist terms translated to Chinese in zh_TW) | 2 |
| F | Placeholder English values in i18n_en.json | 0 |
| G | Keys referenced in code but missing from i18n_en.json | 0 |
| H | JS/HTML fallback literals (`_translations[key] || 'English text'`) | 0 |
| I | Tracked EN keys missing/empty in i18n_zh_TW.json | 0 |

## [A] EN placeholder leaks (key resolved to humanize fallback at lang=en)

_No findings._

## [B] ZH placeholder leaks (key resolved to humanize fallback at lang=zh_TW)

_No findings._

## [C] Hardcoded CJK in non-i18n Python/JS/HTML source files

_No findings._

## [D] Auto-translate residue (zh_TW values with suspicious English words)

**1 finding(s).**

| Location | Key | Detail |
|---|---|---|
| `src/i18n.py` | `rule_ruleset_change` | zh="Rule Set 變更" (untranslated: Rule) |

## [E] Glossary violations (whitelist terms translated to Chinese in zh_TW)

**2 finding(s).**

| Location | Key | Detail |
|---|---|---|
| `src/i18n.py` | `rule_bulk_unpair` | [Workload] en="Bulk Workload Unpair" zh="批次取消配對" |
| `src/i18n.py` | `rule_policy_provision` | [Policy] en="Security Policy Provisioned" zh="安全政策已佈署" |

## [F] Placeholder English values in i18n_en.json

_No findings._

## [G] Keys referenced in code but missing from i18n_en.json

_No findings._

## [H] JS/HTML fallback literals (`_translations[key] || 'English text'`)

_No findings._

## [I] Tracked EN keys missing/empty in i18n_zh_TW.json

_No findings._
