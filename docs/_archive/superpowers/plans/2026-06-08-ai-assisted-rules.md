# AI-Assisted Rule Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analyze blocked / potentially-blocked traffic and SUGGEST (recommend, never apply) scoped allow-rule candidates with a deterministic heuristic engine, optionally enriched by a pluggable LLM provider that is DISABLED BY DEFAULT and never touches the network unless explicitly configured. Output an HTML + CSV report and a `report ai-rules` CLI command.

**Architecture:** A pure, zero-dependency heuristic core (`rule_suggester.suggest_rules`) over a list of flow records → ranked allow-rule candidates with confidence/risk + a deterministic rationale code (mirrors `attack_posture.RECOMMENDATION_TEMPLATES` / `resolve_recommendation`). A small `Provider` interface with a `NullProvider` default (returns heuristic result unchanged, zero network). A report facade (`AiRulesReport.run`, mirrors `security_risk_report.py`) reuses the existing `CsvExporter` and HTML rendering. Config gains an additive `ai_rules` section (`provider="none"` default). Recommendations only — nothing is provisioned.

**Tech Stack:** Python 3.10+, pytest, click (CLI), pydantic v2 (config), pandas (CSV), JSON i18n (EN + ZH_TW). Air-gapped/offline is a first-class constraint.

**Spec:** `docs/superpowers/specs/2026-06-08-ai-assisted-rules-design.md`

**Deliberate refinements to the spec (disclosed):**
1. `suggest_rules` keeps the `flow_pd` decode inline (mirrors `analyzer.check_flow_match`) rather than importing the analyzer, to keep the core dependency-free and unit-testable in isolation.
2. The report pulls flows via `cache_reader.read_flows_raw()` first (offline), falling back to the API path only when no cache reader is supplied — keeping the default path air-gap safe.
3. `resolve_rule_rationale` lives in `rule_suggester.py` (same module as the templates), matching how `attack_posture.py` colocates `RECOMMENDATION_TEMPLATES` + `resolve_recommendation`.

---

### Task 1: Heuristic core — `suggest_rules` + rationale templates

**Files:**
- Create: `src/report/analysis/rule_suggester.py`
- Test: `tests/test_rule_suggester.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_rule_suggester.py`:

```python
"""Tests for the deterministic AI-rule-suggestion heuristic core."""
from src.report.analysis.rule_suggester import (
    suggest_rules,
    resolve_rule_rationale,
    RULE_RATIONALE_TEMPLATES,
)


def _flow(*, src_role, dst_role, port, proto=6, decision):
    """Synthetic flow record in the shape check_flow_match consumes."""
    return {
        "src": {"labels": [{"key": "role", "value": src_role}]},
        "dst": {"labels": [{"key": "role", "value": dst_role}]},
        "service": {"port": port, "proto": proto},
        "policy_decision": decision,
    }


class TestSuggestRules:
    def test_empty_input_returns_empty(self):
        assert suggest_rules([]) == []

    def test_groups_by_src_dst_port_proto(self):
        flows = [
            _flow(src_role="web", dst_role="db", port=3306, decision="blocked"),
            _flow(src_role="web", dst_role="db", port=3306, decision="potentially_blocked"),
            _flow(src_role="web", dst_role="db", port=3306, decision="blocked"),
        ]
        out = suggest_rules(flows)
        assert len(out) == 1
        s = out[0]
        assert s["src_label"] == "role:web"
        assert s["dst_label"] == "role:db"
        assert s["port"] == 3306
        assert s["proto"] == 6
        assert s["pd"] == 0  # candidate is an ALLOW rule
        assert s["observed_blocked"] == 2
        assert s["observed_potentially"] == 1
        assert s["observed_flows"] == 3

    def test_min_pd_excludes_potentially(self):
        flows = [
            _flow(src_role="web", dst_role="db", port=3306, decision="potentially_blocked"),
        ]
        assert suggest_rules(flows, min_pd=2) == []
        assert len(suggest_rules(flows, min_pd=1)) == 1

    def test_allowed_flows_are_ignored(self):
        flows = [_flow(src_role="web", dst_role="db", port=3306, decision="allowed")]
        assert suggest_rules(flows) == []

    def test_risk_classification(self):
        high = suggest_rules([_flow(src_role="a", dst_role="b", port=3389, decision="blocked")])[0]
        low = suggest_rules([_flow(src_role="a", dst_role="b", port=443, decision="blocked")])[0]
        mid = suggest_rules([_flow(src_role="a", dst_role="b", port=12345, decision="blocked")])[0]
        assert high["risk"] == "high"
        assert low["risk"] == "low"
        assert mid["risk"] == "medium"

    def test_confidence_scales_with_volume(self):
        flows = [_flow(src_role="a", dst_role="b", port=3306, decision="blocked") for _ in range(50)]
        assert suggest_rules(flows)[0]["confidence"] == 1.0
        few = [_flow(src_role="a", dst_role="b", port=3306, decision="blocked") for _ in range(5)]
        assert suggest_rules(few)[0]["confidence"] == 0.1

    def test_sort_high_risk_first(self):
        flows = [
            _flow(src_role="a", dst_role="b", port=443, decision="blocked"),    # low
            _flow(src_role="c", dst_role="d", port=3389, decision="blocked"),   # high
        ]
        out = suggest_rules(flows)
        assert out[0]["risk"] == "high"
        assert out[1]["risk"] == "low"

    def test_deterministic(self):
        flows = [
            _flow(src_role="web", dst_role="db", port=3306, decision="blocked"),
            _flow(src_role="app", dst_role="cache", port=6379, decision="potentially_blocked"),
        ]
        assert suggest_rules(flows) == suggest_rules(flows)

    def test_unlabeled_fallback(self):
        f = {"src": {}, "dst": {}, "service": {"port": 80, "proto": 6}, "policy_decision": "blocked"}
        assert suggest_rules([f])[0]["src_label"] == "unlabeled"


class TestRationale:
    def test_known_code(self):
        txt = resolve_rule_rationale("WELL_KNOWN_DB_PORT", "en", port=3306)
        assert "3306" in txt

    def test_zh_tw(self):
        txt = resolve_rule_rationale("HIGH_RISK_PORT", "zh_TW", port=3389)
        assert "3389" in txt

    def test_missing_code_fallback(self):
        assert resolve_rule_rationale("NOPE", "en") != ""

    def test_missing_lang_falls_back_to_en(self):
        assert resolve_rule_rationale("WELL_KNOWN_DB_PORT", "de", port=3306) == \
            RULE_RATIONALE_TEMPLATES["WELL_KNOWN_DB_PORT"]["en"].format(port=3306)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_rule_suggester.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.analysis.rule_suggester'`.

