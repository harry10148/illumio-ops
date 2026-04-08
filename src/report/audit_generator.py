"""
src/report/audit_generator.py
Orchestrates the generation of the Audit & System Events Report.

Enhanced field extraction from Illumio PCE event JSON:
  - action.src_ip, action.api_method, action.api_endpoint
  - created_by (user vs agent vs system disambiguation)
  - resource_changes → human-readable change_detail (before/after)
  - notifications → workloads_affected, supplied_username, details
  - pce_fqdn for multi-PCE environments
  - agent hostname for agent-originated events
"""
import datetime
import logging
import os
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from src.events import normalize_event
from src.i18n import t

logger = logging.getLogger(__name__)

# Event types that represent a policy commit (no field-level diffs, only macro stats)
_PROVISION_EVENT_TYPES = frozenset({
    'sec_policy.create', 'sec_policy.delete', 'sec_policy.restore',
})


@dataclass
class AuditReportResult:
    generated_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    record_count: int = 0
    date_range: tuple = ('', '')
    module_results: dict = field(default_factory=dict)
    dataframe: object = None


# ── Nested-field extraction helpers ──────────────────────────────────────────

def _extract_created_by(raw) -> str:
    """Extract human-readable actor from created_by dict.
    Returns: 'user@example.com', 'agent:hostname', 'system', or string repr.
    """
    if not isinstance(raw, dict):
        return str(raw) if raw is not None else ''
    # User-initiated
    user = raw.get('user')
    if isinstance(user, dict):
        return user.get('username', user.get('name', user.get('href', str(user))))
    # Agent-initiated (VEN event)
    agent = raw.get('agent')
    if isinstance(agent, dict):
        hostname = agent.get('hostname', '')
        if hostname:
            return f'agent:{hostname}'
        return agent.get('href', str(agent))
    # System-initiated
    if raw.get('system'):
        return 'system'
    # Workload-initiated
    wl = raw.get('workload')
    if isinstance(wl, dict):
        return f'workload:{wl.get("hostname", wl.get("href", str(wl)))}'
    # Fallback — try common keys
    for key in ('username', 'name', 'href'):
        val = raw.get(key)
        if val:
            return str(val)
    return str(raw)


def _extract_agent_hostname(raw_created_by) -> str:
    """Extract agent hostname from created_by, if agent-originated."""
    if not isinstance(raw_created_by, dict):
        return ''
    agent = raw_created_by.get('agent')
    if isinstance(agent, dict):
        return agent.get('hostname', '')
    return ''


def _extract_src_ip(raw_action) -> str:
    """Extract source IP from action.src_ip — where admin connected from."""
    if isinstance(raw_action, dict):
        return str(raw_action.get('src_ip', '') or '')
    return ''


def _extract_api_method(raw_action) -> str:
    """Extract HTTP method from action.api_method."""
    if isinstance(raw_action, dict):
        return str(raw_action.get('api_method', '') or '')
    return ''


def _extract_api_endpoint(raw_action) -> str:
    """Extract API endpoint from action.api_endpoint (shortened)."""
    if isinstance(raw_action, dict):
        ep = str(raw_action.get('api_endpoint', '') or '')
        # Shorten long org-prefixed paths for readability
        if '/orgs/' in ep:
            parts = ep.split('/orgs/', 1)
            if len(parts) == 2:
                rest = parts[1]
                # Remove /orgs/N prefix → show from meaningful segment
                segments = rest.split('/', 1)
                if len(segments) == 2:
                    return '…/' + segments[1]
        return ep
    return ''


def _extract_resource_name(entry: dict) -> str:
    """Extract a short human-readable identifier for the changed resource.

    Illumio PCE resource_changes entry structure:
      resource: {"rule_set": {"href": "...", "name": "CoreServices | VMware", ...}}
    or:
      resource: {"sec_policy": {"href": "/orgs/1/sec_policy/516", "commit_message": "...", ...}}

    The actual data is nested under a type key (rule_set, sec_rule, sec_policy, etc).
    """
    resource = entry.get('resource', {})
    if not isinstance(resource, dict):
        return ''

    # Illumio nests: resource.{type_key}.{name/href}
    # Find the first dict value — that's the real resource object
    inner = None
    for _key, val in resource.items():
        if isinstance(val, dict):
            inner = val
            break

    if inner is not None:
        # Prefer name > shortened href; description is too verbose for a label
        name = inner.get('name')
        if name and str(name).strip():
            return str(name).strip()[:60]
        href = inner.get('href', '')
        if href:
            return _shorten_href(href)

    # Fallback: flat resource dict (non-standard)
    name = resource.get('name')
    if name and str(name).strip():
        return str(name).strip()[:60]
    href = resource.get('href', '') or entry.get('href', '')
    if href:
        return _shorten_href(href)
    return ''


