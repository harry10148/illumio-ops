---
title: v6 REST API 參考
verified_against:
  - illumio_ops/web/contract.py
  - illumio_ops/web/app.py
  - web/src/api/contracts.json
---

# v6 REST API 參考

> 本頁由 `scripts/gen_api_reference.py` 從 API 契約產生，請勿手改。新增或修改操作後重新執行該腳本。

這些是網頁介面自己使用的 API，共 125 個操作。每個操作的請求與回應欄位（JSON Schema）在
`web/src/api/contracts.json`，以下只列操作、方法、路徑與模型名稱。

## 共通規則

- 路徑都在 `/api/` 底下，走與網頁介面相同的 HTTPS port。
- 登入：`POST /api/auth/login` 成功後以 session cookie 識別。未登入時回 401 `auth_required`。
  不需登入的操作：`auth.csrf`、`auth.login`、`i18n.dictionary`。
- 寫入（GET 以外）要帶 CSRF 權杖：先 `GET /api/auth/csrf` 取得，放在 `X-CSRFToken` 標頭。登入不需要。
- 設定檔標記為必須改密碼時，除了 `auth.csrf`、`auth.logout`、`auth.me`、`auth.password` 之外的操作都回 423 `password_change_required`。
- 回應一律是同一個封套：

```
{"ok": true,  "data": <回應模型>, "error": null, "meta": {"partial": false, "truncated": false, "notes": []}}
{"ok": false, "data": null, "error": {"code": "...", "message_key": "...", "params": {}, "field": null}, "meta": {...}}
```

- `error.message_key` 是介面字典的鍵，文字由 `GET /api/i18n/<語系>` 取得。
- 請求欄位不符合模型時回 400；`error.field` 指出是哪一欄。

## alert_rules

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `alert_rules.condition_choices` | GET | `/api/alert-rules/condition-choices` | — | `ConditionChoices` |
| `alert_rules.create` | POST | `/api/alert-rules` | `RuleWrite` | `RulesView` |
| `alert_rules.delete` | DELETE | `/api/alert-rules/<rule_id>` | `RuleDelete` | `RulesView` |
| `alert_rules.evaluate_now` | POST | `/api/alert-rules/evaluate-now` | — | `EvaluateRequested` |
| `alert_rules.event_catalog` | GET | `/api/alert-rules/event-catalog` | — | `EventCatalog` |
| `alert_rules.list` | GET | `/api/alert-rules` | — | `RulesView` |
| `alert_rules.pack` | POST | `/api/alert-rules/pack` | `PackApply` | `RulesView` |
| `alert_rules.preview` | POST | `/api/alert-rules/preview` | `RulePreviewRequest` | `RulePreview` |
| `alert_rules.reset_state` | POST | `/api/alert-rules/<rule_id>/reset-state` | — | `RulesView` |
| `alert_rules.retention` | PUT | `/api/alert-rules/retention` | `RetentionUpdate` | `RulesView` |
| `alert_rules.test` | POST | `/api/alert-rules/test` | `RuleTestRequest` | `RuleTestResult` |
| `alert_rules.test_candidates` | GET | `/api/alert-rules/test-candidates` | — | `Candidates` |
| `alert_rules.update` | PUT | `/api/alert-rules/<rule_id>` | `RuleWrite` | `RulesView` |

## alerts

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `alerts.evidence` | GET | `/api/alerts/<int:alert_id>/evidence` | — | `AlertEvidence` |
| `alerts.explain` | POST | `/api/alerts/<int:alert_id>/explain` | `ExplainRequest` | `PolicyExplanation` |
| `alerts.get` | GET | `/api/alerts/<int:alert_id>` | — | `AlertDetail` |
| `alerts.list` | GET | `/api/alerts` | — | `AlertList` |
| `alerts.mark_known` | POST | `/api/alerts/<int:alert_id>/known` | `KnownMark` | `KnownList` |
| `alerts.mark_seen` | POST | `/api/alerts/seen` | — | `SeenBefore` |
| `alerts.note_add` | POST | `/api/alerts/<int:alert_id>/notes` | `NoteAdd` | `AlertDetail` |

