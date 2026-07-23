"""Built-in alert output plugins."""

from __future__ import annotations

import json
import os
import smtplib
import socket
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.i18n import t
from src.utils import Colors

from .base import AlertOutputPlugin


def redact_webhook_url(url: str) -> str:
    """Redact a Teams/Power-Automate webhook URL for safe logging/storage.

    The Teams workflow webhook embeds an invocation secret in its query string
    (``...&sig=<SECRET>``) and identifiers in its path (``/workflows/<id>/...``).
    Per README L-12 (Telegram token leaked via proxy access logs), channel
    secrets must never reach logs, debug output, or persisted dispatch results.
    Keeps only ``scheme://host[:port]`` (userinfo stripped) and elides the rest.
    Returns the ASCII marker ``...`` for cross-platform (Windows console) safety.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        if parts.scheme and parts.hostname:
            host = parts.hostname
            port = f":{parts.port}" if parts.port else ""
            return f"{parts.scheme}://{host}{port}/..."
    except Exception:
        pass
    return "..."


class MailAlertPlugin(AlertOutputPlugin):
    name = "mail"

    def send(self, reporter, subject: str, *, lang: str = "en") -> dict:
        cfg = self.cm.config["email"]
        if not cfg["recipients"]:
            print(f"{Colors.WARNING}{t('no_recipients', lang=lang)}{Colors.ENDC}")
            return {"channel": "mail", "status": "skipped", "target": "", "error": "no recipients"}

        body = reporter._build_mail_html(subject)
        msg = MIMEMultipart('alternative')
        msg["Subject"] = subject
        msg["From"] = cfg["sender"]
        msg["To"] = ",".join(cfg["recipients"])
        # Plain text fallback FIRST (RFC 2046: client picks last that it can render)
        plain_body = reporter._build_mail_plain(subject)
        msg.attach(MIMEText(plain_body, "plain", _charset='utf-8'))
        msg.attach(MIMEText(body, "html", _charset='utf-8'))
        try:
            smtp_conf = self.cm.config.get("smtp", {})
            host = smtp_conf.get("host", "localhost")
            port = int(smtp_conf.get("port", 25))

            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                if smtp_conf.get("enable_tls"):
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()

                if smtp_conf.get("enable_auth"):
                    # Prefer env var over config file to avoid storing credentials in plaintext
                    smtp_password = os.environ.get("ILLUMIO_SMTP_PASSWORD") or smtp_conf.get("password", "")
                    smtp.login(smtp_conf.get("user"), smtp_password)

                smtp.sendmail(cfg["sender"], cfg["recipients"], msg.as_string())

            print(f"{Colors.GREEN}{t('mail_sent', lang=lang, host=host, port=port)}{Colors.ENDC}")
            return {"channel": "mail", "status": "success", "target": ",".join(cfg["recipients"])}
        except smtplib.SMTPAuthenticationError as exc:
            print(f"{Colors.FAIL}{t('mail_failed', lang=lang, error=exc)}{Colors.ENDC}")
            from loguru import logger
            logger.error(f"SMTP auth failed (config error, not retrying): {exc}")
            return {"channel": "mail", "status": "failed", "target": ",".join(cfg.get("recipients", [])), "error": str(exc)}
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ConnectionError, OSError, socket.timeout) as exc:
            print(f"{Colors.FAIL}{t('mail_failed', lang=lang, error=exc)}{Colors.ENDC}")
            from loguru import logger
            logger.warning(f"SMTP transient failure connecting to {host}:{port}: {exc}")
            return {"channel": "mail", "status": "failed", "target": ",".join(cfg.get("recipients", [])), "error": str(exc)}
        except smtplib.SMTPException as exc:
            print(f"{Colors.FAIL}{t('mail_failed', lang=lang, error=exc)}{Colors.ENDC}")
            from loguru import logger
            logger.error(f"SMTP error ({host}:{port}): {exc}")
            return {"channel": "mail", "status": "failed", "target": ",".join(cfg.get("recipients", [])), "error": str(exc)}

class LineAlertPlugin(AlertOutputPlugin):
    name = "line"

    def __init__(self, config_manager):
        super().__init__(config_manager)
        self._consecutive_failures: int = 0
        self._cooldown_until: float = 0.0
        self._last_cooldown_log_at: float = 0.0

    def _maybe_log_cooldown(self, target_id: str) -> None:
        """Emit a cooldown-skip warning at most once per 60 seconds."""
        now = time.monotonic()
        if now - self._last_cooldown_log_at >= 60:
            remaining = max(0.0, self._cooldown_until - now)
            print(
                f"{Colors.WARNING}LINE alert channel in cooldown — skipping send"
                f" ({remaining:.0f}s remaining){Colors.ENDC}"
            )
            self._last_cooldown_log_at = now

    def send(self, reporter, subject: str, *, lang: str = "en") -> dict:
        token = self.cm.config.get("alerts", {}).get("line_channel_access_token", "")
        target_id = self.cm.config.get("alerts", {}).get("line_target_id", "")
        if not token or not target_id:
            print(f"{Colors.WARNING}{t('line_config_missing', lang=lang)}{Colors.ENDC}")
            return {"channel": "line", "status": "skipped", "target": target_id or "", "error": "missing configuration"}

        if time.monotonic() < self._cooldown_until:
            self._maybe_log_cooldown(target_id)
            # skipped 而非 failed：自我冷卻是暫時不可用，不得消耗 DLQ 重試
            # 額度（2026-07-24 審查 B2——failed 會在冷卻窗內燒完 3 次而丟棄）
            return {"channel": "line", "status": "skipped", "target": target_id, "error": "channel cooldown active"}

        # Cooldown has expired (or was never set): reset counter for a fresh 3-strike window
        if self._cooldown_until > 0 and self._consecutive_failures >= 3:
            self._consecutive_failures = 0
            self._cooldown_until = 0.0

        message_text = reporter._build_line_message(subject)
        payload = {
            "to": target_id,
            "messages": [{"type": "text", "text": message_text}],
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            req = urllib.request.Request(
                "https://api.line.me/v2/bot/message/push",
                data=data,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    self._consecutive_failures = 0
                    print(f"{Colors.GREEN}{t('line_alert_sent', lang=lang)}{Colors.ENDC}")
                    return {"channel": "line", "status": "success", "target": target_id}
                self._consecutive_failures += 1
                if self._consecutive_failures >= 3:
                    self._cooldown_until = time.monotonic() + 300
                    print(f"{Colors.WARNING}LINE plugin: 3 consecutive failures — cooling down for 5 min{Colors.ENDC}")
                print(f"{Colors.FAIL}{t('line_alert_failed', lang=lang, error='', status=response.status)}{Colors.ENDC}")
                return {"channel": "line", "status": "failed", "target": target_id, "error": f"status={response.status}"}
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8")
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._cooldown_until = time.monotonic() + 300
                print(f"{Colors.WARNING}LINE plugin: 3 consecutive failures — cooling down for 5 min{Colors.ENDC}")
            print(f"{Colors.FAIL}{t('line_alert_failed', lang=lang, error=f'{exc} - {error_body}', status=exc.code)}{Colors.ENDC}")
            return {"channel": "line", "status": "failed", "target": target_id, "error": f"{exc} - {error_body}"}
        except Exception as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._cooldown_until = time.monotonic() + 300
                print(f"{Colors.WARNING}LINE plugin: 3 consecutive failures — cooling down for 5 min{Colors.ENDC}")
            print(f"{Colors.FAIL}{t('line_alert_failed', lang=lang, error=exc, status='')}{Colors.ENDC}")
            return {"channel": "line", "status": "failed", "target": target_id, "error": str(exc)}

class WebhookAlertPlugin(AlertOutputPlugin):
    name = "webhook"

    def send(self, reporter, subject: str, *, lang: str = "en") -> dict:
        webhook_url = self.cm.config.get("alerts", {}).get("webhook_url", "")
        if not webhook_url:
            print(f"{Colors.WARNING}{t('webhook_url_missing', lang=lang)}{Colors.ENDC}")
            return {"channel": "webhook", "status": "skipped", "target": "", "error": "missing configuration"}

        # Generic webhook URLs (Slack/Discord/incoming connectors) embed a secret
        # token in the path/query; it must never reach target/logs or state.json
        # (README L-12), so report a redacted target everywhere. Keep the real
        # webhook_url only for the actual urlopen() POST below.
        safe_target = redact_webhook_url(webhook_url)

        payload = reporter._build_webhook_payload(subject)
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        try:
            req = urllib.request.Request(webhook_url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status in [200, 201, 202, 204]:
                    print(f"{Colors.GREEN}{t('webhook_alert_sent', lang=lang)}{Colors.ENDC}")
                    return {"channel": "webhook", "status": "success", "target": safe_target}
                print(f"{Colors.FAIL}{t('webhook_alert_failed', lang=lang, error='', status=response.status)}{Colors.ENDC}")
                return {"channel": "webhook", "status": "failed", "target": safe_target, "error": f"status={response.status}"}
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8")
            except Exception:
                error_body = "Could not read error body"
            print(f"{Colors.FAIL}{t('webhook_alert_failed', lang=lang, error=f'{exc} - {error_body}', status=exc.code)}{Colors.ENDC}")
            return {"channel": "webhook", "status": "failed", "target": safe_target, "error": f"{exc} - {error_body}"}
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"{Colors.FAIL}{t('webhook_alert_failed', lang=lang, error=f'Connection Error/Timeout: {exc}', status='')}{Colors.ENDC}")
            return {"channel": "webhook", "status": "failed", "target": safe_target, "error": f"Connection Error/Timeout: {exc}"}
        except Exception as exc:
            print(f"{Colors.FAIL}{t('webhook_alert_failed', lang=lang, error=exc, status='')}{Colors.ENDC}")
            return {"channel": "webhook", "status": "failed", "target": safe_target, "error": str(exc)}


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
