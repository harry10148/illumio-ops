# Static Code-Review Findings — 2026-06-26

Refuted high/critical findings already removed. **109** findings kept; **36** marked `safe-inline`.

## Summary

### By severity

| Severity | Count |
| --- | --- |
| critical | 0 |
| high | 11 |
| medium | 51 |
| low | 39 |
| info | 8 |
| **Total** | **109** |

### By subsystem

| Subsystem | Count |
| --- | --- |
| Entry dispatch, version management, packaging & install/build scripts | 3 |
| GUI routes | 6 |
| GUI shared helpers, templates, and client-side JS | 13 |
| PCE REST client | 5 |
| Security | 5 |
| reporter / alert dispatch | 8 |
| scheduler / config / settings / i18n | 5 |
| src/analyzer.py — B/L/R flow-to-rule matching engine, event/traffic ru | 5 |
| src/cli/* | 11 |
| src/events/* | 4 |
| src/pce_cache | 9 |
| src/report report assembly & scheduling | 6 |
| src/report/exporters | 11 |
| src/report/rules | 9 |
| src/siem | 9 |

---

## Findings

## HIGH (11)

### [src/report report assembly & scheduling] Scheduler crashes (naive vs aware datetime subtraction) under 'local' timezone, killing all report schedules

- **File:** `src/report_scheduler.py:31-40, 112-123, 592-616`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** src/report report assembly & scheduling (report_generator, audit_generator, policy_usage_generator, report_scheduler, policy_resolver_report, traffic facades)

**Detail:** _now_in_schedule_tz('local') (and unset/empty tz) returns a timezone-AWARE datetime (datetime.now(timezone.utc)), whereas every other branch ('UTC', 'UTC+N') returns a NAIVE datetime. In should_run() the min-rerun-gap check parses the stored last_run, strips tzinfo to make it naive (line 118-119), then computes `(now - last_run_dt)`. When tz is 'local', `now` is aware and `last_run_dt` is naive, so the subtraction raises `TypeError: can't subtract offset-naive and offset-aware datetimes`. The surrounding try only catches ValueError (line 122), so the TypeError propagates. tick() calls should_run() WITHOUT any guard (line 604), so the exception escapes tick entirely. Because the gap check runs for every schedule that has a stored last_run (before any due-time check), the FIRST schedule with a prior run aborts the whole tick on every daemon cycle — all report schedules silently stop. 'local' is an explicitly supported value (special-cased in _tz_offset_hours/_now_in_schedule_tz) and is the in-code default literal (tick line 599, get('timezone','local')). I reproduced the TypeError directly. The shipped config.json uses 'UTC+8' (naive path) which masks it, but any deployment on 'local' or with timezone unset is broken after the first successful run.

**Evidence:**

```
if last_run_dt.tzinfo is not None:
    last_run_dt = last_run_dt.replace(tzinfo=None)
if (now - last_run_dt).total_seconds() < _MIN_RERUN_GAP:  # now is aware for 'local'
    return False
...
except ValueError:   # does NOT catch TypeError
    pass
```

**Suggested fix:** Make awareness consistent: either have _now_in_schedule_tz('local') return naive server-local time (datetime.datetime.now()), or in should_run normalize `now` to naive before the subtraction (e.g. `now = now.replace(tzinfo=None) if now.tzinfo else now`). Also broaden the except to `(ValueError, TypeError)` and wrap the should_run call in tick() in try/except so one bad schedule cannot abort evaluation of the rest.

---

### [src/report/exporters] Traffic report table cells and hand-built HTML fragments interpolate untrusted PCE data without HTML-escaping (stored XSS)

- **File:** `src/report/exporters/html_exporter.py:385, 378, 187-193, 467-473, 765-789, 1234-1257, 1521-1523`
- **Category:** security | **Fix risk:** `needs-review`
- **Subsystem:** src/report/exporters (HTML/CSV/XLSX report rendering)

**Detail:** table_renderer.render_df_table() inserts the output of render_cell() raw (`f"<td>{cell_html}</td>"`, table_renderer.py:131-132). The render_cell passed by html_exporter._df_to_html falls through to `return '' if val is None else str(val)` (line 385) for every non-numeric column — i.e. hostnames, app/label names, service names, process names, usernames, IPs — all of which originate from PCE traffic flow records and workload labels and are attacker-influenceable (a compromised endpoint can name a host/process `<img src=x onerror=...>`). The severity-badge branch also returns the cell `val` unescaped (line 378). The same raw interpolation occurs in _format_evidence (label/v_display, 187-193), key_findings_html (kf['finding']/['action'], 467-473), _attack_summary_html (item finding/action, 765-789), _findings_html (f.rule_id, rule_name, f.description, f.recommendation; 1238-1256) and _mod_ringfence_html (app_name from a label; 1521-1523). The generated HTML is opened in a browser and emailed as an attachment, so this is stored/persistent XSS in the report deliverable. Note _default_cell() in table_renderer DOES escape — the vulnerability is specifically the custom render_cell paths and the f-string fragments.

**Evidence:**

```
html_exporter.py:385  `return '' if val is None else str(val)`  ;  _findings_html:1252  `f'<p class="finding-desc">{f.description}</p>'`  ;  table_renderer.py:131  `cell_html = render_cell(col, raw_value, row) ... html_parts.append(f"<td>{cell_html}</td>")`
```

**Suggested fix:** Escape the default render_cell branch: `return '' if val is None else html.escape(str(val))`, and escape `val` in the badge branch. Wrap every PCE-derived value interpolated into the hand-built fragments (f.description, f.recommendation, rule_name, evidence label/value, key-finding finding/action, ringfence app_name/flows) in html.escape(). i18n strings from STRINGS are trusted and need not be escaped.

---

### [src/report/exporters] Audit report: high-impact provision cards and table cells inject actor/resource/src_ip/event_type without escaping

- **File:** `src/report/exporters/audit_html_exporter.py:111, 316-336`
- **Category:** security | **Fix risk:** `safe-inline`
- **Subsystem:** src/report/exporters (HTML/CSV/XLSX report rendering)

**Detail:** _df_to_html._render_cell default branch returns `str(row[col])` unescaped (line 111) for any column that is not event_type/action/change_detail (those use the escaping helpers). Audit event columns include actor names, resource names, source IPs and free-form fields that come directly from PCE audit events and are user/attacker-controlled. Worse, _high_impact_provisions_html() builds raw HTML interpolating `actor`, `resource_name`, `src_ip`, `status`, `et` (event_type) and `ts` straight from the event dict with no escaping (lines 329-334). An audit actor named with markup, or a crafted resource name, yields HTML/JS injection into the rendered audit report.

**Evidence:**

```
audit_html_exporter.py:111  `return "" if row[col] is None else str(row[col])`  ;  :331  `f"<span ...>by <b>{actor}</b></span>"`  ;  :332  `... resource <b>{resource_name}</b> ...`  ;  :333  `... from <code>{src_ip}</code> ...`
```

**Suggested fix:** Escape the default branch: `return "" if row[col] is None else html.escape(str(row[col]))`. In _high_impact_provisions_html escape actor, resource_name, src_ip, status and et with html.escape() before interpolation (wa and ts/threshold are numeric/internal but escaping ts is also advisable).

---

### [src/report/exporters] VEN status report table cells rendered without HTML-escaping

- **File:** `src/report/exporters/ven_html_exporter.py:150-164`
- **Category:** security | **Fix risk:** `safe-inline`
- **Subsystem:** src/report/exporters (HTML/CSV/XLSX report rendering)

**Detail:** The inner _df_to_html._render_cell returns `val_str` (raw str(val)) for every column except policy_sync (badge) and multi-IP (escaped). VEN inventory columns include hostnames, labels, OS strings and single IPs, all PCE/endpoint-derived and attacker-influenceable, giving HTML/JS injection in the VEN report. (Note the estate-inventory and ransomware-posture sections in this same file DO escape via html.escape — only the generic table renderer path is unescaped.)

**Evidence:**

```
ven_html_exporter.py:164  `return val_str`  (where `val_str = "" if val is None or str(val) in ("None","nan") else str(val)`)
```

**Suggested fix:** Return `html.escape(val_str)` from the default branch (the policy_sync badge and IP branches already handle their own escaping).

---

### [src/report/exporters] Policy Usage report table cells and attention/notes rows rendered without escaping

- **File:** `src/report/exporters/policy_usage_html_exporter.py:108-113, 366-372, 399`
- **Category:** security | **Fix risk:** `safe-inline`
- **Subsystem:** src/report/exporters (HTML/CSV/XLSX report rendering)

**Detail:** _df_to_html._render_cell default branch returns `val_str` unescaped (line 113) for all non-'enabled' columns; these summary/deny/top-port tables contain rule descriptions, source/destination label sets and service strings derived from PCE policy and flow data. Additionally _attention_html interpolates `item['ruleset']` unescaped (line 368) and _execution_html interpolates `note` unescaped (line 399). A ruleset or rule description containing markup yields HTML/JS injection. (The richer _rule_cards_html path correctly uses the _e() escaper — only these paths are vulnerable.)

**Evidence:**

```
policy_usage_html_exporter.py:113 `return val_str` ; :368 `f'<span>{item.get("ruleset", "")}</span>'` ; :399 `notes_html = "".join(f"<li>{note}</li>" for note in notes)`
```

**Suggested fix:** Escape the default render_cell branch (`return _e(val_str)` / html.escape), escape item['ruleset'] in _attention_html, and escape each note in _execution_html.

---

### [GUI shared helpers, templates, and client-side JS] DOM XSS in rules-table search highlight (innerHTML re-parses escaped text)

- **File:** `src/static/js/rules.js:198-205`
- **Category:** security | **Fix risk:** `needs-review`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** _highlightRow() reads `td.textContent` (which returns the DECODED literal text of a cell that was originally rendered with escapeHtml) and then assigns it back via `td.innerHTML = orig.replace(re, '<mark>$1</mark>')`. Because textContent of an escaped cell yields raw characters like `<` and `>`, re-assigning to innerHTML re-parses them as live HTML. Rule cells at rules.js:100 render admin/PCE-supplied values (`r.name`, and the joined filter string containing `r.filter_value`, `r.src_label`, `r.dst_label`, `r.src_ip_in`, `r.dst_ip_in`, label values synced from the PCE). A rule whose name/label contains e.g. `webserver <img src=x onerror=alert(1)>` will, the moment any operator types a matching search term, inject a live <img> element and execute JS. This converts safe stored data into an executed payload purely through the client-side filter.

**Evidence:**

```
const orig = td.textContent;
...
td.innerHTML = orig.replace(re, '<mark>$1</mark>');
```

**Suggested fix:** Escape before re-inserting: build the highlighted HTML from an escaped copy, e.g. `td.innerHTML = escapeHtml(orig).replace(re, '<mark>$1</mark>')` (and run the regex against the escaped string), or better, walk text nodes and wrap matches with DOM nodes / <mark> via document.createTextNode + surroundContents so no HTML is ever parsed.

---

### [src/siem] Dispatcher TLS syslog transport ignores configured tls_ca_bundle — custom-CA destinations fail in production but pass the built-in test

- **File:** `src/siem/dispatcher.py:196-198`
- **Category:** correctness | **Fix risk:** `safe-inline`
- **Subsystem:** src/siem (SIEM forwarder: formatters, transports, dispatcher, DLQ, web API)

**Detail:** In _transport_for(), the TLS branch constructs SyslogTLSTransport(host, port, tls_verify=dest_cfg.tls_verify) but never passes ca_bundle=dest_cfg.tls_ca_bundle. SyslogTLSTransport._connect() only calls ctx.load_verify_locations() when self._ca_bundle is set, otherwise it uses the system default trust store. tls_ca_bundle is a real config field (config_models.py:271, prompted in siem_cli.py:137) and the tester DOES pass it (tester.py:78). Result: a destination configured with a private/internal CA and tls_verify=True (the secure default) passes the operator 'Test' button (tester loads the CA bundle) but every real dispatch fails the TLS handshake, retries to exhaustion, and quarantines into the DLQ — a complete, silent forwarding outage that the built-in test cannot reveal.

**Evidence:**

```
elif transport_type == "tls":
    from src.siem.transports.syslog_tls import SyslogTLSTransport
    return SyslogTLSTransport(host, port, tls_verify=dest_cfg.tls_verify)  # tls_ca_bundle dropped
```

**Suggested fix:** Pass the CA bundle through: return SyslogTLSTransport(host, port, tls_verify=dest_cfg.tls_verify, ca_bundle=dest_cfg.tls_ca_bundle) — matching tester._build_transport().

---

### [src/pce_cache] Traffic ingestor sends a tz-naive `since` timestamp to the PCE (events code guards against this exact 406)

- **File:** `src/pce_cache/ingestor_traffic.py:67-73`
- **Category:** correctness | **Fix risk:** `safe-inline`
- **Subsystem:** src/pce_cache (SQLite WAL cache + ingestors/aggregator/retention/reader/subscriber)

**Detail:** `_since_cursor` does `grace = wm.last_timestamp - timedelta(minutes=5); return grace.isoformat()`. `wm.last_timestamp` comes from WatermarkStore.get -> SQLAlchemy DateTime(timezone=True) on SQLite, which returns a NAIVE datetime (reader.py and lag_monitor.py both explicitly re-attach UTC to such reads, confirming this). So after the first successful poll, the traffic ingestor emits an offset-less ISO string (e.g. '2026-06-26T12:00:00') as `start_date` in the async Explorer payload (api_client.get_traffic_flows_async -> _build_native_traffic_payload sets `"start_date": start_time_str` verbatim, while `end_date` is tz-aware). The EventsIngestor handles the identical case deliberately: its `_since_cursor` comment states 'PCE rejects timestamps without a tz marker (HTTP 406 invalid_timestamp)' and re-attaches UTC (ingestor_events.py:71-72). The traffic path does not, so every incremental poll after cold start risks a 406 (run_once then swallows it, records error, returns 0) or a tz-misinterpreted query window — i.e. incremental traffic ingestion silently stalls.

**Evidence:**

```
grace = wm.last_timestamp - timedelta(minutes=5)
return grace.isoformat()   # naive -> no tz offset
```

**Suggested fix:** Mirror EventsIngestor: before isoformat(), normalize tz, e.g. `if grace.tzinfo is None: grace = grace.replace(tzinfo=timezone.utc)` (and/or `.replace(microsecond=0)`), so the emitted `since` always carries a UTC offset.

---

### [src/pce_cache] Events ingestor discards the entire fetched batch when the sync pull hits the async threshold (async is a stub returning [])

- **File:** `src/pce_cache/ingestor_events.py:43-55`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** src/pce_cache (SQLite WAL cache + ingestors/aggregator/retention/reader/subscriber)

**Detail:** When `len(events) >= self._async_threshold` (default/cap = 10000, config async_threshold_events is `ge=1, le=10000`), run_once advances the watermark with no timestamp and reassigns `events = self._api.get_events_async(...)`. But get_events_async is an unimplemented stub that returns `[]` (api_client.py:299-301). The 10000 already-fetched events are thrown away and `_insert_batch([])` inserts nothing. Because `advance(SOURCE)` with no timestamp keeps last_timestamp unchanged, the next poll uses the same `since`, fetches >= 10000 again, and discards again — a permanent stall with total event loss whenever the backlog (e.g. after downtime or on a busy estate) exceeds the threshold. Events ingestion never recovers on its own.

**Evidence:**

```
if len(events) >= self._async_threshold:
    ...
    self._wm.advance(self.SOURCE)
    events = self._api.get_events_async(since=since, rate_limit=True)  # stub -> []
...
inserted = self._insert_batch(events)  # _insert_batch([])
```

**Suggested fix:** Until get_events_async is implemented, do not discard the sync results: insert the already-fetched `events` (and page forward by advancing the watermark to max(timestamp) so the next poll continues), instead of overwriting `events` with the empty async stub. At minimum guard `if events_async: events = events_async` so a stubbed [] never clobbers a real batch.

---

### [src/pce_cache] Aggregator overwrite semantics + raw retention permanently corrupt (shrink) historical daily buckets

- **File:** `src/pce_cache/aggregator.py:31-68`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** src/pce_cache (SQLite WAL cache + ingestors/aggregator/retention/reader/subscriber)

**Detail:** run_once does a full-table GROUP BY over ALL current raw rows (no time window) and `on_conflict_do_update` sets `flow_count = excluded.flow_count` / `bytes_total = excluded.bytes_total` (overwrite, not additive/max). The agg table has 90-day retention while raw has 7-day retention (retention.py defaults events=90, traffic_raw=7, traffic_agg=90) — agg exists precisely to preserve history beyond raw. RetentionWorker deletes raw rows by `ingested_at < cutoff`. A given bucket_day's raw rows are ingested across that day, so as the 7-day cutoff sweeps through that day's ingestion span, retention deletes them PARTIALLY. A subsequent aggregator run recomputes that bucket from only the surviving sliver and OVERWRITES the previously-correct full sum with a smaller value. Once all of the day's raw rows are gone the bucket emits no group and is frozen — at the badly-undercounted last-written value. Net effect: every aged-out bucket's flow_count/bytes_total is permanently corrupted downward, defeating the agg table's purpose.

**Evidence:**

```
stmt = stmt.on_conflict_do_update(... set_={
    "flow_count": stmt.excluded.flow_count,
    "bytes_total": stmt.excluded.bytes_total })  # overwrite with recompute over surviving raw rows only
```

**Suggested fix:** Make aggregation immune to raw expiry: either (a) only (re)aggregate buckets newer than the raw retention horizon and treat older buckets as immutable, or (b) restrict each run's SELECT to a recent window and use additive `flow_count = agg.flow_count + excluded.flow_count` with an ingest cursor (idempotent on already-counted rows), or (c) at minimum `MAX(agg.flow_count, excluded.flow_count)` to prevent downward overwrite. Requires care to keep idempotency across re-runs.

---

### [reporter / alert dispatch] Generic webhook URL (may embed a secret) is persisted to state.json and timeline without redaction

- **File:** `src/alerts/plugins.py:199-214`
- **Category:** security | **Fix risk:** `needs-review`
- **Subsystem:** reporter / alert dispatch (src/reporter.py, src/alerts/*)

**Detail:** WebhookAlertPlugin.send returns `"target": webhook_url` (the full configured URL) on every success/failure path. Reporter.send_alerts feeds results to persist_dispatch_results -> StatsTracker.record_dispatch, which writes `target` into logs/state.json (dispatch_history) AND into the timeline (src/events/stats.py:138,151). Generic webhook URLs for Slack/Discord/incoming connectors embed a secret token in the path/query (e.g. hooks.slack.com/services/T../B../<secret>). This is exactly the L-12 leak class the TeamsAlertPlugin was hardened against via redact_webhook_url (plugins.py:23-43, 271-272), but the webhook channel never redacts. The secret therefore lands on disk and in dispatch history.

**Evidence:**

```
return {"channel": "webhook", "status": "success", "target": webhook_url}  ... (same full webhook_url used in all failed branches)
```

**Suggested fix:** Mirror the Teams plugin: compute safe_target = redact_webhook_url(webhook_url) at the top of WebhookAlertPlugin.send and use safe_target for every returned target value (keep webhook_url only for the actual urlopen call).

---

## MEDIUM (51)

### [src/report report assembly & scheduling] _prune_by_count('traffic') prefix collision deletes security_risk and network_inventory reports

- **File:** `src/report_scheduler.py:516-557`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** src/report report assembly & scheduling (report_generator, audit_generator, policy_usage_generator, report_scheduler, policy_resolver_report, traffic facades)

**Detail:** Both the SecurityRisk and NetworkInventory HTML exporters write files named `Illumio_Traffic_Report_<KIND>_<ts>.html` (html_exporter.py:433). The retention prefix map uses `traffic -> 'Illumio_Traffic_Report_'`, which is a strict prefix of BOTH `Illumio_Traffic_Report_SecurityRisk_` and `Illumio_Traffic_Report_NetworkInventory_`. So when a report_type='traffic' schedule runs _prune_by_count(output_dir, 'traffic', max_reports), startswith() matches all three kinds; if the combined count of security_risk + network_inventory + traffic files in the shared output_dir exceeds max_reports, the oldest are deleted regardless of which schedule produced them — cross-type report loss. Secondary: candidates also include each report's `*.html.metadata.json` sidecar (endswith '.json'), so each report counts as 2 files and the effective kept-report count is roughly half of max_reports.

**Evidence:**

```
_REPORT_PREFIXES = { 'traffic': 'Illumio_Traffic_Report_', 'security_risk': 'Illumio_Traffic_Report_SecurityRisk_', 'network_inventory': 'Illumio_Traffic_Report_NetworkInventory_', ... }
...
if fname.startswith(prefix) and fname.endswith((".html", ".zip", ".json")):
```

**Suggested fix:** Give 'traffic' a precise prefix matching what it actually emits (it defaults to the security_risk profile, i.e. 'Illumio_Traffic_Report_SecurityRisk_'), or exclude the more-specific kind prefixes when pruning 'traffic'. Separately, prune by report unit (group .html with its .metadata.json sidecar) so max_reports counts reports, not files.

---

### [src/report report assembly & scheduling] Hardcoded English CLI output 'Raw Explorer CSV saved' bypasses i18n

- **File:** `src/report/report_generator.py:553`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/report report assembly & scheduling (report_generator, audit_generator, policy_usage_generator, report_scheduler, policy_resolver_report, traffic facades)

**Detail:** Every other save message in export() goes through t() (e.g. rpt_html_saved, rpt_csv_saved, rpt_xlsx_saved at lines 482/510/522), but the raw Explorer CSV branch prints a hardcoded English string. Under lang='zh_TW' the user gets a stray English line, violating the AGENTS.md i18n guardrail that all CLI output use i18n keys.

**Evidence:**

```
print(f"Raw Explorer CSV saved: {raw_export['path']}")
```

**Suggested fix:** Add a key (e.g. rpt_raw_csv_saved) to BOTH src/i18n_en.json and src/i18n_zh_TW.json and replace with print(t("rpt_raw_csv_saved", path=raw_export['path'], lang=lang)).

---

### [src/report report assembly & scheduling] Hardcoded English in user-visible report emails (table headers + 'Generated:' label)

- **File:** `src/report_scheduler.py:423`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/report report assembly & scheduling (report_generator, audit_generator, policy_usage_generator, report_scheduler, policy_resolver_report, traffic facades)

**Detail:** The scheduled-report email's Security Findings table emits literal '<th>ID</th><th>Finding</th><th>Severity</th>' even though the adjacent Attack Summary table localizes its headers via t('rpt_email_finding')/t('rpt_email_action') (lines 461). Likewise the traffic email body in report_generator.py:853 hardcodes 'Generated: ...'. Recipients on zh_TW get partially-English emails, violating the i18n guardrail that alerts/reports use i18n keys.

**Evidence:**

```
body += "<th style='padding:8px;text-align:left;'>ID</th><th style='padding:8px;text-align:left;'>Finding</th><th style='padding:8px;text-align:left;'>Severity</th>"   # report_scheduler.py:423
... 
<div ...>Generated: {mod12.get('generated_at','')}</div>   # report_generator.py:853
```

**Suggested fix:** Introduce keys (e.g. rpt_email_col_id / rpt_email_col_finding / rpt_email_col_severity and rpt_email_generated_label) in both i18n_en.json and i18n_zh_TW.json and resolve them with t(..., lang=lang) at both sites.

---

### [src/report/exporters] Audit 'needs attention' concern cards render actor/target/resource/src_ip/summary unescaped

- **File:** `src/report/exporters/concern_card.py:48-77`
- **Category:** security | **Fix risk:** `safe-inline`
- **Subsystem:** src/report/exporters (HTML/CSV/XLSX report rendering)

**Detail:** render_concern_cards() (used by AuditHtmlExporter._attention_section) interpolates event_type, summary, recommendation, and the joined actors/targets/resources/src_ips strings directly into HTML with no escaping. These come from audit attention-items (actor account names, resource names, source IPs) which are attacker-controllable, producing HTML/JS injection in the audit report hero.

**Evidence:**

```
concern_card.py:61 `<code class="...">{event_type}</code>` ; :64 `<div class="concern-summary ...">{summary}</div>` ; :66 `<strong>...</strong> {actors_str}` ; :76 `<strong>...</strong> {rec}`
```

**Suggested fix:** html.escape() each interpolated value: event_type, summary, rec, actors_str, targets_str, resources_str, src_ips_str (escape each element before join). The _s() i18n labels are trusted.

---

### [src/report/exporters] Spreadsheet formula injection: xlsx export writes untrusted strings as live cell values

- **File:** `src/report/exporters/xlsx_exporter.py:55`
- **Category:** security | **Fix risk:** `needs-review`
- **Subsystem:** src/report/exporters (HTML/CSV/XLSX report rendering)

**Detail:** _write_module_sheet writes each table value with `ws.cell(row=row, column=col_idx, value=val)`. openpyxl auto-detects a leading '=' string as a formula (verified: a value of '=1+2' is stored with data_type 'f'). Report tables contain PCE-derived strings (hostnames, labels, process names, usernames). A value like `=HYPERLINK("http://attacker","open")` or `=cmd|'/c calc'!A0` becomes a live formula when the analyst opens the workbook — classic spreadsheet/CSV formula injection.

**Evidence:**

```
xlsx_exporter.py:55  `cell = ws.cell(row=row, column=col_idx, value=val)`  (no neutralization of leading = + - @)
```

**Suggested fix:** Neutralize formula-leading values before writing, e.g. for str values starting with one of = + - @ prefix with a single quote or a zero-width guard, or set `cell.data_type='s'` / `cell.value = "'"+val`. Apply to header values too.

---

### [src/report/exporters] Maturity-dimension labels and Allowed/Blocked section headings are hardcoded English (i18n guardrail violation)

- **File:** `src/report/exporters/html_exporter.py:511-531, 873-874`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/report/exporters (HTML/CSV/XLSX report rendering)

**Detail:** The micro-segmentation maturity block renders dimension names from the hardcoded English m_dim_labels dict ('Enforcement Coverage', 'Policy Coverage', 'Lateral Movement Control', 'Managed Asset Ratio', 'Risk Port Control') directly into the report hero — they never go through t()/STRINGS, so a zh_TW report still shows English (lines 511-531). Similarly _mod02_html builds the per-decision section heading from `d.replace('_',' ').upper()` plus the literal strings ' of total', '↓ Inbound:' and '↑ Outbound:' (lines 873-874), all hardcoded English. AGENTS.md requires all user-visible report text to use bilingual i18n keys.

**Evidence:**

```
html_exporter.py:519-531  `for dim_key, dim_label in m_dim_labels.items(): ... <div class="mat-name">{dim_label}</div>` ; :874  `f' &nbsp;·&nbsp; ↓ Inbound: {inb} &nbsp;·&nbsp; ↑ Outbound: {outb}</h3>'`
```

**Suggested fix:** Replace m_dim_labels values with t()/STRINGS lookups (add rpt_mat_* keys to both i18n_en.json and i18n_zh_TW.json) and localize the Inbound/Outbound/'of total'/decision-status heading via existing or new keys.

---

### [src/report/rules] R01–R05 draft-policy rules are never evaluated; the whole draft-PD feature is non-functional

- **File:** `src/report/rules_engine.py:88-94, 50-56`
- **Category:** dead-code | **Fix risk:** `needs-review`
- **Subsystem:** src/report/rules (R01–R05), src/report/rules_engine.py (B/L rules), src/report/analysis/* (policy_resolver, mod_vuln, mod03_uncovered_flows, mod02_policy_decisions, mod04, mod12, mod13, mod15, attack_posture, mod_draft_*)

**Detail:** RulesEngine.evaluate() only calls self._eval_builtin(df), which runs B001-B009 and L001-L010. The R01-R05 classes registered in DRAFT_PD_RULES are never instantiated/.evaluate()'d anywhere (grep of '.evaluate(' shows only engine.evaluate and app_summary, neither iterates DRAFT_PD_RULES). DRAFT_PD_RULES is used ONLY by ruleset_needs_draft_pd() as a boolean signal. Worse, even if they were called they could never match: the unified DataFrame is built by flatten_flow_record() (src/report/parsers/api_parser.py:63-104) which never emits a 'draft_policy_decision' column, so every R-rule's _has_draft() guard returns []. And compute_draft in the HTML exporter (html_exporter.py:408,503-504) only toggles a 'draft enabled' header pill — it does not populate the column or render any R-rule output. Net effect: the five documented DraftPolicy security rules (each with severities, i18n keys, MITRE notes) produce zero findings in any traffic report, silently. This is a major capability gap presented to users as working.

**Evidence:**

```
evaluate(): findings.extend(self._eval_builtin(df)) — no draft-rule loop. flatten_flow_record returns a dict with no 'draft_policy_decision'. html_exporter: self._compute_draft only drives draft_pill.
```

**Suggested fix:** Either (a) wire the R-rules into evaluate() (iterate DRAFT_PD_RULES, instantiate, call evaluate(df, ctx, lang) when the column is present) AND ensure flatten_flow_record/cache reader populate 'draft_policy_decision' when requires_draft_pd is set; or (b) if the feature is intentionally deferred, remove/disable the dead R01-R05 registry, mod_draft_summary registration, and the compute_draft pill to avoid implying coverage that does not exist.

---

### [src/report/rules] mod_draft_summary / mod_draft_actions group by non-existent 'src'/'dst' columns (unified schema uses src_ip/dst_ip)

- **File:** `src/report/analysis/mod_draft_summary.py:30-37 (and mod_draft_actions.py:25,38,47,60)`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** src/report/rules (R01–R05), src/report/rules_engine.py (B/L rules), src/report/analysis/* (policy_resolver, mod_vuln, mod03_uncovered_flows, mod02_policy_decisions, mod04, mod12, mod13, mod15, attack_posture, mod_draft_*)

**Detail:** mod_draft_summary.analyze() (registered in TRAFFIC_MODULES and called with the unified df) does flows_df.groupby(['src','dst']), and mod_draft_actions groups by ['src','dst','port']. The unified DataFrame produced by flatten_flow_record has columns src_ip/dst_ip/src_app/dst_app — there is no 'src' or 'dst'. R05DraftReportedMismatch defensively probes both 'src' and 'src_ip', but these draft modules do not. Today the groupby is unreachable only because the draft_policy_decision column is never present (so analyze() returns {'skipped': True}); the moment the draft column is correctly wired (the apparent intent), these modules raise KeyError('src') and get swallowed to {'error': ...} by _run_modules. This is a latent crash and schema mismatch.

**Evidence:**

```
mod_draft_summary.py: flows_df[mask].groupby(['src','dst']).size(); mod_draft_actions.py: sub.groupby(['src','dst','port']). api_parser flatten emits 'src_ip'/'dst_ip', not 'src'/'dst'.
```

**Suggested fix:** Resolve the source/destination columns the same way R05 does (src = 'src' if present else 'src_ip', dst likewise) before grouping, or rename to the unified schema names src_ip/dst_ip.

---

### [src/report/rules] B001 contextual severity uses estate-wide allowed/PB counts instead of cross-subnet-scoped counts, mislabeling severity

- **File:** `src/report/rules_engine.py:184-244`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** src/report/rules (R01–R05), src/report/rules_engine.py (B/L rules), src/report/analysis/* (policy_resolver, mod_vuln, mod03_uncovered_flows, mod02_policy_decisions, mod04, mod12, mod13, mod15, attack_posture, mod_draft_*)

**Detail:** B001 classifies severity using n_allowed and n_pb computed over ALL matched flows, but the branch conditions are meant to describe cross-subnet flows specifically. Example: cross-subnet ransomware-port flows are all potentially_blocked (5) while same-subnet flows are all allowed (3). Then n_cross_subnet=5>0 and n_allowed=3>0 → the HIGH branch fires ('cross-subnet allowed flows'), even though every cross-subnet flow is actually test-mode PB (should be MEDIUM). Conversely, cross-subnet flows all PB plus same-subnet flows also PB (n_allowed=0) falls through to the final else branch and emits the 'same_subnet_allowed' risk_summary/recommendation with n_allowed=0 — contradictory messaging. The docstring promises proximity-scoped severity but the math is global, so severity and the localized risk_summary can be wrong.

**Evidence:**

```
n_allowed = int((matched['policy_decision']=='allowed').sum()); branch: elif n_cross_subnet > 0 and n_allowed > 0: severity='HIGH' — n_allowed is not restricted to the cross-subnet subset.
```

**Suggested fix:** Compute allowed/PB counts on the cross-subnet subset (e.g. cross = matched[~matched['_same_subnet']]; n_cross_allowed = (cross['policy_decision']=='allowed').sum(); n_cross_pb = ...) and drive the HIGH/MEDIUM/else branches and their risk_summary/recommendation off those scoped counts.

---

### [src/report/rules] Chart specs embed process-global get_language() instead of the report's lang parameter (wrong-language charts under concurrency)

- **File:** `src/report/analysis/mod03_uncovered_flows.py:77, 166 (same pattern: mod04:137, mod12:287, mod13:304, mod15:443)`
- **Category:** i18n | **Fix risk:** `safe-inline`
- **Subsystem:** src/report/rules (R01–R05), src/report/rules_engine.py (B/L rules), src/report/analysis/* (policy_resolver, mod_vuln, mod03_uncovered_flows, mod02_policy_decisions, mod04, mod12, mod13, mod15, attack_posture, mod_draft_*)

**Detail:** These modules receive an explicit lang= argument and correctly thread it through t(...) for labels, but their chart_spec embeds 'i18n': {'lang': get_language()}. get_language() returns the process-global singleton (src/i18n/engine.py:58), not the lang passed to the module. The codebase deliberately threads lang= everywhere precisely to avoid relying on the global under the scheduler/concurrent generation. When a scheduled or multi-PCE report is generated with an explicit lang that differs from the process-global language, the chart renderer will localize axes/titles to the wrong language while the rest of the report is correct. mod02 only has get_language() (no lang param) so it is the lone forgivable case; the others ignore an available, correct lang.

**Evidence:**

```
mod03: 'i18n': {'lang': get_language()} inside chart_spec while the function signature is uncovered_flows(df, top_n, *, lang='en') and uses t(..., lang=lang) elsewhere.
```

**Suggested fix:** Replace get_language() in chart_spec['i18n']['lang'] with the lang parameter the function already receives (mod03/mod04/mod12/mod13/mod15).

---

### [src/report/rules] i18n guardrail violation: hardcoded bilingual key-findings text in mod12 _KF bypasses the i18n JSON files

- **File:** `src/report/analysis/mod12_executive_summary.py:116-129, 141-143`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/report/rules (R01–R05), src/report/rules_engine.py (B/L rules), src/report/analysis/* (policy_resolver, mod_vuln, mod03_uncovered_flows, mod02_policy_decisions, mod04, mod12, mod13, mod15, attack_posture, mod_draft_*)

**Detail:** The executive-summary 'Key Findings' strings for staged_enforcement and policy_gap are user-visible (rendered in the HTML report and the email body) but are stored as an inline _KF dict with hardcoded en/zh_TW templates and formatted via _kf(), instead of going through t(key, lang=lang) with keys present in both src/i18n_en.json and src/i18n_zh_TW.json. AGENTS.md requires all user-visible text to use i18n keys; the adjacent Action Matrix (_ACTMTX_KEYS) already does this correctly via t(), so this is an inconsistent, non-compliant island. A language outside {en, zh_TW} silently falls back to en.

**Evidence:**

```
_KF = { 'staged_enforcement': {'en': (...), 'zh_TW': (...)}, ... }; def _kf(...): tmpl = _KF[key].get(lang) or _KF[key]['en']; return tmpl[0].format(...), tmpl[1].format(...).
```

**Suggested fix:** Move the four message/recommendation strings into i18n_en.json and i18n_zh_TW.json (e.g. rpt_kf_staged_enforcement_msg/_reco, rpt_kf_policy_gap_msg/_reco) and resolve via t(key, lang=lang, cov=..., staged=..., gap=...), mirroring _actmtx().

---

### [src/report/rules] i18n guardrail violation: attack_posture recommendation/finding labels hardcoded bilingually; zh_TW falls back to English

- **File:** `src/report/analysis/attack_posture.py:41-90, 145-152, 170-176`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/report/rules (R01–R05), src/report/rules_engine.py (B/L rules), src/report/analysis/* (policy_resolver, mod_vuln, mod03_uncovered_flows, mod02_policy_decisions, mod04, mod12, mod13, mod15, attack_posture, mod_draft_*)

**Detail:** RECOMMENDATION_TEMPLATES and the finding_labels map carry inline en/zh_TW strings that surface in the executive summary / email / snapshot (via summarize_attack_posture -> mod12 boundary_breaches/blast_radius/etc.). These bypass the i18n JSON system required by AGENTS.md. Worse, resolve_recommendation()'s default branch returns an English-only string ('Review attack posture evidence and apply least-privilege segmentation.') even when lang='zh_TW', and template.get('en','') is the fallback when a code lacks a zh_TW entry — so a Chinese report can emit English action text. The finding_labels default (kind.replace('_',' ')) is likewise English.

**Evidence:**

```
def resolve_recommendation(code, lang='en'): template = RECOMMENDATION_TEMPLATES.get(code); if not template: return 'Review attack posture evidence and apply least-privilege segmentation.'; ... return template.get('en','').
```

**Suggested fix:** Replace the inline template/label dicts with t(key, lang=lang) lookups backed by keys in both i18n JSON files (action codes map to rpt_action_<code>; finding kinds to rpt_finding_<kind>), and give the fallback paths localized keys instead of literal English.

---

### [GUI routes] UnboundLocalError on `lang` in report-generation error handlers masks the real failure

- **File:** `src/gui/routes/reports.py:421/448 (audit), 621/648 (ven_status), 674/728 (policy_usage)`
- **Category:** error-handling | **Fix risk:** `safe-inline`
- **Subsystem:** GUI routes (src/gui/__init__.py app shell + src/gui/routes/* blueprints: auth, admin, dashboard, events, reports, rules, rule_scheduler, actions, config)

**Detail:** In api_generate_audit_report, api_generate_ven_status_report and api_generate_policy_usage_report, the local variable `lang` is assigned INSIDE the try block (lines 421, 621, 674) but referenced in the except block's `_err_with_log(..., lang=lang)` call (lines 448, 648, 728). If an exception is raised before the lang assignment — e.g. the `from src.report.* import ...` ImportError, `cm.load()` raising on a malformed config, `ApiClient(cm)` construction, or `_make_cache_reader(cm)` — then evaluating `lang` in the except handler raises UnboundLocalError. That secondary error propagates to the global Exception handler, producing a generic 500 with a DIFFERENT request_id and a misleading UnboundLocalError traceback in the logs instead of the original root cause. Contrast with api_generate_policy_diff_report (line 456) and api_generate_policy_resolver_report (line 502) which correctly define lang BEFORE the try.

**Evidence:**

```
reports.py:442-448  except Exception as e: ... return _err_with_log("report_audit_generate", e, lang=lang)   while  lang = d.get('lang', 'en')  is at line 421 inside the try.
```

**Suggested fix:** Move `lang = d.get('lang', 'en')` (with the en/zh_TW normalization) to just after `d = request.json or {}`, before the try block, in all three handlers — matching the policy_diff/policy_resolver pattern.

---

### [GUI routes] Unsynchronized load-modify-save on the shared ConfigManager causes lost updates across cheroot worker threads

- **File:** `src/gui/routes/config.py:55-88 (api_save_settings 142-199); dashboard.py 342-399; rules.py 236-279`
- **Category:** concurrency | **Fix risk:** `needs-review`
- **Subsystem:** GUI routes (src/gui/__init__.py app shell + src/gui/routes/* blueprints: auth, admin, dashboard, events, reports, rules, rule_scheduler, actions, config)

**Detail:** ConfigManager is a single shared instance mutated in place by request handlers, and ConfigManager.save() (src/config.py:382-405) performs an atomic per-file write but has NO in-process lock. cheroot uses a 10-thread pool, and the _rs_background_scheduler thread also calls cm.load(). Handlers do read-modify-write on cm.config (e.g. api_save_settings: load -> mutate cm.config -> save; api_save_dashboard_query: load -> append -> save; api_pce_profiles_action). Two concurrent writers interleave as load(A), load(B), mutateA, mutateB, save(A), save(B) -> last writer wins and silently drops the other change. Worse, several mutators do NOT re-load first (api_update_rule rules.py:236, api_delete_rule rules.py:276, api_pce_profiles_action config.py:341) so they operate on whatever cm.config a previous request/scheduler left in memory; if the background scheduler's cm.load() replaces cm.config['rules'] mid-iteration in another thread, iteration can read a half-updated structure.

**Evidence:**

```
src/config.py:382 def save(self): ... (no lock); rules.py:240 `old = cm.config['rules'][idx]` with no cm.load() in api_update_rule; dashboard.py:344-398 load/mutate/save with no lock.
```

**Suggested fix:** Guard the load-modify-save critical sections with a module-level threading.Lock (or add an internal RLock to ConfigManager around load()/save()), and ensure every config-mutating handler re-loads under that lock before mutating. Given cheroot's multi-thread pool this is required even in single-process mode.

---

### [GUI routes] SQLAlchemy engines created per request and never disposed (connection/file-descriptor leak)

- **File:** `src/gui/routes/dashboard.py:59-65 (_cache_session), used by 71-104 and 107-144; actions.py:445`
- **Category:** performance | **Fix risk:** `needs-review`
- **Subsystem:** GUI routes (src/gui/__init__.py app shell + src/gui/routes/* blueprints: auth, admin, dashboard, events, reports, rules, rule_scheduler, actions, config)

**Detail:** _cache_session() calls create_engine(f"sqlite:///{...}") on every invocation and returns a sessionmaker, but the Engine (which owns a connection pool) is never disposed. api_dashboard_overview triggers this twice per request (_overview_blocked and _overview_pipeline), and api_traffic_trend (actions.py:445) creates its own engine per request as well. Sessions are closed via `with sf() as s`, but the underlying Engine and its pooled SQLite connections are only reclaimed at GC, so under sustained dashboard polling the process accumulates Engine objects holding open SQLite file handles, leaking file descriptors and connections.

**Evidence:**

```
dashboard.py:63  eng = create_engine(f"sqlite:///{cm.models.pce_cache.db_path}")  with no eng.dispose(); same pattern at actions.py:445.
```

**Suggested fix:** Create the cache Engine once and cache it (module-level or on cm), or wrap usage in try/finally with engine.dispose(). A cached single Engine per db_path is the standard SQLAlchemy pattern and removes the leak.

---

### [GUI routes] Hardcoded user-facing English error strings bypass the i18n guardrail

- **File:** `src/gui/routes/config.py:67, 154, 266, 281, 309, 355, 361, 364, 371, 378, 381 (plus dashboard.py:480,487; events.py:221,223,227; rules.py:87,117; reports.py:393,529; rule_scheduler.py:267)`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** GUI routes (src/gui/__init__.py app shell + src/gui/routes/* blueprints: auth, admin, dashboard, events, reports, rules, rule_scheduler, actions, config)

**Detail:** AGENTS i18n guardrail requires ALL user-visible text (including API error messages surfaced in the SPA) to go through t(key, lang=lang) with keys in both i18n_en.json and i18n_zh_TW.json. Numerous handlers return raw English literals in the `error`/`message` field rendered directly by the UI: config.py:67 f"Invalid allowlist entries: ...", config.py:154 "api.url must use http or https scheme", config.py:266 "Self-signed certificate renewed. Restart the server to apply.", config.py:281 "CN (Common Name) is required", config.py:309 "cert_pem is required", config.py:355/361/364/371/378/381 _err("name and url required")/"id required"/"profile not found"/"unknown action"; dashboard.py:480 _err(f"Unknown chart_id: {chart_id}")/487 "Chart unavailable"; events.py:221 "invalid rule index"/223 "rule not found"/227 "rule is not an event rule"; rules.py:87 "pce_health must be created from the system health rule form"/117 "unsupported system rule type"; reports.py:393 "unknown job"/529 "invalid key"; rule_scheduler.py:267 "href required". zh_TW users see English; the audit_i18n_usage check is meant to forbid exactly this.

**Evidence:**

```
config.py:355 `return _err("name and url required")`; events.py:221 `return _err("invalid rule index", 400)`; dashboard.py:480 `return _err(f"Unknown chart_id: {chart_id}", 404)`.
```

**Suggested fix:** Replace each literal with t("<new_key>", lang=lang) and add the key to both src/i18n_en.json and src/i18n_zh_TW.json. Ensure each affected handler resolves `lang` (from request/config) before building the error.

---

### [GUI shared helpers, templates, and client-side JS] DOM XSS in service-cell popover: encodeURIComponent does not encode single quotes

- **File:** `src/static/js/dashboard.js:1958-1959`
- **Category:** security | **Fix risk:** `needs-review`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** For service strings longer than 25 chars the code builds an inline onclick handler: `encJson = encodeURIComponent(JSON.stringify(arr))` then `onclick="showCellPopover(event,'SVC',JSON.parse(decodeURIComponent('${encJson}')))"`. encodeURIComponent does NOT percent-encode the apostrophe character `'` (it is in its unreserved set), so a service name containing a single quote survives verbatim into the single-quoted JS string literal inside the double-quoted onclick attribute, breaking out of the string and allowing arbitrary JS injection. The svc string is built server-side from `service.name` (an admin-defined Illumio Service object name) concatenated with proto/port (src/gui/routes/dashboard.py:554-556), so a crafted/long service name (>25 chars) with `'` is an XSS vector. The identical pattern exists in quarantine.js:426-427.

**Evidence:**

```
let encJson = encodeURIComponent(JSON.stringify(arr));
svc_str = `<span onclick="showCellPopover(event, 'SVC', JSON.parse(decodeURIComponent('${encJson}')))" ...`
```

**Suggested fix:** Stop using an inline onclick string for the payload. Store the items in a data-* attribute (escaped via escapeHtml) and bind via addEventListener/event delegation, or at minimum additionally escape `'` (e.g. `encJson.replace(/'/g, '%27')`) before interpolating into the attribute.

---

### [GUI shared helpers, templates, and client-side JS] Same single-quote onclick XSS in quarantine traffic table service cell

- **File:** `src/static/js/quarantine.js:426-427`
- **Category:** security | **Fix risk:** `needs-review`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** renderQtPage() reproduces the dashboard svc-popover bug: `encodeURIComponent(JSON.stringify(arr))` is interpolated into a single-quoted JS string inside an onclick attribute. Since encodeURIComponent leaves `'` unencoded and svc_str includes `item.service.name` (admin-defined PCE Service name), a service name >25 chars containing an apostrophe / crafted payload breaks out of the handler and executes JS when the row is rendered/clicked.

**Evidence:**

```
let encJson = encodeURIComponent(JSON.stringify(arr));
svc_str = `<span onclick="showCellPopover(event, 'SVC', JSON.parse(decodeURIComponent('${encJson}')))" ...`
```

**Suggested fix:** Use a data attribute + delegated event listener for the popover payload, or escape the apostrophe before placing it inside the inline handler.

---

### [GUI shared helpers, templates, and client-side JS] Unescaped config values injected into input value attributes (contradicts documented invariant)

- **File:** `src/static/js/settings.js:384-385,457,534`
- **Category:** security | **Fix risk:** `safe-inline`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** The Settings render helpers carry the comment 'All user-supplied values are escaped via escapeHtml()' (settings.js:345), but several admin-supplied config values are interpolated raw into `value="..."` attributes: `a.url` and `a.org_id` (API Connection block, l.384-385), `rpt.output_dir` (l.457), and `sec.username` (l.534). A value containing a double quote plus markup (e.g. PCE URL `https://x"><img src=x onerror=alert(1)>`) breaks out of the attribute and injects HTML when the settings panel re-renders. The PCE profile table rows just above (l.350-351) and the TLS cert paths (l.477-478) ARE escaped, so this is an inconsistency, not an intended exception. (Note: `a.key`/`a.secret` are masked to asterisks server-side by _redact_secrets, so no secret leak — but a.url/org_id/output_dir/username are not.)

**Evidence:**

```
<input id="s-url" value="${a.url || ''}">...<input id="s-org" value="${a.org_id || ''}">
<input id="s-rpt-dir" value="${rpt.output_dir || 'reports/'}">
<input id="s-sec-user" value="${sec.username || 'admin'}">
```

**Suggested fix:** Wrap each interpolated value in escapeHtml(): `value="${escapeHtml(a.url || '')}"`, likewise for a.org_id, rpt.output_dir, and sec.username, to honor the file's stated escaping invariant.

---

### [GUI shared helpers, templates, and client-side JS] Hardcoded English in Overview drill labels and tiles (i18n guardrail)

- **File:** `src/static/js/dashboard.js:1651,1662-1665,1678`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** renderOverview() emits user-visible strings without t()/_t(): the VEN tile drill link '→ Workloads' (l.1651), the pipeline tile 'DLQ ' label and '→ Integrations' drill (l.1678), and the blocked tile 'Blocked'/'Potentially Blocked'/'→ Traffic' (l.1662-1665). The AGENTS.md i18n guardrail requires all user-visible text to use i18n keys present in both locale files; these render literal English regardless of selected language. (The blocked tile at l.1657-1665 is additionally noted in-code as a removed/guarded tile, so it is partly dead, but ov-ven-body and ov-pipeline-body are live.)

**Evidence:**

```
+ '<div class="ov-drill">&#8594; Workloads</div>';
... 'DLQ ' + (p.dlq || 0)]) + '<div class="ov-drill">→ Integrations</div>';
```

**Suggested fix:** Replace the literals with T('gui_ov_drill_workloads', 'Workloads'), T('gui_ov_drill_integrations','Integrations'), T('gui_ov_dlq','DLQ'), etc., and add the keys to both src/i18n_en.json and src/i18n_zh_TW.json.

---

### [GUI shared helpers, templates, and client-side JS] Hardcoded English schedule chips and 'Last:' label in report cards (i18n)

- **File:** `src/static/js/dashboard.js:256-263,274,276`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** loadRcardMeta() renders report-card meta strips with hardcoded English: schedChip() returns 'Manual'/'Daily'/'Weekly'/'Monthly'/'Scheduled', and the last-run line is set to 'Last: ' + date or 'Last: —'. These are visible on the Reports tab for both languages and never localize.

**Evidence:**

```
if (!s || !s.enabled) return 'Manual';
...
lastEl.textContent = 'Last: ' + d.toLocaleDateString(...);
```

**Suggested fix:** Route every chip and the 'Last:' prefix through _t() with keys added to both locale JSON files (e.g. gui_rcard_sched_manual, gui_rcard_last).

---

### [src/cli/*] --host CLI flag is silently ignored; Web GUI always binds 0.0.0.0

- **File:** `src/cli/_runtime.py:86-110, 113-165`
- **Category:** security | **Fix risk:** `safe-inline`
- **Subsystem:** src/cli/* (root, report, rule, workload, cache, siem, status, config, monitor, gui, menus) + src/main.py (legacy argparse) + src/rule_scheduler_cli.py

**Detail:** run_gui_only() and run_daemon_with_gui() both accept a host parameter (default '0.0.0.0') that is wired through from the click commands gui_cmd (src/cli/gui_cmd.py:14 --host) and monitor_gui_cmd (src/cli/monitor_gui_cmd.py:15 --host). But neither function passes host into launch_gui(): line 110 calls launch_gui(cm, port=port) and line 165 calls launch_gui(cm, port=port, persistent_mode=True). launch_gui's signature is launch_gui(cm, host='0.0.0.0', port=5001, ...) (src/gui/__init__.py:695), so host always defaults to 0.0.0.0. An operator running 'illumio-ops gui --host 127.0.0.1' to restrict the GUI to loopback (a real hardening step for a tool holding PCE keys/SMTP/LINE tokens) gets their flag silently dropped and the GUI exposed on all interfaces.

**Evidence:**

```
def run_gui_only(cm, port: int = 5001, host: str = "0.0.0.0") -> None:
    ...
    launch_gui(cm, port=port)   # host never passed
```

**Suggested fix:** Pass host through: in run_gui_only use launch_gui(cm, host=host, port=port); in run_daemon_with_gui use launch_gui(cm, host=host, port=port, persistent_mode=True).

---

### [src/cli/*] Dead/unreachable FileNotFoundError handlers in every report command (OSError catches subclass first)

- **File:** `src/cli/report.py:289-298 (repeated at 342-351, 385-394, 422-431, 452-461, 501-510, 631-640, 683-692, 726-735)`
- **Category:** error-handling | **Fix risk:** `needs-review`
- **Subsystem:** src/cli/* (root, report, rule, workload, cache, siem, status, config, monitor, gui, menus) + src/main.py (legacy argparse) + src/rule_scheduler_cli.py

**Detail:** Each report command orders 'except (ConnectionError, OSError)' BEFORE 'except FileNotFoundError'. Since FileNotFoundError is a subclass of OSError, a FileNotFoundError (e.g. a missing CSV / vuln-csv opened inside the generator, or a missing output path) is caught by the OSError clause. There, 'if isinstance(exc, OSError) and "connection" not in str(exc).lower(): raise' re-raises it (the message never contains 'connection'). The re-raise propagates out of the try entirely, so the sibling 'except FileNotFoundError' that was meant to emit a clean 'Input file not found' message and exit EXIT_NOINPUT can never run — it is dead code, and the user instead hits the generic top-level excepthook.

**Evidence:**

```
except (ConnectionError, OSError) as exc:
    if isinstance(exc, OSError) and 'connection' not in str(exc).lower():
        raise
    ...
except FileNotFoundError as exc:   # unreachable: OSError above already caught it
    echo_error(ctx, f"Input file not found: {exc}")
    ctx.exit(EXIT_NOINPUT)
```

**Suggested fix:** Move the 'except FileNotFoundError' clause ABOVE the 'except (ConnectionError, OSError)' clause in each handler so the more specific subclass is matched first.

---

### [src/cli/*] Interactive 'config login' silently wipes the stored API secret when left blank

- **File:** `src/cli/config.py:239-251`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** src/cli/* (root, report, rule, workload, cache, siem, status, config, monitor, gui, menus) + src/main.py (legacy argparse) + src/rule_scheduler_cli.py

**Detail:** In interactive mode the url/key/org_id prompts preserve the existing value via default=current.get(...), but the secret prompt uses default="". ApiSettings.secret is 'str = Field(default="")' (src/config_models.py:33), so an empty secret passes validation. An operator running 'config login' to change only the URL who presses Enter at the secret prompt overwrites cm.config['api']['secret'] with '' and cm.save() persists it, silently destroying the PCE API secret and breaking all subsequent API calls.

**Evidence:**

```
if secret is None:
    secret = click.prompt("API secret", default="", hide_input=True, show_default=False)
...
cm.config["api"]["secret"] = secret
```

**Suggested fix:** Treat an empty interactive secret as 'keep existing': e.g. prompt with a sentinel and, if blank, retain current.get('secret', '') instead of overwriting with ''.

---

### [src/cli/*] workload.py CLI output is entirely hardcoded English (no i18n)

- **File:** `src/cli/workload.py:44-127`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/cli/* (root, report, rule, workload, cache, siem, status, config, monitor, gui, menus) + src/main.py (legacy argparse) + src/rule_scheduler_cli.py

**Detail:** AGENTS.md mandates that ALL CLI output use i18n keys via t(...). This module never imports t and hardcodes every user-visible string: the spinner 'Fetching workloads from PCE...' (line 54), the error 'Cannot reach PCE: {exc}' (line 65), the table title 'Workloads (...)' (line 105) and all column headers '#','Name','Hostname','Env','Enforcement','OS' (lines 106-111). zh_TW users see English throughout.

**Evidence:**

```
echo_error(ctx, f"Cannot reach PCE: {exc}")
...
table = Table(title=f"Workloads ({len(workloads)})", ...)
table.add_column("Name")
```

**Suggested fix:** Import t from src.i18n, resolve lang from settings, and replace the spinner text, error string, table title and column headers with t() keys added to both src/i18n_en.json and src/i18n_zh_TW.json.

---

### [src/cli/*] status.py CLI output is entirely hardcoded English (no i18n)

- **File:** `src/cli/status.py:34-57`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/cli/* (root, report, rule, workload, cache, siem, status, config, monitor, gui, menus) + src/main.py (legacy argparse) + src/rule_scheduler_cli.py

**Detail:** The status command never imports t; all human-readable output is hardcoded: '(no log file)' (line 34/46), the quiet-mode 'ok'/'no log' (line 46), the table title 'illumio-ops status' and the row labels 'PCE URL','Language','Rules','Last log activity' (lines 50-57). Violates the AGENTS.md i18n guardrail for CLI output.

**Evidence:**

```
table = Table(title="illumio-ops status", ...)
table.add_row("PCE URL", pce_url)
table.add_row("Language", language)
```

**Suggested fix:** Resolve lang and replace the title and row labels (and the no-log-file string) with t() keys present in both i18n JSON files.

---

### [src/cli/*] cache.py emits hardcoded English for user-facing progress, results and errors

- **File:** `src/cli/cache.py:75,82,102,115,117,152,157,177,199,205`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/cli/* (root, report, rule, workload, cache, siem, status, config, monitor, gui, menus) + src/main.py (legacy argparse) + src/rule_scheduler_cli.py

**Detail:** cache.py uses t() for some strings (cli_cache_err_no_db, cli_cache_retention_done) but hardcodes most operator-facing output: 'Invalid --since/--until date' (75/82), 'Backfilling {source} from ... to ...' (102), 'Done: N inserted, M duplicates' (115), 'Backfill failed: {exc}' (117), table headers Table('Source','Rows','Last ingested') (152), 'Status query failed' (157), Table('Setting','Days') (177), Table('Table','Rows deleted') (199), 'Retention failed' (205). Inconsistent and violates the CLI i18n guardrail.

**Evidence:**

```
console.print(f"[green]Done:[/green] {result.inserted} inserted, {result.duplicates} duplicates, {result.elapsed_seconds:.1f}s")
...
table = Table("Source", "Rows", "Last ingested")
```

**Suggested fix:** Route these strings through t() with keys added to both i18n files; keep the existing cli_cache_* keys as the naming pattern.

---

### [src/cli/*] rule.py table headers, prompts and save confirmation are hardcoded English

- **File:** `src/cli/rule.py:62-77,101-124,129`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/cli/* (root, report, rule, workload, cache, siem, status, config, monitor, gui, menus) + src/main.py (legacy argparse) + src/rule_scheduler_cli.py

**Detail:** list_rules hardcodes the Rich table title 'Monitoring Rules (...)' and column headers '#','Type','Name','Enabled','Threshold' (lines 62-67). edit_rule hardcodes the questionary prompts 'Rule name:', 'Enabled?', 'Threshold (blank to keep):', 'Save changes?' (lines 101-124). The save confirmation 'Rule {rule_id} saved.' (line 129) is hardcoded even though the adjacent abort message correctly uses t('cli_rule_aborted') (line 125), making the inconsistency explicit. Violates the CLI i18n guardrail.

**Evidence:**

```
click.echo(t("cli_rule_aborted"))   # line 125: i18n
...
cm.save()
click.echo(f"Rule {rule_id} saved.")   # line 129: hardcoded
```

**Suggested fix:** Replace the table title/headers, questionary prompt labels and the save confirmation with t() keys (e.g. cli_rule_saved) added to both i18n files.

---

### [src/cli/*] rule_scheduler_cli.py mixes t() with pervasive hardcoded English in the schedule list and prompts

- **File:** `src/rule_scheduler_cli.py:179,182,496,497,521,523,527,534,536,554,555,669,675`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/cli/* (root, report, rule, workload, cache, siem, status, config, monitor, gui, menus) + src/main.py (legacy argparse) + src/rule_scheduler_cli.py

**Detail:** The rule-scheduler CLI uses t() heavily but leaves many operator-facing strings hardcoded in the unified schedule view and menus: 'Commands' header (179), 'r=Refresh' (182), the 'EXPIRE' mode and 'Until ...' timing (496-497, 554-555), rule action labels 'Allow'/'Deny' (521-523), '(No description)' (527), '(Failed connection)' (536) and 'Wait' (534), and settings confirmations 'Rule Scheduler → ON/OFF' / 'Interval → Ns' (669, 675). For a zh_TW operator these render as untranslated English inline with translated columns, violating the CLI i18n guardrail. (Note: the English-forced note_msg strings pushed into PCE rule descriptions at lines 261/299/306/337 are deliberate and correctly use lang='en'.)

**Evidence:**

```
mode = f"{Colors.FAIL}EXPIRE    {Colors.ENDC}"
time_str = f"Until {c['expire_at'].replace('T', ' ')}"
...
type_str = f"{Colors.GREEN}{'Allow':<6}{Colors.ENDC}"
```

**Suggested fix:** Route the display-only literals (EXPIRE, Until, Allow/Deny, (No description), (Failed connection), Wait, Refresh, settings confirmations) through t() with keys in both i18n files; leave the lang='en' note_msg values as-is.

---

### [src/events/*] fetch_batch crashes (TypeError) when any polled event has a missing/unparseable timestamp

- **File:** `src/events/poller.py:101-104`
- **Category:** correctness | **Fix risk:** `safe-inline`
- **Subsystem:** src/events/* (PCE event poll / dedup / normalize / classify / throttle / runbooks)

**Detail:** latest_event_ts is computed as max() over a generator that yields parse_event_timestamp(...) for every raw event. parse_event_timestamp returns None for a missing or malformed timestamp. As soon as the batch contains >=2 events and at least one yields None, max() compares None against a datetime and raises `TypeError: '>' not supported between instances of 'NoneType' and 'datetime.datetime'`. This propagates out of fetch_batch -> analyzer._fetch_event_batch, aborting the entire poll cycle; because the offending event stays inside the time-window query (plus the 60s overlap), every subsequent poll keeps crashing until it ages out. The rest of the function already defends against None (the sort key uses `... or poll_started_at` and the dedup loop uses `... or poll_started_at`), proving None timestamps are an expected input here. I reproduced the TypeError directly with a 3-event batch where one timestamp is None. Note also that the server-side query bounds end_time at poll_started_at, so latest_event_ts is virtually always <= poll_started_at and the max() rarely changes next_watermark — i.e. this crash-prone line provides almost no benefit.

**Evidence:**

```
latest_event_ts = max(
    (parse_event_timestamp(item.get("timestamp")) for item in raw_events),
    default=None,
)  # reproduced: TypeError: '>' not supported between instances of 'NoneType' and 'datetime.datetime'
```

**Suggested fix:** Filter out None before max(): `latest_event_ts = max((ts for item in raw_events if (ts := parse_event_timestamp(item.get("timestamp"))) is not None), default=None)` (or build the list comprehension equivalent). This matches the defensive `or poll_started_at` handling used elsewhere in the same function.

---

### [src/events/*] normalize_event raises AttributeError when event['resource'] is a non-dict (e.g. list)

- **File:** `src/events/normalizer.py:271-289`
- **Category:** error-handling | **Fix risk:** `safe-inline`
- **Subsystem:** src/events/* (PCE event poll / dedup / normalize / classify / throttle / runbooks)

**Detail:** For user./request./agent./container_cluster. events the target-resolution branches call `(event.get("resource") or {}).get("user")` (and .get('agent'), .get('workload'), .get('container_cluster')). If event['resource'] is a non-dict truthy value such as a list, `list or {}` evaluates to the list and `.get` raises `AttributeError: 'list' object has no attribute 'get'`. This is inconsistent with the module's own defensive helpers: `_extract_resource_entry` (line 101) explicitly guards `isinstance(resource, dict)` and returns ('', {}) for non-dicts, and `_resource_name` (lines 65-71) explicitly handles `isinstance(resource, list)` — proving the author knows `event['resource']` can be a list/non-dict. The raw `.get()` calls bypass that guard. normalize_event is called in an unguarded per-event loop in analyzer.py:599-600 (and as a list comprehension in report/audit_generator.py:523), so a single such event aborts normalization of the whole batch / the whole audit report. I reproduced the crash with `{'event_type':'user.update','resource':[{'user':{'username':'bob'}}]}`.

**Evidence:**

```
if event_type.startswith(("user.", "request.")):
    target_type = "user"
    target_name = _pick_first(
        _resource_name((event.get("resource") or {}).get("user")),  # AttributeError if resource is a list
        ...
```

**Suggested fix:** Compute a guarded dict once at the top of normalize_event, e.g. `resource_dict = event.get("resource") if isinstance(event.get("resource"), dict) else {}`, and replace each `(event.get("resource") or {}).get(...)` with `resource_dict.get(...)`.

---

### [src/analyzer.py — B/L/R flow-to-rule matching engine, event/traffic ru] Alert 'criteria' text is hardcoded English, leaking into all alert channels regardless of language

- **File:** `src/analyzer.py:839-843`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/analyzer.py — B/L/R flow-to-rule matching engine, event/traffic rule evaluation, state management, monitor-cycle concurrency (plus src/rule_id.py)

**Detail:** _build_criteria_str() composes user-facing alert text from hardcoded English literals 'Threshold: > {n}' and 'Port:{p}'. The returned string is stored in alert_data['criteria'] (set at lines 781-787) and dispatched verbatim through reporter.add_traffic_alert / add_metric_alert. Confirmed it is rendered directly into Email HTML (src/reporter.py:1626,1671), text/LINE summaries (src/reporter.py:592,603) and the compact alert sections (src/reporter.py:986,998). So every Email/LINE/Webhook/Telegram/Teams alert shows English 'Threshold: > ... , Port:...' even when the deployment language is zh_TW, violating the AGENTS.md i18n guardrail that all alert text must use t(key, lang=lang).

**Evidence:**

```
def _build_criteria_str(self, rule):
    crit = [f"Threshold: > {rule['threshold_count']}"]
    if rule.get('port'):
        crit.append(f"Port:{rule['port']}")
    return ", ".join(crit)
```

**Suggested fix:** Thread the active language into the alert pipeline and build the criteria string from i18n keys, e.g. t('alert_criteria_threshold', lang=lang, n=rule['threshold_count']) and t('alert_criteria_port', lang=lang, p=rule['port']). Requires adding the two keys to both src/i18n_en.json and src/i18n_zh_TW.json and giving Analyzer/Reporter access to the configured language.

---

### [src/analyzer.py — B/L/R flow-to-rule matching engine, event/traffic ru] Unguarded int(pd)/int(num_connections) coercion of PCE flow data can abort the entire monitor cycle

- **File:** `src/analyzer.py:254-256`
- **Category:** error-handling | **Fix risk:** `safe-inline`
- **Subsystem:** src/analyzer.py — B/L/R flow-to-rule matching engine, event/traffic rule evaluation, state management, monitor-cycle concurrency (plus src/rule_id.py)

**Detail:** In check_flow_match the policy-decision field is converted with `if p is not None: flow_pd = int(p)` and has NO try/except, unlike the immediately following port (271-274) and proto (279-282) conversions which are guarded. If a single flow record carries a non-numeric/empty 'pd' (e.g. '' or a malformed cache-decoded value), int(p) raises ValueError. That exception propagates out of check_flow_match -> _run_rule_engine's flow loop -> run_analysis (none of which catch it), so run_monitor_cycle's outer except swallows it as 'Monitor cycle failed': the whole cycle aborts, NO traffic alerts dispatch and save_state never runs. The same unguarded pattern exists for conn_val = int(f.get('num_connections') or f.get('count', 1)) at lines 712-713 and 1121. One bad row from the PCE/cache thus silently kills a monitoring cycle.

**Evidence:**

```
p = f.get("pd")
raw_dec = str(f.get("policy_decision", "")).lower()
flow_pd = -1
if p is not None:
    flow_pd = int(p)   # no try/except, unlike port/proto below
```

**Suggested fix:** Guard the conversion like the adjacent port/proto checks: wrap `flow_pd = int(p)` in try/except (ValueError, TypeError) and fall through to the raw_dec string parsing (or default flow_pd = -1) on failure. Apply the same guard to the conn_val int() conversions at lines 712-713 and 1121.

---

### [PCE REST client] Five user-facing error i18n keys do not exist in either i18n catalog; status/error detail is silently lost

- **File:** `src/api_client.py:285, 289; src/api/traffic_query.py:461, 508, 648`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** PCE REST client (src/api_client.py, src/api/traffic_query.py, src/api/async_jobs.py, src/api/labels.py)

**Detail:** The calls t('api_get_events_failed', status=..., error=...), t('api_fetch_events_error', error=...), t('api_error_status', status=..., text=...), t('api_timeout'), and t('api_query_exception', error=...) reference keys that are absent from BOTH src/i18n_en.json and src/i18n_zh_TW.json (grep confirms 0 matches). None of these keys start with a strict prefix (api_ is not in strict_prefixes.json), so t() does NOT emit a [MISSING:key] marker — it falls through to _humanize_key_en/_humanize_key_zh, producing a generic label like 'Api Get Events Failed'. Crucially, the humanized fallback contains no {status}/{error}/{text} placeholders, so text.format(**kwargs) silently discards the interpolated diagnostics. Result: when event fetch fails, an async query errors, or a query times out, the CLI prints a vague humanized string with NO HTTP status code and NO error body — directly defeating the purpose of these error messages and violating the AGENTS.md i18n guardrail (keys must exist in both catalogs).

**Evidence:**

```
src/api_client.py:285  print(f"{Colors.FAIL}{t('api_get_events_failed', status=e.status, error=e.message[:500])}{Colors.ENDC}")  ;  traffic_query.py:461  print(t("api_error_status", status=status, text=text))  ;  grep -> api_get_events_failed/api_fetch_events_error/api_error_status/api_timeout/api_query_exception : 0 matches in both i18n json files
```

**Suggested fix:** Add the five keys to both src/i18n_en.json and src/i18n_zh_TW.json with the proper interpolation placeholders, e.g. EN 'api_error_status': 'API Error {status}: {text}', 'api_get_events_failed': 'Get Events failed: {status} - {error}', 'api_timeout': 'Timed out.', 'api_query_exception': 'Query error: {error}', 'api_fetch_events_error': 'Fetch events error: {error}', and curated zh_TW equivalents preserving the same {placeholders}.

---

### [PCE REST client] Native filters that fail to resolve are silently dropped from both the PCE query and the client-side filter, producing over-broad report data

- **File:** `src/api/traffic_query.py:605-649, 748-770`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** PCE REST client (src/api_client.py, src/api/traffic_query.py, src/api/async_jobs.py, src/api/labels.py)

**Detail:** fetch_traffic_for_report() builds query_spec = build_traffic_query_spec(filters) at line 754 and later filters downloaded rows with self._flow_matches_filters(r, query_spec.fallback_filters) (line 765). However execute_traffic_query_stream() internally calls _build_native_traffic_payload(), which moves any native filter that fails href resolution (e.g. a label/IP-list that is not in cache, a typo, or a stale name) into effective_spec.fallback_filters (residual) via _record_unresolved(). That effective_spec is local to execute_traffic_query_stream and is NOT returned to fetch_traffic_for_report. Consequently: (a) the unresolved filter is removed from the native PCE payload (so the PCE returns UNFILTERED traffic), and (b) the post-download client-side pass uses the original query_spec.fallback_filters, which never contained the unresolved native key — so it is never re-applied. Net effect: when a requested src_label/dst_label/ip filter cannot be resolved, the generated traffic/security report silently includes flows that do NOT match the requested filter, with only an info-level log line and no error surfaced to the user. For a security/audit tool this yields misleading (over-broad) results.

**Evidence:**

```
traffic_query.py:754  query_spec = self.build_traffic_query_spec(filters) ... :765  records = [r for r in records if self._flow_matches_filters(r, query_spec.fallback_filters)]   (uses pre-built spec, not effective_spec)  ;  traffic_query.py:619  c.last_traffic_query_diagnostics = dict(effective_spec.diagnostics)  (effective_spec never propagated back to the caller's filter pass)
```

**Suggested fix:** Propagate the residual/unresolved fallback filters out of execute_traffic_query_stream (e.g. expose effective_spec on the client like last_traffic_query_diagnostics already is, or have fetch_traffic_for_report read c.last_traffic_query_diagnostics['unresolved_native_filters'] and either apply them client-side or raise/warn loudly). At minimum, when unresolved_native_filters is non-empty, surface a visible warning to the user that the report is unfiltered for those keys instead of silently widening the result set.

---

### [src/siem] Dispatcher HEC transport ignores tls_verify config; production and test diverge

- **File:** `src/siem/dispatcher.py:199-202`
- **Category:** correctness | **Fix risk:** `safe-inline`
- **Subsystem:** src/siem (SIEM forwarder: formatters, transports, dispatcher, DLQ, web API)

**Detail:** The HEC branch builds SplunkHECTransport(url, token=dest_cfg.hec_token or "") and never forwards verify_tls=dest_cfg.tls_verify, so SplunkHECTransport always defaults to verify_tls=True. The tester (tester.py:65-69) DOES pass verify_tls=dest_cfg.tls_verify. Consequence: a dev-profile HEC destination with tls_verify=False (e.g. self-signed Splunk in a lab) is accepted by config validation and passes the 'Test' button, but real dispatch always verifies TLS and fails the handshake, quarantining all events. The forwarder cannot honor the operator's explicit tls_verify=False setting.

**Evidence:**

```
elif transport_type == "hec":
    from src.siem.transports.splunk_hec import SplunkHECTransport
    url = f"https://{host}:{port}"
    return SplunkHECTransport(url, token=dest_cfg.hec_token or "")  # verify_tls not passed
```

**Suggested fix:** return SplunkHECTransport(url, token=dest_cfg.hec_token or "", verify_tls=dest_cfg.tls_verify) — mirror the tester.

---

### [src/siem] DLQ replay never deletes the DeadLetter entry — repeated replays double-forward events and the DLQ list stays stale

- **File:** `src/siem/dlq.py:24-63`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** src/siem (SIEM forwarder: formatters, transports, dispatcher, DLQ, web API)

**Detail:** Both replay() and replay_ids() create new pending SiemDispatch rows from DeadLetter entries but never delete (or mark) the DeadLetter rows. After a successful replay the entry remains in the DLQ until purge() removes it (default 30 days), so the operator UI keeps showing it as quarantined. Worse, the replay endpoints are operator-triggered and non-idempotent: calling replay twice (or replay_ids on the same id twice) enqueues the same source record again, causing duplicate events to be forwarded to the SIEM. Quarantine itself does delete nothing here either, so there is no de-dup safeguard.

**Evidence:**

```
for entry in entries:
    s.add(SiemDispatch(source_table=entry.source_table, source_id=entry.source_id, destination=destination, status="pending", retries=0, queued_at=now))
    requeued += 1
# DeadLetter rows never removed
```

**Suggested fix:** Delete (or flag as 'replayed') the corresponding DeadLetter rows in the same transaction after enqueuing the replacement dispatch, so the DLQ reflects reality and a second replay click cannot re-enqueue the same record.

---

### [src/siem] Payload-build failures bypass the DLQ entirely — events are silently dropped with no replay path

- **File:** `src/siem/dispatcher.py:86-96`
- **Category:** error-handling | **Fix risk:** `needs-review`
- **Subsystem:** src/siem (SIEM forwarder: formatters, transports, dispatcher, DLQ, web API)

**Detail:** When _build_payload() returns None (e.g. a malformed timestamp makes _ts_to_epoch_ms raise ValueError, or orjson.loads fails on corrupt raw_json), _process_batch sets the dispatch row status='failed', last_error='payload_build_failed' and continues. Unlike transport-send failures, this path never writes a DeadLetter row, so the event is permanently lost: it is not retried, not visible in the DLQ, and has no replay route. The only trace is a log line. A single bad source record is therefore irrecoverably dropped from SIEM forwarding.

**Evidence:**

```
if payload is None:
    with self._sf.begin() as s:
        s.execute(update(SiemDispatch)...values(status="failed", last_error="payload_build_failed"))
    failed += 1
    continue  # no DeadLetter created
```

**Suggested fix:** Route payload-build failures through _quarantine() (with a placeholder payload preview) so they land in the DLQ and remain inspectable/replayable, instead of silently marking status='failed' with no DLQ record.

---

### [src/siem] mask_pii does not redact the flow username (un) / process name (pn) it forwards, contradicting its own non-PII claim

- **File:** `src/siem/mask.py:99-105`
- **Category:** security | **Fix risk:** `needs-review`
- **Subsystem:** src/siem (SIEM forwarder: formatters, transports, dispatcher, DLQ, web API)

**Detail:** mask_flow() is a no-op that returns the flow unchanged, documented as 'Traffic flows are non-PII by nature'. But the flow formatters emit un=service.user_name and pn=service.process_name (cef.py:175-180, normalized_json.py:117-122). un is the OS user that owns the connection — genuine user attribution. So a destination configured with mask_pii=True (e.g. an external/managed SIEM) still receives raw usernames in every traffic flow, defeating the privacy guarantee the feature advertises and contradicting the docstring.

**Evidence:**

```
def mask_flow(flow, *, mask_pii=False):
    """Traffic flows are non-PII by nature ..."""
    return flow
# yet cef.format_flow emits: un = svc.get("user_name") ... ext.append(f"un={_cef_escape(un)}")
```

**Suggested fix:** When mask_pii is True, deep-copy the flow and redact (or drop) the un/user_name and pn/process_name fields before formatting; update the docstring to stop asserting flows are PII-free.

---

### [src/pce_cache] ON CONFLICT DO NOTHING freezes long-lived flows: re-pulled active flows never refresh last_detected/bytes/flow_count

- **File:** `src/pce_cache/ingestor_traffic.py:70-72,140`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** src/pce_cache (SQLite WAL cache + ingestors/aggregator/retention/reader/subscriber)

**Detail:** flow_hash includes first_detected (ingestor_traffic.py:163-174), and _since_cursor re-pulls a 5-minute grace window. An active flow re-appears across polls with the SAME first_detected (hence same flow_hash) but a LARGER last_detected and higher bytes_in/out/flow_count. Insert uses `.on_conflict_do_nothing(index_elements=["flow_hash"])`, so the already-stored row is never updated. The cache therefore freezes each flow at its first sighting's counters and last_detected. Reports/aggregation that sum bytes_in+bytes_out (aggregator.py:40) systematically undercount bandwidth/volume for long-lived flows, and last_detected-based windowing under-reports flow recency — contradicting the 'grace window: re-pull to catch late-arriving flows' intent (the data is re-pulled but then dropped).

**Evidence:**

```
# _since_cursor: grace = wm.last_timestamp - timedelta(minutes=5)  # re-pull
...
.on_conflict_do_nothing(index_elements=["flow_hash"])  # re-pulled updated counters ignored
```

**Suggested fix:** Use on_conflict_do_update for the volatile columns (last_detected, bytes_in, bytes_out, flow_count, report_json) keyed on flow_hash, taking GREATEST(existing, excluded) for last_detected/bytes so re-pulls refresh rather than no-op. Note the RETURNING-driven SIEM enqueue must still fire only for genuinely new rows, so updates and inserts may need separating.

---

### [src/pce_cache] siem_dispatch table is never purged — unbounded growth (one row per flow x destination, kept forever as 'sent')

- **File:** `src/pce_cache/retention.py:17-47`
- **Category:** performance | **Fix risk:** `needs-review`
- **Subsystem:** src/pce_cache (SQLite WAL cache + ingestors/aggregator/retention/reader/subscriber)

**Detail:** Both ingestors enqueue a SiemDispatch row per new record per destination (ingestor_traffic.py:146-159, ingestor_events.py:112-126). The dispatcher only flips status pending->sent (siem/dispatcher.py:103); nothing ever deletes 'sent' rows. RetentionWorker.run_once purges pce_events, pce_traffic_flows_raw, pce_traffic_flows_agg and dead_letter, but NOT siem_dispatch. With up to 200k traffic flows per batch times each enabled SIEM destination, siem_dispatch grows without bound (long after the underlying raw flows are deleted at 7 days), inflating the SQLite file and slowing the ix_dispatch_* index maintenance and the SIEM status COUNT queries indefinitely.

**Evidence:**

```
RetentionWorker.run_once deletes PceEvent / PceTrafficFlowRaw / PceTrafficFlowAgg / DeadLetter — no `delete(SiemDispatch)` for status=='sent' rows older than a cutoff.
```

**Suggested fix:** Add a siem_dispatch purge to RetentionWorker.run_once, e.g. delete rows where status=='sent' AND sent_at < now - dispatch_retention_days (config-driven, default e.g. 7-14d), leaving pending/failed rows intact.

---

### [src/pce_cache] cover_state reports 'miss'/'partial' purely from retention-day cutoff, ignoring actually-present backfilled data

- **File:** `src/pce_cache/reader.py:26-36`
- **Category:** consistency | **Fix risk:** `needs-review`
- **Subsystem:** src/pce_cache (SQLite WAL cache + ingestors/aggregator/retention/reader/subscriber)

**Detail:** cover_state computes `cutoff = now - retention_days` and returns 'miss' if `end < cutoff` and 'partial' if `start < cutoff`, BEFORE consulting actual data. earliest_data_timestamp (used only in the 'full' branch) is documented to judge coverage by the ACTUAL data window 'not by when rows were inserted (which would defeat backfill workflows)'. But retention deletes raw by ingested_at, so backfilled rows with old last_detected legitimately live in the cache for up to traffic_raw_retention_days after backfill — yet a report for that old window still gets 'miss' from the cutoff check and bypasses the cache entirely. The cutoff-based short-circuit contradicts the stated backfill-friendly design and silently negates backfill for coverage decisions.

**Evidence:**

```
cutoff = datetime.now(timezone.utc) - timedelta(days=days)
if end < cutoff:
    return "miss"
if start < cutoff:
    return "partial"
```

**Suggested fix:** Base miss/partial on actual stored extent (earliest_data_timestamp / a MAX(last_detected)) rather than (or in addition to) the retention-day cutoff, so backfilled windows that physically exist in the cache are reported as covered.

---

### [reporter / alert dispatch] LINE 3-strike cooldown/throttle is dead: plugin re-instantiated on every dispatch resets failure state

- **File:** `src/alerts/plugins.py:103-179`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** reporter / alert dispatch (src/reporter.py, src/alerts/*)

**Detail:** LineAlertPlugin tracks _consecutive_failures / _cooldown_until as instance state and only enters cooldown after >=3 consecutive failures. But Reporter._get_output_plugin -> build_output_plugin constructs a brand-new plugin instance for every send_alerts call (reporter.py:94-99, 863), and within a single send_alerts each channel's send() is invoked exactly once (reporter.py:873). So _consecutive_failures can reach at most 1 before the instance is discarded; the >=3 threshold is never hit and the 300s cooldown never activates. The rate-limit protection the code advertises does not function across (or within) dispatches.

**Evidence:**

```
def __init__(self, config_manager): super().__init__(config_manager); self._consecutive_failures = 0; self._cooldown_until = 0.0  ... if self._consecutive_failures >= 3: self._cooldown_until = time.monotonic() + 300
```

**Suggested fix:** Persist the failure/cooldown counters outside the per-call plugin instance (e.g. cache plugin instances on the Reporter/ConfigManager keyed by channel name, or store the counters in a module/class-level structure keyed by target_id) so state survives across dispatches.

---

### [reporter / alert dispatch] Hardcoded English labels in live mail event-detail renderer violate the i18n guardrail

- **File:** `src/reporter.py:1130-1219`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** reporter / alert dispatch (src/reporter.py, src/alerts/*)

**Detail:** _render_vendor_event_detail_html is the renderer actually used to build the per-event detail cards in alert emails (called from _build_mail_html at line 1587). It emits user-visible labels as hardcoded English: 'Time'/'Status'/'Severity'/'Created By' (1131-1134), 'Endpoint'/'Source IP'/'HTTP Status'/'Target'/'Resource' (1143-1147), 'Field'/'Before'/'After' (1168), 'Parser Notes:' (1190), 'View on PCE' (1196), 'No action details' (1213), 'API Action' (1219), 'Resource Changes (...)'/'Notifications (...)' (1201/1207). AGENTS.md requires all user-visible text use t() keys, and matching keys already exist (alert_field_time, alert_status_*, alert_change_col_field/before/after, etc.). zh_TW recipients get English in every detailed alert email.

**Evidence:**

```
("Time", event.get("timestamp")), ("Status", ...), ("Severity", ...), ("Created By", ...) ; <th ...>Field</th><th ...>Before</th><th ...>After</th> ; >View on PCE</a>
```

**Suggested fix:** Replace each hardcoded label with the existing/added t() key (alert_field_time, alert_status_*, alert_change_col_field/col_before/col_after, plus new keys for 'View on PCE', 'Parser Notes', 'API Action', 'Resource Changes', 'Notifications', 'No action details'), adding any missing keys to both i18n_en.json and i18n_zh_TW.json.

---

### [reporter / alert dispatch] Hardcoded English direction/decision strings in traffic snapshot table (alert email body)

- **File:** `src/reporter.py:529-547`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** reporter / alert dispatch (src/reporter.py, src/alerts/*)

**Detail:** generate_pretty_snapshot_html renders the traffic snapshot table embedded in alert emails. While the column headers are i18n-resolved, the cell values are hardcoded English: direction 'Inbound'/'Outbound' (530-534) and the policy-decision pills 'Blocked'/'Potential'/'Allowed' (pd_map, 542-544). These are user-visible and violate the i18n guardrail for zh_TW operators.

**Evidence:**

```
direction = ("Inbound" if d.get("flow_direction")=="inbound" else "Outbound" if ...) ; pd_map = {"blocked": "...Blocked</span>", "potentially_blocked": "...Potential...", "allowed": "...Allowed..."}
```

**Suggested fix:** Resolve direction and decision labels through t() keys (e.g. t('snap_dir_inbound'/'snap_dir_outbound'), t('snap_decision_blocked'/'potential'/'allowed')), adding keys to both locale files.

---

### [reporter / alert dispatch] Teams card 'See web for details' action gated on orphan config key gui_base_url (never populated in production)

- **File:** `src/reporter.py:409`
- **Category:** consistency | **Fix risk:** `safe-inline`
- **Subsystem:** reporter / alert dispatch (src/reporter.py, src/alerts/*)

**Detail:** _build_teams_card reads a flat top-level config key gui_base_url to decide whether to render the Action.OpenUrl button. Everywhere else the GUI base URL comes from web_gui.public_url (or PCE-URL stripping) via _gui_base_url() (used by the mail CTAs at 1529). The key gui_base_url is not defined in config_models and is set nowhere in src — only in tests. So operators who configure web_gui.public_url still get a Teams card with no deep-link action; the button effectively never appears in production. Tests pass only because they inject the key directly, masking the drift.

**Evidence:**

```
base_url = self.cm.config.get("gui_base_url", "")  # while mail uses self._gui_base_url() reading web_gui.public_url
```

**Suggested fix:** Use base_url = self._gui_base_url() in _build_teams_card so the Teams deep link uses the same resolution (web_gui.public_url / stripped PCE URL) as the mail CTAs.

---

### [reporter / alert dispatch] send_alerts lang argument is not propagated to subject/body content; delivered alert text follows process-global language

- **File:** `src/reporter.py:773-841`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** reporter / alert dispatch (src/reporter.py, src/alerts/*)

**Detail:** send_alerts(lang=...) forwards _lang only to plugin.send(..., lang=_lang), which uses it for console dispatch status lines (mail_sent/mail_failed). The actual delivered content ignores it: the subject is built with t() and no lang (810,819,839,841), and every content builder (_build_mail_html, _build_line_message, _build_telegram_message, _build_teams_card, _build_webhook_payload and helpers) calls t() with no lang=, so they resolve against the process-global language via get_language(). AGENTS.md mandates t(key, lang=lang) for user-visible text and forbids set_language() in scheduler/concurrent code — meaning per-call language can only be honored by threading lang through. As written, the lang parameter is a no-op for everything the recipient actually sees; under a multi-language/concurrent scheduler the body can render in the wrong language.

**Evidence:**

```
results.append(plugin.send(self, subj, lang=_lang))  # but subj = t("mail_subject_test") / t("mail_subject_structured", ...) and _build_mail_html etc. call t(key) with no lang
```

**Suggested fix:** Thread lang into subject construction and all _build_* content builders (pass lang=_lang down to every t() call in the content path) so delivered subject/body honor the requested language instead of global state.

---

### [reporter / alert dispatch] Telegram HTML digest truncation at a fixed byte offset can split a tag/entity and cause Telegram to reject the message

- **File:** `src/reporter.py:1102-1107`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** reporter / alert dispatch (src/reporter.py, src/alerts/*)

**Detail:** When the rendered Telegram digest exceeds 3500 chars it is hard-cut with body[:3300].rstrip() and a footer appended. The body contains parse_mode=HTML markup (<b>, <code>, <a href=...>). A cut at an arbitrary offset can land inside a tag or split an HTML entity, producing malformed HTML. Telegram's sendMessage with parse_mode=HTML rejects unbalanced/partial entities with HTTP 400, so an oversized alert digest is dropped entirely rather than truncated-but-delivered.

**Evidence:**

```
if len(body) > 3500: cut = body[:3300].rstrip(); more = total_issues - kept_total; footer = ...; body = f"{cut}\n\n{footer}"
```

**Suggested fix:** Truncate on safe boundaries (cut at the last newline before the limit so whole <a>/<b> lines survive) or strip/close dangling tags before appending the footer; alternatively assemble the digest line-by-line and stop before exceeding the limit so no tag is split.

---

### [Entry dispatch, version management, packaging & install/build scripts] Windows migration uses bare `nssm` from PATH, ignoring the bundled deploy\nssm.exe — aborts on air-gapped hosts

- **File:** `scripts/install.ps1:35-42, 54, 58-62, 122-126`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** Entry dispatch, version management, packaging & install/build scripts

**Detail:** Invoke-MigrateFromUnderscoreRoot (and its helper Invoke-NssmSet) reconfigure the service by calling the call operator on a bare command name: `& nssm set @NssmArgs` and `& nssm get IllumioOps AppDirectory`. This resolves nssm only via PATH. The entire offline-bundle design assumes nssm is shipped in the bundle and NOT on PATH: build_offline_bundle.sh bundles nssm.exe into deploy/, deploy/install_service.ps1 resolves $NSSM from -NssmPath -> $PSScriptRoot\nssm.exe (deploy\nssm.exe) -> PATH, and preflight.ps1 explicitly PASSes when nssm is only found 'in bundle'. On an air-gapped host with nssm present only at deploy\nssm.exe, every `& nssm ...` in the migration throws a terminating CommandNotFoundException (not even caught by the $LASTEXITCODE check in Invoke-NssmSet, and not suppressed by `2>$null` on the `nssm get` call), aborting the C:\illumio_ops -> C:\illumio-ops upgrade midway. Because this only runs on the underscore->hyphen migration of an existing install, it fails exactly the offline-upgrade scenario the bundle targets.

**Evidence:**

```
function Invoke-NssmSet { param([string[]]$NssmArgs)  & nssm set @NssmArgs ... }  $currentAppDir = ((& nssm get IllumioOps AppDirectory 2>$null) -join "").Trim()  ## vs deploy/install_service.ps1 which resolves $NSSM = deploy\nssm.exe before use
```

**Suggested fix:** Resolve the nssm executable once at the top of install.ps1 the same way install_service.ps1 does (prefer $SRC\deploy\nssm.exe, then Get-Command nssm) into a $NSSM variable, and replace every bare `& nssm` in Invoke-NssmSet and the `nssm get` call with `& $NSSM`. Fail with a clear error if neither is found.

---

### [Security] Generic Webhook plugin leaks webhook URL (potential embedded secret) into persisted + dashboard-exposed dispatch history

- **File:** `src/alerts/plugins.py:199-214`
- **Category:** security | **Fix risk:** `needs-review`
- **Subsystem:** Security (auth/secrets/TLS/web) + Code-vs-Doc drift

**Detail:** WebhookAlertPlugin.send() returns the raw configured webhook_url in the dispatch-result dict's `target` field on every path (success/failed). These results are persisted to logs/state.json dispatch_history via reporter.py:891 -> persist_dispatch_results -> StatsTracker.record_dispatch (src/events/stats.py:138 copies result['target'] into the stored entry and timeline), and the raw entries are returned to the admin browser by the dashboard overview API (src/gui/routes/dashboard.py:164 `recent: last24[-5:]`). The sibling TeamsAlertPlugin deliberately calls redact_webhook_url() for exactly this reason, citing README L-12: 'channel secrets must never reach logs, debug output, or persisted dispatch results' (plugins.py:28-30, 271-272). Generic webhook URLs commonly embed secret tokens in the path/query (Slack hooks.slack.com/services/T../B../XXXX, Discord webhook tokens), so the generic plugin's failure to redact persists those secrets to disk and surfaces them in an API response — inconsistent with the project's stated security rule and with the Teams plugin.

**Evidence:**

```
return {"channel": "webhook", "status": "success", "target": webhook_url}  (plugins.py:199; same raw webhook_url at 201/208/211/214) vs Teams: safe_target = redact_webhook_url(webhook_url)  (plugins.py:272)
```

**Suggested fix:** Mirror the Teams plugin: compute safe_target = redact_webhook_url(webhook_url) once and use it for the `target` field in all four return dicts of WebhookAlertPlugin.send(); keep the real URL only for the actual urllib request. Optionally scrub the URL from the `error` strings too.

---

### [Security] Telegram and Teams alert channels implemented but undocumented in README and user-guide

- **File:** `README.md:9, 45, 63, 71`
- **Category:** doc-drift | **Fix risk:** `needs-review`
- **Subsystem:** Security (auth/secrets/TLS/web) + Code-vs-Doc drift

**Detail:** README repeatedly states the tool supports only three alert channels — 'multi-channel alerting (Email, LINE, Webhook)' (line 9), Highlights SIEM line, 'reporter.py — Multi-channel alert dispatch (SMTP, LINE, Webhook)' (line 63), and 'alerts/ — Alert plugins (mail, LINE, webhook)' (line 71). However src/alerts/plugins.py registers fully-working TelegramAlertPlugin (name='telegram', line 218) and TeamsAlertPlugin (name='teams', line 263), both auto-registered via AlertOutputPlugin.__init_subclass__ and dispatched by reporter.py, and Teams/Telegram are user-configurable via the CLI alert menu (src/cli/menus/alert.py:36-118). docs/user-guide/alerts-and-quarantine.md 'Notification channels' section (lines 134-168) likewise documents only mail/line/webhook. Users cannot discover the Telegram/Teams channels from the docs, contradicting shipped functionality.

**Evidence:**

```
plugins.py: class TelegramAlertPlugin ... name = "telegram"; class TeamsAlertPlugin ... name = "teams". README line 9: 'multi-channel alerting (Email, LINE, Webhook)'. user-guide lists only '### Email (SMTP)', '### LINE', '### Webhook'.
```

**Suggested fix:** Add Telegram and Teams to README highlights/structure (lines 9/45/63/71) and add '### Telegram' and '### Microsoft Teams' subsections to docs/user-guide/alerts-and-quarantine.md (+ _zh) documenting required config fields (alerts.telegram_bot_token/telegram_chat_id, alerts.teams_webhook_url) and the L-12 redaction note.

---

## LOW (39)

### [src/report report assembly & scheduling] Standalone XLSX generators emit hardcoded English sheet names/labels (no i18n)

- **File:** `src/report/report_generator.py:877-983`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/report report assembly & scheduling (report_generator, audit_generator, policy_usage_generator, report_scheduler, policy_resolver_report, traffic facades)

**Detail:** generate_traffic_xlsx() (and the parallel generate_audit_xlsx() in audit_generator.py:799-878, generate_policy_usage_xlsx() in policy_usage_generator.py:566-642) hardcode all sheet names and notes in English ('Executive Summary', 'Policy Decisions', 'Uncovered Flows', 'KPI', 'Value', 'No data', 'Executive summary unavailable', etc.). These are report deliverables, which the i18n guardrail requires to be localized. The XLSX produced is English-only regardless of lang. Lower severity because these are direct-call helpers (the main pipeline xlsx path is export_xlsx), but it is a genuine localization gap.

**Evidence:**

```
ws = wb.create_sheet("Executive Summary")
... ws.append(["KPI", "Value"]) ... ws.append(["Note", "Executive summary unavailable"])
```

**Suggested fix:** If these helpers are user-facing, thread a lang parameter and resolve sheet/column labels via t(); if they are dead/legacy, confirm and remove. At minimum document that XLSX exports are English-only so the gap is intentional and tracked.

---

### [src/report report assembly & scheduling] Schedules with timezone 'local' fire on UTC wall-clock, not server-local time

- **File:** `src/report_scheduler.py:31-40, 149-165`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** src/report report assembly & scheduling (report_generator, audit_generator, policy_usage_generator, report_scheduler, policy_resolver_report, traffic facades)

**Detail:** For tz='local', _now_in_schedule_tz returns UTC-aware now, and should_run then compares `now.hour`/`now.minute` against the schedule's configured hour/minute. So a schedule set to run at 08:00 'local' actually fires at 08:00 UTC. The function name and docstring ('adjusted to the configured schedule timezone') imply server-local time, but the implementation deliberately uses UTC (commented as DST-avoidance). This is a semantic mismatch that will surprise operators on non-UTC servers. (In practice the 'local' path is currently unusable due to the aware/naive crash above; fixing that without addressing this leaves the hour/minute semantics wrong.)

**Evidence:**

```
if not tz_str or tz_str == 'local':
    # Fall back to UTC-aware (avoids naive datetime / DST ambiguity)
    return datetime.datetime.now(datetime.timezone.utc)
```

**Suggested fix:** Decide the intended semantics: either return true server-local time for 'local' (datetime.datetime.now(), naive) so hour/minute matching means local wall-clock, or rename/document 'local' as meaning UTC. Align with the fix for the aware/naive crash.

---

### [src/report/exporters] CSV raw-data export does not neutralize formula-injection payloads

- **File:** `src/report/exporters/csv_exporter.py:76`
- **Category:** security | **Fix risk:** `needs-review`
- **Subsystem:** src/report/exporters (HTML/CSV/XLSX report rendering)

**Detail:** CsvExporter writes DataFrames with `df.to_csv(buf, index=False)`, which performs no neutralization of cells beginning with = + - @. The bundled CSVs contain untrusted PCE values (hostnames, labels, process/user names); opening them in Excel/Sheets can execute injected formulas. Lower severity than the xlsx case because these are raw-data ZIP attachments aimed at analysts, but the exposure is real.

**Evidence:**

```
csv_exporter.py:76  `df.to_csv(buf, index=False)`
```

**Suggested fix:** Pre-process string columns to prefix a leading = + - @ with a single quote (or document/strip the risk), or write via a csv writer that escapes formula-leading cells.

---

### [src/report/exporters] Navigation chrome 'Contents' and 'Print / PDF' are hardcoded English in every report exporter

- **File:** `src/report/exporters/html_exporter.py:610-612`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/report/exporters (HTML/CSV/XLSX report rendering)

**Detail:** The report TOC heading 'Contents' and the 'Print / PDF' button label are hardcoded English literals, identically duplicated across html_exporter.py (610-612), audit_html_exporter.py (169,176), ven_html_exporter.py (99,107) and policy_usage_html_exporter.py (174,183). They are visible UI text in every generated report including zh_TW, violating the i18n guardrail.

**Evidence:**

```
html_exporter.py:610-612  `'<h3>Contents</h3>' ... '<button class="print-btn" onclick="window.print()">Print / PDF</button>'`
```

**Suggested fix:** Introduce shared i18n keys (e.g. rpt_nav_contents, rpt_nav_print_pdf) in both i18n JSON files and resolve via t() in all four exporters.

---

### [src/report/exporters] 'No data' fallback text in attack-summary is hardcoded English

- **File:** `src/report/exporters/html_exporter.py:764, 780`
- **Category:** i18n | **Fix risk:** `safe-inline`
- **Subsystem:** src/report/exporters (HTML/CSV/XLSX report rendering)

**Detail:** _attack_summary_html returns the literal '<p class="note">No data</p>' for empty boundary-breach / pivot / blast-radius / blind-spot sections and for an empty action matrix. This English string surfaces in the security-risk report (including zh_TW) when a sub-section is empty, contrary to the i18n guardrail (the rest of the report uses STRINGS keys such as rpt_no_data).

**Evidence:**

```
html_exporter.py:764  `return '<p class="note">No data</p>'` ; :780 `... or '<p class="note">No data</p>'`
```

**Suggested fix:** Use an existing key (e.g. _s('rpt_no_data')) for both empty fallbacks instead of the literal string.

---

### [src/report/exporters] detail_level constructor/_build parameter is silently ignored (dead parameter)

- **File:** `src/report/exporters/html_exporter.py:402-407, 441-443`
- **Category:** dead-code | **Fix risk:** `needs-review`
- **Subsystem:** src/report/exporters (HTML/CSV/XLSX report rendering)

**Detail:** Every exporter accepts a detail_level argument but immediately overrides it with the module constant: __init__ sets `self._detail_level = _REPORT_DETAIL_LEVEL` ignoring the passed value (line 407), and _build sets `detail_level = _REPORT_DETAIL_LEVEL` ignoring its parameter (line 443). The same pattern repeats in audit_html_exporter.py (131,160), ven_html_exporter.py (70,87) and policy_usage_html_exporter.py (141,158). Callers passing detail_level='summary'/'standard' get no effect — section visibility is always computed at 'full'. This is a misleading API: the parameter looks functional but is inert.

**Evidence:**

```
html_exporter.py:407 `self._detail_level = _REPORT_DETAIL_LEVEL` (param `detail_level` discarded) ; :443 `detail_level = _REPORT_DETAIL_LEVEL`
```

**Suggested fix:** Either honor the passed detail_level (assign `self._detail_level = detail_level` and use it) or remove the dead parameter from the constructor/_build signatures and document that reports are always rendered at full detail.

---

### [src/report/rules] mod15 articulation-point detection uses unbounded recursion; large lateral graphs raise RecursionError that is silently swallowed

- **File:** `src/report/analysis/mod15_lateral_movement.py:37-73`
- **Category:** error-handling | **Fix risk:** `needs-review`
- **Subsystem:** src/report/rules (R01–R05), src/report/rules_engine.py (B/L rules), src/report/analysis/* (policy_resolver, mod_vuln, mod03_uncovered_flows, mod02_policy_decisions, mod04, mod12, mod13, mod15, attack_posture, mod_draft_*)

**Detail:** _articulation_points runs a recursive Tarjan DFS (dfs() calls itself per edge). Recursion depth scales with the size of the connected component of the undirected app|env graph. For large estates with a long chain / deep connected component of app|env nodes (default CPython limit ~1000 frames), this raises RecursionError. _run_modules catches all module exceptions and stores {'error': str(e)}, so the entire Module 15 lateral-movement analysis (bridge nodes, attack paths, posture items feeding mod12) is silently dropped from the report with only a warning log — a security report quietly losing its lateral-movement section.

**Evidence:**

```
def dfs(at): ... dfs(to) ...; _run_modules: except Exception as e: results[mod_id] = {'error': str(e)}.
```

**Suggested fix:** Convert _articulation_points to an iterative (explicit-stack) Tarjan, or raise the recursion limit guarded by component size; alternatively cap graph size with an explicit, surfaced note rather than letting it crash the whole module.

---

### [src/report/rules] mod03 uncovered-flow classifier treats NaN src_managed as managed (NaN is truthy)

- **File:** `src/report/analysis/mod03_uncovered_flows.py:105-110`
- **Category:** correctness | **Fix risk:** `safe-inline`
- **Subsystem:** src/report/rules (R01–R05), src/report/rules_engine.py (B/L rules), src/report/analysis/* (policy_resolver, mod_vuln, mod03_uncovered_flows, mod02_policy_decisions, mod04, mod12, mod13, mod15, attack_posture, mod_draft_*)

**Detail:** _classify does `if not row['src_managed']: return 'unmanaged_source'`. When src_managed is NaN (possible from the CSV-sourced path where the column may be float/NaN rather than the bool produced by the API flatten), `not float('nan')` evaluates to False, so NaN rows are misclassified as managed and never bucketed as 'unmanaged_source'. This skews the by_recommendation breakdown and the unmanaged remediation guidance for CSV-fed reports.

**Evidence:**

```
def _classify(row): if not row['src_managed']: return 'unmanaged_source' ...
```

**Suggested fix:** Coerce explicitly: treat missing/NaN as unmanaged, e.g. `if row.get('src_managed') is not True:` or normalize src_managed to a real bool (fillna(False)) before classify.

---

### [GUI routes] Unguarded int() on user-supplied query params raises 500 instead of 400

- **File:** `src/gui/routes/rule_scheduler.py:81-82 (rs_rulesets); admin.py:37 (api_log_get)`
- **Category:** error-handling | **Fix risk:** `safe-inline`
- **Subsystem:** GUI routes (src/gui/__init__.py app shell + src/gui/routes/* blueprints: auth, admin, dashboard, events, reports, rules, rule_scheduler, actions, config)

**Detail:** rs_rulesets parses page/size with int(request.args.get('page', 1)) / int(request.args.get('size', 50)) with no try/except; a non-numeric ?page=foo raises ValueError, caught only by the global handler and returned as a generic 500. Similarly admin.py:37 `n = min(int(request.args.get("n", 200)), 500)` raises on non-numeric n and applies no lower bound (a negative n flows into ml.get_recent(n)). Other handlers in events.py defensively wrap int() parsing in try/except and clamp; these do not.

**Evidence:**

```
rule_scheduler.py:81 `page = int(request.args.get('page', 1))`; admin.py:37 `n = min(int(request.args.get("n", 200)), 500)`.
```

**Suggested fix:** Wrap these int() conversions in try/except (ValueError, TypeError) with sane defaults and clamp to a valid range (e.g. page>=1, size in 1..200, n in 1..500), mirroring the events.py handlers.

---

### [GUI routes] rs_schedule_delete dereferences request.get_json() without a null/empty fallback

- **File:** `src/gui/routes/rule_scheduler.py:338-339`
- **Category:** error-handling | **Fix risk:** `safe-inline`
- **Subsystem:** GUI routes (src/gui/__init__.py app shell + src/gui/routes/* blueprints: auth, admin, dashboard, events, reports, rules, rule_scheduler, actions, config)

**Detail:** rs_schedule_delete does `data = request.get_json()` then `hrefs = data.get('hrefs', [])`. Unlike sibling handlers that use `request.get_json() or {}` / `request.json or {}`, this lacks the `or {}` fallback. A POST with a JSON null body (or otherwise yielding None) makes data None, so data.get('hrefs') raises AttributeError -> generic 500. Minor robustness gap relative to the rest of the blueprint.

**Evidence:**

```
rule_scheduler.py:338  `data = request.get_json()`  then 339 `hrefs = data.get('hrefs', [])`.
```

**Suggested fix:** Change to `data = request.get_json(silent=True) or {}` to match the other handlers.

---

### [GUI shared helpers, templates, and client-side JS] Hardcoded English error/labels in Integrations panes (i18n)

- **File:** `src/static/js/integrations.js:92,567,1094`
- **Category:** i18n | **Fix risk:** `safe-inline`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** Three failure paths write untranslated English directly into innerHTML: 'Failed to load cache data: ' (l.92), 'Failed to load SIEM data: ' (l.567), and 'Failed to load: ' in the DLQ table (l.1094). Because these strings are injected as literal HTML (not via a data-i18n attribute that applyI18n would later replace), they never localize.

**Evidence:**

```
el.innerHTML = '<p style="color:red">Failed to load cache data: ' + escapeAttr(String(err)) + '</p>';
```

**Suggested fix:** Use _t('gui_it_load_failed_cache') etc. for the message prefix and add the keys to both locale files; keep escapeAttr on the error detail.

---

### [GUI shared helpers, templates, and client-side JS] Hardcoded 'Draft ' prefix in quarantine policy-decision badge (i18n + inconsistency)

- **File:** `src/static/js/quarantine.js:447`
- **Category:** i18n | **Fix risk:** `safe-inline`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** makePdBadge() builds the draft badge prefix as a literal `'<span ...>Draft </span>'`. dashboard.js renders the equivalent draft prefix via _t('gui_draft') (dashboard.js:1911), so this is both an i18n-guardrail violation and an inconsistency between the two tables: the same draft indicator shows localized in one view and English-only in the other.

**Evidence:**

```
const prefix = isReported ? '' : '<span style="font-size:9px;opacity:0.8;">Draft </span>';
```

**Suggested fix:** Use `_t('gui_draft')` (the key already exists and is used in dashboard.js) instead of the literal 'Draft '.

---

### [GUI shared helpers, templates, and client-side JS] Hardcoded English in rules table aria/title and condensed field prefixes (i18n)

- **File:** `src/static/js/rules.js:83-99`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** renderRules() emits several untranslated user-visible strings: aria-label/title 'Edit Rule' (l.96), the rule-switch title 'Enabled'/'Disabled' (l.99), and the condensed filter-column prefixes 'Event:', 'PD:', 'Port:', 'Src:'/'Dst:', 'SrcIP:'/'DstIP:', 'Suppressed:', 'Match:' (l.83-95). These are shown in the Rules table irrespective of selected language.

**Evidence:**

```
const editBtn = `<button ... aria-label="Edit Rule" title="Edit Rule">...`;
...title="${isEnabled ? 'Enabled' : 'Disabled'}"...
if (r.port) f.push('Port:' + r.port);
```

**Suggested fix:** Replace each literal with _t() lookups (gui_edit_rule, gui_enabled/gui_disabled, and per-prefix keys) and add them to both locale JSON files.

---

### [GUI shared helpers, templates, and client-side JS] Hardcoded result-suffix strings in report toasts and traffic KPI ('flows'/'events')

- **File:** `src/static/js/dashboard.js:970,1072`
- **Category:** i18n | **Fix risk:** `safe-inline`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** Report completion messages embed hardcoded English units: `${s.record_count} flows` (_pollTrafficJob, l.970) and `${r.record_count} events` (_doGenerateAudit, l.1072). quarantine.js:362 likewise hardcodes the 'flows' suffix in the traffic KPI strip via setKpi('tw-kpi-flows', fmtInt(flows), 'flows'), even though _t('gui_flows') exists and is used elsewhere (quarantine.js:417). These render English regardless of language.

**Evidence:**

```
const msg = `${s.record_count} flows`;
...
const msg = `${r.record_count} events`;
```

**Suggested fix:** Use a localized template, e.g. _t('gui_toast_flows_count').replace('{n}', s.record_count), and use _t('gui_flows') for the KPI suffix; add any missing keys to both locale files.

---

### [GUI shared helpers, templates, and client-side JS] Half-hour timezone offsets are truncated in scheduler hour conversion

- **File:** `src/static/js/utils.js:102-108`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** _utcToLocal()/_localToUtc() apply Math.floor() to the result of adding/subtracting the timezone offset. For half-hour zones (the option list includes UTC+5.5 and UTC+9.5), a 0.5h offset is silently dropped when converting whole-hour scheduler values, so an operator in UTC+5.5 sees/saves an hour that is 30 minutes off versus what they intend. Whole-hour zones are unaffected.

**Evidence:**

```
function _localToUtc(localHour) {
  const off = _tzOffsetHours();
  return Math.floor(((localHour - off) % 24 + 24) % 24);
}
```

**Suggested fix:** Either drop the half-hour options from _TZ_OPTIONS, or carry minutes through the conversion (return {hour, minute}) so half-hour offsets are represented rather than floored away.

---

### [src/cli/*] Legacy argparse report path and report.py raise hardcoded-English ClickExceptions

- **File:** `src/main.py:642-666 (and src/cli/report.py:117,126,175,196,232,272,642-644-style messages)`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/cli/* (root, report, rule, workload, cache, siem, status, config, monitor, gui, menus) + src/main.py (legacy argparse) + src/rule_scheduler_cli.py

**Detail:** User-facing CLI error/validation messages are hardcoded English rather than t() keys: in src/main.py '--email is only supported for traffic reports', '--source csv is not supported for audit reports', '--source csv is not supported for ven_status reports' (lines 642-660); in src/cli/report.py 'No data for report' (126/175/196/232), '--file is required when --source csv is used' (117/222), and the deprecation note 'report traffic --profile is deprecated...' (272). These reach the operator on stdout/stderr and violate the CLI i18n guardrail.

**Evidence:**

```
raise click.ClickException("--email is only supported for traffic reports")
...
raise click.ClickException("No data for report")
```

**Suggested fix:** Move these literals to t() keys defined in both i18n JSON files; for ClickException, pass the translated string.

---

### [src/cli/*] siem.py table titles and column headers are hardcoded English

- **File:** `src/cli/siem.py:173-178,282-287`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/cli/* (root, report, rule, workload, cache, siem, status, config, monitor, gui, menus) + src/main.py (legacy argparse) + src/rule_scheduler_cli.py

**Detail:** siem.py correctly uses cli_siem_* keys for messages but hardcodes the Rich tables: Table(title='SIEM Dispatch Status') with columns 'Destination','Pending','Sent','Failed','DLQ' (lines 173-178) and Table(title=f'DLQ — {dest}') with columns 'ID','Source','Retries','Error','Quarantined At' (lines 282-287). These are operator-facing and should use i18n keys.

**Evidence:**

```
table = Table(title="SIEM Dispatch Status")
table.add_column("Destination")
table.add_column("Pending", justify="right")
```

**Suggested fix:** Replace the table titles and column headers with t() keys added to both i18n files.

---

### [src/cli/*] Bare-invocation deprecation warning in root group is hardcoded English

- **File:** `src/cli/root.py:57-61`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/cli/* (root, report, rule, workload, cache, siem, status, config, monitor, gui, menus) + src/main.py (legacy argparse) + src/rule_scheduler_cli.py

**Detail:** When 'illumio-ops' is run with no subcommand, the deprecation warning text is hardcoded English passed to echo_warning. This is operator-facing CLI output and should use an i18n key like the rest of the cli_* namespace.

**Evidence:**

```
echo_warning(ctx, "Bare 'illumio-ops' invocation is deprecated; use 'illumio-ops shell' to launch the interactive menu explicitly.")
```

**Suggested fix:** Replace the literal with t('cli_bare_invocation_deprecated', lang=...) added to both i18n files.

---

### [src/events/*] runbooks.py is dead production code (only referenced by a test) and hardcodes English operator-facing text

- **File:** `src/events/runbooks.py:1-313`
- **Category:** dead-code | **Fix risk:** `needs-review`
- **Subsystem:** src/events/* (PCE event poll / dedup / normalize / classify / throttle / runbooks)

**Detail:** RUNBOOK_CATEGORIES / runbook_for are imported only by tests/test_event_reference_coverage.py; no production module imports them, and __init__.py does not export them. The live runbook/severity/remediation data path is src/events/reference.py (load_reference) backed by docs/_meta/illumio-event-reference.json, consumed by src/gui/routes/events.py and src/alerts/template_utils.py. So this module is a parallel, unwired catalog. Beyond being dead, every `response` block and `severity_hint` is hardcoded English (e.g. 'CRITICAL: VEN tampering or clone detected...'); if it were ever wired into the GUI/alerts it would violate the AGENTS.md i18n guardrail (all operator-visible text must come from t(key) with keys present in both i18n_en.json and i18n_zh_TW.json). Flagging rather than deleting per surgical-change rules.

**Evidence:**

```
grep shows the only importer is tests/test_event_reference_coverage.py: `from src.events.runbooks import runbook_for`; production uses src/events/reference.py instead. Strings like `"CRITICAL: VEN tampering or clone detected.\n..."` are hardcoded English.
```

**Suggested fix:** Confirm with the team, then either delete runbooks.py and its test (since reference.py is the authoritative source) or wire it through reference.py / i18n keys. Do not leave a second, untranslated runbook catalog that can drift from the JSON reference.

---

### [src/analyzer.py — B/L/R flow-to-rule matching engine, event/traffic ru] run_debug_mode CLI output mixes hardcoded English labels with i18n keys

- **File:** `src/analyzer.py:1271-1275,1320`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** src/analyzer.py — B/L/R flow-to-rule matching engine, event/traffic rule evaluation, state management, monitor-cycle concurrency (plus src/rule_id.py)

**Detail:** run_debug_mode() is interactive user-facing CLI output (the comment at 1149-1151 states stdout is the contract for the CLI menu and GUI debug API). Most lines correctly use t(), but several status labels are hardcoded English: 'Health Check:' (1271), 'Status:' (1272), 'Details:' (1275) and 'Value:' (1320). These appear to the user untranslated, contradicting the i18n guardrail for CLI output. (Note: the dual logger.info(t(...)) + logger.info('English') pattern elsewhere in this file is intentional dual-logging and is excluded.)

**Evidence:**

```
print(f"  -> Health Check: {health_type}")
print(f"  -> Status: {h_status if h_status is not None else 'N/A'}")
...
print(f"     [{i+1}] {key} Value: {m.get('_metric_fmt')} (PD:{m.get('policy_decision')})")
```

**Suggested fix:** Replace the hardcoded 'Health Check:', 'Status:', 'Details:', 'Value:' labels with t('...') keys (with inline default= for safety) and add the keys to both i18n_en.json and i18n_zh_TW.json. Low blast radius but touches several lines.

---

### [src/analyzer.py — B/L/R flow-to-rule matching engine, event/traffic ru] Alert criteria advertises '> threshold' but traffic/volume rules trigger at '>=' threshold

- **File:** `src/analyzer.py:840`
- **Category:** doc-drift | **Fix risk:** `needs-review`
- **Subsystem:** src/analyzer.py — B/L/R flow-to-rule matching engine, event/traffic rule evaluation, state management, monitor-cycle concurrency (plus src/rule_id.py)

**Detail:** _build_criteria_str always renders 'Threshold: > {n}'. However in _dispatch_alerts the non-bandwidth (traffic count / volume) branch fires when `val >= threshold` (line 770), and run_debug_mode mirrors this with `val >= threshold` for non-bandwidth types (line 1309). Only bandwidth uses a strict '>'. So a traffic/volume rule with threshold N fires at exactly N while the alert text tells the operator it requires more than N — an off-by-one misrepresentation of the firing condition shown in every alert.

**Evidence:**

```
crit = [f"Threshold: > {rule['threshold_count']}"]   # always '>'
# but _dispatch_alerts non-bandwidth: if val >= threshold: is_trigger = True
```

**Suggested fix:** Make the operator displayed in the criteria depend on rule type: use '>' for bandwidth and '>=' (≥) for traffic/volume, matching the actual comparison in _dispatch_alerts. Fold this into the i18n criteria rework above so the operator and value come from a single source of truth.

---

### [PCE REST client] Hardcoded English progress strings printed to the CLI bypass i18n

- **File:** `src/api/traffic_query.py:1037, 1055, 1106, 1148-1149, 1172; src/api/async_jobs.py:295, 304`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** PCE REST client (src/api_client.py, src/api/traffic_query.py, src/api/async_jobs.py, src/api/labels.py)

**Detail:** batch_get_rule_traffic_counts() emits user-visible progress via the on_progress callback, which policy_usage_generator._on_progress prints to stdout (print(f"\r  {msg:<70}")). The messages are hardcoded English: 'Reused {n}/{t} cached rule summaries...', 'Submitting {n}/{m}...', 'Polling {n} jobs (0/{n} done)...', 'Polling... {a}/{b} done, {c} pending', 'Downloading {n}/{m}...'. Similarly AsyncJobManager._wait_for_async_query feeds the rich Progress widget hardcoded English: 'Polling async query...' and 'Async query: {state} (poll {n}/{m})' (shown on a TTY). Per the AGENTS.md i18n guardrail, all user-visible CLI output must use t(key, lang=lang).

**Evidence:**

```
traffic_query.py:1037  _progress(f"Reused {cached_hits}/{total} cached rule summaries...")  ; 1148  _progress(f"Polling... {len(completed)}/{len(job_map)} done, "  ; async_jobs.py:304  prog.update(task_id, description=f"Async query: {state} (poll {poll_num + 1}/{max_polls})")
```

**Suggested fix:** Replace each hardcoded progress string with an i18n key (added to both catalogs) carrying the same {placeholders}, e.g. t('pu_progress_polling', done=..., total=..., pending=...). Pass an explicit lang where one is available rather than relying on process-global language.

---

### [PCE REST client] submit_async_query parses the response body without guarding orjson.loads, crashing the whole parallel batch on an empty/non-JSON 202 body

- **File:** `src/api/async_jobs.py:250-270`
- **Category:** error-handling | **Fix risk:** `safe-inline`
- **Subsystem:** PCE REST client (src/api_client.py, src/api/traffic_query.py, src/api/async_jobs.py, src/api/labels.py)

**Detail:** submit_async_query() accepts status in (200, 201, 202) and then unconditionally calls result = orjson.loads(body). A 202 Accepted (which the status check explicitly permits) frequently carries an empty body; orjson.loads(b'') raises orjson.JSONDecodeError. The sequential caller get_rule_traffic_count wraps this in try/except, but the parallel path batch_get_rule_traffic_counts._submit() does not — the exception propagates through fut.result() inside the as_completed loop (line 1051) and aborts the entire rule-usage batch (and thus the Policy Usage Report run). _submit_and_stream_async_query has the identical orjson.loads but is protected by execute_traffic_query_stream's try/except; submit_async_query is not.

**Evidence:**

```
async_jobs.py:259  result = orjson.loads(body)   (no try/except; reached for any 200/201/202 incl. empty-body 202)  ;  traffic_query.py:1051  job_href, rule, payload = fut.result()   (re-raises submit_async_query's exception)
```

**Suggested fix:** Guard the parse: wrap orjson.loads(body) in try/except (orjson.JSONDecodeError, ValueError) and return None on failure (logging at debug), matching the function's documented 'returns the job href, or None on failure' contract; or treat an empty 202 body as 'submitted with no href yet' explicitly.

---

### [src/siem] CEF header fields incorrectly escape '=' producing malformed header tokens

- **File:** `src/siem/formatters/cef.py:52-57`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** src/siem (SIEM forwarder: formatters, transports, dispatcher, DLQ, web API)

**Detail:** _cef_escape() escapes '=' to '\=', which is correct for CEF *extension* values but wrong for *header* fields. event_type is passed through _cef_escape and then placed into the DeviceEventClassID and Name header positions. Per the CEF spec only '\' and '|' are special in the header; '=' is a literal there. An event_type containing '=' yields an unexpected backslash in the header, which strict CEF parsers may mishandle. Impact is low because PCE event_type values rarely contain '=', but the escaping is technically incorrect.

**Evidence:**

```
event_type = _cef_escape(str(event.get("event_type", "unknown")))
header = (f"CEF:0|Illumio|PCE|{_PCE_VERSION}|{event_type}|{event_type}|{sev_num}")
```

**Suggested fix:** Add a separate _cef_header_escape() that escapes only '\' and '|' (not '=') and use it for header fields, keeping _cef_escape for extension values.

---

### [src/siem] TLS transport assigns self._sock before connect(), leaking an SSLSocket fd when connect fails

- **File:** `src/siem/transports/syslog_tls.py:35-38`
- **Category:** concurrency | **Fix risk:** `safe-inline`
- **Subsystem:** src/siem (SIEM forwarder: formatters, transports, dispatcher, DLQ, web API)

**Detail:** _connect() wraps the socket and assigns self._sock = ctx.wrap_socket(...) BEFORE calling self._sock.connect(). If connect() raises (host down, handshake failure), self._sock is left non-None pointing at an unconnected, unclosed SSLSocket. The next send() sees self._sock is not None, attempts sendall (fails), enters the except path and closes/reconnects — so it self-heals, but each failed connect leaks one fd until the following send. The TCP transport (syslog_tcp.py:16-20) correctly assigns self._sock only after a successful connect; the TLS path is inconsistent.

**Evidence:**

```
self._sock = ctx.wrap_socket(raw, server_hostname=self._host)
self._sock.connect((self._host, self._port))  # if this raises, self._sock stays set
```

**Suggested fix:** Connect into a local variable and assign self._sock only after a successful handshake/connect (mirroring syslog_tcp.py), closing the raw/wrapped socket on failure.

---

### [src/siem] dlq_export calls quarantined_at.isoformat() without the null guard used by the other DLQ endpoints

- **File:** `src/siem/web.py:341`
- **Category:** error-handling | **Fix risk:** `safe-inline`
- **Subsystem:** src/siem (SIEM forwarder: formatters, transports, dispatcher, DLQ, web API)

**Detail:** The CSV export writes row.quarantined_at.isoformat() unconditionally, whereas list_dlq (line 233) and get_dlq_item (line 258) guard with 'if e.quarantined_at else None'. If any DeadLetter row has a NULL quarantined_at, the export raises AttributeError and returns 500. quarantined_at is always set on the normal quarantine path so this is unlikely in practice, but the inconsistency makes the export the only endpoint that can crash on the same data the others tolerate.

**Evidence:**

```
w.writerow([..., row.quarantined_at.isoformat()])
```

**Suggested fix:** Use row.quarantined_at.isoformat() if row.quarantined_at else "" to match the other endpoints.

---

### [src/pce_cache] Backfill does not populate report_json, contradicting the schema comment and undermining the partial-index perf rationale

- **File:** `src/pce_cache/backfill.py:100-116`
- **Category:** doc-drift | **Fix risk:** `safe-inline`
- **Subsystem:** src/pce_cache (SQLite WAL cache + ingestors/aggregator/retention/reader/subscriber)

**Detail:** BackfillRunner._insert_traffic inserts PceTrafficFlowRaw without setting report_json (unlike the live TrafficIngestor which precomputes it at ingestor_traffic.py:100-101,130). schema.py:62-66 justifies the ix_raw_report_json_null partial index by asserting 'On a backfilled DB every row has report_json, so the fallback matches 0 rows.' That is false for rows created by this backfill path: they have report_json=NULL, so they populate the partial index and are served by read_flows_df's slower raw_json re-flatten fallback (reader.py:144-149). Functionally correct (fallback exists) but the documented invariant and the perf assumption are wrong for backfilled data.

**Evidence:**

```
s.add(PceTrafficFlowRaw(... raw_json=..., ingested_at=now))  # no report_json=...
```

**Suggested fix:** Compute report_json in _insert_traffic the same way the live ingestor does (orjson.dumps(flatten_flow_record(fl)), best-effort), or correct the schema.py comment to acknowledge backfilled rows lack report_json and rely on the fallback.

---

### [src/pce_cache] Every scheduler tick recreates the Engine and re-runs init_schema DDL (CREATE/ALTER/CREATE INDEX/DROP INDEX) — wasteful churn, 60s cadence for lag monitor

- **File:** `src/scheduler/jobs.py:100-101,123-124,144-145,161-162`
- **Category:** performance | **Fix risk:** `needs-review`
- **Subsystem:** src/pce_cache (SQLite WAL cache + ingestors/aggregator/retention/reader/subscriber)

**Detail:** run_events_ingest / run_traffic_ingest / run_traffic_aggregate / run_cache_retention, and lag_monitor.run_cache_lag_monitor (scheduled every 60s per scheduler/__init__.py:142), each call create_engine(...) followed by init_schema(engine) on every invocation. init_schema runs the full migration path each time: PRAGMA table_info, conditional ALTER TABLE, CREATE INDEX IF NOT EXISTS x3, DROP INDEX IF EXISTS x5, plus _enable_wal_pragma opening a connection to set journal_mode=WAL and commit. The engine is discarded at function exit (pool reclaimed only on GC). This is repeated DDL/connection churn against the live DB on a tight schedule — pure overhead and extra write-lock contention, no functional gain.

**Evidence:**

```
engine = create_engine(f"sqlite:///{cfg.db_path}")
init_schema(engine)
sf = sessionmaker(engine)   # repeated every job tick, engine never disposed/cached
```

**Suggested fix:** Build the engine + sessionmaker once and run init_schema a single time (cache on cm or a module-level singleton like web.py's _get_sf), reusing it across ticks; or at least skip the full init_schema migration on the high-frequency lag-monitor job.

---

### [src/pce_cache] CacheSubscriber advances its cursor before the caller processes rows (at-most-once; rows lost on consumer failure)

- **File:** `src/pce_cache/subscriber.py:39-44`
- **Category:** error-handling | **Fix risk:** `needs-review`
- **Subsystem:** src/pce_cache (SQLite WAL cache + ingestors/aggregator/retention/reader/subscriber)

**Detail:** poll_new_rows reads the rows, then immediately persists the cursor to the last row (_write_cursor) and returns the rows to the caller. If the caller (analyzer / future alert engine / exporter, per the IngestionCursor docstring) crashes or fails while processing the returned batch, those rows are permanently skipped — the cursor has already advanced past them. This is at-most-once delivery with silent data loss on the consumer side, which is risky for alert/exporter consumers expecting at-least-once.

**Evidence:**

```
rows = s.execute(q).scalars().all()
...
last_row = rows[-1]
self._write_cursor(last_row.ingested_at, last_row.id)
return [_row_to_dict(r) for r in rows]   # cursor committed before caller handles rows
```

**Suggested fix:** Defer cursor advancement until the consumer acknowledges successful processing — e.g. expose a commit/ack method the caller invokes after handling the batch, or pass a processing callback and only write the cursor if it succeeds.

---

### [reporter / alert dispatch] Dead code: _render_event_detail_html and _build_plain_text_report unused in src (the i18n-correct event renderer is the dead one)

- **File:** `src/reporter.py:562-609, 1236-1473`
- **Category:** dead-code | **Fix risk:** `needs-review`
- **Subsystem:** reporter / alert dispatch (src/reporter.py, src/alerts/*)

**Detail:** Neither _build_plain_text_report (562-609) nor the static _render_event_detail_html (1236-1473) is referenced anywhere in src (grep finds only their defs plus stale build/ artifacts; no production caller). Notably _render_event_detail_html is the fully i18n-correct event-card renderer (it resolves every label via t() keys), while the actually-used _render_vendor_event_detail_html hardcodes English (see separate finding). Keeping the i18n-correct twin dead while shipping the English one is misleading and a maintenance hazard.

**Evidence:**

```
grep across src/ and tests/ shows no callers of _render_event_detail_html or _build_plain_text_report (only defs); enrich_event_context in template_utils.py is likewise referenced only by a test.
```

**Suggested fix:** Either remove the dead methods, or repoint _build_mail_html to the i18n-correct _render_event_detail_html and drop the hardcoded-English _render_vendor_event_detail_html. Flag rather than delete without owner confirmation since behavior differs subtly.

---

### [scheduler / config / settings / i18n] Scheduler 'Scheduler built' log uses printf %d/%s but loguru only does str.format {} — interpolation never happens

- **File:** `src/scheduler/__init__.py:158-163`
- **Category:** correctness | **Fix risk:** `safe-inline`
- **Subsystem:** scheduler / config / settings / i18n

**Detail:** loguru's logger.info(message, *args) lazily calls message.format(*args, **kwargs). The format string here uses C/printf-style %d / %s placeholders, which str.format ignores. With no {} fields present, the three positional args (interval_minutes, rule_interval, bool(persist)) are silently dropped and the line is emitted verbatim as 'Scheduler built: monitor=%dm report=60s rule=%ds persist=%s'. Every other logger call in this module correctly uses {} (e.g. line 52). Operators reading startup logs never see the real intervals or persist flag.

**Evidence:**

```
logger.info(
    "Scheduler built: monitor=%dm report=60s rule=%ds persist=%s",
    interval_minutes,
    rule_interval,
    bool(sched_cfg.get("persist")),
)
```

**Suggested fix:** Switch to loguru's brace style: logger.info("Scheduler built: monitor={}m report=60s rule={}s persist={}", interval_minutes, rule_interval, bool(sched_cfg.get("persist"))).

---

### [scheduler / config / settings / i18n] Duplicate definition of ConfigManager._LEGACY_FILTER_TO_NAME_KEY (second silently shadows the first)

- **File:** `src/config.py:238-276`
- **Category:** dead-code | **Fix risk:** `safe-inline`
- **Subsystem:** scheduler / config / settings / i18n

**Detail:** The class attribute _LEGACY_FILTER_TO_NAME_KEY is defined twice back-to-back with byte-identical content and the same comment block. The second definition (257-276) simply overwrites the first at class-body execution; the first is dead. Beyond wasted space, this is a maintenance hazard: a future edit to one copy (e.g. adding a new filter→name_key mapping) would be silently overridden or cause the two to drift, and the legacy-rule promotion in _resolve_rule_keys would use whichever wins.

**Evidence:**

```
Lines 238-255 define `_LEGACY_FILTER_TO_NAME_KEY = { ... }` and lines 259-276 redefine the exact same dict with the identical leading comment 'Map rule filter_value → canonical name_key (for legacy alerts.json migration).'
```

**Suggested fix:** Delete the second duplicate block (lines 257-276), keeping a single definition.

---

### [scheduler / config / settings / i18n] Config validation failure prints unredacted str(e) to console — can leak secret field values

- **File:** `src/config.py:220`
- **Category:** security | **Fix risk:** `needs-review`
- **Subsystem:** scheduler / config / settings / i18n

**Detail:** The structured logger loop (lines 215-219) deliberately redacts secret-looking fields via _format_error_input before logging each pydantic error. The user-facing print on line 220 bypasses that redaction and emits str(e)[:200]. Pydantic v2 ValidationError.__str__ embeds 'input_value=...' for each failing field, so if a secret-bearing field (api.key, api.secret, smtp.password, line token, web_gui.password) fails a type/constraint check, its raw value can be echoed to the console (and any captured stdout). The 200-char truncation only partially mitigates this. The redaction infrastructure already exists (_SECRET_FIELD_TOKENS / _format_error_input) but is not applied to this print path.

**Evidence:**

```
print(f"{Colors.FAIL}{t('error_loading_config', error=str(e)[:200])}{Colors.ENDC}")
```

**Suggested fix:** Do not surface raw str(e) to the console; print a generic summary (e.g. t('error_loading_config', error=f"{e.error_count()} validation error(s); see logs")) and rely on the already-redacted logger loop for detail.

---

### [scheduler / config / settings / i18n] run_ven_summary builds hardcoded English 'attention' reason strings surfaced via the dashboard overview

- **File:** `src/scheduler/jobs.py:218-221`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** scheduler / config / settings / i18n

**Detail:** The job constructs per-host attention reasons as literal English ('{n}h no heartbeat', 'status={status}') and writes them into ven_summary.attention, which the docstring states feeds the dashboard overview (confirmed: src/gui/routes/dashboard.py:233 returns ven_summary['attention'] in the /api/dashboard/overview payload). Per the AGENTS.md i18n guardrail, all user-visible text must go through t(key, lang=lang); these strings are emitted in a fixed language regardless of the operator's selected UI language. (Note: these are produced in a scheduler thread, so the fix must pass lang= explicitly via t(...) and must NOT call set_language.)

**Evidence:**

```
reason = (f"{int(hslh)}h no heartbeat" if hslh is not None
          else f"status={status or 'unknown'}")
attention.append({"host": host, "reason": reason})
```

**Suggested fix:** Store a structured/translatable reason instead of an English literal — e.g. {"host": host, "reason_key": "ven_no_heartbeat", "hours": int(hslh)} or {"reason_key": "ven_status", "status": status} — and render via t(reason_key, lang=...) at the presentation layer, adding the keys to both i18n_en.json and i18n_zh_TW.json.

---

### [Entry dispatch, version management, packaging & install/build scripts] Windows migration hardcodes `--interval 10`, silently resetting an operator's custom service interval on upgrade

- **File:** `scripts/install.ps1:60, 124`
- **Category:** correctness | **Fix risk:** `needs-review`
- **Subsystem:** Entry dispatch, version management, packaging & install/build scripts

**Detail:** During the underscore->hyphen migration the NSSM AppParameters are rewritten to a fixed `--monitor --interval 10`. If the existing C:\illumio_ops service was originally registered with a non-default interval (install_service.ps1 accepts -Interval, e.g. 5), the migration overwrites it back to 10 without warning. The migration is meant to be a path rename only; changing runtime behavior is a surprise. The normal install path that follows calls install_service.ps1, but Install-Service is idempotent and skips reconfiguring AppParameters when the service already exists, so the interval is not restored afterward.

**Evidence:**

```
Invoke-NssmSet IllumioOps,AppParameters,"$NewRoot\illumio-ops.py --monitor --interval 10"
```

**Suggested fix:** Read the existing AppParameters via `nssm get IllumioOps AppParameters` and only rewrite the path portion (replace $OldRoot with $NewRoot), preserving the original --interval value, rather than substituting a fixed parameter string.

---

### [Entry dispatch, version management, packaging & install/build scripts] Dead constant `_CLICK_SUBCOMMANDS` contradicts the module docstring describing dispatch by subcommand name

- **File:** `illumio-ops.py:8-9, 26, 36-53`
- **Category:** dead-code | **Fix risk:** `safe-inline`
- **Subsystem:** Entry dispatch, version management, packaging & install/build scripts

**Detail:** The module docstring and the comment on line 25 state the dispatcher 'picks which to use based on argv[1] — if it matches a known click subcommand name we delegate to click'. The actual dispatcher, _looks_like_click_invocation, never consults _CLICK_SUBCOMMANDS at all: it routes to click for any argv[1] that is a help flag, a click global flag, or simply does not start with '-'. A repo-wide grep confirms _CLICK_SUBCOMMANDS is referenced only at its definition (the only other hits are stale copies under build/). The set is dead code, and the docstring misdescribes the routing rule (a bogus positional like `illumio-ops montior` is routed to click and errors there, not 'falls through to legacy argparse' as implied).

**Evidence:**

```
_CLICK_SUBCOMMANDS = {"cache", "monitor", "monitor-gui", ...}  # defined but never read  ... return not first.startswith('-')  # actual rule, ignores _CLICK_SUBCOMMANDS
```

**Suggested fix:** Remove the unused _CLICK_SUBCOMMANDS constant and update the docstring/comment to describe the real rule (route to click when argv[1] is a help flag, a click global flag, or any non-dash positional; otherwise fall back to legacy argparse). No behavior change; tests/test_cli_compat_matrix.py only exercises _looks_like_click_invocation.

---

### [Security] Teams channel absent from Web GUI integrations + settings allowlist omits Telegram/Teams keys

- **File:** `src/gui/_helpers.py:171-180`
- **Category:** consistency | **Fix risk:** `needs-review`
- **Subsystem:** Security (auth/secrets/TLS/web) + Code-vs-Doc drift

**Detail:** _SETTINGS_ALLOWLISTS['alerts'] = {'active','line_channel_access_token','line_target_id','webhook_url'} — it omits telegram_bot_token, telegram_chat_id and teams_webhook_url, so any POST /api/settings that includes those keys is silently filtered out at src/gui/routes/config.py:172 (filtered = {k:v ... if k in allowlist}). Correspondingly the Web GUI integrations page renders read-only cards for Mail/LINE/Telegram/Webhook only — there is no Teams card at all (src/static/js/integrations.js has zero 'teams' references) and the channel subtitle hardcodes 'Mail · LINE · Telegram · Webhook' (integrations.js:1539). Net effect: Teams (and to a lesser degree Telegram) is a backend/CLI-only feature with no Web GUI management path, an inconsistency that will confuse GUI-first operators and is a latent silent-data-loss trap if the GUI ever POSTs those alert keys.

**Evidence:**

```
_SETTINGS_ALLOWLISTS = { ... "alerts": {"active", "line_channel_access_token", "line_target_id", "webhook_url"}, ... }  (no telegram_/teams_ keys)
```

**Suggested fix:** Add telegram_bot_token, telegram_chat_id, teams_webhook_url to the 'alerts' allowlist so the settings API can persist them, and add a Teams card (and editable forms) to integrations.js — or, if GUI management is intentionally out of scope, document that Telegram/Teams are CLI-only.

---

### [Security] Unresolved author TODO published in user-facing documentation

- **File:** `docs/user-guide/alerts-and-quarantine.md:168`
- **Category:** doc-drift | **Fix risk:** `safe-inline`
- **Subsystem:** Security (auth/secrets/TLS/web) + Code-vs-Doc drift

**Detail:** A shipped user-guide page contains an internal authoring note: '> [!TODO] @harry: confirm whether there is a SIEM forwarder plugin distinct from the webhook'. This leaks an unfinished editorial note to end users and signals the doc was not finalized. (The answer is determinable from code: SIEM forwarding is a separate subsystem under src/siem/ with its own transports, distinct from the alert webhook plugin.)

**Evidence:**

```
> [!TODO] @harry: confirm whether there is a SIEM forwarder plugin distinct from the webhook
```

**Suggested fix:** Resolve the TODO: state that SIEM forwarding (src/siem/, CEF/JSON/syslog/HEC) is a separate subsystem from the alert webhook plugin, and remove the [!TODO] marker (also check the _zh mirror).

---

### [Security] Daemon-restart endpoint returns hardcoded English error strings (i18n guardrail violation)

- **File:** `src/gui/__init__.py:575-578`
- **Category:** i18n | **Fix risk:** `needs-review`
- **Subsystem:** Security (auth/secrets/TLS/web) + Code-vs-Doc drift

**Detail:** The POST /api/daemon/restart handler returns user-visible error messages as hardcoded English rather than via t(key, lang=lang): 'Daemon is managed externally; restart via systemctl or your service manager.' (409) and 'restart hook not installed' (500). These are surfaced in the Web GUI, so under zh_TW the user sees raw English, violating the AGENTS.md i18n guardrail that all user-visible text must use i18n keys. Neighbouring handlers (admin.py shutdown, the global error handlers) correctly use t().

**Evidence:**

```
return jsonify({"ok": False, "error": "Daemon is managed externally; restart via systemctl or your service manager."}), 409  /  return jsonify({"ok": False, "error": "restart hook not installed"}), 500
```

**Suggested fix:** Replace both literals with t() calls (e.g. t('gui_err_daemon_external', lang=_request_lang()) and t('gui_err_restart_hook_missing', lang=_request_lang())) and add the keys to both src/i18n_en.json and src/i18n_zh_TW.json.

---

## INFO (8)

### [src/report/rules] Dead variable _RISK_COLORS in ransomware exposure module

- **File:** `src/report/analysis/mod04_ransomware_exposure.py:6-7`
- **Category:** dead-code | **Fix risk:** `safe-inline`
- **Subsystem:** src/report/rules (R01–R05), src/report/rules_engine.py (B/L rules), src/report/analysis/* (policy_resolver, mod_vuln, mod03_uncovered_flows, mod02_policy_decisions, mod04, mod12, mod13, mod15, attack_posture, mod_draft_*)

**Detail:** _RISK_COLORS = {'critical':'CRITICAL', ...} is defined at module scope but never referenced anywhere in the module. Harmless but misleading (looks like a color map but maps to uppercase level names).

**Evidence:**

```
_RISK_COLORS = {'critical': 'CRITICAL', 'high': 'HIGH', 'medium': 'MEDIUM', 'low': 'LOW'}  # never used
```

**Suggested fix:** Remove the unused _RISK_COLORS constant.

---

### [GUI shared helpers, templates, and client-side JS] Redundant no-op ternary in browser timezone detection

- **File:** `src/static/js/utils.js:100`
- **Category:** dead-code | **Fix risk:** `safe-inline`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** _detectBrowserTimezone() ends with `return \`UTC${sign}${abs % 1 === 0 ? abs : abs}\``; both branches of the ternary return `abs`, so the conditional has no effect. It signals an unfinished/typo'd intent (likely meant to format whole vs fractional offsets differently) though it currently produces a correct string. Harmless but misleading.

**Evidence:**

```
return `UTC${sign}${abs % 1 === 0 ? abs : abs}`;
```

**Suggested fix:** Simplify to `return \`UTC${sign}${abs}\`;`, or implement the intended differing format if one was meant.

---

### [GUI shared helpers, templates, and client-side JS] Duplicated identical branches in posture metric severity classing

- **File:** `src/static/js/dashboard.js:1479-1483`
- **Category:** dead-code | **Fix risk:** `safe-inline`
- **Subsystem:** GUI shared helpers, templates, and client-side JS (src/gui/_helpers.py, src/templates/*, src/static/js/*)

**Detail:** In _renderPostureHero the if/else for severity class has identical bodies: when c.key==='risk_health' it uses `c.value >= 70 ? 'v-ok' : (c.value >= 40 ? 'v-md' : 'v-hi')`, and the else branch is the exact same expression. The branch is dead — the comment above even claims different thresholds were intended ('coverage/readiness' vs risk_health) but they are the same.

**Evidence:**

```
if (c.key === 'risk_health') {
  cls = c.value >= 70 ? 'v-ok' : (c.value >= 40 ? 'v-md' : 'v-hi');
} else {
  cls = c.value >= 70 ? 'v-ok' : (c.value >= 40 ? 'v-md' : 'v-hi');
}
```

**Suggested fix:** Collapse to a single assignment, or apply the genuinely-intended distinct thresholds if risk_health was supposed to differ.

---

### [src/events/*] Catalog references non-existent event type 'agent.refresh_policy' (real type is 'agent.refresh_token')

- **File:** `src/events/catalog.py:437,666`
- **Category:** doc-drift | **Fix risk:** `needs-review`
- **Subsystem:** src/events/* (PCE event poll / dedup / normalize / classify / throttle / runbooks)

**Detail:** _LEGACY_STUB ('Agent Health Detail') maps 'agent.refresh_policy' -> 'event_agent_refresh_policy', and EVENT_TIPS_KEYS maps 'agent.refresh_policy' -> 'event_tips_agent_refresh_policy'. But KNOWN_EVENT_TYPES contains 'agent.refresh_token' and 'agent.request_policy' — there is no 'agent.refresh_policy'. Consequently this id never enters FULL_EVENT_CATALOG (built from KNOWN_EVENT_TYPES only) and its tips/description-override entries are dead lookups that no real event will ever hit. runbooks.py 'agent-lifecycle' correctly lists 'agent.refresh_token', confirming the typo. Low impact (dead key, no crash), but it is a maintenance/doc-drift wart in the canonical catalog that also feeds the event-rules doc.

**Evidence:**

```
_LEGACY_STUB: "agent.refresh_policy": "event_agent_refresh_policy"  and  EVENT_TIPS_KEYS: "agent.refresh_policy": "event_tips_agent_refresh_policy"  — vs catalog membership "agent.refresh_token" / "agent.request_policy" (no agent.refresh_policy).
```

**Suggested fix:** Rename the two stale references to 'agent.refresh_token' (and add the matching i18n keys) or remove the dead entries, so the catalog/tips agree with KNOWN_EVENT_TYPES.

---

### [src/analyzer.py — B/L/R flow-to-rule matching engine, event/traffic ru] Vestigial per-record count default rec.get('c', 1) — records never carry a 'c' field

- **File:** `src/analyzer.py:389`
- **Category:** dead-code | **Fix risk:** `safe-inline`
- **Subsystem:** src/analyzer.py — B/L/R flow-to-rule matching engine, event/traffic rule evaluation, state management, monitor-cycle concurrency (plus src/rule_id.py)

**Detail:** _event_count_in_window sums `int(rec.get('c', 1))`, implying history records may store a compressed count under 'c'. But _record_event_matches (lines 375-378) only ever writes {'t': ..., 'event_id': ...} — no 'c' key is ever produced anywhere. The default of 1 makes the result correct (one record == one event), so this is not a behavioral bug, but the 'c' lookup is dead/vestigial and can mislead future maintainers into thinking count-compression exists.

**Evidence:**

```
self.state["history"][rid].append({"t": format_utc(event_ts), "event_id": event_identity(event)})
...
total += int(rec.get('c', 1))   # 'c' is never written
```

**Suggested fix:** Either drop the 'c' indirection (use `total += 1`) or, if count-compression is intended, have _record_event_matches actually emit a 'c' field. No behavior change required; cleanup only.

---

### [PCE REST client] Dead 'if stream is None' guard — execute_traffic_query_stream is a generator and never returns None

- **File:** `src/api/traffic_query.py:755-759`
- **Category:** dead-code | **Fix risk:** `safe-inline`
- **Subsystem:** PCE REST client (src/api_client.py, src/api/traffic_query.py, src/api/async_jobs.py, src/api/labels.py)

**Detail:** fetch_traffic_for_report assigns stream = self.execute_traffic_query_stream(...) and then checks 'if stream is None: return []'. execute_traffic_query_stream is a generator function (it contains yield from), so calling it always returns a generator object — never None, even when the underlying logic 'return's early. The guard is unreachable. Harmless but misleading about the failure contract.

**Evidence:**

```
traffic_query.py:755  stream = self.execute_traffic_query_stream(...) ; 758  if stream is None: return []   (generator funcs cannot return None)
```

**Suggested fix:** Remove the dead 'if stream is None: return []' check; rely on list(stream) yielding [] when the generator produces nothing.

---

### [src/siem] Dead code: JSONLineFormatter and _escape_sd_param are defined but never used

- **File:** `src/siem/formatters/json_line.py:8-16`
- **Category:** dead-code | **Fix risk:** `needs-review`
- **Subsystem:** src/siem (SIEM forwarder: formatters, transports, dispatcher, DLQ, web API)

**Detail:** JSONLineFormatter is never referenced anywhere in src/ (the formatter factories in dispatcher._formatter_for and tester._build_formatter only return CEFFormatter, SyslogWrappedFormatter, and NormalizedJSONFormatter). Similarly, _escape_sd_param in src/siem/formatters/syslog_header.py:7 is defined but never called — wrap_rfc5424 hardcodes STRUCTURED-DATA as '-'. Both are confirmed unused via grep. Not a behavior bug, but dead weight that suggests an unfinished structured-data feature.

**Evidence:**

```
grep -rn 'JSONLineFormatter|_escape_sd_param' src/ shows only the definitions, no call sites.
```

**Suggested fix:** Remove JSONLineFormatter and _escape_sd_param, or wire _escape_sd_param into wrap_rfc5424 if structured-data emission was intended. (Flag only — do not delete pre-existing dead code without owner confirmation.)

---

### [scheduler / config / settings / i18n] set_language() docstring cites stale config.py line numbers for allowed callers

- **File:** `src/i18n/engine.py:46-48`
- **Category:** doc-drift | **Fix risk:** `safe-inline`
- **Subsystem:** scheduler / config / settings / i18n

**Detail:** The docstring lists allowed bootstrap callers as 'src/config.py:185, 268', but the actual set_language() call sites in config.py are now at lines 228 (load) and 400 (save). The referenced lines 185/268 point to unrelated code (alerts migration / the duplicated legacy dict). This drift undermines the allowlist's usefulness as the documented contract for who may call the process-global setter.

**Evidence:**

```
Allowed callers (Phase 3 baseline):
  - src/config.py:185, 268 — bootstrap from config.json
```

**Suggested fix:** Update the docstring to reference the current call sites (src/config.py:228 and :400), or drop explicit line numbers in favor of the function names (ConfigManager.load / ConfigManager.save) which won't drift.

---
