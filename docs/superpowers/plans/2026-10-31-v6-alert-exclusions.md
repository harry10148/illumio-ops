# v6 Alert-rule exclusions (labels / Workload / IP-CIDR / IP list / public)

User 2026-10-31: 「我覺得排除針對告警就好吧？」 then 「等等目前告警的功能都沒有任何filter功能?例入排除某個標籤或ip或是iplist或這次的公網ip?」 and chose option 1 (drop the detector-level public exclusion; detections show everything, alert rules filter).

## Decisions

- One condition per lateral rule, `exclude: EndpointFilter | None`, applied to the detection's ends: left out when **a source end matches, or every target end matches** (targets non-empty). Account subjects are not ends; their source hosts are.
- Ends are stored with the detection (`detections.ends_json`, migration 0011): `[[role, key, ip], ...]`, role `s`/`t`, key href or `ip:…`. Labels come from the current inventory at evaluation. Rows stored before have no ends → nothing to compare → never excluded (fail open towards alerting).
- `EndpointFilter.public: bool` = `netaddr.outside(ip, href)` (a public address no Workload holds). Works in `to_sql` (UDF), `matches`, and goes residual in `to_pce_payload`.
- `EndpointFilter.ip_lists: tuple[str, ...]` (PCE IP list hrefs), synced by the inventory collector into flowdb `ip_list_ranges(href, net)`; ranges and exclusions resolved with `policy_resolver.build_iplist_to_cidrs`. A deleted list matches nothing.
- Settings v12: drop `lateral.detectors.exclude_public`; when it was true, every lateral rule without an exclusion gets `exclude={public: true}` (behaviour preserved). Pack lateral rules default to `exclude={public: true}`.
- Traffic-rule defaults unchanged (decided after checking .106's HIGH_BLOCKED alerts).

## Slices (each ships alone)

1. **Rule-level public exclusion, detector-level removed** — filter `public`; detection ends + migration; `LateralRule.exclude` evaluated in `evaluate_lateral` and preview; v12 upgrade + pack default; remove detector setting/UI/i18n/tests; docs guide.
2. **Editor** — `ConditionEditor` `Side` gets the public checkbox; `RuleEditor` lateral section mounts one exclude side; e2e.
3. **IP lists** — inventory sync + migration; `EndpointFilter.ip_lists` in SQL / matches / PCE payload; on-demand store copy; picker choices API; editor picker.

Acceptance (lab .106, 72 h): lateral page shows all detections (≈51); default lateral rules would alert only the east-west ones (≈35).

Gates: `.superpowers/sdd/2026-10-31-v6-phase7-siem/gates.sh`.
