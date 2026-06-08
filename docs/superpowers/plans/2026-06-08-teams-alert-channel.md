# Microsoft Teams Alert Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fifth alert output channel `teams` that POSTs an Adaptive Card to a Microsoft Teams **Power Automate (Workflows) incoming webhook**, mirroring the existing `WebhookAlertPlugin` / `TelegramAlertPlugin` architecture exactly. The Teams workflow webhook URL is a secret (contains a `sig=` token) and must never be logged or stored unredacted (README L-12 lesson).

**Architecture:** A new `TeamsAlertPlugin(AlertOutputPlugin)` in `src/alerts/plugins.py` (auto-registered via `__init_subclass__` with `name="teams"`); a new `Reporter._build_teams_card(subj)` builder reusing `render_alert_template`; a new `src/alerts/templates/teams_card.json.tmpl`; config field `alerts.teams_webhook_url` (pydantic + default); plugin metadata; CLI menu entry; EN/ZH_TW i18n. All HTTP is mocked in tests (no real network).

**Tech Stack:** Python 3.10+, pytest, urllib.request (stdlib), pydantic, JSON i18n (EN + ZH_TW). No new third-party deps (air-gap safe).

**Spec:** `docs/superpowers/specs/2026-06-08-teams-alert-channel-design.md`

**Deliberate refinements to the spec (disclosed):**
1. `redact_webhook_url` lives in `src/alerts/plugins.py` (module-level, near the plugin that uses it) rather than `src/utils.py` — keeps the L-12 redaction logic co-located with its only consumer (YAGNI).
2. The Teams card reuses the existing `alert_tpl_telegram_title` i18n key for its title instead of a new `alert_tpl_teams_title`, to avoid a duplicate string (disclosed in spec §4.3).
3. Adaptive Card schema version pinned to `1.4` (broad Teams support); no severity color containers (YAGNI, spec §11).

---

### Task 1: schema + default — `alerts.teams_webhook_url`

**Files:**
- Modify: `src/config_models.py` (`AlertsSettings`, ~63-84)
- Modify: `src/config.py` (`_DEFAULT_CONFIG["alerts"]`, ~51-56)
- Test: `tests/test_teams_webhook_scheme.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_teams_webhook_scheme.py`:

```python
"""AlertsSettings must accept a Teams Power Automate workflow webhook URL (https-only)."""
import pytest
from pydantic import ValidationError

from src.config_models import AlertsSettings


def test_teams_default_empty():
    a = AlertsSettings()
    assert a.teams_webhook_url == ""
    # Existing defaults unchanged
    assert a.active == ["mail"]


def test_teams_accepts_https():
    url = "https://prod-12.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=SECRET"
    a = AlertsSettings(teams_webhook_url=url)
    assert a.teams_webhook_url == url


def test_teams_rejects_http():
    with pytest.raises((ValidationError, ValueError), match="https"):
        AlertsSettings(teams_webhook_url="http://example.com/hook")


def test_teams_accepts_empty():
    assert AlertsSettings(teams_webhook_url="").teams_webhook_url == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_teams_webhook_scheme.py -v`
Expected: FAIL — `test_teams_accepts_https`/`test_teams_default_empty` error because `AlertsSettings` has no `teams_webhook_url`; `test_teams_rejects_http` fails because no validator rejects http (pydantic ignores the unknown kwarg or accepts it).

- [ ] **Step 3: Add the field + validator to `AlertsSettings`**

In `src/config_models.py`, inside `class AlertsSettings(_Base):`, after the existing `telegram_chat_id: str = ""` line (and the existing `webhook_url` validator block), add the field and a mirrored validator. The class currently ends:

```python
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @field_validator("webhook_url", mode="after")
    @classmethod
    def _require_https(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            scheme = v.split("://")[0] if "://" in v else "no scheme"
            raise ValueError(
                "webhook_url must use https:// scheme (got: "
                f"{scheme}://...)"
            )
        return v
```

Change it to:

```python
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    teams_webhook_url: str = ""

    @field_validator("webhook_url", mode="after")
    @classmethod
    def _require_https(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            scheme = v.split("://")[0] if "://" in v else "no scheme"
            raise ValueError(
                "webhook_url must use https:// scheme (got: "
                f"{scheme}://...)"
            )
        return v

    @field_validator("teams_webhook_url", mode="after")
    @classmethod
    def _require_https_teams(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            scheme = v.split("://")[0] if "://" in v else "no scheme"
            raise ValueError(
                "teams_webhook_url must use https:// scheme (got: "
                f"{scheme}://...)"
            )
        return v
```

