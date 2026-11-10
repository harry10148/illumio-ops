"""Why a part of a report is not there (6.6.0 §1). Three reasons, never worded as one:
- unset: an optional setting is not made — the note says what is missing, what setting it would add, and where;
- pending: not computed yet, or no data for it — the note says what and why;
- unsupported: this PCE does not provide it.
The part itself is left out of the report (no key number, no section, no column); the note in the data notes is the
only trace, one per missing thing. A thing that was computed and came out 0 is not a hint: it is shown as 0."""
from __future__ import annotations

from illumio_ops.domain.values import Language
from illumio_ops.services.reports.common import tr

KINDS = ("rpt_hint_unset_", "rpt_hint_pending_", "rpt_hint_unsupported_")


def hint(lang: Language, key: str, **params: object) -> str:
    """The data note for one missing thing. The key names its reason: rpt_hint_unset_*, rpt_hint_pending_* or
    rpt_hint_unsupported_* (written out at the call, so the dictionary checks see it)."""
    if not key.startswith(KINDS):
        raise ValueError("a hint key says why the part is missing")
    return tr(lang, key, **params)


def once(*lines: str) -> tuple[str, ...]:
    """The lines without repeats, in order."""
    return tuple(dict.fromkeys(line for line in lines if line))