- [ ] **Step 3: Implement the heuristic core**

Create `src/report/analysis/rule_suggester.py`:

```python
"""Deterministic AI-rule-suggestion heuristic core (zero external deps, air-gap safe).

Input: a list of blocked / potentially-blocked flow records (same shape that
src/analyzer.py::check_flow_match consumes). Output: ranked, minimal allow-rule
candidates with a deterministic confidence/risk score and a rationale code.

RECOMMENDATIONS ONLY — this module never provisions, applies, or persists rules.
"""
from __future__ import annotations

from typing import Any

_UNLABELED = "unlabeled"

# Mirrors src/analyzer.py::check_flow_match policy_decision encoding.
_PD_BLOCKED = 2
_PD_POTENTIALLY = 1
_PD_ALLOWED = 0

# Port → risk class (deterministic). Mirrors operator intuition; no I/O.
_HIGH_RISK_PORTS = {22, 23, 135, 139, 445, 3389, 5985, 5986}
_WELL_KNOWN_SERVICE_PORTS = {53, 80, 443, 1433, 3306, 5432, 6379, 27017}
_DB_PORTS = {1433, 3306, 5432, 6379, 27017}

RULE_RATIONALE_TEMPLATES: dict[str, dict[str, str]] = {
    "WELL_KNOWN_DB_PORT": {
        "en": "Recurring blocked flows to a well-known database port ({port}); likely a legitimate app-to-DB dependency. Review before allowing.",
        "zh_TW": "重複出現往資料庫常見 Port（{port}）的 Blocked 流量，可能是合理的 App-to-DB 依賴，建議審查後再 Allow。",
    },
    "HIGH_RISK_PORT": {
        "en": "Blocked flows on a high-risk port ({port}); treat with caution and confirm the source is authorized before allowing.",
        "zh_TW": "高風險 Port（{port}）的 Blocked 流量，請審慎確認來源已授權後再 Allow。",
    },
    "GENERIC_RECURRING_BLOCK": {
        "en": "Recurring blocked flows between these workloads on {port}/{proto}; candidate for a scoped allow rule after review.",
        "zh_TW": "這些 Workload 之間在 {port}/{proto} 上重複被 Block，審查後可考慮新增收斂範圍的 Allow 規則。",
    },
}

_FALLBACK_RATIONALE = {
    "en": "Review the blocked flows and apply a least-privilege allow rule only if the dependency is legitimate.",
    "zh_TW": "請審查這些 Blocked 流量，僅在依賴關係合理時才套用最小權限的 Allow 規則。",
}

_RISK_ORDER = {"high": 0, "medium": 1, "low": 2}


def resolve_rule_rationale(code: str, lang: str = "en", **args: Any) -> str:
    """Deterministic rationale text. Missing code → fallback; missing lang → en."""
    template = RULE_RATIONALE_TEMPLATES.get(str(code or "").strip())
    if not template:
        return _FALLBACK_RATIONALE.get(lang, _FALLBACK_RATIONALE["en"])
    text = template.get(lang, template.get("en", ""))
    try:
        return text.format(**args)
    except (KeyError, IndexError):
        return text


def _flow_pd(f: dict) -> int:
    """Decode policy decision exactly like analyzer.check_flow_match."""
    p = f.get("pd")
    if p is not None:
        try:
            return int(p)
        except (TypeError, ValueError):
            return -1
    raw = str(f.get("policy_decision", "")).lower()
    if "blocked" in raw and "potentially" not in raw:
        return _PD_BLOCKED
    if "potentially" in raw:
        return _PD_POTENTIALLY
    if "allowed" in raw:
        return _PD_ALLOWED
    return -1


def _label(side: dict) -> str:
    """First usable label (role > app > env) as 'key:value', else 'unlabeled'."""
    labels = side.get("labels") if isinstance(side, dict) else None
    if isinstance(labels, list):
        by_key = {}
        for lbl in labels:
            if isinstance(lbl, dict) and lbl.get("key") and lbl.get("value"):
                by_key[str(lbl["key"])] = str(lbl["value"])
        for key in ("role", "app", "env"):
            if key in by_key:
                return f"{key}:{by_key[key]}"
        if by_key:
            k = sorted(by_key)[0]
            return f"{k}:{by_key[k]}"
    return _UNLABELED


def _port_proto(f: dict) -> tuple[int, int] | None:
    svc = f.get("service") or {}
    raw_port = f.get("dst_port") or svc.get("port")
    raw_proto = f.get("proto") or svc.get("proto")
    try:
        return int(raw_port), int(raw_proto)
    except (TypeError, ValueError):
        return None


def _flow_count(f: dict) -> int:
    try:
        return max(1, int(f.get("flow_count") or 1))
    except (TypeError, ValueError):
        return 1


def _classify_risk(port: int) -> str:
    if port in _HIGH_RISK_PORTS:
        return "high"
    if port in _WELL_KNOWN_SERVICE_PORTS:
        return "low"
    return "medium"


def _rationale_code(port: int) -> str:
    if port in _HIGH_RISK_PORTS:
        return "HIGH_RISK_PORT"
    if port in _DB_PORTS:
        return "WELL_KNOWN_DB_PORT"
    return "GENERIC_RECURRING_BLOCK"


def suggest_rules(flows: list[dict], *, min_pd: int = 1) -> list[dict]:
    """Pure derivation: blocked/potentially-blocked flows → ranked allow-rule candidates.

    Deterministic, no I/O, no network. min_pd=1 includes potentially_blocked(1)
    and blocked(2); min_pd=2 includes only blocked(2).
    """
    groups: dict[tuple, dict] = {}
    for f in flows or []:
        pd = _flow_pd(f)
        if pd < min_pd or pd < _PD_POTENTIALLY:
            continue
        pp = _port_proto(f)
        if pp is None:
            continue
        port, proto = pp
        src_label = _label(f.get("src") or {})
        dst_label = _label(f.get("dst") or {})
        key = (src_label, dst_label, port, proto)
        g = groups.setdefault(key, {
            "src_label": src_label, "dst_label": dst_label,
            "port": port, "proto": proto,
            "observed_flows": 0, "observed_blocked": 0, "observed_potentially": 0,
        })
        n = _flow_count(f)
        g["observed_flows"] += n
        if pd == _PD_BLOCKED:
            g["observed_blocked"] += n
        elif pd == _PD_POTENTIALLY:
            g["observed_potentially"] += n

    out: list[dict] = []
    for g in groups.values():
        port = g["port"]
        risk = _classify_risk(port)
        code = _rationale_code(port)
        out.append({
            "src_label": g["src_label"],
            "dst_label": g["dst_label"],
            "port": port,
            "proto": g["proto"],
            "pd": 0,  # candidate is an ALLOW rule
            "observed_flows": g["observed_flows"],
            "observed_blocked": g["observed_blocked"],
            "observed_potentially": g["observed_potentially"],
            "confidence": round(min(1.0, g["observed_flows"] / 50.0), 2),
            "risk": risk,
            "rationale_code": code,
            "rationale_args": {"port": port, "proto": g["proto"]},
        })

    out.sort(key=lambda s: (
        _RISK_ORDER.get(s["risk"], 9),
        -s["confidence"],
        s["src_label"], s["dst_label"], s["port"], s["proto"],
    ))
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_rule_suggester.py -q`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```
cd /home/harry/rd/illumio-ops && git add src/report/analysis/rule_suggester.py tests/test_rule_suggester.py && git commit -m "feat(ai-rules): deterministic heuristic rule-suggestion core + rationale templates"
```