- [ ] **Step 4: Add the in-memory default**

In `src/config.py`, the `_DEFAULT_CONFIG["alerts"]` block currently reads:

```python
    "alerts": {
        "active": ["mail"],
        "line_channel_access_token": "",
        "line_target_id": "",
        "webhook_url": ""
    },
```

Change it to:

```python
    "alerts": {
        "active": ["mail"],
        "line_channel_access_token": "",
        "line_target_id": "",
        "webhook_url": "",
        "teams_webhook_url": ""
    },
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_teams_webhook_scheme.py tests/test_webhook_scheme.py tests/test_config_models_alerts.py -v`
Expected: PASS (new Teams scheme tests + pre-existing webhook/alerts schema tests still green).

- [ ] **Step 6: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/config_models.py src/config.py tests/test_teams_webhook_scheme.py
git commit -m "feat(alerts): add alerts.teams_webhook_url schema field + https validator"
```

---

### Task 2: secret redaction helper (README L-12)

**Files:**
- Modify: `src/alerts/plugins.py` (add module-level `redact_webhook_url`)
- Test: `tests/test_teams_redaction.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_teams_redaction.py`:

```python
"""Teams webhook URL is a secret (contains sig= token); it must be redacted (README L-12)."""
from src.alerts.plugins import redact_webhook_url


_URL = ("https://prod-12.westus.logic.azure.com:443/workflows/abc123/"
        "triggers/manual/paths/invoke?api-version=2016-06-01&sig=SUPERSECRETSIG")


def test_redaction_drops_secret_and_path():
    red = redact_webhook_url(_URL)
    assert "SUPERSECRETSIG" not in red
    assert "sig=" not in red
    assert "/workflows/" not in red
    assert "paths/invoke" not in red


def test_redaction_keeps_scheme_and_host():
    red = redact_webhook_url(_URL)
    assert red.startswith("https://")
    assert "prod-12.westus.logic.azure.com" in red


def test_redaction_empty_returns_empty():
    assert redact_webhook_url("") == ""


def test_redaction_handles_garbage():
    # Non-URL input must not raise; just return something secret-free.
    assert "SUPERSECRETSIG" not in redact_webhook_url("not a url SUPERSECRETSIG")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_teams_redaction.py -v`
Expected: FAIL — `ImportError: cannot import name 'redact_webhook_url' from 'src.alerts.plugins'`.

- [ ] **Step 3: Implement `redact_webhook_url`**

In `src/alerts/plugins.py`, the import block at the top currently is:

```python
from __future__ import annotations

import json
import os
import smtplib
import socket
import ssl
import time
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.i18n import t
from src.utils import Colors

