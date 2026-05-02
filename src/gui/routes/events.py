"""Events Blueprint: event viewer, shadow compare, rule test, and catalog routes."""
from __future__ import annotations

import datetime
import json

from flask import Blueprint, jsonify, request
from loguru import logger

from src.config import ConfigManager
from src.gui._helpers import _err


def make_events_blueprint(
    cm: ConfigManager,
    csrf,           # flask_wtf.csrf.CSRFProtect instance (unused here, kept for consistent signature)
    limiter,        # flask_limiter.Limiter instance (unused here, kept for consistent signature)
    login_required,  # flask_login.login_required decorator (unused here, kept for consistent signature)
) -> Blueprint:
    bp = Blueprint("events", __name__)

    @bp.route('/api/events/viewer')
    def api_events_viewer():
        cm.load()
        try:
            from src.api_client import ApiClient, EventFetchError
            from src.events import event_identity, format_utc, normalize_event, parse_event_timestamp
            from src.settings import _event_category
        except Exception as exc:
            logger.error("Failed to load event viewer dependencies: {}", exc)
            return _err("Service unavailable", 500)

        try:
            mins = max(5, min(int(request.args.get('mins', 60)), 10080))
        except (TypeError, ValueError):
            mins = 60
        try:
            limit = max(1, min(int(request.args.get('limit', 50)), 200))
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = max(0, int(request.args.get('offset', 0)))
        except (TypeError, ValueError):
            offset = 0

        search = str(request.args.get('search', '') or '').strip().lower()
        category_filter = str(request.args.get('category', '') or '').strip()
        type_group_filter = str(request.args.get('type_group', '') or '').strip()
        event_type_filter = str(request.args.get('event_type', '') or '').strip()

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        since_utc = now_utc - datetime.timedelta(minutes=mins)
        query_since = format_utc(since_utc)
        query_until = format_utc(now_utc)
        fetch_limit = min(max((offset + limit) * 4, 100), 5000)

        api_client = ApiClient(cm)
        try:
            raw_events = api_client.fetch_events_strict(
                start_time_str=query_since,
                end_time_str=query_until,
                max_results=fetch_limit,
            )
        except EventFetchError as exc:
            logger.error("Event viewer fetch failed: {} - {}", exc.status, exc.message)
            return _err(f"PCE event fetch failed ({exc.status}): {exc.message[:300]}", 502)
        except Exception as exc:
            logger.error("Event viewer fetch failed: {}", exc, exc_info=True)
            return _err(f"PCE event fetch failed: {exc}", 502)

        items = []
        for raw_event in raw_events:
            normalized = normalize_event(raw_event)
            event_type = normalized.get("event_type") or raw_event.get("event_type") or ""
            event_group = "*" if event_type == "*" else event_type.split(".", 1)[0]

            if event_type_filter and event_type != event_type_filter:
                continue
            if type_group_filter and event_group != type_group_filter:
                continue
            if category_filter and _event_category(event_type) != category_filter:
                continue

            if search:
                haystack = " ".join([
                    event_type,
                    normalized.get('actor', ''),
                    normalized.get('target_name', ''),
                    normalized.get('resource_name', ''),
                    normalized.get('action', ''),
                    normalized.get('source_ip', ''),
                    json.dumps(raw_event, ensure_ascii=False, default=str),
                ]).lower()
                if search not in haystack:
                    continue

            items.append({
                "event_id": event_identity(raw_event),
                "timestamp": normalized.get("timestamp") or raw_event.get("timestamp"),
                "event_type": event_type,
                "status": normalized.get("status") or raw_event.get("status"),
                "severity": normalized.get("severity") or raw_event.get("severity"),
                "known_event_type": normalized.get("known_event_type"),
                "parser_notes": normalized.get("parser_notes") or [],
                "category": _event_category(event_type),
                "type_group": event_group,
                "normalized": normalized,
                "raw": raw_event,
            })

        items.sort(
            key=lambda item: parse_event_timestamp(item.get("timestamp")) or now_utc,
            reverse=True,
        )
        visible_items = items[offset:offset + limit]

        return jsonify({
            "ok": True,
            "items": visible_items,
            "summary": {
                "fetched_count": len(raw_events),
                "matched_count": len(items),
                "returned_count": len(visible_items),
                "offset": offset,
                "limit": limit,
                "has_more": (offset + limit) < len(items),
                "query_since": query_since,
                "query_until": query_until,
                "category": category_filter,
                "type_group": type_group_filter,
                "event_type": event_type_filter,
            },
        })

    @bp.route('/api/events/shadow_compare')
    def api_events_shadow_compare():
        cm.load()
        try:
            from src.api_client import ApiClient, EventFetchError
            from src.events import compare_event_rules, format_utc
        except Exception as exc:
            logger.error("Failed to load shadow compare dependencies: {}", exc)
            return _err("Service unavailable", 500)

        try:
            mins = max(5, min(int(request.args.get('mins', 60)), 10080))
        except (TypeError, ValueError):
            mins = 60
        try:
            limit = max(1, min(int(request.args.get('limit', 200)), 500))
        except (TypeError, ValueError):
            limit = 200

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        since_utc = now_utc - datetime.timedelta(minutes=mins)
        query_since = format_utc(since_utc)
        query_until = format_utc(now_utc)

        api_client = ApiClient(cm)
        try:
            events = api_client.fetch_events_strict(
                start_time_str=query_since,
                end_time_str=query_until,
                max_results=limit,
            )
        except EventFetchError as exc:
            return _err(f"PCE event fetch failed ({exc.status}): {exc.message[:300]}", 502)
        except Exception as exc:
            return _err(f"PCE event fetch failed: {exc}", 502)

        event_rules = [rule for rule in cm.config.get("rules", []) if rule.get("type") == "event"]
        comparisons = compare_event_rules(event_rules, events)
        divergent = [item for item in comparisons if item.get("status") != "same"]

        return jsonify({
            "ok": True,
            "summary": {
                "query_since": query_since,
                "query_until": query_until,
                "fetched_events": len(events),
                "rule_count": len(event_rules),
                "divergent_rules": len(divergent),
            },
            "items": comparisons,
        })

    @bp.route('/api/events/rule_test')
    def api_events_rule_test():
        cm.load()
        try:
            from src.api_client import ApiClient, EventFetchError
            from src.events import (
                compare_event_rules,
                event_identity,
                format_utc,
                matches_event_rule,
                matches_event_rule_legacy,
                normalize_event,
            )
        except Exception as exc:
            logger.error("Failed to load rule test dependencies: {}", exc)
            return _err("Service unavailable", 500)

        try:
            idx = int(request.args.get('idx', '-1'))
        except (TypeError, ValueError):
            return _err("invalid rule index", 400)
        if idx < 0 or idx >= len(cm.config.get('rules', [])):
            return _err("rule not found", 404)

        rule = cm.config['rules'][idx]
        if rule.get('type') != 'event':
            return _err("rule is not an event rule", 400)

        try:
            mins = max(5, min(int(request.args.get('mins', 60)), 10080))
        except (TypeError, ValueError):
            mins = 60
        try:
            limit = max(1, min(int(request.args.get('limit', 300)), 500))
        except (TypeError, ValueError):
            limit = 300

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        since_utc = now_utc - datetime.timedelta(minutes=mins)
        query_since = format_utc(since_utc)
        query_until = format_utc(now_utc)

        api_client = ApiClient(cm)
        try:
            events = api_client.fetch_events_strict(
                start_time_str=query_since,
                end_time_str=query_until,
                max_results=limit,
            )
        except EventFetchError as exc:
            return _err(f"PCE event fetch failed ({exc.status}): {exc.message[:300]}", 502)
        except Exception as exc:
            return _err(f"PCE event fetch failed: {exc}", 502)

        event_lookup = {event_identity(event): event for event in events}
        current_ids = {
            event_identity(event)
            for event in events
            if matches_event_rule(rule, event)
        }
        legacy_ids = {
            event_identity(event)
            for event in events
            if matches_event_rule_legacy(rule, event)
        }
        only_current = sorted(current_ids - legacy_ids)
        only_legacy = sorted(legacy_ids - current_ids)
        current_matches = sorted(current_ids)
        comparison = compare_event_rules([rule], events)[0]

        def _serialize(event_id):
            raw_event = event_lookup.get(event_id, {})
            return {
                "event_id": event_id,
                "timestamp": raw_event.get("timestamp"),
                "event_type": raw_event.get("event_type"),
                "normalized": normalize_event(raw_event),
                "raw": raw_event,
            }

        return jsonify({
            "ok": True,
            "rule": {
                "index": idx,
                "id": rule.get("id"),
                "name": rule.get("name"),
                "filter_value": rule.get("filter_value"),
                "filter_status": rule.get("filter_status"),
                "filter_severity": rule.get("filter_severity"),
                "match_fields": rule.get("match_fields") or rule.get("filter_match_fields") or {},
            },
            "summary": {
                "query_since": query_since,
                "query_until": query_until,
                "fetched_events": len(events),
                "current_count": len(current_ids),
                "legacy_count": len(legacy_ids),
                "delta": len(current_ids) - len(legacy_ids),
                "status": comparison.get("status"),
            },
            "current_matches": [_serialize(event_id) for event_id in current_matches[:20]],
            "only_current": [_serialize(event_id) for event_id in only_current[:10]],
            "only_legacy": [_serialize(event_id) for event_id in only_legacy[:10]],
        })

    @bp.route('/api/event-catalog')
    def api_event_catalog():
        from src.events.catalog import LOCAL_EXTENSION_EVENT_TYPES
        from src.settings import FULL_EVENT_CATALOG, ACTION_EVENTS, SEVERITY_FILTER_EVENTS, EVENT_DESCRIPTION_KEYS, EVENT_TIPS_KEYS
        from src.i18n import set_language, t

        cm.load()
        set_language(cm.config.get("settings", {}).get("language", "en"))

        # Build prefix → [event_id, ...] map for related_events computation
        prefix_map: dict[str, list[str]] = {}
        for events in FULL_EVENT_CATALOG.values():
            for event_id in events:
                if event_id == "*":
                    continue
                prefix = event_id.split(".")[0]
                prefix_map.setdefault(prefix, []).append(event_id)

        translated_catalog = {}
        categories = []
        for category, events in FULL_EVENT_CATALOG.items():
            trans_cat = t('cat_' + category.replace(' ', '_').lower())
            if category == "Agent Health Detail":
                trans_cat = t('cat_agent_health', default="Agent Health")

            if trans_cat not in translated_catalog:
                translated_catalog[trans_cat] = {}

            event_items = []
            for event_id, translation_key in events.items():
                label = t(translation_key)
                desc_key = EVENT_DESCRIPTION_KEYS.get(event_id)
                description = t(desc_key) if desc_key else ''
                tips_key = EVENT_TIPS_KEYS.get(event_id)
                tips = t(tips_key) if tips_key else ''
                supports_status = event_id in ACTION_EVENTS
                supports_severity = event_id in SEVERITY_FILTER_EVENTS or event_id == "*"
                prefix = event_id.split(".")[0] if event_id != "*" else None
                related = [e for e in prefix_map.get(prefix, []) if e != event_id] if prefix else []
                translated_catalog[trans_cat][event_id] = label
                event_items.append({
                    'id': event_id,
                    'label': label,
                    'description': description,
                    'tips': tips,
                    'related_events': related,
                    'source': 'local_extension' if event_id in LOCAL_EXTENSION_EVENT_TYPES else 'vendor_baseline',
                    'supports_status': supports_status,
                    'supports_severity': supports_severity,
                })

            categories.append({
                'id': category,
                'label': trans_cat,
                'events': event_items,
            })

        return jsonify({
            'catalog': translated_catalog,
            'categories': categories,
            'action_events': ACTION_EVENTS,
            'severity_filter_events': SEVERITY_FILTER_EVENTS,
        })

    return bp