---

### Task 2: Provider abstraction + default-off / no-network enforcement

**Files:**
- Create: `src/report/analysis/rule_providers.py`
- Test: `tests/test_rule_providers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_rule_providers.py`:

```python
"""Tests for the pluggable LLM provider layer (default off, air-gap safe)."""
import socket

import pytest

from src.report.analysis.rule_providers import (
    NullProvider,
    make_provider,
    enrich_suggestions,
)

_SUGGESTIONS = [
    {"src_label": "role:web", "dst_label": "role:db", "port": 3306, "proto": 6,
     "risk": "low", "confidence": 0.8, "observed_flows": 40,
     "observed_blocked": 30, "observed_potentially": 10,
     "rationale_code": "WELL_KNOWN_DB_PORT", "rationale_args": {"port": 3306}},
]


class TestNullProvider:
    def test_returns_unchanged(self):
        out = NullProvider().enrich(list(_SUGGESTIONS), lang="en")
        assert out == _SUGGESTIONS

    def test_make_provider_none_returns_null(self):
        assert isinstance(make_provider({"provider": "none"}), NullProvider)

    def test_make_provider_unknown_returns_null(self):
        assert isinstance(make_provider({"provider": "bogus"}), NullProvider)

    def test_make_provider_empty_returns_null(self):
        assert isinstance(make_provider({}), NullProvider)


class TestNoNetwork:
    def test_null_provider_makes_no_network_call(self, monkeypatch):
        """provider='none' must never open a socket (air-gap enforcement)."""
        def _boom(*a, **k):
            raise AssertionError("network access attempted with provider=none")
        monkeypatch.setattr(socket, "socket", _boom)
        prov = make_provider({"provider": "none", "endpoint": "http://x", "api_key": "secret"})
        out = enrich_suggestions(list(_SUGGESTIONS), {"provider": "none"}, lang="en")
        assert out == _SUGGESTIONS
        assert isinstance(prov, NullProvider)


class TestProviderEnrichContract:
    def test_fake_provider_only_adds_llm_note(self):
        class FakeProvider:
            def enrich(self, suggestions, lang="en"):
                for s in suggestions:
                    s["llm_note"] = "looks legitimate"
                return suggestions
        out = FakeProvider().enrich([dict(_SUGGESTIONS[0])], lang="en")
        assert out[0]["llm_note"] == "looks legitimate"
        # heuristic fields untouched
        assert out[0]["risk"] == "low"
        assert out[0]["confidence"] == 0.8

    def test_failing_provider_falls_back_to_heuristic(self, monkeypatch):
        from src.report.analysis import rule_providers as rp

        class Boom:
            def enrich(self, suggestions, lang="en"):
                raise RuntimeError("llm down")
        monkeypatch.setattr(rp, "make_provider", lambda cfg: Boom())
        out = enrich_suggestions(list(_SUGGESTIONS), {"provider": "ollama"}, lang="en")
        assert out == _SUGGESTIONS  # unchanged on failure

    def test_api_key_not_in_logs(self, monkeypatch):
        """Provider failures must not log the api_key (repo lesson L-12)."""
        from src.report.analysis import rule_providers as rp
        logged = []

        class Boom:
            def enrich(self, suggestions, lang="en"):
                raise RuntimeError("boom")
        monkeypatch.setattr(rp, "make_provider", lambda cfg: Boom())
        monkeypatch.setattr(rp.logger, "warning", lambda msg, *a, **k: logged.append(str(msg)))
        enrich_suggestions(list(_SUGGESTIONS), {"provider": "ollama", "api_key": "TOPSECRET"}, lang="en")
        assert all("TOPSECRET" not in m for m in logged)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_rule_providers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.analysis.rule_providers'`.

