---
title: i18n Contract
audience: [developer]
last_verified: 2026-06-26
verified_against:
  - src/i18n/engine.py
  - src/i18n/__init__.py
  - src/i18n/data/zh_explicit.json
  - src/i18n/data/dashboard_approved.json
  - src/gui/routes/dashboard.py
  - src/config.py
  - tests/test_i18n_audit.py
  - commit 503f029
related_docs:
  - ../../README.md
  - ../contributing/i18n-workflow.md
  - glossary.md
---

> **[English](i18n-contract.md)** | [繁體中文](i18n-contract_zh.md)
> 📍 [INDEX](../INDEX.md) › Reference › i18n Contract
> 🔍 Last verified **2026-05-15** against commit `503f029` — see frontmatter for sources

# i18n Contract

This document describes the invariants, APIs, and data layout that every
contributor must respect when working with internationalization (i18n) in
illumio-ops. Read it before adding a key, changing a translation, or
modifying language-switching logic.

---

## Languages supported

illumio-ops supports exactly **two locales**:

| Code | Name | Status |
|------|------|--------|
| `en` | English | default; always complete |
| `zh_TW` | Traditional Chinese | fully supported; gap detection active |

No other locale is planned. The valid-locale set is enforced in
`src/i18n/engine.py` via `_I18nState._VALID = frozenset({"en", "zh_TW"})`.
Any unknown locale code falls back silently to `"en"`.

---

## Storage

### Source-of-truth files

| File | Role |
|------|------|
| `src/i18n_en.json` | Primary English message catalogue |
| `src/i18n_zh_TW.json` | Primary zh_TW message catalogue |
| `src/i18n/data/zh_explicit.json` | **Authoritative** overrides for Illumio product terms in zh_TW |
| `src/i18n/data/glossary.json` | Whitelist of terms that **must stay in English** in zh_TW (e.g. PCE, VEN, Policy, Workload) |
| `src/i18n/data/dashboard_approved.json` | Approved zh_TW translations for the 9 dashboard mini-KPI keys — Category J regression gate |
| `src/i18n/data/phrase_overrides.json` | Phrase-level substitutions applied by `_translate_text()` |
| `src/i18n/data/token_map_en.json` | Token → English word map for `_humanize_key_en()` |
| `src/i18n/data/token_map_zh.json` | Token → zh_TW word map for `_humanize_key_zh()` |
| `src/i18n/data/strict_prefixes.json` | Key prefixes that emit `[MISSING:key]` on gap instead of a silent fallback |

### zh_TW.json does NOT exist

`src/i18n/data/zh_TW.json` **does not exist** in this repository (confirmed
by B2.1 audit and re-verified at `503f029`). The zh_TW translations come
from `src/i18n_zh_TW.json` (root of `src/`), not from inside `src/i18n/data/`.

The engine loads it via:

```python
_ZH_MESSAGES_PATH = _ROOT / "i18n_zh_TW.json"   # _ROOT = src/
```

`zh_explicit.json` in `src/i18n/data/` is a separate file that holds
Illumio-specific term overrides; it is not a full message catalogue.

### Resolution order for zh_TW

When `_build_messages("zh_TW")` is called:

1. Look up the key in `_normalized_zh_messages()` (built from `src/i18n_zh_TW.json`).
2. If found and non-empty → use it.
3. If the key matches a **strict prefix** (defined in `strict_prefixes.json`) → emit `[MISSING:key]`.
4. Otherwise → log a warning and return the **raw key name** as visible signal.

`zh_explicit.json` is loaded separately and exposed as `_ZH_EXPLICIT` for
use by the audit script and quality tests; it is not merged into the runtime
message dict automatically. The audit script (Category E) enforces that
Illumio product terms in `zh_TW` translations match `zh_explicit.json`.

---

## API

### Public surface (`src/i18n/__init__.py`)

```python
from src.i18n import t, get_messages, set_language, get_language
```

### `t()` — primary translation function

```python
def t(key: str, *, lang: str | None = None, default: str | None = None, **kwargs) -> str:
```

| Parameter | Type | Meaning |
|-----------|------|---------|
| `key` | `str` | Translation key (alphanumeric + `_`) |
| `lang` | `str \| None` | Explicit locale (`"en"` or `"zh_TW"`). `None` → uses process-global. |
| `default` | `str \| None` | Fallback when no translation found and key is non-strict. |
| `**kwargs` | `Any` | Passed to `str.format(**kwargs)` on the result. |

**Resolution order inside `t()`:**

1. `_lang = lang if lang in {"en", "zh_TW"} else get_language()`
2. Look up `key` in `get_messages(_lang)` (pre-built dict for that locale).
3. If not found, try `_normalized_en_messages()` as fallback.
4. If still not found and key matches a strict prefix → return `[MISSING:key]`.
5. If still not found → return `default` if provided, else `_humanize_key_zh(key)` (for zh_TW) or `_humanize_key_en(key)` (for en).
6. Apply `str.format(**kwargs)` if any kwargs are present.

