"""Metadata for built-in alert output plugins."""

from __future__ import annotations

from dataclasses import dataclass, field

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

@dataclass
class PluginMeta:
    name: str
    display_name: str
    description: str
    fields: dict[str, FieldMeta] = field(default_factory=dict)

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
        description="Send vendor-aligned alert content as an HTML email.",
        fields={
            "sender": FieldMeta(label="Sender", required=True, placeholder="monitor@example.com"),
            "recipients": FieldMeta(
                label="Recipients",
                required=True,
                placeholder="ops@example.com, soc@example.com",
                input_type="list",
                value_type="string_list",
            ),
            "smtp.host": FieldMeta(label="SMTP Host", required=True, placeholder="smtp.example.com"),
            "smtp.port": FieldMeta(
                label="SMTP Port",
                required=True,
                placeholder="587",
                input_type="number",
                value_type="integer",
            ),
            "smtp.user": FieldMeta(label="SMTP Username"),
            "smtp.password": FieldMeta(label="SMTP Password", secret=True),
            "smtp.enable_tls": FieldMeta(
                label="STARTTLS",
                help="Enable STARTTLS before sending mail.",
                input_type="checkbox",
                value_type="boolean",
            ),
            "smtp.enable_auth": FieldMeta(
                label="SMTP Auth",
                help="Authenticate to the SMTP server with username/password.",
                input_type="checkbox",
                value_type="boolean",
            ),
        },
    ),
    "line": PluginMeta(
        name="line",
        display_name="LINE Messaging API",
        description="Send compact triage alerts to a LINE user, room, or group.",
        fields={
            "alerts.line_channel_access_token": FieldMeta(label="Channel Access Token", required=True, secret=True),
            "alerts.line_target_id": FieldMeta(label="Target ID", required=True, placeholder="Uxxxxxxxx"),
        },
    ),
    "webhook": PluginMeta(
        name="webhook",
        display_name="Webhook",
        description="POST canonical alert payloads to an HTTP endpoint.",
        fields={
            "alerts.webhook_url": FieldMeta(label="Webhook URL", required=True, placeholder="https://hooks.example.com/events"),
        },
    ),
}
