# Alert Channel: Telegram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. If working in an isolated worktree, it should have been created via the `superpowers:using-git-worktrees` skill.

**Goal:** Add `TelegramAlertPlugin` to the existing `src/alerts/` plugin system so operators can receive HTML-formatted alert digests via Telegram Bot API (single chat, no new pip deps).

**Architecture:** Auto-registering subclass of `AlertOutputPlugin` (same pattern as `LineAlertPlugin` / `MailAlertPlugin`). Config keys live under `alerts.*` next to `line_*`. Message body renders via `render_alert_template("telegram_digest.html.tmpl", …)` reusing `string.Template` + auto-injected `alert_tpl_*` i18n keys. HTTP via stdlib `urllib.request.urlopen` (matches LINE plugin).

**Tech Stack:** Python 3.12, stdlib only (`urllib.request`, `string.Template`, `html.escape`), Pydantic v2 for config validation, existing pytest harness.

**Spec:** `docs/superpowers/specs/2026-05-16-alert-channel-telegram-design.md`

---

## File Surface

| File | Action | LOC est. |
|---|---|---:|
| `src/config_models.py` | modify — add 2 fields to `AlertsSettings` | +2 |
| `config/config.json.example` | modify — add 2 keys under `alerts` | +2 |
| `src/i18n/data/zh_explicit.json` | modify — add 9 i18n keys | +18 |
| `src/alerts/templates/telegram_digest.html.tmpl` | create | ~12 |
| `src/reporter.py` | modify — add `_build_telegram_message` | ~70 |
| `src/alerts/plugins.py` | modify — add `TelegramAlertPlugin` class | ~50 |
| `src/alerts/metadata.py` | modify — register `PLUGIN_METADATA["telegram"]` | ~25 |
| `tests/test_alerts_telegram.py` | create | ~140 |
| `tests/test_gui_alert_plugins.py` | modify — extend metadata assertions | +6 |

Total ≈ 325 LOC, 8 commits.

---

## Task 1: Config schema — add Telegram fields to `AlertsSettings`

**Files:**
- Modify: `src/config_models.py:52-59`
- Test: `tests/test_config_models_alerts.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_models_alerts.py`:

```python
"""AlertsSettings schema must accept Telegram bot/chat config."""
from src.config_models import AlertsSettings


def test_alerts_defaults_include_empty_telegram_fields():
    a = AlertsSettings()
    assert a.telegram_bot_token == ""
    assert a.telegram_chat_id == ""
    # Existing defaults unchanged
    assert a.active == ["mail"]
    assert a.line_target_id == ""


def test_alerts_accepts_telegram_values():
    a = AlertsSettings(
        active=["mail", "telegram"],
        telegram_bot_token="123:abc",
        telegram_chat_id="-1001234567890",
    )
    assert "telegram" in a.active
    assert a.telegram_bot_token == "123:abc"
    assert a.telegram_chat_id == "-1001234567890"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config_models_alerts.py -v`
Expected: FAIL with `AttributeError: 'AlertsSettings' object has no attribute 'telegram_bot_token'`

- [ ] **Step 3: Add fields to `AlertsSettings`**

Edit `src/config_models.py:52-59` — change to:

```python
class AlertsSettings(_Base):
    active: list[str] = Field(default_factory=lambda: ["mail"])
    line_channel_access_token: str = Field(
        default="",
        validation_alias=AliasChoices("line_channel_access_token", "line_token"),
    )
    line_target_id: str = ""
    webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config_models_alerts.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/config_models.py tests/test_config_models_alerts.py
git commit -m "feat(alerts): add telegram_bot_token/chat_id to AlertsSettings"
```

---

## Task 2: `config.json.example` — surface new keys for fresh installs

**Files:**
- Modify: `config/config.json.example`

- [ ] **Step 1: Verify current state**

Run: `python3 -c "import json; c=json.load(open('config/config.json.example')); print(list(c['alerts'].keys()))"`
Expected output: `['active', 'line_channel_access_token', 'line_target_id', 'webhook_url']`

- [ ] **Step 2: Edit `config/config.json.example`**

Find the `"alerts"` block; replace it with:

```json
    "alerts": {
        "active": [
            "mail"
        ],
        "line_channel_access_token": "",
        "line_target_id": "",
        "webhook_url": "",
        "telegram_bot_token": "",
        "telegram_chat_id": ""
    },
```

