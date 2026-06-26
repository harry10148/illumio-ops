# App Summary — Server-Side App Scoping (Design Spec, 2026-06-13)

## Goal

Stop App Summary from pulling the **entire estate's** traffic (e.g. ~240k flows)
and filtering to one app in pandas. Instead, push the app scope to the PCE so the
Explorer query returns **only flows where the app is source OR destination**.

This reduces PCE load (per-app query instead of a full-estate traffic scan),
cuts generation time (no full-estate parse), and removes the GUI poll-timeout
risk on large estates. It reverses spec decision #2 of the App Summary v1 plan
("post-filter, accept full-estate fetch") now that we've confirmed the PCE API
and the codebase support single-query src-OR-dst label scoping.

## Confirmed feasibility (the "OR trap" is solved)

- The Illumio Explorer async query supports `sources_destinations_query_op: "and"|"or"`.
  Placing the app label in BOTH `sources.include` and `destinations.include` with
  op=`"or"` returns all flows touching the app as source OR destination in ONE
  query. (NotebookLM Illumio API guide.)
- `src/api/traffic_query.py` already implements native filters:
  `src_labels`/`dst_labels` → resolved to label hrefs → `sources.include`/
  `destinations.include`; `query_operator` → `sources_destinations_query_op`.
  (PCE ≥ 21.2 native execution.)
- `ReportGenerator.fetch_traffic_df(start, end, filters)` already accepts a
  `filters` dict and threads it to `_fetch_traffic` → the query. App Summary
  currently passes NO filters (full estate).
- Filter value format: `src_labels`/`dst_labels` are lists of `key=value` strings
  (e.g. `"app=K8sNode"`), per the GUI traffic report's `report_filters` builder
  (`reports.py:327`) and the modal's `role=Web` precedent.

## Change

In `src/report/app_summary_report.py`:

1. `build()` builds a scoping filter dict and passes it to `_fetch_estate_df`:
   ```python
   labels = [f"app={app}"] + ([f"env={env}"] if env else [])
   filters = {"src_labels": labels, "dst_labels": labels, "query_operator": "or"}
   df = self._fetch_estate_df(start_date=..., end_date=..., filters=filters)
   ```
   The PCE returns only the app's flows. (env, when present, AND-combines with app
   inside one include set — the implementer confirms the resolver builds the inner
   `[[{app},{env}]]` AND-array; if the resolver treats the list as OR, pass env via
   the mechanism that yields AND, or scope by app server-side and keep env in the
   post-filter. Either way the post-filter is the safety net.)

2. `_fetch_estate_df(start_date, end_date, filters=None)` forwards `filters` to
   `gen.fetch_traffic_df(start_date=, end_date=, filters=filters)`.

3. **Keep `filter_app_flows(df, app, env)`** after the fetch as a defensive
   safety net. On the now-already-scoped df it is a cheap near-no-op, but it
   guarantees correctness if the server-side resolution is partial (e.g. unmanaged
   endpoints, env edge). Correctness never depends solely on the PCE filter.

4. **Preserve all policy decisions**: do NOT restrict `policy_decisions` — App
   Summary's Policy Impact needs allowed + potentially_blocked + blocked. Confirm
   `fetch_traffic_df`'s default keeps all decisions (it does in `generate_from_api`);
   do not add a `policy_decisions` filter that drops any.

## Out of scope / unchanged

- The CLI / GUI / scheduler entrypoints, the exporter, the two v2 sections
  (Policy Impact, Enforcement State), `policy_impact`/`enforcement_summary`,
  the labels dropdown, the async job flow — ALL unchanged.
- The workloads fetch (enforcement) is independent of the traffic scope.
- Empty-state still works: a scoped query returning no flows → `{empty: True}`.
- Label-group scoping, multi-app — still out (v1 decisions hold).

## Error handling / fallback

- If the PCE doesn't support native label filtering (older PCE) or resolution
  fails, `traffic_query` already falls back to fetching + Python-side filtering
  (its native/fallback split). The `filter_app_flows` safety net then scopes
  correctly. So a resolution failure degrades to the old behavior, not breakage.
- Empty scoped result → empty-state page (unchanged).

## Success criteria

- App Summary for a real app (e.g. K8sNode) generates **dramatically faster** and
  with the **same scoped content** (same sections, same coverage %, same
  enforced/total) as the full-estate-then-filter version.
- The PCE traffic query is app-scoped (returns the app's flows, not the full
  estate) — verified by the much smaller fetched row count vs the ~240k full
  estate, and faster completion.
- All existing App Summary tests pass; a new test asserts `build()` passes the
  expected `src_labels`/`dst_labels`/`query_operator` filters to the fetch.
- Verified live on the test machine against the healthy PCE.