### Default language resolution

The process-global language is stored in a thread-safe singleton
`_I18nState` (lock-protected `str`). It defaults to `"en"`.

```python
get_language()           # → "en" | "zh_TW"
set_language("zh_TW")   # process-global; BOOT ONLY (see below)
```

**`set_language()` is for process bootstrap only.** The docstring explicitly
prohibits calling it from request handlers, scheduler tasks, or any
concurrent context. Allowed callers are enforced by the allowlist test
`tests/test_i18n_set_language_callers.py`.

### Per-request language threading

For concurrent web requests, the language is resolved per-request without
mutating global state:

```python
# src/gui/__init__.py
def _request_lang() -> str:
    """Resolve lang for the current request: session > config default."""
    if has_request_context():
        s_lang = session.get("lang")
        if s_lang:
            return s_lang
    return cm.config.get("settings", {}).get("language", "en")
```

The resolved `lang` string is then passed explicitly to every `t(key, lang=lang)`
call within that request. No thread-local storage; no global mutation.

---

## UI vs stored data distinction

| Category | Language behaviour |
|----------|--------------------|
| **UI labels** — button text, chart axis titles, KPI captions, nav items | Re-translated on every request using the current `lang`. Switch language → labels update immediately. |
| **Stored data** — rule descriptions and recommendations written to `config/alerts.json`, audit log entries | Frozen in the language active at **write time**. Not re-translated on language switch. |
| **Report HTML** — generated by the report engine | Frozen in the language active at **generation time**. |

The distinction matters: a rule named "PCE health check failed." in English
will not automatically become the zh_TW string when the operator switches
language. The `_resolve_rule_keys` mechanism (see below) upgrades legacy
literal-text rules to key-based rules so that language-switch re-translation
becomes possible for _known_ best-practice rules — but user-customised rule
names are always left untouched.

---

## Snapshot retranslation pattern

Dashboard snapshots are JSON blobs written to disk at report-generation time.
Their `kpis` list contains entries of the form:

```json
{ "label": "Hit Rules", "value": "42", "label_key": "rpt_pu_hit_rules" }
```

When a snapshot is served to the browser, the dashboard route calls:

```python
# src/gui/routes/dashboard.py
def _retranslate_kpi_labels(data: dict, lang: str) -> None:
```

This function iterates over every item in `data["kpis"]`. When `label_key`
is present, it overwrites `label` with `t(label_key, lang=lang)` — so the
dashboard always shows labels in the current UI language regardless of what
language was active when the snapshot was written.

Legacy snapshots that have no `label_key` field are left as-is; they show
the language frozen at generation time and will naturally age out as new
snapshots are generated.

`_retranslate_kpi_labels` is called in three dashboard endpoint handlers
(`/api/dashboard`, `/api/dashboard/story`, `/api/dashboard/policy-usage`).

---

## alerts.json key resolution

`config/alerts.json` stores alert rules. Rule records have three text fields
(`name`, `desc`, `rec`) and three parallel key fields (`name_key`, `desc_key`,
`rec_key`). The key-based storage allows language-transparent rules.

### Load path — `_resolve_rule_keys()`

Called by `ConfigManager.load()` immediately after reading `alerts.json`:

```python
# src/config.py
def _resolve_rule_keys(self) -> None:
```

Per rule, three cases:

1. **New-style rule** — `name_key` / `desc_key` / `rec_key` are set.
   Render via `t(key, lang=lang)` and write result back into `name` / `desc` / `rec`.

2. **Legacy `[MISSING:key]` marker** — older best-practice runs wrote
   `[MISSING:rule_*]` when the i18n key did not yet exist. The loader parses
   out the key, re-resolves, and back-fills the `*_key` field so the next
   `save()` persists it properly.

3. **Pure legacy literal** — no `*_key`, no `[MISSING:]`, but the literal
   value matches one of the canonical EN or zh_TW renderings of a known
   best-practice key (derived via `_LEGACY_FILTER_TO_NAME_KEY`). Promote to
   key-based storage. User-customised names that don't match any canonical
   rendering are **not** touched.

### Save path — `_write_alerts_file()`

```python
# src/config.py
def _write_alerts_file(self):
    """Atomically write {"rules": self.config['rules']} to alerts.json
    ...
    rendered text is repopulated by load() via _resolve_rule_keys()."""
```

The save strips rendered text before persisting — only `*_key` fields are
written to disk; the `name` / `desc` / `rec` text is treated as ephemeral
and re-populated on every `load()`.

### `_LEGACY_FILTER_TO_NAME_KEY`

A hardcoded mapping from `filter_value` strings to canonical `rule_*` base
keys. Used by case 3 above to recognise auto-generated best-practice rules:

```python
_LEGACY_FILTER_TO_NAME_KEY = {
    "agent.tampering":          "rule_agent_tampering",
    "user.sign_in,user.login":  "rule_login_failed",
    # ... 15 entries total
}
```

---

