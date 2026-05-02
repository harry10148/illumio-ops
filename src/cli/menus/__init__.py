"""CLI interactive wizard menus.

Public wizard functions are exported here as a convenience. Each function
also lives in its own module (event.py, traffic.py, etc.).
"""
# Populated incrementally by Tasks 5-10.
from src.cli.menus.event import add_event_menu  # noqa: F401
from src.cli.menus.system_health import add_system_health_menu  # noqa: F401
from src.cli.menus.traffic import add_traffic_menu  # noqa: F401
