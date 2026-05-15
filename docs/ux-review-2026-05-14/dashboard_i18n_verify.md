# Dashboard i18n Fix — Deployment Verification Checklist

This Phase 1.2 work modifies translation tables only (no production code). The test machine at `172.16.15.106` runs the merged-to-main snapshot — visual verification requires deploying this branch first.

## Verification steps (run AFTER `git pull && systemctl restart illumio-ops` on test machine)

```bash
/home/harry/rd/illumio-ops/venv/bin/python scripts/ux_review_runner.py tab dashboard dashboard_i18n_after
```

Open `screenshots/tab_dashboard_i18n_after.png` and confirm:

| Element | Before (broken) | After (approved) |
|---|---|---|
| Health-check KPI | 健康規則 | 健康檢查規則 |
| Unknown types KPI | 未知類型 | 未知事件類型 |
| Ransomware exposure KPI | Ransomware 暴露 | Ransomware 暴露面 |
| Cooldown title | 冷卻中的規則 | 冷卻中規則 |
| Attack Summary badge | Attack/攻擊摘要 (混雜) | 攻擊摘要（Boundary/Pivot/Blast Radius/Blind Spots/行動） |
| Action Matrix lateral reco | 對 RDP/SSH/SMB 橫向通信窗用 | 對 RDP/SSH/SMB 等橫向移動路徑套用微分段控制 |

Run the audit script — should report 0 findings:

```bash
/home/harry/rd/illumio-ops/venv/bin/python scripts/audit_i18n_usage.py --only J
# expected: exit 0, no Category J findings
```

## Known preserved EN terms (intentional)

`PCE` / `VEN` / `Workload` / `Policy` / `Enforcement` / `Boundary` / `Visibility` / `Blast Radius` / `Blind Spots` / `Ransomware` — all whitelisted in `src/i18n/data/glossary.json` `preserve_in_zh_tw`. These appear in Chinese strings by design (e.g. "Ransomware 暴露面") because they are Illumio product/security terminology.

## Regression locked in by

- `tests/test_dashboard_kpi_translations.py` — locks 9 approved zh_TW values; CI fails if any drift.
- `tests/test_action_matrix_i18n.py` — locks 8 `rpt_actmtx_*` keys exist in en+zh and `lateral_reco` contains `RDP/SSH/SMB/微分段` but NOT the old broken phrase.
- `scripts/audit_i18n_usage.py` Category J — Han-ratio ≥ 0.8 enforced (2 exceptions for glossary-Latin-heavy strings).
- `src/i18n/data/dashboard_approved.json` — single source of truth.

## Verification status

- [ ] Deploy to test machine (172.16.15.106)
- [ ] Run `ux_review_runner.py tab dashboard dashboard_i18n_after`
- [ ] Manual visual diff against pre-fix screenshots
- [ ] All 6 elements in the table above match "After (approved)"
- [ ] `audit_i18n_usage.py --only J` exit 0
