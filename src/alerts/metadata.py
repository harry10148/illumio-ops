"""Metadata for built-in alert output plugins."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.i18n import t


@dataclass
class FieldMeta:
    label: str
    help: str = ""
    required: bool = False
    secret: bool = False
    placeholder: str = ""
    input_type: str = "text"
    value_type: str = "string"
    list_delimiter: str = ","
    label_key: str = ""
    help_key: str = ""

    def resolved_label(self, lang: str = "en") -> str:
        return t(self.label_key, lang=lang, default=self.label) if self.label_key else self.label

    def resolved_help(self, lang: str = "en") -> str:
        return t(self.help_key, lang=lang, default=self.help) if self.help_key else self.help


@dataclass
class PluginMeta:
    name: str
    display_name: str
    description: str
    fields: dict[str, FieldMeta] = field(default_factory=dict)
    display_name_key: str = ""
    description_key: str = ""

    def resolved_display_name(self, lang: str = "en") -> str:
        if self.display_name_key:
            return t(self.display_name_key, lang=lang, default=self.display_name)
        return self.display_name

    def resolved_description(self, lang: str = "en") -> str:
        if self.description_key:
            return t(self.description_key, lang=lang, default=self.description)
        return self.description

def plugin_config_path(plugin_name: str, field_key: str) -> tuple[str, ...]:
    if plugin_name == "mail":
        if field_key in {"sender", "recipients"}:
            return ("email", field_key)
        if field_key.startswith("smtp."):
            return ("smtp", field_key.split(".", 1)[1])
    if "." in field_key:
        return tuple(part for part in field_key.split(".") if part)
    return (plugin_name, field_key)

def plugin_config_value(config: dict, plugin_name: str, field_key: str):
    cursor = config
    for part in plugin_config_path(plugin_name, field_key):
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor.get(part)
    return cursor

PLUGIN_METADATA: dict[str, PluginMeta] = {
    "mail": PluginMeta(
        name="mail",
        display_name="Email (SMTP)",
        display_name_key="alert_plugin_mail_display_name",
        description="Send vendor-aligned alert content as an HTML email.",
        description_key="alert_plugin_mail_description",
        fields={
            "sender": FieldMeta(
                label="Sender", label_key="alert_plugin_field_sender",
                required=True, placeholder="monitor@example.com",
            ),
            "recipients": FieldMeta(
                label="Recipients", label_key="alert_plugin_field_recipients",
                required=True,
                placeholder="ops@example.com, soc@example.com",
                input_type="list",
                value_type="string_list",
            ),
            "smtp.host": FieldMeta(
                label="SMTP Host", label_key="alert_plugin_field_smtp_host",
                required=True, placeholder="smtp.example.com",
            ),
            "smtp.port": FieldMeta(
                label="SMTP Port", label_key="alert_plugin_field_smtp_port",
                required=True,
                placeholder="587",
                input_type="number",
                value_type="integer",
            ),
            "smtp.user": FieldMeta(label="SMTP Username", label_key="alert_plugin_field_smtp_user"),
            "smtp.password": FieldMeta(label="SMTP Password", label_key="alert_plugin_field_smtp_password", secret=True),
            "smtp.enable_tls": FieldMeta(
                label="STARTTLS",
                label_key="alert_plugin_field_smtp_starttls",
                help="Enable STARTTLS before sending mail.",
                help_key="alert_plugin_help_smtp_starttls",
                input_type="checkbox",
                value_type="boolean",
            ),
            "smtp.enable_auth": FieldMeta(
                label="SMTP Auth",
                label_key="alert_plugin_field_smtp_enable_auth",
                help="Authenticate to the SMTP server with username/password.",
                help_key="alert_plugin_help_smtp_enable_auth",
                input_type="checkbox",
                value_type="boolean",
            ),
        },
    ),
    "line": PluginMeta(
        name="line",
        display_name="LINE Messaging API",
        display_name_key="alert_plugin_line_display_name",
        description="Send compact triage alerts to a LINE user, room, or group.",
        description_key="alert_plugin_line_description",
        fields={
            "alerts.line_channel_access_token": FieldMeta(
                label="Channel Access Token",
                label_key="alert_plugin_field_line_channel_access_token",
                required=True, secret=True,
            ),
            "alerts.line_target_id": FieldMeta(
                label="Target ID",
                label_key="alert_plugin_field_line_target_id",
                required=True, placeholder="Uxxxxxxxx",
            ),
        },
    ),
    "webhook": PluginMeta(
        name="webhook",
        display_name="Webhook",
        display_name_key="alert_plugin_webhook_display_name",
        description="POST canonical alert payloads to an HTTP endpoint.",
        description_key="alert_plugin_webhook_description",
        fields={
            "alerts.webhook_url": FieldMeta(
                label="Webhook URL",
                label_key="alert_plugin_field_webhook_url",
                required=True, placeholder="https://hooks.example.com/events",
            ),
        },
    ),
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
}