## auth

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `auth.csrf` | GET | `/api/auth/csrf` | — | `CsrfToken` |
| `auth.login` | POST | `/api/auth/login` | `LoginRequest` | `LoginResult` |
| `auth.logout` | POST | `/api/auth/logout` | — | `Empty` |
| `auth.me` | GET | `/api/auth/me` | — | `Me` |
| `auth.password` | POST | `/api/auth/password` | `PasswordChangeRequest` | `CsrfToken` |
| `auth.username` | POST | `/api/auth/username` | `UsernameChangeRequest` | `CsrfToken` |

## custom_reports

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `custom_reports.add_section` | POST | `/api/custom-reports/sections` | `CustomSectionAdd` | `CustomReport` |
| `custom_reports.delete` | DELETE | `/api/custom-reports/<int:report_id>` | — | `Empty` |
| `custom_reports.list` | GET | `/api/custom-reports` | — | `CustomReportList` |
| `custom_reports.remove_section` | POST | `/api/custom-reports/<int:report_id>/sections/<int:index>/remove` | `Empty` | `CustomReport` |
| `custom_reports.rename` | POST | `/api/custom-reports/<int:report_id>/rename` | `CustomRename` | `CustomReport` |
| `custom_reports.section_request` | GET | `/api/custom-reports/<int:report_id>/sections/<int:index>/request` | — | `SectionRequest` |

## fleet

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `fleet.enforcement_apply` | POST | `/api/fleet/enforcement/apply` | `EnforcementApplyRequest` | `FleetOutcome` |
| `fleet.enforcement_preview` | POST | `/api/fleet/enforcement/preview` | `EnforcementPreviewRequest` | `EnforcementPreview` |
| `fleet.history` | GET | `/api/fleet/actions` | — | `FleetHistory` |
| `fleet.hosts` | GET | `/api/fleet/hosts` | — | `FleetHostList` |
| `fleet.overview` | GET | `/api/fleet/overview` | — | `FleetOverview` |
| `fleet.rate_apply` | POST | `/api/fleet/traffic-rate/apply` | `FleetKeys` | `FleetOutcome` |
| `fleet.rate_check` | POST | `/api/fleet/traffic-rate/check` | `FleetKeys` | `RateCheck` |

## home

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `home.focus` | GET | `/api/home/focus` | — | `FocusView` |

## hosts

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `hosts.alerted` | GET | `/api/hosts/alerted` | — | `AlertedHosts` |
| `hosts.profile` | GET | `/api/hosts/profile` | — | `HostProfile` |
| `hosts.ransomware_allows` | POST | `/api/hosts/ransomware-allows` | `HostKey` | `HostRansomware` |
| `hosts.search` | GET | `/api/hosts/search` | — | `HostSearch` |
| `hosts.tamper_note_add` | POST | `/api/hosts/tamper-notes` | `TamperNoteAdd` | `HostProfile` |
| `hosts.tamper_note_remove` | POST | `/api/hosts/tamper-notes/<int:note_id>/remove` | `HostKey` | `HostProfile` |

## i18n

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `i18n.dictionary` | GET | `/api/i18n/<lang>` | — | `Dictionary` |

## lateral

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `lateral.compute` | POST | `/api/lateral/compute` | `LateralCompute` | `LateralPage` |
| `lateral.initiators` | GET | `/api/lateral/initiators` | — | `LateralInitiators` |
| `lateral.simulate` | POST | `/api/lateral/simulate` | `LateralSimulate` | `DenySimulationView` |
| `lateral.view` | GET | `/api/lateral` | — | `LateralPage` |

## quarantine

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `quarantine.apply` | POST | `/api/quarantine/apply` | `QuarantineApplyRequest` | `QuarantineOutcome` |
| `quarantine.current` | GET | `/api/quarantine/current` | — | `QuarantineCurrent` |
| `quarantine.history` | GET | `/api/quarantine/history` | — | `QuarantineHistory` |
| `quarantine.preview` | POST | `/api/quarantine/preview` | `QuarantinePreviewRequest` | `QuarantinePreview` |
| `quarantine.remove` | POST | `/api/quarantine/remove` | `QuarantineTargets` | `QuarantineOutcome` |