(Indentation matches surrounding JSON — 4 spaces. Do not change other top-level keys.)

- [ ] **Step 3: Verify JSON is valid + keys present**

Run: `python3 -c "import json; c=json.load(open('config/config.json.example')); print(sorted(c['alerts'].keys()))"`
Expected output: `['active', 'line_channel_access_token', 'line_target_id', 'telegram_bot_token', 'telegram_chat_id', 'webhook_url']`

- [ ] **Step 4: Commit**

```bash
git add config/config.json.example
git commit -m "feat(alerts): seed telegram_bot_token/chat_id in config example"
```

---

## Task 3: i18n keys (en + zh_TW)

**Files:**
- Modify: `src/i18n_en.json` (English source — flat JSON dict, alphabetically sorted)
- Modify: `src/i18n/data/zh_explicit.json` (zh_TW overrides — same shape)

i18n wiring (verified): `src/i18n/engine.py` loads `src/i18n_en.json` as `EN_MESSAGES` and `src/i18n/data/zh_explicit.json` as the zh_TW override layer. `t(key, lang='en')` reads from EN; `t(key, lang='zh_TW')` reads from zh layer with EN fallback. **Both files must contain every new key.**

- [ ] **Step 1: Add 9 keys to `src/i18n_en.json`**

Open `src/i18n_en.json` and slot these entries into alphabetical position:

```jsonc
  "alert_plugin_field_telegram_bot_token": "Bot Token",
  "alert_plugin_field_telegram_chat_id": "Chat ID",
  "alert_plugin_telegram_description": "Push triaged alert summaries to a Telegram Bot chat.",
  "alert_plugin_telegram_display_name": "Telegram Bot",
  "alert_tpl_telegram_title": "Illumio Monitor Alerts",
  "telegram_alert_failed": "Telegram alert dispatch failed (status={status}): {error}",
  "telegram_alert_sent": "Telegram alert sent.",
  "telegram_config_missing": "Telegram alert skipped: bot token or chat id not configured.",
  "telegram_truncated_footer": "… and {more} more (truncated to fit Telegram's 4096-char limit)",
```

- [ ] **Step 2: Add 9 keys to `src/i18n/data/zh_explicit.json`**

Slot the zh_TW versions into alphabetical position:

```jsonc
  "alert_plugin_field_telegram_bot_token": "Bot Token",
  "alert_plugin_field_telegram_chat_id": "Chat ID",
  "alert_plugin_telegram_description": "將精煉後的警示推送至 Telegram Bot 對話。",
  "alert_plugin_telegram_display_name": "Telegram Bot",
  "alert_tpl_telegram_title": "Illumio 監控警示",
  "telegram_alert_failed": "Telegram 告警送出失敗（status={status}）：{error}",
  "telegram_alert_sent": "Telegram 告警已送出。",
  "telegram_config_missing": "Telegram 告警略過：尚未設定 Bot Token 或 Chat ID。",
  "telegram_truncated_footer": "… 還有 {more} 條訊息（已截斷以符合 Telegram 4096 字元上限）",
```

(Per project glossary, `Bot Token` / `Chat ID` stay English in both locales.)

- [ ] **Step 3: Validate both JSON files**

Run:
```bash
python3 -c "
import json
for path in ('src/i18n_en.json', 'src/i18n/data/zh_explicit.json'):
    d = json.load(open(path))
    tg = sorted(k for k in d if 'telegram' in k)
    print(f'{path}  count={len(tg)}  keys={tg}')
    assert len(tg) == 9, f'expected 9 telegram-related keys in {path}, got {len(tg)}'
"
```
Expected: both paths show `count=9` with the same 9 keys.

- [ ] **Step 4: Resolve check via `t()`**

Run:
```bash
python3 -c "
from src.i18n import t
keys = ['alert_plugin_telegram_display_name', 'telegram_alert_sent',
        'telegram_config_missing', 'alert_tpl_telegram_title',
        'telegram_truncated_footer']
for k in keys:
    en = t(k, lang='en')
    zh = t(k, lang='zh_TW')
    assert en and en != k, f'en missing for {k}: got {en!r}'
    assert zh and zh != k, f'zh missing for {k}: got {zh!r}'
    assert en != zh, f'{k}: en and zh equal — zh override probably missing'
    print(f'{k}  en={en!r}  zh={zh!r}')
"
```
Expected: 5 lines printed, no AssertionError.

- [ ] **Step 5: Commit**