- [ ] **Step 3: Implement the provider layer**

Create `src/report/analysis/rule_providers.py`:

```python
"""Pluggable LLM provider layer for AI-rule-suggestion enrichment.

DISABLED BY DEFAULT (provider='none' → NullProvider). No network call ever
happens unless a real provider is explicitly configured. The heuristic result
is complete on its own; providers only ADD an `llm_note` field. Any provider
failure falls back to the unchanged heuristic result.

Secrets (api_key) are NEVER logged (repo lesson L-12).
"""
from __future__ import annotations

from typing import Protocol

from loguru import logger


class Provider(Protocol):
    def enrich(self, suggestions: list[dict], lang: str = "en") -> list[dict]: ...


class NullProvider:
    """Default provider. Returns heuristic suggestions unchanged. Zero network."""

    def enrich(self, suggestions: list[dict], lang: str = "en") -> list[dict]:
        return suggestions


def make_provider(cfg: dict) -> Provider:
    """Return a provider for cfg['provider']; 'none'/unknown → NullProvider.

    The 'none' path imports no network library and builds no client.
    """
    name = str((cfg or {}).get("provider", "none")).strip().lower()
    if name in ("ollama", "openai", "anthropic"):
        # Real adapters are thin and imported lazily so the default ('none')
        # path never pulls in any network dependency. Until implemented they
        # degrade safely to NullProvider.
        try:
            from src.report.analysis import rule_provider_adapters as adapters
            builder = getattr(adapters, f"make_{name}_provider", None)
            if builder is not None:
                return builder(cfg)
        except Exception as e:  # noqa: BLE001 - never let provider setup break the core
            logger.warning("ai-rules provider %s unavailable (%s); using heuristic only",
                           name, type(e).__name__)
    return NullProvider()


def enrich_suggestions(suggestions: list[dict], cfg: dict, lang: str = "en") -> list[dict]:
    """Enrich via the configured provider; fall back to heuristic on any failure.

    Never logs the api_key or any secret (only the provider name + error class).
    """
    try:
        provider = make_provider(cfg)
        return provider.enrich(suggestions, lang=lang)
    except Exception as e:  # noqa: BLE001
        name = str((cfg or {}).get("provider", "none")).strip().lower()
        logger.warning("ai-rules enrichment failed for provider %s (%s); using heuristic only",
                       name, type(e).__name__)
        return suggestions
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_rule_providers.py -q`
Expected: `8 passed`.