def _shorten_href(href: str) -> str:
    """Shorten an Illumio href like /orgs/1/sec_policy/draft/rule_sets/471 to rule_sets/471."""
    if '/orgs/' in href:
        rest = href.split('/orgs/', 1)[1]
        rest = rest.split('/', 1)[1] if '/' in rest else rest
        for pfx in ('sec_policy/draft/', 'sec_policy/active/', 'sec_policy/'):
            if rest.startswith(pfx):
                rest = rest[len(pfx):]
                break
        return rest[:60]
    return href[-60:]


def _summarize_resource_changes(raw_changes) -> str:
    """Build a concise human-readable summary of resource_changes.

    For each change entry, prefixes with resource name/href so the reader
    knows *which* rule/ruleset was changed, then shows field before → after.
    Returns '' if no meaningful changes found.
    """
    if not isinstance(raw_changes, (list, tuple)) or not raw_changes:
        return ''

    summaries = []
    for entry in raw_changes:
        if not isinstance(entry, dict):
            continue

        resource_name = _extract_resource_name(entry)
        prefix = f'[{resource_name}] ' if resource_name else ''

        changes = entry.get('changes', {})
        resource = entry.get('resource', {})
        wa = entry.get('workloads_affected')

        # change_type indicator (create/update/delete)
        change_type = entry.get('change_type', '')

        if isinstance(changes, dict) and changes:
            for field_name, change_val in changes.items():
                if isinstance(change_val, dict):
                    before = change_val.get('before')
                    after = change_val.get('after')
                    b_str = _truncate_val(before)
                    a_str = _truncate_val(after)
                    summaries.append(f'{prefix}{field_name}: {b_str} → {a_str}')
                else:
                    summaries.append(f'{prefix}{field_name}: {_truncate_val(change_val)}')
        elif isinstance(resource, dict) and resource:
            # For create/delete events with no field-level diffs —
            # Illumio nests: resource.{type_key}.{fields}
            inner = None
            for _key, val in resource.items():
                if isinstance(val, dict):
                    inner = val
                    break
            target = inner if inner else resource
            shown = 0
            for key in ('name', 'description', 'enabled', 'providers', 'consumers',
                        'ingress_services', 'scope'):
                if key in target and shown < 4:
                    summaries.append(f'{prefix}{key}: {_truncate_val(target[key])}')
                    shown += 1
            if change_type and not shown:
                summaries.append(f'{prefix}{change_type}')

        if wa is not None and wa:
            summaries.append(f'{prefix}workloads_affected: {wa}')

    return '; '.join(summaries[:8])  # Cap at 8 fields for readability


def _summarize_provision(row) -> str:
    """Build a concise summary for sec_policy.create/delete/restore events.

    Actual Illumio PCE structure for sec_policy.create:
      resource_changes[0]:
        resource: {sec_policy: {href, commit_message, version, modified_objects: {rulesets: {...}}}}
        changes: {commit_message: {before, after}, version: {before, after},
                  workloads_affected: {before, after}, object_counts: {before, after}}
        change_type: "create"

    Provision events have commit_message and object_counts as before/after in
    changes, not field-level rule diffs.
    """
    parts = []
    rc = row.get('resource_changes')
    if not isinstance(rc, (list, tuple)) or not rc:
        return ''

    for entry in rc:
        if not isinstance(entry, dict):
            continue
        changes = entry.get('changes')
        if not isinstance(changes, dict):
            continue

        # 1. Version number
        ver = changes.get('version')
        if isinstance(ver, dict):
            v = ver.get('after')
            if v is not None:
                parts.append(f'v{v}')

        # 2. Commit message (admin note)
        cm = changes.get('commit_message')
        if isinstance(cm, dict):
            note = cm.get('after')
            if note and str(note).strip():
                parts.append(str(note).strip()[:120])

        # 3. Object counts (what was in this provision)
        oc = changes.get('object_counts')
        if isinstance(oc, dict):
            after = oc.get('after')
            if isinstance(after, dict) and after:
                obj_parts = [f'{k}: {v}' for k, v in after.items() if v]
                if obj_parts:
                    parts.append('objects: ' + ', '.join(obj_parts[:6]))

        # 4. modified_objects from resource (names of what actually changed)
        resource = entry.get('resource', {})
        if isinstance(resource, dict):
            for _key, inner in resource.items():
                if isinstance(inner, dict):
                    mo = inner.get('modified_objects')
                    if isinstance(mo, dict) and mo:
                        mo_parts = []
                        for obj_type, obj_data in mo.items():
                            count = 0
                            if isinstance(obj_data, dict):
                                count = len(obj_data)
                            elif isinstance(obj_data, (list, tuple)):
                                count = len(obj_data)
                            if count > 0:
                                mo_parts.append(f'{obj_type}({count})')
                        if mo_parts:
                            parts.append('modified: ' + ', '.join(mo_parts[:6]))
                    break

    return '; '.join(parts) if parts else ''