## label_key vs resolved label

Two naming conventions are used for i18n keys in this codebase:

| Prefix family | Where used | Example |
|---------------|-----------|---------|
| `gui_*` | Web GUI labels, nav items, error messages, button text | `gui_err_internal`, `gui_last_activity` |
| `rpt_*` | Report and dashboard chart titles, axis labels, KPI captions | `rpt_pd_allowed`, `rpt_pu_hit_rules` |
| `rule_*` | Alert rule name / desc / rec text | `rule_agent_tampering_desc` |
| `alert_*` | Alert notification field labels and text | `alert_field_src_ip` |
| `sched_*` | Scheduler status messages | (strict prefix) |

The `label_key` field in a JSON object (snapshot KPI, FieldMeta, chart spec)
always holds one of these raw key strings. The corresponding `label` field
holds the **rendered** string for the current language.

**Rule for frontend code:** always store `label_key` and treat `label` as
display-only. The `_retranslate_kpi_labels()` / `FieldMeta.render(lang=)` pattern
relies on `label_key` being present.

Keys starting with `gui_`, `sched_`, `status_`, `error_`, `pd_` are filtered
as "GUI-surface" keys in `src/gui/_helpers.py` and subject to stricter
validation. The `strict_prefixes.json` file governs which prefixes emit
`[MISSING:key]` instead of a silent fallback — ensuring developer-visible
gaps on the surface that end users see.

---

## How to add a new key

> Full step-by-step workflow: see [i18n Workflow](../contributing/i18n-workflow.md).

Short version:

1. Add the English string to `src/i18n_en.json`.
2. Add the zh_TW string to `src/i18n_zh_TW.json`.
3. If the key is an Illumio product term, add or verify the zh_TW entry in `src/i18n/data/zh_explicit.json`.
4. If the key is a dashboard KPI, add an entry to `src/i18n/data/dashboard_approved.json`.
5. Use `t("your_key", lang=lang)` — never `t("your_key")` in request handlers.
6. Run `python scripts/audit_i18n_usage.py` and confirm zero findings.

---

## Audit tests

### Test files

| File | What it covers |
|------|---------------|
| `tests/test_i18n_audit.py` | CI gate: runs `scripts/audit_i18n_usage.py` as subprocess; fails on any non-zero exit |
| `tests/test_i18n_quality.py` | Translation quality checks |
| `tests/test_i18n_lang_param.py` | Validates explicit `lang=` parameter propagation |
| `tests/test_i18n_strict_prefixes.py` | Strict-prefix gap detection emits `[MISSING:key]` |
| `tests/test_i18n_strings_parity.py` | EN/zh_TW key parity |
| `tests/test_i18n_glossary.py` | Glossary whitelist enforcement |
| `tests/test_i18n_set_language_callers.py` | Allowlist for `set_language()` callers |
| `tests/test_i18n_consumers_smoke.py` | Smoke test for i18n consumer code paths |
| `tests/test_i18n_menu_strings.py` | Menu string completeness |
| `tests/test_i18n_traffic_strings.py` | Traffic report string coverage |
| `tests/test_i18n_translate_text_audit.py` | `_translate_text()` output audit |

### Audit categories (A–J)

`scripts/audit_i18n_usage.py` defines ten categories. `test_non_glossary_categories_clean`
runs A, B, C, D, F, G, H, I, J individually and hard-fails on any finding:

| Cat | Description |
|-----|-------------|
| A | Placeholder leaks in EN locale |
| B | Placeholder leaks in zh_TW locale |
| C | Hardcoded CJK characters outside translation tables |
| D | Auto-translate residue in zh_TW strings |
| E | Glossary drift — whitelist terms must stay English in zh_TW *(xfail: ~90 known open violations)* |
| F | Placeholder leak variants (format strings) |
| G | Duplicate/inconsistent placeholder declarations |
| H | JS/HTML literal fallback defaults (`_translations[key] \|\| '...'`) |
| I | Tracked EN keys missing in `i18n_zh_TW.json` |
| **J** | **Dashboard zh_TW approved-translation regression gate** — every key in `src/i18n/data/dashboard_approved.json` must match its approved value exactly AND have Han-ratio ≥ 0.8 (exceptions listed in `han_ratio_exceptions`) |

Category E is currently `xfail` (approximately 90 known open glossary violations
documented in `README.md`). All other categories must stay clean.

Category J was added in commit `b9d88de` and covers the 9 dashboard mini-KPI
translations (e.g. `rpt_pu_total_rules`, `rpt_pu_hit_rate`). It prevents
silent drift in the translations most visible to operators on the dashboard.

---

## Related Docs

- [Architecture Overview](../../README.md) — bigger picture
- [i18n Workflow](../contributing/i18n-workflow.md) — add a new translation key (B3 deliverable)
- [Glossary](glossary.md) — Illumio terminology
- [Operations Manual](../operations-manual_zh.md) — operator-level i18n behavior in the Web GUI (§3) (繁體中文)