```bash
git add src/i18n_en.json src/i18n/data/zh_explicit.json
git commit -m "feat(alerts): add 9 i18n keys for Telegram plugin (en + zh_TW)"
```

---

## Task 4: Digest template

**Files:**
- Create: `src/alerts/templates/telegram_digest.html.tmpl`

- [ ] **Step 1: Write the failing test**

Create `tests/test_alerts_telegram.py` (first test only — more added in Task 6):

```python
"""TelegramAlertPlugin + digest template tests."""
from src.alerts import render_alert_template


def test_telegram_digest_template_renders_sections():
    rendered = render_alert_template(
        "telegram_digest.html.tmpl",
        subject="Test Alert",
        generated_at="2026-05-16 14:23 (UTC+8)",
        total_issues=3,
        health_count=1,
        event_count=2,
        traffic_count=0,
        metric_count=0,
        health_section="<b>health item</b>",
        event_section="<b>event item</b>",
        traffic_section="",
        metric_section="",
    )
    # Title from auto-injected alert_tpl_telegram_title
    assert "Illumio" in rendered
    assert "Test Alert" in rendered
    assert "<b>health item</b>" in rendered
    assert "<b>event item</b>" in rendered
    # No literal $placeholder leakage
    assert "$" not in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_alerts_telegram.py::test_telegram_digest_template_renders_sections -v`
Expected: FAIL with `FileNotFoundError: …/templates/telegram_digest.html.tmpl`

- [ ] **Step 3: Create the template**

Create `src/alerts/templates/telegram_digest.html.tmpl` with this exact content:

```
<b>$alert_tpl_telegram_title</b>

$alert_tpl_subject：$subject
$alert_tpl_generated_at：$generated_at
$alert_tpl_total_issues：$total_issues
$alert_tpl_health_alert：$health_count  $alert_tpl_security_events：$event_count
$alert_tpl_traffic_alert：$traffic_count  $alert_tpl_metric_alert：$metric_count
$health_section
$event_section
$traffic_section
$metric_section
$alert_tpl_see_web_for_details
```