def _truncate_val(val, max_len: int = 80) -> str:
    """Convert a value to a truncated string for display."""
    if val is None:
        return 'null'
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, (list, tuple)):
        if not val:
            return '[]'
        # For label/href lists, try to extract meaningful names
        items = []
        for item in val[:4]:
            if isinstance(item, dict):
                name = item.get('label', item.get('name', item.get('href', '')))
                if isinstance(name, dict):
                    name = name.get('value', name.get('key', str(name)))
                items.append(str(name))
            else:
                items.append(str(item))
        result = ', '.join(items)
        if len(val) > 4:
            result += f' …(+{len(val)-4})'
        return f'[{result}]'
    s = str(val)
    if len(s) > max_len:
        return s[:max_len] + '…'
    return s


def _extract_notifications_detail(raw_notifications) -> str:
    """Extract useful information from notifications array.

    Extracts: supplied_username, notification_type, and other info fields.
    """
    if not isinstance(raw_notifications, (list, tuple)) or not raw_notifications:
        return ''

    details = []
    for n in raw_notifications:
        if not isinstance(n, dict):
            continue
        ntype = n.get('notification_type', '')
        info = n.get('info', {})
        if ntype:
            details.append(ntype)
        if isinstance(info, dict):
            # Failed login: supplied_username
            username = info.get('supplied_username')
            if username:
                details.append(f'username={username}')
            # Agent info
            hostname = info.get('hostname')
            if hostname:
                details.append(f'host={hostname}')
    return '; '.join(details[:4])


def _extract_supplied_username(raw_notifications) -> str:
    """Extract the username supplied during failed auth flows."""
    if not isinstance(raw_notifications, (list, tuple)) or not raw_notifications:
        return ''

    for notification in raw_notifications:
        if not isinstance(notification, dict):
            continue
        info = notification.get('info', {})
        if not isinstance(info, dict):
            continue
        username = info.get('supplied_username')
        if username:
            return str(username).strip()
    return ''


def _stringify_parser_notes(value) -> str:
    if not isinstance(value, (list, tuple)):
        return ''
    notes = [str(note).strip() for note in value if str(note).strip()]
    return '; '.join(notes)


def _extract_workloads_affected_from_event(row) -> int:
    """Extract workloads_affected from resource_changes and notifications.

    Actual Illumio PCE structure:
      resource_changes[0].changes.workloads_affected.after = N
    Also checks legacy locations (top-level entry, notifications.info).
    """
    total = 0
    rc = row.get('resource_changes')
    if isinstance(rc, (list, tuple)):
        for entry in rc:
            if not isinstance(entry, dict):
                continue
            # Primary: changes.workloads_affected.after (actual PCE format)
            changes = entry.get('changes')
            if isinstance(changes, dict):
                wa = changes.get('workloads_affected')
                if isinstance(wa, dict):
                    val = wa.get('after', 0)
                    try:
                        total += int(val or 0)
                    except (TypeError, ValueError):
                        pass
                    continue
            # Fallback: top-level entry.workloads_affected
            val = entry.get('workloads_affected', 0)
            try:
                total += int(val or 0)
            except (TypeError, ValueError):
                pass
    # Source 2: notifications (backup)
    if total == 0:
        notifications = row.get('notifications')
        if isinstance(notifications, (list, tuple)):
            for n in notifications:
                if isinstance(n, dict):
                    info = n.get('info', {})
                    if isinstance(info, dict):
                        val = info.get('workloads_affected', 0)
                        try:
                            total += int(val or 0)
                        except (TypeError, ValueError):
                            pass
    return total


