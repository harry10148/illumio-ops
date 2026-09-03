"""Job-health / TLS overview i18n contract.

Phase 2A Task 11 cut this file down. It used to make static string
assertions about the LEGACY src/static/js/integrations.js
(`_buildOvJobHealth`, `_buildOvTlsCard`), dashboard.js (`_ovStale`),
rule-scheduler.js (`colspan="13"`) and index.html — every one of those files
is gone. The v2 equivalents are real browser tests, not string greps:

  job health table    tests/test_v2_automation_e2e.py (#/system/jobs, AU-11)
  job health light    tests/test_v2_shell_e2e.py + core_e2e (XC-01's five lights,
                      src/static/js/v2/components/healthbar.mjs jobsLight)
  TLS card            tests/test_v2_system_e2e.py (#/system/tls, SY-16)
  staleness           tests/test_v2_overview_e2e.py (the overview board's
                      computed_at/generated_at handling)
  scheduler last-run  tests/test_v2_automation_e2e.py (#/policy/rulesets)

What has no browser equivalent, and is what survives here, is the catalogue
contract: these keys must exist in BOTH locales or the panels above render
their key names. src/static/js/v2/components/healthbar.mjs and
areas/system.mjs read every one of them.
"""
import json
from pathlib import Path

_EN = Path("src/i18n_en.json")
_ZH = Path("src/i18n_zh_TW.json")

KEYS = (
    "gui_ov_job_health", "gui_jh_th_job", "gui_jh_th_last_run",
    "gui_jh_th_status", "gui_jh_th_interval", "gui_jh_th_detail",
    "gui_jh_never_ran", "gui_jh_overdue", "gui_ov_tls_cert",
    "gui_ov_tls_days", "gui_ov_tls_expiring",
)

# Two of the eleven have NO reader in the v2 frontend — found by the second
# test below when this file was rewritten, and recorded rather than hidden:
#
#   gui_jh_th_detail     the legacy job-health table's "detail" column. v2's
#                        AU-11 table (areas/automation.mjs) and the XC-01
#                        jobs light both surface the detail as part of the
#                        status line instead of as its own column.
#   gui_ov_tls_expiring  the legacy overview's "expiring soon" TLS chip. v2
#                        shows the certificate's remaining days at
#                        #/system/tls (SY-16) with no separate warning label.
#
# Both are product decisions made by Tasks 7/9, not regressions this task
# introduced; they are listed in task-11-report.md's backlog. Keeping them in
# KEYS above preserves the bilingual check (the strings still exist and are
# still translated); excluding them here keeps the consumer check honest.
KEYS_WITHOUT_A_V2_CONSUMER = ("gui_jh_th_detail", "gui_ov_tls_expiring")


def test_job_health_i18n_bilingual():
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in KEYS:
        assert k in en and en[k].strip(), k
        assert k in zh and zh[k].strip(), k


def test_job_health_keys_are_actually_read_by_the_v2_frontend():
    """Guards the other direction: a key that no longer has a consumer is
    backlog, not coverage. If a panel stops reading one of these, this test
    says so instead of quietly asserting a dead entry forever."""
    v2 = "".join(
        p.read_text(encoding="utf-8")
        for p in sorted(Path("src/static/js/v2").rglob("*.mjs"))
    )
    orphans = [k for k in KEYS if k not in v2]
    assert sorted(orphans) == sorted(KEYS_WITHOUT_A_V2_CONSUMER), (
        "the set of job-health/TLS keys with no v2 consumer changed: "
        f"{sorted(orphans)} != {sorted(KEYS_WITHOUT_A_V2_CONSUMER)}. "
        "A key that GAINED a consumer should come off the exclusion list; a "
        "key that LOST one is a panel that stopped rendering something."
    )