(Mirror of `line_digest.txt.tmpl` line-for-line, with `<b>` wrapping the title. The auto-injection machinery in `template_utils.py` already covers all `$alert_tpl_*` keys.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_alerts_telegram.py::test_telegram_digest_template_renders_sections -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/alerts/templates/telegram_digest.html.tmpl tests/test_alerts_telegram.py
git commit -m "feat(alerts): add telegram_digest.html.tmpl"
```

---

## Task 5: `Reporter._build_telegram_message`

**Files:**
- Modify: `src/reporter.py` (add new method near `_build_line_message` at line ~880)
- Test: `tests/test_alerts_telegram.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_alerts_telegram.py`:

```python
import html as _html
from unittest.mock import MagicMock


def _make_reporter_with_alerts(monkeypatch):
    """Build a minimal Reporter with one health alert + one event alert queued."""
    from src.config import ConfigManager
    from src.reporter import Reporter

    cm = MagicMock(spec=ConfigManager)
    cm.config = {
        "alerts": {"active": ["telegram"], "telegram_bot_token": "T", "telegram_chat_id": "C"},
        "settings": {"language": "en"},
        "gui_base_url": "",
    }
    r = Reporter(cm)
    r.add_health_alert({
        "rule": "API Health",
        "status": "503",
        "time": "2026-05-16 06:00",
        "details": "PCE unreachable",
    })
    r.event_alerts = []  # default
    r.traffic_alerts = []
    r.metric_alerts = []
    return r


def test_build_telegram_message_includes_subject_and_alert(monkeypatch):
    r = _make_reporter_with_alerts(monkeypatch)
    body = r._build_telegram_message("Daily Digest")
    assert "Daily Digest" in body
    assert "API Health" in body
    assert "<b>" in body  # title is bold


def test_build_telegram_message_escapes_html_in_dynamic_fields(monkeypatch):
    r = _make_reporter_with_alerts(monkeypatch)
    r.health_alerts[0]["details"] = "<script>alert(1)</script>"
    body = r._build_telegram_message("S")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_build_telegram_message_truncates_above_3500_chars(monkeypatch):
    r = _make_reporter_with_alerts(monkeypatch)
    # Stuff in 50 fat health alerts
    for i in range(50):
        r.add_health_alert({
            "rule": f"r{i}",
            "status": "error",
            "time": "t",
            "details": "X" * 200,
        })
    body = r._build_telegram_message("Bulk")
    assert len(body) <= 3500
    # Footer marks truncation
    assert "more" in body.lower() or "…" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_alerts_telegram.py -v -k "telegram_message"`
Expected: 3 FAIL with `AttributeError: 'Reporter' object has no attribute '_build_telegram_message'`

- [ ] **Step 3: Add the method to `src/reporter.py`**

Locate the end of `_build_line_message` (currently ends around line 915 where it does `return render_alert_template("line_digest.txt.tmpl", …)`). Immediately after that method, add:

```python
    def _build_telegram_message(self, subj: str) -> str:
        """Build an HTML-formatted alert digest for Telegram (parse_mode=HTML).

        Mirrors _build_line_message's section structure but produces Telegram-flavored
        HTML — <b>, <code>, <a href> — and escapes every dynamic value with
        html.escape(value, quote=False). Output is capped at 3500 chars (Telegram's
        hard limit is 4096) with a translated footer announcing how many entries got
        truncated.
        """
        import html as _html

        def esc(value) -> str:
            return _html.escape(self._compact_text(value), quote=False)

        records: str = t("alert_field_records")

        def section_header(title: str, count: int) -> str:
            return f"\n<b>{_html.escape(title)}</b> · {count} {records}"

        total_issues = (
            len(self.health_alerts) + len(self.event_alerts)
            + len(self.traffic_alerts) + len(self.metric_alerts)
        )
        time_lbl = t("alert_field_time")
        summary_lbl = t("alert_field_summary")
        sev_crit = t("alert_sev_critical")
        sev_warn = t("alert_sev_warning")

        health_lines, kept_health = [], 0
        if self.health_alerts:
            health_lines.append(section_header(t("alert_sec_health"), len(self.health_alerts)))
            for idx, alert in enumerate(self.health_alerts, start=1):
                status = self._compact_text(alert.get("status", ""))
                label = sev_crit if status.lower() in {"503", "error", "critical"} else sev_warn
                health_lines.append(f"{idx}. [<b>{_html.escape(label)}</b>] {esc(alert.get('rule', t('alert_field_health_rule_fallback')))}")
                health_lines.append(f"{time_lbl}：{esc(alert.get('time', ''))}")
                health_lines.append(f"{summary_lbl}：{esc(alert.get('details', ''))}")
                health_lines.append("")
                kept_health = idx

        event_lines = []
        if self.event_alerts:
            event_lines.append(section_header(t("alert_sec_event"), len(self.event_alerts)))
            for payload in self._build_all_event_alert_payloads():
                first = payload["events"][0] if payload["events"] else {}
                event_lines.append(f"[<b>{_html.escape(payload['severity_label'])}</b>] {esc(payload['rule'])}")
                if first.get("event_type"):
                    event_lines.append(f"<code>{_html.escape(first['event_type'])}</code>")
                if first.get("pce_link"):
                    event_lines.append(f"<a href=\"{_html.escape(first['pce_link'], quote=True)}\">PCE</a>")
                event_lines.append("")

        traffic_lines = []
        if self.traffic_alerts:
            traffic_lines.append(section_header(t("alert_sec_traffic"), len(self.traffic_alerts)))
            for alert in self.traffic_alerts:
                traffic_lines.append(f"• {esc(alert.get('summary', ''))}")
            traffic_lines.append("")

        metric_lines = []
        if self.metric_alerts:
            metric_lines.append(section_header(t("alert_sec_metric"), len(self.metric_alerts)))
            for alert in self.metric_alerts:
                metric_lines.append(f"• {esc(alert.get('summary', ''))}")
            metric_lines.append("")

        body = render_alert_template(
            "telegram_digest.html.tmpl",
            subject=_html.escape(subj),
            generated_at=_html.escape(self._now_str()),
            total_issues=total_issues,
            health_count=len(self.health_alerts),
            event_count=len(self.event_alerts),
            traffic_count=len(self.traffic_alerts),
            metric_count=len(self.metric_alerts),
            health_section="\n".join(health_lines),
            event_section="\n".join(event_lines),
            traffic_section="\n".join(traffic_lines),
            metric_section="\n".join(metric_lines),
        )

        if len(body) > 3500:
            cut = body[:3300].rstrip()
            more = total_issues - kept_health
            footer = t("telegram_truncated_footer").format(more=max(more, 0))
            body = f"{cut}\n\n{footer}"
        return body
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_alerts_telegram.py -v -k "telegram_message"`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/reporter.py tests/test_alerts_telegram.py
git commit -m "feat(alerts): Reporter._build_telegram_message — HTML digest with 3500-char cap"
```

---

## Task 6: `TelegramAlertPlugin` class

**Files:**
- Modify: `src/alerts/plugins.py` (append new class after `WebhookAlertPlugin`)
- Test: `tests/test_alerts_telegram.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_alerts_telegram.py`:

```python
import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from src.alerts import build_output_plugin, get_output_registry


def _make_cm(token="T", chat="C"):
    cm = MagicMock()
    cm.config = {
        "alerts": {"telegram_bot_token": token, "telegram_chat_id": chat},
        "settings": {"language": "en"},
    }
    return cm


def _reporter_stub():
    r = MagicMock()
    r._build_telegram_message.return_value = "<b>hi</b>"
    return r


def test_telegram_plugin_registered():
    assert "telegram" in get_output_registry()


def test_telegram_plugin_skipped_when_unconfigured():
    plug = build_output_plugin("telegram", _make_cm(token="", chat=""))
    res = plug.send(_reporter_stub(), "subj")
    assert res == {"channel": "telegram", "status": "skipped", "target": "", "error": "missing configuration"}


def test_telegram_plugin_posts_payload_on_success():
    plug = build_output_plugin("telegram", _make_cm())
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda self, *a: False
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        res = plug.send(_reporter_stub(), "subj")
    assert res["channel"] == "telegram"
    assert res["status"] == "success"
    assert res["target"] == "C"
    # Inspect outgoing request
    req = mock_open.call_args[0][0]
    assert req.full_url == "https://api.telegram.org/botT/sendMessage"
    payload = json.loads(req.data.decode())
    assert payload["chat_id"] == "C"
    assert payload["text"] == "<b>hi</b>"
    assert payload["parse_mode"] == "HTML"
    assert payload["disable_web_page_preview"] is True


def test_telegram_plugin_fails_on_4xx():
    plug = build_output_plugin("telegram", _make_cm())
    err = urllib.error.HTTPError("https://x", 400, "Bad Request", {}, MagicMock(read=lambda: b'{"description":"bad"}'))
    with patch("urllib.request.urlopen", side_effect=err):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert res["target"] == "C"
    assert "400" in res["error"] or "Bad Request" in res["error"]


def test_telegram_plugin_fails_on_url_error():
    plug = build_output_plugin("telegram", _make_cm())
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        res = plug.send(_reporter_stub(), "subj")
    assert res["status"] == "failed"
    assert "timeout" in res["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_alerts_telegram.py -v -k "telegram_plugin or telegram_registered"`
Expected: 5 FAIL — `"telegram" not in registry` or `KeyError: 'telegram'` from `build_output_plugin`

- [ ] **Step 3: Add `TelegramAlertPlugin` class**

Open `src/alerts/plugins.py`. After the closing line of `WebhookAlertPlugin` (currently the last class), append:

```python
class TelegramAlertPlugin(AlertOutputPlugin):
    name = "telegram"

    def send(self, reporter, subject: str, *, lang: str = "en") -> dict:
        alerts_cfg = self.cm.config.get("alerts", {})
        token = alerts_cfg.get("telegram_bot_token", "")
        chat_id = alerts_cfg.get("telegram_chat_id", "")
        if not token or not chat_id:
            print(f"{Colors.WARNING}{t('telegram_config_missing', lang=lang)}{Colors.ENDC}")
            return {"channel": "telegram", "status": "skipped", "target": chat_id or "", "error": "missing configuration"}

        text = reporter._build_telegram_message(subject)
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    print(f"{Colors.GREEN}{t('telegram_alert_sent', lang=lang)}{Colors.ENDC}")
                    return {"channel": "telegram", "status": "success", "target": chat_id}
                print(f"{Colors.FAIL}{t('telegram_alert_failed', lang=lang, error='', status=response.status)}{Colors.ENDC}")
                return {"channel": "telegram", "status": "failed", "target": chat_id, "error": f"status={response.status}"}
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8")
            except Exception:
                error_body = ""
            print(f"{Colors.FAIL}{t('telegram_alert_failed', lang=lang, error=f'{exc} - {error_body}', status=exc.code)}{Colors.ENDC}")
            return {"channel": "telegram", "status": "failed", "target": chat_id, "error": f"{exc} - {error_body}"}
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"{Colors.FAIL}{t('telegram_alert_failed', lang=lang, error=f'Connection Error/Timeout: {exc}', status='')}{Colors.ENDC}")
            return {"channel": "telegram", "status": "failed", "target": chat_id, "error": f"Connection Error/Timeout: {exc}"}
        except Exception as exc:
            print(f"{Colors.FAIL}{t('telegram_alert_failed', lang=lang, error=exc, status='')}{Colors.ENDC}")
            return {"channel": "telegram", "status": "failed", "target": chat_id, "error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_alerts_telegram.py -v`
Expected: 8 passed (3 from earlier tasks + 5 from this one)

- [ ] **Step 5: Commit**

```bash
git add src/alerts/plugins.py tests/test_alerts_telegram.py
git commit -m "feat(alerts): TelegramAlertPlugin — HTML parse_mode + stdlib urllib"
```

---

## Task 7: PLUGIN_METADATA registration (GUI rendering)

**Files:**
- Modify: `src/alerts/metadata.py:67-150` — add `"telegram"` entry

- [ ] **Step 1: Write the failing test**

Append to `tests/test_alerts_telegram.py`:

```python
def test_telegram_plugin_metadata_present():
    from src.alerts.metadata import PLUGIN_METADATA
    assert "telegram" in PLUGIN_METADATA
    meta = PLUGIN_METADATA["telegram"]
    assert meta.display_name == "Telegram Bot"
    assert "alerts.telegram_bot_token" in meta.fields
    assert "alerts.telegram_chat_id" in meta.fields
    assert meta.fields["alerts.telegram_bot_token"].secret is True
    assert meta.fields["alerts.telegram_bot_token"].required is True
    assert meta.fields["alerts.telegram_chat_id"].required is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_alerts_telegram.py::test_telegram_plugin_metadata_present -v`
Expected: FAIL with `KeyError: 'telegram'`

- [ ] **Step 3: Add the metadata entry**

Edit `src/alerts/metadata.py`. Inside the `PLUGIN_METADATA: dict[str, PluginMeta] = { … }` literal, after the `"webhook"` entry's closing `}`, add:

```python
    "telegram": PluginMeta(
        name="telegram",
        display_name="Telegram Bot",
        display_name_key="alert_plugin_telegram_display_name",
        description="Push triaged alert summaries to a Telegram Bot chat.",
        description_key="alert_plugin_telegram_description",
        fields={
            "alerts.telegram_bot_token": FieldMeta(
                label="Bot Token",
                label_key="alert_plugin_field_telegram_bot_token",
                required=True, secret=True,
                placeholder="123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            ),
            "alerts.telegram_chat_id": FieldMeta(
                label="Chat ID",
                label_key="alert_plugin_field_telegram_chat_id",
                required=True,
                placeholder="-1001234567890 or 1284061527",
            ),
        },
    ),
```

(Mind the trailing comma after the dict-entry; preserve the closing `}` of `PLUGIN_METADATA`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_alerts_telegram.py::test_telegram_plugin_metadata_present -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/alerts/metadata.py tests/test_alerts_telegram.py
git commit -m "feat(alerts): register Telegram in PLUGIN_METADATA for GUI rendering"
```

---

## Task 8: GUI metadata endpoint test

**Files:**
- Modify: `tests/test_gui_alert_plugins.py:21-34`

- [ ] **Step 1: Add assertions to the existing endpoint test**

Edit `tests/test_gui_alert_plugins.py`. Inside `test_alert_plugins_endpoint_returns_metadata`, after the existing LINE assertion (`assert response.json["plugins"]["line"]["fields"][0]["secret"] is True`), append:

```python
    # Telegram plugin metadata exposed identically to LINE
    assert "telegram" in response.json["plugins"]
    tg = response.json["plugins"]["telegram"]
    assert tg["display_name"] == "Telegram Bot"
    token_field = next(f for f in tg["fields"] if f["key"] == "alerts.telegram_bot_token")
    assert token_field["secret"] is True
    assert token_field["required"] is True
    chat_field = next(f for f in tg["fields"] if f["key"] == "alerts.telegram_chat_id")
    assert chat_field["required"] is True
    assert chat_field["secret"] is False
```

- [ ] **Step 2: Run test**

Run: `python3 -m pytest tests/test_gui_alert_plugins.py::test_alert_plugins_endpoint_returns_metadata -v`
Expected: PASS (the GUI endpoint reads `PLUGIN_METADATA` dynamically — no GUI code change needed)

- [ ] **Step 3: Commit**

```bash
git add tests/test_gui_alert_plugins.py
git commit -m "test(gui): assert Telegram plugin metadata exposed via /api/alert-plugins"
```

---

## Task 9: End-to-end dispatch smoke test + final sweep

**Files:**
- Modify: `tests/test_alerts_telegram.py` (one more test)
- Verify: full suite + manual config drill

- [ ] **Step 1: Write the dispatch integration test**

Append to `tests/test_alerts_telegram.py`:

```python
def test_send_alerts_routes_through_telegram_plugin(monkeypatch):
    """Reporter.send_alerts must route an active telegram channel through TelegramAlertPlugin."""
    from src.reporter import Reporter
    cm = MagicMock()
    cm.config = {
        "alerts": {"active": ["telegram"], "telegram_bot_token": "T", "telegram_chat_id": "C"},
        "settings": {"language": "en"},
        "gui_base_url": "",
    }
    r = Reporter(cm)
    r.add_health_alert({"rule": "X", "status": "503", "time": "t", "details": "d"})
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda self, *a: False
    with patch("urllib.request.urlopen", return_value=fake_resp), \
         patch("src.events.persist_dispatch_results"):
        results = r.send_alerts(force_test=False)
    chans = [x["channel"] for x in results]
    assert "telegram" in chans
    tg = next(x for x in results if x["channel"] == "telegram")
    assert tg["status"] == "success"
    assert tg["target"] == "C"
```

- [ ] **Step 2: Run the full Telegram test set**

Run: `python3 -m pytest tests/test_alerts_telegram.py -v`
Expected: all green (at least 10 tests).

- [ ] **Step 3: Run impacted test files**

Run:
```bash
python3 -m pytest tests/test_alerts_telegram.py tests/test_gui_alert_plugins.py \
                  tests/test_config_models_alerts.py tests/test_reporter_email_multipart.py \
                  -v --tb=short
```
Expected: all green.

- [ ] **Step 4: Verify config example loads via ConfigManager**

Run:
```bash
python3 -c "
from src.config import ConfigManager
import shutil, tempfile, os
src = 'config/config.json.example'
tmp = tempfile.mkdtemp()
dst = os.path.join(tmp, 'config.json')
shutil.copy(src, dst)
cm = ConfigManager(config_path=dst)
print('alerts.active        =', cm.config['alerts']['active'])
print('telegram_bot_token   =', repr(cm.config['alerts']['telegram_bot_token']))
print('telegram_chat_id     =', repr(cm.config['alerts']['telegram_chat_id']))
shutil.rmtree(tmp)
"
```
Expected:
```
alerts.active        = ['mail']
telegram_bot_token   = ''
telegram_chat_id     = ''
```

- [ ] **Step 5: Final commit**

```bash
git add tests/test_alerts_telegram.py
git commit -m "test(alerts): end-to-end dispatch routes through TelegramAlertPlugin"
```

---

## Verification Checklist (run after Task 9)

- [ ] `python3 -m pytest tests/test_alerts_telegram.py tests/test_config_models_alerts.py tests/test_gui_alert_plugins.py -v` → all green
- [ ] `python3 -c "from src.alerts import get_output_registry as g; print(sorted(g().keys()))"` → contains `'telegram'`
- [ ] `python3 -c "from src.alerts.metadata import PLUGIN_METADATA; print(sorted(PLUGIN_METADATA))"` → contains `'telegram'`
- [ ] `grep -r 'telegram' src/i18n/data/zh_explicit.json | wc -l` → at least 9
- [ ] Manual smoke (optional, requires real bot): set `alerts.active = ["telegram"]`, real `telegram_bot_token` + `telegram_chat_id` in dev `config.json`, run `python3 illumio-ops.py monitor --once` against a PCE — expect a digest in the chat.

---

## Out-of-Plan / Phase 2 Reminders (DO NOT IMPLEMENT NOW)

- WhatsApp Cloud API plugin (deferred — see spec §7)
- Multi-chat fan-out (`telegram_chat_ids`)
- Forum-topic routing (`message_thread_id`)
- `parse_mode=null` fallback retry on `Bad Request: can't parse entities` (defensive; add only if real-world failures observed)