- [ ] **Step 5: Commit**

```
cd /home/harry/rd/illumio-ops && git add src/report/analysis/rule_providers.py tests/test_rule_providers.py && git commit -m "feat(ai-rules): pluggable provider layer with NullProvider default + no-network enforcement"
```

---

### Task 3: Config — additive `ai_rules` section

**Files:**
- Modify: `src/config_models.py` (add `AiRulesSettings` before `ConfigSchema` ~308; add field to `ConfigSchema`)
- Modify: `src/config.py` (`_DEFAULT_CONFIG` ~49)
- Test: `tests/test_config_ai_rules.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_ai_rules.py`:

```python
"""Tests for the additive ai_rules config section (default off, secret redaction)."""
import json

from src.config import ConfigManager
from src.config_models import ConfigSchema


def test_default_ai_rules_is_off():
    cfg = ConfigSchema().model_dump(mode="json")
    assert cfg["ai_rules"]["provider"] == "none"
    assert cfg["ai_rules"]["enabled"] is False
    assert cfg["ai_rules"]["api_key"] == ""


def test_default_config_includes_ai_rules(tmp_path):
    cm = ConfigManager(config_file=str(tmp_path / "config.json"))
    assert cm.config["ai_rules"]["provider"] == "none"


def test_ai_rules_validates_provider_literal(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"ai_rules": {"provider": "ollama", "model": "llama3"}}))
    cm = ConfigManager(config_file=str(p))
    assert cm.config["ai_rules"]["provider"] == "ollama"
    assert cm.config["ai_rules"]["model"] == "llama3"


def test_invalid_provider_does_not_leak_api_key_in_log(tmp_path, capsys):
    """An invalid ai_rules block must not print the api_key (repo lesson L-12)."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"ai_rules": {"provider": "bogus", "api_key": "TOPSECRET"}}))
    ConfigManager(config_file=str(p))
    captured = capsys.readouterr()
    assert "TOPSECRET" not in (captured.out + captured.err)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_config_ai_rules.py -q`
Expected: FAIL with `KeyError: 'ai_rules'`.

- [ ] **Step 3: Add the pydantic model**

In `src/config_models.py`, immediately BEFORE `class ConfigSchema(_Base):` (~308), insert:

```python
class AiRulesSettings(_Base):
    enabled: bool = False
    provider: Literal["none", "ollama", "openai", "anthropic"] = "none"
    model: str = ""
    endpoint: str = ""
    api_key: str = ""
```

Then add a field to `ConfigSchema` (after the `siem:` line ~327):

```python
    ai_rules: AiRulesSettings = Field(default_factory=AiRulesSettings)
```

- [ ] **Step 4: Add the default config block**

In `src/config.py`, inside `_DEFAULT_CONFIG` (~49), add a top-level entry (place it after the `"api": {...}` line for readability):

```python
    "ai_rules": {"enabled": False, "provider": "none", "model": "", "endpoint": "", "api_key": ""},
```