# ── Main generator class ─────────────────────────────────────────────────────

class AuditGenerator:
    def __init__(self, config_manager, api_client=None, config_dir: str = 'config'):
        self.cm = config_manager
        self.api = api_client
        self._config_dir = config_dir

    def generate_from_api(self, start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> AuditReportResult:
        if not self.api:
            raise RuntimeError("api_client required for audit generation")

        if not end_date:
            end_date = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        if not start_date:
            start_date = (
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
            ).isoformat().replace("+00:00", "Z")

        print(t("rpt_audit_querying", start=start_date, end=end_date))
        events = self.api.fetch_events(start_time_str=start_date, end_time_str=end_date)

        if not events:
            print(t("rpt_audit_no_events"))
            return AuditReportResult(record_count=0)

        df = self._build_dataframe(events)
        print(t("rpt_audit_records", count=f"{len(df):,}"))

        return self._run_pipeline(df, start_date, end_date)

    @staticmethod
    def _build_dataframe(events: list) -> pd.DataFrame:
        """Build a DataFrame from raw PCE event JSON list, flattening nested fields."""
        df = pd.DataFrame(events)
        normalized_events = [normalize_event(event) for event in events]
        normalized_df = pd.DataFrame(normalized_events)

        if 'created_by' in df.columns:
            df['created_by_raw'] = df['created_by']
        if 'action' in df.columns:
            df['action_raw'] = df['action']

        normalized_columns = (
            'event_id',
            'category',
            'verb',
            'actor',
            'actor_type',
            'actor_user',
            'actor_agent',
            'source',
            'source_ip',
            'target_type',
            'target_name',
            'resource_type',
            'resource_name',
            'action',
            'action_method',
            'action_path',
            'workloads_affected',
            'known_event_type',
            'parser_notes',
            'resource_changes_count',
            'notifications_count',
        )
        for column in normalized_columns:
            if column in normalized_df.columns:
                df[column] = normalized_df[column]

        # 1. actor / created_by
        if 'actor' in df.columns:
            df['created_by'] = df['actor'].fillna('').astype(str)
        elif 'created_by' in df.columns:
            raw_cb = df['created_by']
            df['agent_hostname'] = raw_cb.apply(_extract_agent_hostname)
            df['created_by'] = raw_cb.apply(_extract_created_by)
            df['actor'] = df['created_by']
        else:
            df['actor'] = ''
            df['created_by'] = ''

        if 'agent_hostname' not in df.columns:
            if 'created_by_raw' in df.columns:
                df['agent_hostname'] = df['created_by_raw'].apply(_extract_agent_hostname)
            else:
                df['agent_hostname'] = ''

        # 2. action / source IP aliases
        if 'source_ip' not in df.columns:
            if 'action_raw' in df.columns:
                df['source_ip'] = df['action_raw'].apply(_extract_src_ip)
            else:
                df['source_ip'] = ''
        df['src_ip'] = df['source_ip'].fillna('').astype(str)

        if 'action_method' not in df.columns:
            if 'action_raw' in df.columns:
                df['action_method'] = df['action_raw'].apply(_extract_api_method)
            else:
                df['action_method'] = ''
        if 'action_path' not in df.columns:
            if 'action_raw' in df.columns:
                df['action_path'] = df['action_raw'].apply(_extract_api_endpoint)
            else:
                df['action_path'] = ''
        if 'action' not in df.columns:
            df['action'] = ''

        df['api_method'] = df['action_method'].fillna('').astype(str)
        df['api_endpoint'] = df['action_path'].fillna('').astype(str)

        # 3. notifications
        if 'notifications' in df.columns:
            df['notification_detail'] = df['notifications'].apply(_extract_notifications_detail)
            df['supplied_username'] = df['notifications'].apply(_extract_supplied_username)
        else:
            df['notification_detail'] = ''
            df['supplied_username'] = ''

        # 4. parser completeness fields
        if 'parser_notes' in df.columns:
            df['parser_note_count'] = df['parser_notes'].apply(
                lambda value: len(value) if isinstance(value, (list, tuple)) else 0
            )
            df['parser_notes'] = df['parser_notes'].apply(_stringify_parser_notes)
        else:
            df['parser_notes'] = ''
            df['parser_note_count'] = 0
        if 'known_event_type' not in df.columns:
            df['known_event_type'] = False

        # 5. workloads_affected (parser first, raw fallback)
        if 'workloads_affected' not in df.columns:
            df['workloads_affected'] = 0
        fallback_wa = df.apply(_extract_workloads_affected_from_event, axis=1)
        df['workloads_affected'] = (
            pd.to_numeric(df['workloads_affected'], errors='coerce')
            .fillna(0)
            .astype(int)
        )
        fallback_wa = pd.to_numeric(fallback_wa, errors='coerce').fillna(0).astype(int)
        df.loc[df['workloads_affected'] <= 0, 'workloads_affected'] = fallback_wa[df['workloads_affected'] <= 0]

        # 6. change_detail: draft events → before/after field diffs;
        #    provision events → commit_message + object_counts (no field diffs exist)
        if 'resource_changes' in df.columns:
            if 'event_type' in df.columns:
                prov_mask = df['event_type'].isin(_PROVISION_EVENT_TYPES)
                df['change_detail'] = ''
                if (~prov_mask).any():
                    df.loc[~prov_mask, 'change_detail'] = (
                        df.loc[~prov_mask, 'resource_changes']
                        .apply(_summarize_resource_changes)
                    )
                if prov_mask.any():
                    df.loc[prov_mask, 'change_detail'] = (
                        df[prov_mask].apply(_summarize_provision, axis=1)
                    )
            else:
                df['change_detail'] = df['resource_changes'].apply(_summarize_resource_changes)
        else:
            df['change_detail'] = ''

        # 7. convenience aliases + defaults
        if 'target_name' not in df.columns:
            df['target_name'] = ''
        if 'resource_name' not in df.columns:
            df['resource_name'] = ''
        if 'source' not in df.columns:
            df['source'] = df['actor']

        # 8. pce_fqdn (keep as-is if present)
        if 'pce_fqdn' not in df.columns:
            df['pce_fqdn'] = ''

        return df

    def _run_pipeline(self, df: pd.DataFrame, start_date: str,
                      end_date: str) -> AuditReportResult:
        from src.report.analysis.audit.audit_mod01_health import audit_system_health
        from src.report.analysis.audit.audit_mod02_users import audit_user_activity
        from src.report.analysis.audit.audit_mod03_policy import audit_policy_changes
        from src.report.analysis.audit.audit_mod00_executive import audit_executive_summary

        results = {}
        _MODS = [
            ('mod01', lambda: audit_system_health(df)),
            ('mod02', lambda: audit_user_activity(df)),
            ('mod03', lambda: audit_policy_changes(df)),
        ]

        for mod_id, fn in _MODS:
            try:
                results[mod_id] = fn()
                print(f"[Audit Report]   {mod_id} OK", end="  \r", flush=True)
            except Exception as e:
                logger.warning(f"{mod_id} failed: {e}")
                results[mod_id] = {'error': str(e)}

        results['mod00'] = audit_executive_summary(results, df)
        print(t("rpt_audit_complete") + "             ")

        return AuditReportResult(
            record_count=len(df),
            date_range=(start_date[:10], end_date[:10]),
            module_results=results,
            dataframe=df
        )

    def export(self, result: AuditReportResult, fmt: str = 'html',
               output_dir: str = 'reports') -> list[str]:
        from src.report.exporters.audit_html_exporter import AuditHtmlExporter
        from src.report.exporters.csv_exporter import CsvExporter
        paths = []
        if fmt in ('html', 'all'):
            path = AuditHtmlExporter(
                result.module_results, df=result.dataframe,
                date_range=result.date_range
            ).export(output_dir)
            paths.append(path)
            print(t("rpt_audit_html_saved", path=path))
        if fmt in ('csv', 'all'):
            # Include full raw event data alongside module results
            export_data = dict(result.module_results)
            if result.dataframe is not None and not result.dataframe.empty:
                export_data['raw_events'] = result.dataframe
            path = CsvExporter(export_data, report_label='Audit').export(output_dir)
            paths.append(path)
            print(t("rpt_audit_csv_saved", path=path))
        return paths
