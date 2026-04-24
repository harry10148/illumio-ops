# i18n Audit Report (Phase 1)

Run `python scripts/audit_i18n_usage.py` to regenerate.

**Total findings:** 8

| Category | Description | Count |
|---|---|---|
| A | EN placeholder leaks (key resolved to humanize fallback at lang=en) | 0 |
| B | ZH placeholder leaks (key resolved to humanize fallback at lang=zh_TW) | 0 |
| C | Hardcoded CJK in non-i18n Python/JS/HTML source files | 0 |
| D | Auto-translate residue (zh_TW values with suspicious English words) | 6 |
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

**6 finding(s).**

| Location | Key | Detail |
|---|---|---|
| `src/i18n.py` | `event_tips_rule_set_create` | zh="已建立新的 Rule Set。變更只有在 sec_policy.create（佈建）後才生效。搭配 rule_set.update 和 rule_set.delete 追蹤完整 Policy 生命週期；監控操作者以防未授權的 Policy 編寫。" (untranslated: Rule) |
| `src/i18n.py` | `event_tips_rule_set_delete` | zh="Rule Set 已被刪除，佈建後無法復原。對意外刪除設定警示——此操作會移除安全規則的邏輯分組。搭配 rule_set.create 和 rule_set.update 追蹤完整生命週期。" (untranslated: Rule) |
| `src/i18n.py` | `event_tips_rule_set_update` | zh="現有 Rule Set 已被修改。變更為草稿狀態，需透過 sec_policy.create 佈建後才生效。搭配 rule_set.create 和 rule_set.delete；使用 status=failure 捕捉失敗的更新。" (untranslated: Rule) |
| `src/i18n.py` | `event_tips_sec_policy_create` | zh="新 Policy 版本已佈建並推送至所有 VEN——即「提交」事件，所有先前的規則及 Rule Set 變更在此生效。對意外佈建（非工作時間、未知操作者）設定警示。無子事件。" (untranslated: Rule) |
| `src/i18n.py` | `event_tips_sec_rule_create` | zh="在 Rule Set 中建立了個別安全規則，為草稿狀態，需佈建後才生效。搭配 sec_rule.update、sec_rule.delete，以及 sec_policy.create 佈建觸發器使用。" (untranslated: Rule) |
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