> Note: `api_key` contains the substring `key`, so the existing `_SECRET_FIELD_TOKENS` redaction in `src/config.py::_format_error_input` already masks it in validation error logs (verified by Step 1's `test_invalid_provider_does_not_leak_api_key_in_log`).

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_config_ai_rules.py -q`
Expected: `4 passed`.

- [ ] **Step 6: Run config regression tests**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_config_backwards_compat.py tests/test_config_deprecated_keys.py -q`
Expected: all pass (the new section is additive; round-trip identity preserved).

- [ ] **Step 7: Commit**

```
cd /home/harry/rd/illumio-ops && git add src/config_models.py src/config.py tests/test_config_ai_rules.py && git commit -m "feat(ai-rules): add additive ai_rules config section (provider=none default)"
```

---

### Task 4: i18n keys (EN + ZH_TW)

**Files:**
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`
- Test: i18n audit (existing `scripts/audit_i18n_usage.py` + existing i18n parity tests)

> i18n JSON files are flat `{ "key": "value" }` objects, alphabetically grouped by prefix. Keys MUST exist in BOTH files (parity check, category I). zh_TW MUST keep glossary terms in English (Block/Blocked/Allow/Port/Service/Workload/App/Policy — category E).

- [ ] **Step 1: Add EN keys**

In `src/i18n_en.json`, add (in the `rpt_` alphabetical region):

```json
  "rpt_ai_rules_title": "AI-Assisted Rule Suggestions",
  "rpt_ai_rules_disclaimer": "Suggestions only — no rules were created or applied on the PCE. Review each candidate before acting.",
  "rpt_ai_rules_col_src": "Source Label",
  "rpt_ai_rules_col_dst": "Destination Label",
  "rpt_ai_rules_col_port": "Port",
  "rpt_ai_rules_col_proto": "Protocol",
  "rpt_ai_rules_col_risk": "Risk",
  "rpt_ai_rules_col_confidence": "Confidence",
  "rpt_ai_rules_col_observed": "Observed Flows",
  "rpt_ai_rules_col_rationale": "Rationale",
  "rpt_ai_rules_empty": "No blocked or potentially-blocked flows to suggest rules for.",
```

- [ ] **Step 2: Add ZH_TW keys**

In `src/i18n_zh_TW.json`, add the same keys (glossary terms stay English):

```json
  "rpt_ai_rules_title": "AI 輔助規則建議",
  "rpt_ai_rules_disclaimer": "僅為建議，未在 PCE 上建立或套用任何規則，請逐筆審查後再採取行動。",
  "rpt_ai_rules_col_src": "來源 Label",
  "rpt_ai_rules_col_dst": "目的地 Label",
  "rpt_ai_rules_col_port": "Port",
  "rpt_ai_rules_col_proto": "Protocol",
  "rpt_ai_rules_col_risk": "風險",
  "rpt_ai_rules_col_confidence": "信心度",
  "rpt_ai_rules_col_observed": "觀測流量數",
  "rpt_ai_rules_col_rationale": "佐證理由",
  "rpt_ai_rules_empty": "沒有 Blocked 或 Potentially Blocked 流量可供建議規則。",
```

- [ ] **Step 3: Run the i18n audit**

Run: `cd /home/harry/rd/illumio-ops && python scripts/audit_i18n_usage.py`
Expected: `0 findings` (exit 0). If category E flags a zh_TW glossary violation, replace the offending Chinese term with the English glossary term.

- [ ] **Step 4: Run i18n parity tests**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/ -q -k i18n`
Expected: all pass.

- [ ] **Step 5: Commit**

```
cd /home/harry/rd/illumio-ops && git add src/i18n_en.json src/i18n_zh_TW.json && git commit -m "i18n(ai-rules): add rpt_ai_rules_* keys (EN + ZH_TW)"
```

---

### Task 5: Report facade — `AiRulesReport.run` (HTML + CSV)

**Files:**
- Create: `src/report/ai_rules_report.py`
- Test: `tests/test_ai_rules_report.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ai_rules_report.py`:

```python
"""Tests for the AI-rules report facade (HTML + CSV, recommendation-only)."""
import os
import zipfile

from src.report.ai_rules_report import AiRulesReport


class _FakeCacheReader:
    def __init__(self, flows):
        self._flows = flows
    def read_flows_raw(self, start, end):
        return self._flows


def _flows():
    return [
        {"src": {"labels": [{"key": "role", "value": "web"}]},
         "dst": {"labels": [{"key": "role", "value": "db"}]},
         "service": {"port": 3306, "proto": 6}, "policy_decision": "blocked"},
        {"src": {"labels": [{"key": "role", "value": "adm"}]},
         "dst": {"labels": [{"key": "role", "value": "srv"}]},
         "service": {"port": 3389, "proto": 6}, "policy_decision": "blocked"},
    ]


class _Cm:
    config = {"settings": {"language": "en"}, "ai_rules": {"provider": "none"}}


def test_run_writes_html_with_disclaimer(tmp_path):
    rpt = AiRulesReport(_Cm(), cache_reader=_FakeCacheReader(_flows()))
    path = rpt.run(output_dir=str(tmp_path), lang="en")
    assert path and os.path.exists(path)
    html = open(path, encoding="utf-8").read()
    assert "Suggestions only" in html
    assert "3306" in html  # the db candidate is present


def test_empty_flows_returns_empty_string(tmp_path):
    rpt = AiRulesReport(_Cm(), cache_reader=_FakeCacheReader([]))
    assert rpt.run(output_dir=str(tmp_path), lang="en") == ""


def test_csv_export_contains_candidates(tmp_path):
    rpt = AiRulesReport(_Cm(), cache_reader=_FakeCacheReader(_flows()))
    zip_path = rpt.export_csv(output_dir=str(tmp_path), lang="en")
    assert zip_path and zipfile.is_zipfile(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        body = "".join(zf.read(n).decode("utf-8") for n in zf.namelist())
    assert "3306" in body
    assert "3389" in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_ai_rules_report.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.report.ai_rules_report'`.

- [ ] **Step 3: Implement the facade**

Create `src/report/ai_rules_report.py`:

```python
"""AI-Assisted Rule Suggestions report facade (HTML + CSV).

Mirrors src/report/security_risk_report.py. RECOMMENDATIONS ONLY — this report
never provisions or applies any rule. The default path reads from the offline
PCE cache; the API path is only used when no cache_reader is supplied.
"""
from __future__ import annotations

import datetime
import os

import pandas as pd
from loguru import logger

from src.i18n import t
from src.report.analysis.rule_suggester import suggest_rules, resolve_rule_rationale
from src.report.analysis.rule_providers import enrich_suggestions
from src.report.exporters.csv_exporter import CsvExporter

_LOOKBACK_DAYS = 7


class AiRulesReport:
    def __init__(self, cm, api_client=None, config_dir: str = "config", cache_reader=None):
        self.cm = cm
        self.api_client = api_client
        self.config_dir = config_dir
        self.cache_reader = cache_reader

    # ── data ────────────────────────────────────────────────────────────
    def _fetch_flows(self) -> list[dict]:
        now = datetime.datetime.now(datetime.timezone.utc)
        start = now - datetime.timedelta(days=_LOOKBACK_DAYS)
        if self.cache_reader is not None:
            return self.cache_reader.read_flows_raw(start, now)
        if self.api_client is not None:
            from src.api.traffic_query import TrafficQuery  # lazy: avoids API import on cache path
            tq = TrafficQuery(self.api_client)
            return tq.fetch_traffic_for_report(
                start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                policy_decisions=["blocked", "potentially_blocked"],
            )
        return []

    def _suggestions(self, lang: str) -> list[dict]:
        flows = self._fetch_flows()
        suggestions = suggest_rules(flows)
        if not suggestions:
            return []
        cfg = (self.cm.config or {}).get("ai_rules", {}) or {}
        return enrich_suggestions(suggestions, cfg, lang=lang)

    @staticmethod
    def _to_dataframe(suggestions: list[dict], lang: str) -> pd.DataFrame:
        rows = []
        for s in suggestions:
            rows.append({
                t("rpt_ai_rules_col_src"): s["src_label"],
                t("rpt_ai_rules_col_dst"): s["dst_label"],
                t("rpt_ai_rules_col_port"): s["port"],
                t("rpt_ai_rules_col_proto"): s["proto"],
                t("rpt_ai_rules_col_risk"): s["risk"],
                t("rpt_ai_rules_col_confidence"): s["confidence"],
                t("rpt_ai_rules_col_observed"): s["observed_flows"],
                t("rpt_ai_rules_col_rationale"): resolve_rule_rationale(
                    s["rationale_code"], lang, **s.get("rationale_args", {})),
            })
        return pd.DataFrame(rows)

    # ── outputs ─────────────────────────────────────────────────────────
    def run(self, output_dir: str = "reports", lang: str = "en") -> str:
        suggestions = self._suggestions(lang)
        if not suggestions:
            return ""
        df = self._to_dataframe(suggestions, lang)
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        path = os.path.join(output_dir, f"Illumio_AI_Rule_Suggestions_{ts}.html")
        title = t("rpt_ai_rules_title")
        disclaimer = t("rpt_ai_rules_disclaimer")
        table_html = df.to_html(index=False, escape=True, border=0)
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{title}</title>"
            "<style>body{font-family:sans-serif;margin:24px}"
            ".disclaimer{background:#fff3cd;border:1px solid #ffc107;padding:10px;"
            "border-radius:6px;margin-bottom:16px;font-weight:600}"
            "table{border-collapse:collapse;width:100%}"
            "th,td{border:1px solid #ddd;padding:6px 10px;text-align:left}"
            "th{background:#f5f5f5}</style></head><body>"
            f"<h1>{title}</h1>"
            f"<div class='disclaimer'>{disclaimer}</div>"
            f"{table_html}</body></html>"
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        logger.info("[AiRulesReport] wrote %s (%d suggestions)", path, len(suggestions))
        return path

    def export_csv(self, output_dir: str = "reports", lang: str = "en") -> str:
        suggestions = self._suggestions(lang)
        if not suggestions:
            return ""
        df = self._to_dataframe(suggestions, lang)
        results = {"ai_rules": {"suggestions": df}}
        return CsvExporter(results, report_label="AI_Rule_Suggestions").export(output_dir)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_ai_rules_report.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```
cd /home/harry/rd/illumio-ops && git add src/report/ai_rules_report.py tests/test_ai_rules_report.py && git commit -m "feat(ai-rules): AiRulesReport facade (HTML + CSV, recommendation-only)"
```

---

### Task 6: CLI command — `report ai-rules`

**Files:**
- Modify: `src/cli/report.py` (add `generate_ai_rules_report` + `report ai-rules` command)
- Test: `tests/test_cli_ai_rules.py`

> The `report` group is already registered in `src/cli/root.py:89` — no root change needed.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_ai_rules.py`:

```python
"""Tests for the `report ai-rules` CLI command."""
from click.testing import CliRunner

from src.cli.root import cli
import src.cli.report as report_mod


def test_ai_rules_command_exists():
    runner = CliRunner()
    res = runner.invoke(cli, ["report", "ai-rules", "--help"])
    assert res.exit_code == 0
    assert "ai-rules" in res.output or "AI" in res.output


def test_ai_rules_emits_path(monkeypatch, tmp_path):
    out_file = str(tmp_path / "ai.html")
    open(out_file, "w").write("<html></html>")
    monkeypatch.setattr(report_mod, "generate_ai_rules_report", lambda **kw: [out_file])
    runner = CliRunner()
    res = runner.invoke(cli, ["report", "ai-rules", "--output-dir", str(tmp_path)])
    assert res.exit_code == 0
    assert out_file in res.output
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_cli_ai_rules.py -q`
Expected: FAIL (no `ai-rules` subcommand; `generate_ai_rules_report` missing).

- [ ] **Step 3: Add the handler + command**

In `src/cli/report.py`, add the handler function (next to `generate_security_report`, ~106):

```python
def generate_ai_rules_report(
    *,
    source: str = "cache",
    fmt: str = "html",
    output_dir: str | None = None,
) -> list[str]:
    from src.config import ConfigManager
    from src.report.ai_rules_report import AiRulesReport

    cm = ConfigManager()
    _root_dir, config_dir = _resolve_paths(output_dir)
    out = _resolve_output_dir(cm, output_dir)
    lang = _resolve_lang(cm)

    api = None
    cache_reader = None
    if source == "cache":
        from src.main import _make_cache_reader
        cache_reader = _make_cache_reader(cm)
    else:
        from src.api_client import ApiClient
        api = ApiClient(cm)

    rpt = AiRulesReport(cm, api_client=api, config_dir=config_dir, cache_reader=cache_reader)
    path = rpt.export_csv(out, lang=lang) if fmt == "csv" else rpt.run(out, lang=lang)
    if not path:
        raise click.ClickException("No blocked/potentially-blocked flows to suggest rules for")
    return [path]
```

Then add the command (after `report_traffic`, near the other `@report_group.command(...)` defs):

```python
@report_group.command("ai-rules")
@click.option("--source", type=click.Choice(["cache", "api"]), default="cache",
              help="Flow source (default: cache — offline / air-gap safe)")
@click.option("--format", "fmt", type=click.Choice(["html", "csv"]), default="html")
@click.option("--output-dir", type=click.Path(), default=None)
@click.pass_context
def report_ai_rules(ctx: click.Context, source: str, fmt: str, output_dir) -> None:
    """Suggest allow-rule candidates from blocked traffic (recommendations only)."""
    paths = generate_ai_rules_report(source=source, fmt=fmt, output_dir=output_dir)
    _emit_paths(ctx, paths, fmt)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_cli_ai_rules.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Run CLI regression tests**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_cli_report_commands.py tests/test_cli_subcommands.py -q`
Expected: all pass (additive command; existing ones unchanged).

- [ ] **Step 6: Commit**

```
cd /home/harry/rd/illumio-ops && git add src/cli/report.py tests/test_cli_ai_rules.py && git commit -m "feat(ai-rules): add `report ai-rules` CLI command (cache source default)"
```

---

### Final Verification

- [ ] **Run the full AI-rules test set**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_rule_suggester.py tests/test_rule_providers.py tests/test_config_ai_rules.py tests/test_ai_rules_report.py tests/test_cli_ai_rules.py -q`
Expected: all pass (30 tests).

- [ ] **Air-gap assertion is present and green**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_rule_providers.py::TestNoNetwork -q`
Expected: `1 passed` — confirms `provider="none"` opens no socket.

- [ ] **i18n audit clean**

Run: `cd /home/harry/rd/illumio-ops && python scripts/audit_i18n_usage.py`
Expected: exit 0, 0 findings.

- [ ] **No regressions in config / report / CLI**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/ -q -k "config or report or cli or i18n"`
Expected: all pass.

---

## Self-Review Notes (author)

- **Spec coverage:** A (heuristic core) → Task 1; B (rationale templates) → Task 1; C (provider abstraction + default-off + no-network) → Task 2; config `ai_rules` → Task 3; i18n → Task 4; D (HTML+CSV report) → Task 5; CLI → Task 6; air-gap test → Task 2 + Final Verification. All spec sections mapped.
- **Type consistency:** the suggestion dict shape (src_label/dst_label/port/proto/pd/observed_*/confidence/risk/rationale_code/rationale_args) is produced in Task 1, passed through unchanged by Task 2's `enrich_suggestions`, and consumed in Task 5 (`_to_dataframe` reads every field; `resolve_rule_rationale` reads `rationale_code` + `rationale_args`). Consistent end to end.
- **Air-gap:** default `provider="none"` (Task 3) → `NullProvider` (Task 2) → zero network, asserted by `test_null_provider_makes_no_network_call`. Report default source is `cache` (Task 6). The API import in the report facade is lazy and only reached when a caller explicitly passes `--source api`.
- **Secrets (L-12):** `api_key` field name contains `key` → existing `_SECRET_FIELD_TOKENS` redaction covers validation logs (Task 3 test); provider failure logs record only provider name + error class (Task 2 test `test_api_key_not_in_logs`).
- **Non-destructive:** no provision/create-rule API call anywhere; report + CLI both carry the disclaimer; `config["rules"]` and `alerts.json` are never touched.
- **Placeholders:** none — every code/step has concrete, repo-grounded content.
