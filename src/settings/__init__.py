"""src/settings — backwards-compatibility re-export shim.

The wizard functions and catalog constants have moved:
  Wizards  → src/cli/menus/
  Catalogs → src/events/catalog

This shim re-exports every public symbol so all six importers of
`from src.settings import X` continue to work unchanged.

This shim also re-exports `os` and `get_last_input_action` at module level
so that test patches of `settings_module.os` and
`settings_module.get_last_input_action` (in tests/test_manage_rules_menu.py
and tests/test_wizard_default_enter.py) remain effective during Tasks 3-10
while wizard code still lives in _legacy.py.
"""
from __future__ import annotations

import os  # noqa: F401  (needed for test-patch compatibility)
from src.utils import get_last_input_action  # noqa: F401  (ditto)

from src.settings._legacy import (  # noqa: F401
    # Catalog constants
    FULL_EVENT_CATALOG,
    ACTION_EVENTS,
    SEVERITY_FILTER_EVENTS,
    DISCOVERY_EVENTS,
    EVENT_DESCRIPTION_KEYS,
    EVENT_TIPS_KEYS,
    # Catalog helpers (used by src/gui/__init__.py)
    _event_category,
    # Wizard functions (used by src/main.py)
    settings_menu,
    add_event_menu,
    add_system_health_menu,
    add_traffic_menu,
    add_bandwidth_volume_menu,
    manage_rules_menu,
    manage_report_schedules_menu,
    # Helpers accessed via settings_module in tests
    _parse_manage_rules_command,
    _wizard_step,
    _wizard_confirm,
    _menu_hints,
    _tz_offset_info,
    _utc_to_local_hour,
    _local_to_utc_hour,
    _empty_uses_default,
)
