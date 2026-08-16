"""Dashboard story-card group labels — the i18n contract.

Phase 2A Task 11 cut this file down. Three of its four tests asserted the
LEGACY DOM: `story-card--health/traffic/risk` classes and the six
`d-rules`/`d-health`/... story-stat ids in src/templates/index.html, plus
that src/static/js/dashboard.js referenced those same ids. All three files
are gone. The v2 overview board is a different shape entirely (panels with
data-cov anchors, tests/test_v2_overview_e2e.py), so those assertions have
no counterpart to be repointed at.

The catalogue contract survives, and one of the three keys is still read:
src/static/js/v2/areas/overview.mjs renders gui_story_group_risk as the risk
section's eyebrow.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N_EN = ROOT / "src" / "i18n_en.json"
I18N_ZH = ROOT / "src" / "i18n_zh_TW.json"

KEYS = ("gui_story_group_health", "gui_story_group_traffic", "gui_story_group_risk")
# health/traffic lost their consumer when the three-card story strip became
# the v2 overview board; risk kept one. Recorded, not hidden — see
# task-11-report.md's orphaned-key list.
KEYS_READ_BY_V2 = ("gui_story_group_risk",)


def test_i18n_has_group_keys():
    en = json.loads(I18N_EN.read_text(encoding="utf-8"))
    zh = json.loads(I18N_ZH.read_text(encoding="utf-8"))
    for k in KEYS:
        assert k in en and en[k].strip(), f"missing EN {k}"
        assert k in zh and zh[k].strip(), f"missing ZH {k}"


def test_which_group_keys_the_v2_overview_actually_reads():
    v2 = "".join(
        p.read_text(encoding="utf-8")
        for p in sorted((ROOT / "src" / "static" / "js" / "v2").rglob("*.mjs"))
    )
    read = tuple(k for k in KEYS if k in v2)
    assert read == KEYS_READ_BY_V2, (
        f"the set of story-group keys with a v2 consumer changed: {read}. "
        "A key that gained one should move into KEYS_READ_BY_V2; a key that "
        "lost one means a section stopped labelling itself."
    )