from .base import AlertOutputPlugin
```

Add `from urllib.parse import urlsplit` to the stdlib imports (after `import urllib.request`), then add the module-level function immediately after the `from .base import AlertOutputPlugin` line:

```python
from urllib.parse import urlsplit
```

and:

```python
def redact_webhook_url(url: str) -> str:
    """Redact a Teams/Power-Automate webhook URL for safe logging/storage.

    The Teams workflow webhook embeds an invocation secret in its query string
    (``...&sig=<SECRET>``) and identifiers in its path (``/workflows/<id>/...``).
    Per README L-12 (Telegram token leaked via proxy access logs), channel
    secrets must never reach logs, debug output, or persisted dispatch results.
    Keeps only ``scheme://host`` and elides the rest.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}/…"
    except Exception:
        pass
    return "…"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_teams_redaction.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/alerts/plugins.py tests/test_teams_redaction.py
git commit -m "feat(alerts): add redact_webhook_url helper for Teams secret (L-12)"
```

---

### Task 3: Adaptive Card template + `Reporter._build_teams_card`

**Files:**
- Create: `src/alerts/templates/teams_card.json.tmpl`
- Modify: `src/reporter.py` (add `_build_teams_card` after `_build_webhook_payload`, ~342-420)
- Test: `tests/test_teams_card.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_teams_card.py`:

```python
"""Reporter._build_teams_card builds a Power-Automate Adaptive Card POST body."""
from unittest.mock import MagicMock

from src.config import ConfigManager
from src.reporter import Reporter


def _reporter(gui_base_url=""):
    cm = MagicMock(spec=ConfigManager)
    cm.config = {
        "alerts": {"active": ["teams"], "teams_webhook_url": "https://x.logic.azure.com/…"},
        "settings": {"language": "en"},
        "gui_base_url": gui_base_url,
    }
    r = Reporter(cm)
    r.add_health_alert({
        "rule": "API Health",
        "status": "503",
        "time": "2026-06-08 06:00",
        "details": "PCE unreachable",
    })
    r.event_alerts = []
    r.traffic_alerts = []
    r.metric_alerts = []
    return r


def test_card_outer_envelope_is_power_automate_shape():
    card = _reporter()._build_teams_card("Daily Digest")
    assert card["type"] == "message"
    att = card["attachments"][0]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert att["content"]["type"] == "AdaptiveCard"
    assert att["content"]["version"] == "1.4"


def test_card_contains_subject_and_alert():
    card = _reporter()._build_teams_card("Daily Digest")
    blob = str(card)
    assert "Daily Digest" in blob
    assert "API Health" in blob


def test_card_has_open_in_pce_action_when_base_url_set():
    card = _reporter(gui_base_url="https://pce.example.com:8443")._build_teams_card("S")
    actions = card["attachments"][0]["content"].get("actions", [])
    assert any(a.get("type") == "Action.OpenUrl" for a in actions)


def test_card_omits_actions_without_base_url():
    card = _reporter(gui_base_url="")._build_teams_card("S")
    assert not card["attachments"][0]["content"].get("actions")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_teams_card.py -v`
Expected: FAIL — `AttributeError: 'Reporter' object has no attribute '_build_teams_card'`.

- [ ] **Step 3: Create the Adaptive Card template**

Create `src/alerts/templates/teams_card.json.tmpl` (mirrors `webhook_payload.json.tmpl`'s `$*_json` substitution style so every dynamic value is injected as a pre-serialized JSON token):

```
{
  "type": "message",
  "attachments": [
    {
      "contentType": "application/vnd.microsoft.card.adaptive",
      "content": {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
          {
            "type": "TextBlock",
            "size": "Large",
            "weight": "Bolder",
            "text": $title_json,
            "wrap": true
          },
          {
            "type": "TextBlock",
            "spacing": "None",
            "isSubtle": true,
            "text": $subject_json,
            "wrap": true
          },
          {
            "type": "FactSet",
            "facts": $facts_json
          },
          {
            "type": "TextBlock",
            "text": $summary_json,
            "wrap": true
          }
        ]$actions_fragment
      }
    }
  ]
}
```

> Note: `$actions_fragment` expands to either `""` (no actions) or `,\n        "actions": [ ... ]` so the surrounding JSON stays valid in both cases. `$title_json` reuses `alert_tpl_telegram_title` (spec §4.3).

- [ ] **Step 4: Implement `_build_teams_card`**

In `src/reporter.py`, locate `_build_webhook_payload` (def at ~342). Immediately AFTER that method's `return ...` (before the next `def`), add:

```python
    def _build_teams_card(self, subj: str) -> dict:
        """Build a Power-Automate Adaptive Card (v1.4) POST body for Teams.

        Mirrors _build_webhook_payload's template-driven assembly but emits the
        `attachments`-wrapped Adaptive Card shape Power Automate Workflows
        expect. Pure data assembly (no I/O). Values go into TextBlock/FactSet
        elements as plain text; everything is injected via *_json tokens so the
        rendered template is valid JSON.
        """
        total_issues = (
            len(self.health_alerts) + len(self.event_alerts)
            + len(self.traffic_alerts) + len(self.metric_alerts)
        )

        facts = [
            {"title": t("alert_sec_health"), "value": str(len(self.health_alerts))},
            {"title": t("alert_sec_event"), "value": str(len(self.event_alerts))},
            {"title": t("alert_sec_traffic"), "value": str(len(self.traffic_alerts))},
            {"title": t("alert_sec_metric"), "value": str(len(self.metric_alerts))},
            {"title": t("alert_field_time"), "value": self._now_str()},
        ]

        # Compact one-line summaries of the first few issues (plain text).
        lines: list[str] = []
        for alert in self.health_alerts[:5]:
            lines.append(
                f"• {self._compact_text(alert.get('rule', ''))}"
                f" — {self._compact_text(alert.get('details', ''))}"
            )
        for payload in self._build_all_event_alert_payloads()[:5]:
            lines.append(f"• {self._compact_text(payload.get('rule', ''))}")
        summary = "\n".join(lines) if lines else t("mail_subject", count=total_issues)

        actions_fragment = ""
        base_url = self.cm.config.get("gui_base_url", "")
        if base_url:
            action = {
                "type": "Action.OpenUrl",
                "title": t("alert_tpl_see_web_for_details"),
                "url": base_url,
            }
            actions_fragment = ',\n        "actions": ' + json.dumps([action])

        rendered = render_alert_template(
            "teams_card.json.tmpl",
            title_json=json.dumps(t("alert_tpl_telegram_title")),
            subject_json=json.dumps(subj),
            facts_json=json.dumps(facts),
            summary_json=json.dumps(summary),
            actions_fragment=actions_fragment,
        )
        return json.loads(rendered)
```

> Verify the helpers exist in `reporter.py`: `json` is imported, `render_alert_template` is imported, and `self._now_str()` / `self._compact_text()` / `self._build_all_event_alert_payloads()` are defined (they are used by `_build_telegram_message`). If `render_alert_template` is not yet imported at module top, add `from src.alerts import render_alert_template` (it is already used by `_build_webhook_payload`/`_build_telegram_message`, so it is present).

- [ ] **Step 5: Add the i18n key the template needs (title reuse only — no new key here)**

No new i18n key is required in this task: `alert_tpl_telegram_title`, `alert_sec_*`, `alert_field_time`, `alert_tpl_see_web_for_details`, and `mail_subject` already exist (used by `_build_telegram_message` / `_build_webhook_payload`). New Teams-specific keys are added in Task 6.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_teams_card.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/alerts/templates/teams_card.json.tmpl src/reporter.py tests/test_teams_card.py
git commit -m "feat(alerts): add Reporter._build_teams_card Adaptive Card builder + template"
```

---

### Task 4: `TeamsAlertPlugin` (HTTP POST, mirrors WebhookAlertPlugin)

**Files:**
- Modify: `src/alerts/plugins.py` (add `TeamsAlertPlugin` after `TelegramAlertPlugin`)
- Test: `tests/test_alerts_teams.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_alerts_teams.py`:

```python
"""TeamsAlertPlugin: POSTs an Adaptive Card; redacts the secret webhook URL (L-12)."""
import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from src.alerts import build_output_plugin, get_output_registry

_URL = ("https://prod-12.westus.logic.azure.com/workflows/abc/"
        "triggers/manual/paths/invoke?sig=SUPERSECRETSIG")


def _make_cm(url=_URL):
    cm = MagicMock()
    cm.config = {"alerts": {"teams_webhook_url": url}, "settings": {"language": "en"}}
    return cm


def _reporter_stub():
    r = MagicMock()
    r._build_teams_card.return_value = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {"type": "AdaptiveCard", "version": "1.4", "body": []},
        }],
    }
    return r


def test_teams_plugin_registered():
    assert "teams" in get_output_registry()


def test_teams_plugin_skipped_when_unconfigured():
    plug = build_output_plugin("teams", _make_cm(url=""))
    res = plug.send(_reporter_stub(), "subj")
    assert res == {"channel": "teams", "status": "skipped", "target": "", "error": "missing configuration"}


def test_teams_plugin_posts_card_on_success_and_redacts_target():
    plug = build_output_plugin("teams", _make_cm())
    fake_resp = MagicMock(status=202)
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda self, *a: False
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        res = plug.send(_reporter_stub(), "subj")
    assert res["channel"] == "teams"
    assert res["status"] == "success"
    # L-12: target is redacted — no secret, no full path
    assert "SUPERSECRETSIG" not in res["target"]
    assert "sig=" not in res["target"]
    assert res["target"].startswith("https://prod-12.westus.logic.azure.com")
    # Outgoing request: full URL preserved on the wire, Adaptive Card body
    req = mock_open.call_args[0][0]
    assert req.full_url == _URL
    body = json.loads(req.data.decode())
    assert body["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"


def test_teams_plugin_fails_on_4xx_without_leaking_secret():
    plug = build_output_plugin("teams", _make_cm())
    err = urllib.error.HTTPError(_URL, 400, "Bad Request", {},
                                 MagicMock(read=lambda: b'{"error":"bad"}'))
    with patch("urllib.request.urlopen", side_effect=err):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert "SUPERSECRETSIG" not in res["target"]
    assert "SUPERSECRETSIG" not in res["error"]
    assert "400" in res["error"] or "Bad Request" in res["error"]


def test_teams_plugin_fails_on_url_error():
    plug = build_output_plugin("teams", _make_cm())
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert "timeout" in res["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_alerts_teams.py -v`
Expected: FAIL — `test_teams_plugin_registered` fails (`"teams"` not in registry); `build_output_plugin("teams", ...)` raises `KeyError`.

- [ ] **Step 3: Implement `TeamsAlertPlugin`**

In `src/alerts/plugins.py`, after the end of `class TelegramAlertPlugin` (its final `return {"channel": "telegram", "status": "failed", ...}` line), add:

```python
class TeamsAlertPlugin(AlertOutputPlugin):
    name = "teams"

    def send(self, reporter, subject: str, *, lang: str = "en") -> dict:
        webhook_url = self.cm.config.get("alerts", {}).get("teams_webhook_url", "")
        if not webhook_url:
            print(f"{Colors.WARNING}{t('teams_config_missing', lang=lang)}{Colors.ENDC}")
            return {"channel": "teams", "status": "skipped", "target": "", "error": "missing configuration"}

        # L-12: never expose the secret webhook URL in target/logs.
        safe_target = redact_webhook_url(webhook_url)

        card = reporter._build_teams_card(subject)
        data = json.dumps(card).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        try:
            req = urllib.request.Request(webhook_url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status in [200, 201, 202, 204]:
                    print(f"{Colors.GREEN}{t('teams_alert_sent', lang=lang)}{Colors.ENDC}")
                    return {"channel": "teams", "status": "success", "target": safe_target}
                print(f"{Colors.FAIL}{t('teams_alert_failed', lang=lang, error='', status=response.status)}{Colors.ENDC}")
                return {"channel": "teams", "status": "failed", "target": safe_target, "error": f"status={response.status}"}
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8")
            except Exception:
                error_body = "Could not read error body"
            print(f"{Colors.FAIL}{t('teams_alert_failed', lang=lang, error=f'{exc} - {error_body}', status=exc.code)}{Colors.ENDC}")
            return {"channel": "teams", "status": "failed", "target": safe_target, "error": f"{exc} - {error_body}"}
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"{Colors.FAIL}{t('teams_alert_failed', lang=lang, error=f'Connection Error/Timeout: {exc}', status='')}{Colors.ENDC}")
            return {"channel": "teams", "status": "failed", "target": safe_target, "error": f"Connection Error/Timeout: {exc}"}
        except Exception as exc:
            print(f"{Colors.FAIL}{t('teams_alert_failed', lang=lang, error=exc, status='')}{Colors.ENDC}")
            return {"channel": "teams", "status": "failed", "target": safe_target, "error": str(exc)}
```

> The i18n keys `teams_config_missing` / `teams_alert_sent` / `teams_alert_failed` are added in Task 6. `t()` returns the key itself (or a default) if a translation is missing, so these tests pass before Task 6; the strings just read as the raw key until then.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_alerts_teams.py tests/test_alerts_telegram.py tests/test_webhook_scheme.py -v`
Expected: PASS (new Teams plugin tests + pre-existing telegram/webhook tests still green).

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/alerts/plugins.py tests/test_alerts_teams.py
git commit -m "feat(alerts): add TeamsAlertPlugin posting Adaptive Card via workflow webhook"
```

---

### Task 5: plugin metadata + routing through `send_alerts`

**Files:**
- Modify: `src/alerts/metadata.py` (`PLUGIN_METADATA`, add `"teams"` after `"telegram"`, ~150-171)
- Test: `tests/test_alerts_teams.py` (append routing + metadata tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_alerts_teams.py`:

```python
def test_teams_plugin_metadata_present():
    from src.alerts.metadata import PLUGIN_METADATA
    assert "teams" in PLUGIN_METADATA
    meta = PLUGIN_METADATA["teams"]
    assert meta.display_name == "Microsoft Teams"
    fld = meta.fields["alerts.teams_webhook_url"]
    assert fld.secret is True
    assert fld.required is True


def test_send_alerts_routes_through_teams_plugin():
    from src.reporter import Reporter
    cm = MagicMock()
    cm.config = {
        "alerts": {"active": ["teams"], "teams_webhook_url": _URL},
        "settings": {"language": "en"},
        "gui_base_url": "",
    }
    r = Reporter(cm)
    r.add_health_alert({"rule": "X", "status": "503", "time": "t", "details": "d"})
    fake_resp = MagicMock(status=202)
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda self, *a: False
    with patch("urllib.request.urlopen", return_value=fake_resp), \
         patch("src.events.persist_dispatch_results"):
        results = r.send_alerts(force_test=False)
    teams = next(x for x in results if x["channel"] == "teams")
    assert teams["status"] == "success"
    # Persisted target must be redacted (dispatch history is stored).
    assert "SUPERSECRETSIG" not in teams["target"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_alerts_teams.py::test_teams_plugin_metadata_present -v`
Expected: FAIL — `KeyError: 'teams'` (metadata not registered).

> `test_send_alerts_routes_through_teams_plugin` already passes once the plugin from Task 4 exists (routing is generic), but keep both in this task so metadata + routing land together.

- [ ] **Step 3: Add the `"teams"` metadata entry**

In `src/alerts/metadata.py`, the `"telegram"` entry ends like this (closing the `PLUGIN_METADATA` dict):

```python
            "alerts.telegram_chat_id": FieldMeta(
                label="Chat ID",
                label_key="alert_plugin_field_telegram_chat_id",
                required=True,
                placeholder="-1001234567890 or 1284061527",
            ),
        },
    ),
}
```

Insert a new entry before the final `}` so it becomes:

```python
            "alerts.telegram_chat_id": FieldMeta(
                label="Chat ID",
                label_key="alert_plugin_field_telegram_chat_id",
                required=True,
                placeholder="-1001234567890 or 1284061527",
            ),
        },
    ),
    "teams": PluginMeta(
        name="teams",
        display_name="Microsoft Teams",
        display_name_key="alert_plugin_teams_display_name",
        description="Post an Adaptive Card to a Teams channel via a Power Automate Workflow webhook.",
        description_key="alert_plugin_teams_description",
        fields={
            "alerts.teams_webhook_url": FieldMeta(
                label="Workflow Webhook URL",
                label_key="alert_plugin_field_teams_webhook_url",
                required=True, secret=True,
                placeholder="https://prod-XX.logic.azure.com:443/workflows/.../triggers/manual/paths/invoke?...",
            ),
        },
    ),
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_alerts_teams.py tests/test_gui_alert_plugins.py -v`
Expected: PASS (metadata + routing tests + pre-existing GUI alert-plugins endpoint tests still green).

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/alerts/metadata.py tests/test_alerts_teams.py
git commit -m "feat(alerts): register Teams plugin metadata + routing test"
```

---

### Task 6: i18n keys (EN + ZH_TW)

**Files:**
- Modify: `src/i18n_en.json`
- Modify: `src/i18n_zh_TW.json`

- [ ] **Step 1: Add the new keys to `src/i18n_en.json`**

Add the plugin-metadata keys in alphabetical position within the existing `alert_plugin_*` block (after `alert_plugin_telegram_display_name`, ~line 82):

```json
  "alert_plugin_field_teams_webhook_url": "Workflow Webhook URL",
  "alert_plugin_teams_description": "Post an Adaptive Card to a Teams channel via a Power Automate Workflow webhook.",
  "alert_plugin_teams_display_name": "Microsoft Teams",
```

Add the runtime keys in alphabetical position near the other `*_alert_*` keys (the `telegram_alert_*` block is ~line 3679-3682; place these after it):

```json
  "teams_alert_failed": "Teams alert dispatch failed (status={status}): {error}",
  "teams_alert_sent": "Teams alert sent.",
  "teams_config_missing": "Teams alert skipped: workflow webhook URL not configured.",
```

Add the CLI keys near `edit_webhook_url` (~line 280) and `toggle_webhook_alert` (~line 3687):

```json
  "edit_teams_webhook_url": "8. Edit Teams Workflow Webhook URL",
```

```json
  "toggle_teams_alert": "5. Toggle Teams Alert (Current: {status})",
  "teams_webhook_url_input": "Teams Workflow Webhook URL",
```

> Exact numeric prefixes in `edit_teams_webhook_url` / `toggle_teams_alert` must match the final CLI menu numbering chosen in Task 7 — keep them consistent with Task 7's `print()` order.

- [ ] **Step 2: Add the SAME keys to `src/i18n_zh_TW.json`**

Insert in the same alphabetical positions. Per `src/i18n/data/glossary.json`, keep "Microsoft Teams", "Adaptive Card", "Workflow", "Webhook", and "PCE" in English:

```json
  "alert_plugin_field_teams_webhook_url": "Workflow Webhook URL",
  "alert_plugin_teams_description": "透過 Power Automate Workflow webhook 將 Adaptive Card 張貼到 Teams 頻道。",
  "alert_plugin_teams_display_name": "Microsoft Teams",
```

```json
  "teams_alert_failed": "Teams 告警送出失敗（status={status}）：{error}",
  "teams_alert_sent": "Teams 告警已送出。",
  "teams_config_missing": "Teams 告警略過：尚未設定 Workflow Webhook URL。",
```

```json
  "edit_teams_webhook_url": "8. 編輯 Teams Workflow Webhook URL",
```

```json
  "toggle_teams_alert": "5. 切換 Teams 告警（目前：{status}）",
  "teams_webhook_url_input": "Teams Workflow Webhook URL",
```

- [ ] **Step 3: Verify i18n parity + glossary**

Run: `cd /home/harry/rd/illumio-ops && python scripts/audit_i18n_usage.py`
Expected: no NEW parity (Cat I) or glossary (Cat E) failures for the `teams_*` / `alert_plugin_teams_*` keys. If a glossary violation is flagged, edit the ZH_TW value to preserve the flagged English term, then re-run.

- [ ] **Step 4: Run the i18n test suite**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_i18n_audit.py tests/test_i18n_glossary.py -v`
Expected: PASS (no new failures introduced by the added keys). If these test files do not exist, skip this step and rely on Step 3's audit script.

- [ ] **Step 5: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/i18n_en.json src/i18n_zh_TW.json
git commit -m "i18n(alerts): add Teams channel strings (EN/ZH_TW)"
```

---

### Task 7: CLI menu entry (`alert_settings_menu`)

**Files:**
- Modify: `src/cli/menus/alert.py`
- Test: manual (the CLI wizard is interactive; not covered by pytest)

> The menu currently has options 0-7 with `safe_input(..., int, range(0, 8))`. Adding Teams toggle + URL edit extends it to 0-9. Mirror the webhook toggle (option 4) and webhook URL edit (option 7). **Never print the full URL** — reuse the existing `current[:5] + "..."` mask.

- [ ] **Step 1: Add the menu lines and status**

In `src/cli/menus/alert.py`, after the `webhook_status = (...)` block, add:

```python
        teams_status = (
            t("ssl_status_on") if "teams" in active_alerts else t("ssl_status_off")
        )
```

In the `print(...)` block, after `print(t("toggle_webhook_alert", status=webhook_status))` add:

```python
        print(t("toggle_teams_alert", status=teams_status))
```

and after `print(t("edit_webhook_url"))` add:

```python
        print(t("edit_teams_webhook_url"))
```

> This makes the visible options: 1 language, 2 mail, 3 line, 4 webhook, **5 teams**, 6 edit line token, 7 edit line target, 8 edit webhook url, **9 edit teams url**, 0 return. Update the `print()` ordering so the existing `toggle_*`/`edit_*` i18n numeric prefixes stay correct, and align Task 6's numbers (`toggle_teams_alert` = "5.", `edit_teams_webhook_url` = "9.") — adjust the other edit-line/edit-webhook prefixes if you renumber. Keep numbering consistent across the i18n strings and the menu print order.

- [ ] **Step 2: Widen the input range**

Change:

```python
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 8))
```

to:

```python
        sel = safe_input(f"\n{t('please_select')}", int, range(0, 10))
```

- [ ] **Step 3: Handle the Teams toggle**

The existing toggle handles `mail`/`line`/`webhook` as options 2/3/4:

```python
        elif sel in [2, 3, 4]:
            channel = "mail" if sel == 2 else "line" if sel == 3 else "webhook"
            if channel in active_alerts:
                active_alerts.remove(channel)
            else:
                active_alerts.append(channel)
            cm.config.setdefault("alerts", {})["active"] = active_alerts
            cm.save()
```

Extend it to include Teams as option 5:

```python
        elif sel in [2, 3, 4, 5]:
            channel = {2: "mail", 3: "line", 4: "webhook", 5: "teams"}[sel]
            if channel in active_alerts:
                active_alerts.remove(channel)
            else:
                active_alerts.append(channel)
            cm.config.setdefault("alerts", {})["active"] = active_alerts
            cm.save()
```

> Renumber the subsequent `elif sel == 5/6/7` edit branches (line token / line target / webhook URL) to `6/7/8` accordingly, since Teams toggle now occupies 5.

- [ ] **Step 4: Add the Teams URL edit branch**

After the webhook-URL edit branch (now `elif sel == 8`), add the Teams URL edit as option 9, mirroring the webhook edit and masking the existing value:

```python
        elif sel == 9:
            current_url = cm.config.get("alerts", {}).get("teams_webhook_url", "")
            masked = current_url[:5] + "..." if current_url else t("not_set")
            new_url = safe_input(
                t("teams_webhook_url_input"), str, allow_cancel=True, hint=masked
            )
            if new_url:
                cm.config.setdefault("alerts", {})["teams_webhook_url"] = new_url
                cm.save()
```

> Match the exact `elif`/branch style used for the webhook edit branch already in the file.

- [ ] **Step 5: Sanity-check the module imports and runs**

Run: `cd /home/harry/rd/illumio-ops && python -c "import src.cli.menus.alert"`
Expected: no import error (syntax/logic compile check). The interactive flow is verified manually.

- [ ] **Step 6: Manual verification (interactive)**

```bash
cd /home/harry/rd/illumio-ops && python illumio-ops.py
```

Navigate Settings > Alerts. Verify:
- A "Toggle Teams Alert" line appears with on/off status reflecting `alerts.active`.
- Toggling it adds/removes `"teams"` from `active` and persists.
- "Edit Teams Workflow Webhook URL" accepts a URL; the hint shows only a 5-char masked prefix, never the full secret URL.

- [ ] **Step 7: Commit**

```bash
cd /home/harry/rd/illumio-ops
git add src/cli/menus/alert.py
git commit -m "feat(cli): add Teams alert toggle + webhook URL edit to alert menu"
```

---

## Final Verification

- [ ] **Run the full Teams + alerts + i18n test scope**

Run: `cd /home/harry/rd/illumio-ops && python -m pytest tests/test_teams_webhook_scheme.py tests/test_teams_redaction.py tests/test_teams_card.py tests/test_alerts_teams.py tests/test_alerts_telegram.py tests/test_webhook_scheme.py tests/test_config_models_alerts.py tests/test_gui_alert_plugins.py -v`
Expected: all PASS.

- [ ] **Run the i18n audit**

Run: `cd /home/harry/rd/illumio-ops && python scripts/audit_i18n_usage.py`
Expected: no new parity/glossary failures for the `teams_*` / `alert_plugin_teams_*` keys.

- [ ] **Confirm secret never leaks (L-12)**

Grep the new code paths to confirm the raw `teams_webhook_url` is never passed to `print`, `logger`, or a returned `target`/`error` except via `redact_webhook_url`:

Run: `cd /home/harry/rd/illumio-ops && grep -n 'teams_webhook_url\|redact_webhook_url\|safe_target' src/alerts/plugins.py`
Expected: every place that surfaces the URL (target field, any print) uses `safe_target` / `redact_webhook_url`; the raw `webhook_url` is used only to build the `urllib.request.Request`.

- [ ] **Confirm backward compatibility**

The four existing channels (`mail`/`line`/`webhook`/`telegram`) are untouched; `AlertOutputPlugin.send` signature is unchanged; `send_alerts` registry dispatch gained `teams` purely via auto-registration. `AlertsSettings` only gained an additive `teams_webhook_url` field with an https validator.

---

## Self-Review Notes (author)

- **Spec coverage:** schema/default → Task 1; redaction (L-12) → Task 2; card builder + template → Task 3; plugin → Task 4; metadata + routing → Task 5; i18n → Task 6; CLI → Task 7; tests → each task + Final Verification. All spec sections (§3-§9) mapped.
- **Secret handling (L-12):** `redact_webhook_url` is unit-tested in isolation (Task 2) and asserted on the plugin's `target`/`error` in success, 4xx, and persisted-dispatch paths (Tasks 4-5). The raw URL is used only on the wire (`Request(webhook_url, ...)`).
- **HTTP mocked:** every plugin/routing test patches `urllib.request.urlopen` — no real network.
- **Type consistency:** `_build_teams_card` returns the `{"type":"message","attachments":[{contentType, content}]}` dict consumed by `TeamsAlertPlugin.send` (json.dumps'd) and asserted in both card tests (Task 3) and plugin tests (Task 4).
- **Placeholders:** none — every code/template/i18n step has concrete content grounded in the actual repo files.
