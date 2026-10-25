"""What the 5.x → v6 migration did with every key it found. Key names only, never values."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from illumio_ops.domain.values import Language
from illumio_ops.i18n import translate

Action = Literal["carried", "rewritten", "dropped", "unsupported"]


@dataclass(frozen=True)
class MigrationItem:
    source: str
    target: str | None
    action: Action
    reason_key: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class MigrationReport:
    items: list[MigrationItem] = field(default_factory=list)


_SECTION_KEYS: dict[Action, str] = {
    "carried": "migrate_section_carried",
    "rewritten": "migrate_section_rewritten",
    "unsupported": "migrate_section_unsupported",
    "dropped": "migrate_section_dropped",
}


def render(report: MigrationReport, lang: Language) -> str:
    lines = [translate(lang, "migrate_report_title"), ""]
    for action in ("carried", "rewritten", "unsupported", "dropped"):
        items = sorted((i for i in report.items if i.action == action), key=lambda i: i.source)
        if not items:
            continue
        lines.append(translate(lang, _SECTION_KEYS[action], {"n": str(len(items))}))
        for i in items:
            arrow = f"{i.source} → {i.target}" if i.target else i.source
            reason = translate(lang, i.reason_key, i.params)
            lines.append(f"  {arrow}" if action == "carried" else f"  {arrow}: {reason}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
