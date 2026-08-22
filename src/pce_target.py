"""Is this edit re-pointing the appliance at a different PCE?

The cache, the ingestion watermarks, the archive files and the alert cooldowns
all carry one PCE's data with nothing marking them as such, so this question
has to be asked wherever the connection can be edited — the GUI and both CLI
paths. One definition, so the three cannot drift apart.

Only url and org_id answer it. Rotating the key or the secret is still the
same PCE.
"""
from __future__ import annotations


def pce_target_changed(old_api: dict, new_url: str | None, new_org_id: str | None) -> bool:
    """True when *new_url* or *new_org_id* names a different PCE than *old_api*.

    A None means "not being changed", not "changed to empty".
    """
    if new_url is not None and str(new_url).strip() != str(old_api.get("url", "")).strip():
        return True
    if new_org_id is not None and str(new_org_id).strip() != str(old_api.get("org_id", "")).strip():
        return True
    return False