## report_schedules

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `report_schedules.create` | POST | `/api/report-schedules` | `ScheduleWrite` | `SchedulesView` |
| `report_schedules.delete` | DELETE | `/api/report-schedules/<schedule_id>` | `ScheduleDelete` | `SchedulesView` |
| `report_schedules.list` | GET | `/api/report-schedules` | — | `SchedulesView` |
| `report_schedules.run_now` | POST | `/api/report-schedules/<schedule_id>/run` | `RunNow` | `ReportItem` |
| `report_schedules.update` | PUT | `/api/report-schedules/<schedule_id>` | `ScheduleWrite` | `SchedulesView` |

## reports

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `reports.bulk_delete` | POST | `/api/reports/bulk-delete` | `BulkDelete` | `BulkDeleted` |
| `reports.catalog` | GET | `/api/reports/catalog` | — | `Catalog` |
| `reports.delete` | DELETE | `/api/reports/<int:report_id>` | — | `Empty` |
| `reports.generate` | POST | `/api/reports` | `ReportParams` | `ReportItem` |
| `reports.get` | GET | `/api/reports/<int:report_id>` | — | `ReportItem` |
| `reports.list` | GET | `/api/reports` | — | `ReportPage` |

## rhc

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `rhc.enable` | POST | `/api/rhc/enable` | `RhcEnable` | `RhcEnabled` |
| `rhc.status` | GET | `/api/rhc` | — | `RhcStatus` |

## rule_schedules

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `rule_schedules.check` | POST | `/api/rule-schedules/<int:schedule_id>/check` | `Empty` | `CheckResult` |
| `rule_schedules.create` | POST | `/api/rule-schedules` | `ScheduleCreate` | `ScheduleView` |
| `rule_schedules.delete` | DELETE | `/api/rule-schedules/<int:schedule_id>` | — | `DeleteResult` |
| `rule_schedules.list` | GET | `/api/rule-schedules` | — | `RuleSchedulesView` |
| `rule_schedules.pause` | POST | `/api/rule-schedules/<int:schedule_id>/pause` | `Empty` | `ScheduleView` |
| `rule_schedules.resume` | POST | `/api/rule-schedules/<int:schedule_id>/resume` | `Empty` | `ScheduleView` |
| `rule_schedules.rulesets` | GET | `/api/rule-schedules/rulesets` | — | `RulesetBrowse` |
| `rule_schedules.runs` | GET | `/api/rule-schedules/runs` | — | `RunList` |
| `rule_schedules.targets` | GET | `/api/rule-schedules/targets` | — | `TargetSearch` |
| `rule_schedules.update` | PUT | `/api/rule-schedules/<int:schedule_id>` | `ScheduleEdit` | `ScheduleView` |

## shell

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `shell.status` | GET | `/api/shell/status` | — | `ShellStatus` |

## siem

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `siem.destination.test` | POST | `/api/siem/test` | `SiemTestRequest` | `SiemTestView` |
| `siem.dlq.get` | GET | `/api/siem/dlq/<int:dead_id>` | — | `DlqDetail` |
| `siem.dlq.list` | GET | `/api/siem/dlq` | — | `DlqPage` |
| `siem.dlq.purge` | POST | `/api/siem/dlq/purge` | `DlqAction` | `DlqPurgeView` |
| `siem.dlq.resend` | POST | `/api/siem/dlq/resend` | `DlqAction` | `DlqResendView` |
| `siem.settings.get` | GET | `/api/siem/settings` | — | `SiemSettingsView` |
| `siem.settings.update` | PUT | `/api/siem/settings` | `SiemSettingsUpdate` | `SiemSettingsView` |
| `siem.status` | GET | `/api/siem/status` | — | `SiemStatusView` |

