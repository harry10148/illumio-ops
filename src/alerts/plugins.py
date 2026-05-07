"""Built-in alert output plugins."""

from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.i18n import t
from src.utils import Colors

from .base import AlertOutputPlugin

class MailAlertPlugin(AlertOutputPlugin):
    name = "mail"

    def send(self, reporter, subject: str) -> dict:
        cfg = self.cm.config["email"]
        if not cfg["recipients"]:
            print(f"{Colors.WARNING}{t('no_recipients')}{Colors.ENDC}")
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

            smtp = smtplib.SMTP(host, port)
            smtp.ehlo()
            if smtp_conf.get("enable_tls"):
                smtp.starttls()
                smtp.ehlo()

            if smtp_conf.get("enable_auth"):
                # Prefer env var over config file to avoid storing credentials in plaintext
                smtp_password = os.environ.get("ILLUMIO_SMTP_PASSWORD") or smtp_conf.get("password", "")
                smtp.login(smtp_conf.get("user"), smtp_password)

            smtp.sendmail(cfg["sender"], cfg["recipients"], msg.as_string())
            smtp.quit()
            print(f"{Colors.GREEN}{t('mail_sent', host=host, port=port)}{Colors.ENDC}")
            return {"channel": "mail", "status": "success", "target": ",".join(cfg["recipients"])}
        except Exception as exc:
            print(f"{Colors.FAIL}{t('mail_failed', error=exc)}{Colors.ENDC}")
            return {"channel": "mail", "status": "failed", "target": ",".join(cfg.get("recipients", [])), "error": str(exc)}

class LineAlertPlugin(AlertOutputPlugin):
    name = "line"

    def send(self, reporter, subject: str) -> dict:
        token = self.cm.config.get("alerts", {}).get("line_channel_access_token", "")
        target_id = self.cm.config.get("alerts", {}).get("line_target_id", "")
        if not token or not target_id:
            print(f"{Colors.WARNING}{t('line_config_missing')}{Colors.ENDC}")
            return {"channel": "line", "status": "skipped", "target": target_id or "", "error": "missing configuration"}

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
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    print(f"{Colors.GREEN}{t('line_alert_sent')}{Colors.ENDC}")
                    return {"channel": "line", "status": "success", "target": target_id}
                print(f"{Colors.FAIL}{t('line_alert_failed', error='', status=response.status)}{Colors.ENDC}")
                return {"channel": "line", "status": "failed", "target": target_id, "error": f"status={response.status}"}
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8")
            print(f"{Colors.FAIL}{t('line_alert_failed', error=f'{exc} - {error_body}', status=exc.code)}{Colors.ENDC}")
            return {"channel": "line", "status": "failed", "target": target_id, "error": f"{exc} - {error_body}"}
        except Exception as exc:
            print(f"{Colors.FAIL}{t('line_alert_failed', error=exc, status='')}{Colors.ENDC}")
            return {"channel": "line", "status": "failed", "target": target_id, "error": str(exc)}

class WebhookAlertPlugin(AlertOutputPlugin):
    name = "webhook"

    def send(self, reporter, subject: str) -> dict:
        webhook_url = self.cm.config.get("alerts", {}).get("webhook_url", "")
        if not webhook_url:
            print(f"{Colors.WARNING}{t('webhook_url_missing')}{Colors.ENDC}")
            return {"channel": "webhook", "status": "skipped", "target": "", "error": "missing configuration"}

        payload = reporter._build_webhook_payload(subject)
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        try:
            req = urllib.request.Request(webhook_url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status in [200, 201, 202, 204]:
                    print(f"{Colors.GREEN}{t('webhook_alert_sent')}{Colors.ENDC}")
                    return {"channel": "webhook", "status": "success", "target": webhook_url}
                print(f"{Colors.FAIL}{t('webhook_alert_failed', error='', status=response.status)}{Colors.ENDC}")
                return {"channel": "webhook", "status": "failed", "target": webhook_url, "error": f"status={response.status}"}
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8")
            except Exception:
                error_body = "Could not read error body"
            print(f"{Colors.FAIL}{t('webhook_alert_failed', error=f'{exc} - {error_body}', status=exc.code)}{Colors.ENDC}")
            return {"channel": "webhook", "status": "failed", "target": webhook_url, "error": f"{exc} - {error_body}"}
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"{Colors.FAIL}{t('webhook_alert_failed', error=f'Connection Error/Timeout: {exc}', status='')}{Colors.ENDC}")
            return {"channel": "webhook", "status": "failed", "target": webhook_url, "error": f"Connection Error/Timeout: {exc}"}
        except Exception as exc:
            print(f"{Colors.FAIL}{t('webhook_alert_failed', error=exc, status='')}{Colors.ENDC}")
            return {"channel": "webhook", "status": "failed", "target": webhook_url, "error": str(exc)}
