"""
Traffic flow analysis modules and module registry.

The registry allows _run_modules() to dynamically discover and execute
analysis modules without hardcoding imports.  To add a new module:

1. Create src/report/analysis/mod{NN}_{name}.py with a callable entry point.
2. Add an entry to TRAFFIC_MODULES below.
3. The module will be automatically imported, executed, and its results
   included in the report.
"""
from __future__ import annotations

import importlib
from loguru import logger
from typing import Callable, Any

import pandas as pd

# ── Module registry ──────────────────────────────────────────────────────────
# Each tuple: (module_id, dotted_module_path, function_name, call_builder)
#   call_builder: a callable (fn, df, report_cfg, top_n) -> result
#   This adapter handles the varying signatures of each module function.

def _call_df(fn, df, _cfg, _n):
    return fn(df)

def _call_df_n(fn, df, _cfg, n):
    return fn(df, n)

def _call_df_cfg_n(fn, df, cfg, n):
    return fn(df, cfg, n)

def _call_readiness(fn, df, _cfg, n):
    return fn(df, workloads=None, top_n=n)

TRAFFIC_MODULES: list[tuple[str, str, str, Callable]] = [
    ('mod01', 'src.report.analysis.mod01_traffic_overview',     'traffic_overview',              _call_df),
    ('mod02', 'src.report.analysis.mod02_policy_decisions',     'policy_decision_analysis',      _call_df_n),
    ('mod03', 'src.report.analysis.mod03_uncovered_flows',      'uncovered_flows',               _call_df_n),
    ('mod04', 'src.report.analysis.mod04_ransomware_exposure',  'ransomware_exposure',           _call_df_cfg_n),
    # mod05 (Remote Access) consolidated into mod15 (Lateral Movement Risk)
    ('mod06', 'src.report.analysis.mod06_user_process',         'user_process_analysis',         _call_df_n),
    ('mod07', 'src.report.analysis.mod07_cross_label_matrix',   'cross_label_flow_matrix',       _call_df_n),
    ('mod08', 'src.report.analysis.mod08_unmanaged_hosts',      'unmanaged_traffic',             _call_df_n),
    ('mod09', 'src.report.analysis.mod09_traffic_distribution', 'traffic_distribution',          _call_df_n),
    ('mod10', 'src.report.analysis.mod10_allowed_traffic',      'allowed_traffic',               _call_df_n),
    ('mod11', 'src.report.analysis.mod11_bandwidth',            'bandwidth_analysis',            _call_df_n),
    ('mod13', 'src.report.analysis.mod13_readiness',            'enforcement_readiness',         _call_readiness),
    ('mod14', 'src.report.analysis.mod14_infrastructure',       'infrastructure_scoring',        _call_df_n),
    ('mod15', 'src.report.analysis.mod15_lateral_movement',     'lateral_movement_risk',         _call_df_n),
]

# Module 12 (executive_summary) runs last and depends on all other results.
SUMMARY_MODULE = ('mod12', 'src.report.analysis.mod12_executive_summary', 'executive_summary')

def load_module_fn(module_path: str, func_name: str) -> Callable:
    """Lazily import a module and return the named function."""
    mod = importlib.import_module(module_path)
    return getattr(mod, func_name)

def get_traffic_modules() -> list[tuple[str, Callable, Callable]]:
    """Return list of (mod_id, function, call_adapter) for all registered traffic modules."""
    result = []
    for mod_id, mod_path, func_name, adapter in TRAFFIC_MODULES:
        try:
            fn = load_module_fn(mod_path, func_name)
            result.append((mod_id, fn, adapter))
        except Exception as e:
            logger.error(f"Failed to load module {mod_id} ({mod_path}): {e}")
    return result

def get_summary_module() -> tuple[str, Callable]:
    """Return (mod_id, function) for the summary module."""
    mod_id, mod_path, func_name = SUMMARY_MODULE
    fn = load_module_fn(mod_path, func_name)
    return mod_id, fn