## system

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `system.channels.get` | GET | `/api/system/channels` | — | `ChannelsView` |
| `system.channels.test` | POST | `/api/system/channels/test` | `ChannelTest` | `ChannelTestResult` |
| `system.channels.test_all` | POST | `/api/system/channels/test-all` | `ChannelTestAll` | `ChannelTestAllResult` |
| `system.channels.update` | PUT | `/api/system/channels` | `ChannelsUpdate` | `ChannelsView` |
| `system.collection.backfill` | POST | `/api/system/collection/backfill` | `BackfillRequest` | `BackfillAccepted` |
| `system.collection.clear` | POST | `/api/system/collection/clear` | `ClearRequest` | `CollectedCleared` |
| `system.collection.data` | GET | `/api/system/collection/data` | — | `DataStatus` |
| `system.collection.get` | GET | `/api/system/collection` | — | `CollectionView` |
| `system.collection.retention_run` | POST | `/api/system/collection/retention/run` | `Empty` | `RetentionQueued` |
| `system.collection.status` | GET | `/api/system/collection/status` | — | `CollectionStatus` |
| `system.collection.update` | PUT | `/api/system/collection` | `CollectionUpdate` | `CollectionView` |
| `system.display.get` | GET | `/api/system/display` | — | `DisplayView` |
| `system.display.update` | PUT | `/api/system/display` | `DisplayUpdate` | `DisplayView` |
| `system.jobs.list` | GET | `/api/system/jobs` | — | `JobList` |
| `system.lateral.get` | GET | `/api/system/lateral` | — | `LateralView` |
| `system.lateral.known` | GET | `/api/system/lateral/known` | — | `KnownList` |
| `system.lateral.known_delete` | DELETE | `/api/system/lateral/known/<int:mark_id>` | — | `KnownList` |
| `system.lateral.update` | PUT | `/api/system/lateral` | `LateralUpdate` | `LateralView` |
| `system.logs.query` | POST | `/api/system/logs/query` | `LogQuery` | `LogLines` |
| `system.pce.get` | GET | `/api/system/pce` | — | `PceConnection` |
| `system.pce.latest` | GET | `/api/system/pce/latest` | — | `LatestProbe` |
| `system.pce.probe` | POST | `/api/system/pce/probe` | — | `ProbeRun` |
| `system.pce.update` | PUT | `/api/system/pce` | `PceConnectionUpdate` | `PceConnectionSaved` |
| `system.reports.get` | GET | `/api/system/reports` | — | `ReportSettingsView` |
| `system.reports.update` | PUT | `/api/system/reports` | `ReportSettingsUpdate` | `ReportSettingsView` |
| `system.security.get` | GET | `/api/system/security` | — | `SecurityView` |
| `system.security.update` | PUT | `/api/system/security` | `SecurityUpdate` | `SecurityView` |
| `system.tls.csr` | POST | `/api/system/tls/csr` | `CsrRequest` | `CsrResult` |
| `system.tls.import` | POST | `/api/system/tls/import` | `ImportRequest` | `TlsStatus` |
| `system.tls.renew` | POST | `/api/system/tls/renew` | — | `TlsStatus` |
| `system.tls.status` | GET | `/api/system/tls` | — | `TlsStatus` |
| `system.tls.update` | PUT | `/api/system/tls` | `TlsUpdate` | `TlsStatus` |

## workbench

| 操作 | 方法 | 路徑 | 請求模型 | 回應模型 |
|---|---|---|---|---|
| `workbench.dimension` | POST | `/api/workbench/dimension` | `WorkbenchDimension` | `DimensionTop` |
| `workbench.from_alert` | GET | `/api/workbench/from-alert/<int:alert_id>` | — | `WorkbenchStart` |
| `workbench.meta` | GET | `/api/workbench/meta` | — | `WorkbenchMeta` |
| `workbench.predicted` | POST | `/api/workbench/predicted` | `WorkbenchRun` | `PredictedView` |
| `workbench.run` | POST | `/api/workbench/run` | `WorkbenchRun` | `WorkbenchResult` |
