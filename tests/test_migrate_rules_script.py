"""Migration converts text-based rules to key-based rules."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_migration_dry_run(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "rules": [
            {"id": "001", "event_type": "sec_policy.create",
             "desc": "Policy provisioning event detected",
             "rec": "Review provisioning logs."}
        ]
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_rules_to_keys.py"),
         "--config", str(cfg), "--dry-run"],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert result.returncode == 0, result.stderr
    assert "would migrate 1 rule" in result.stdout
    # File unchanged on dry-run
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "desc_key" not in data["rules"][0]
    assert "rec_key" not in data["rules"][0]


def test_migration_write(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "rules": [
            {"id": "001", "event_type": "sec_policy.create",
             "desc": "Policy provisioning event detected",
             "rec": "Review provisioning logs."}
        ]
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_rules_to_keys.py"),
         "--config", str(cfg), "--write"],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(cfg.read_text(encoding="utf-8"))
    rule = data["rules"][0]
    assert rule.get("desc_key") == "rule_sec_policy.create_desc", rule
    assert rule.get("rec_key") == "alert_rec_sec_policy_create", rule
    # Original desc/rec preserved (T19 strips them on save)
    assert rule.get("desc")
    assert rule.get("rec")


def test_migration_idempotent(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "rules": [
            {"id": "001", "event_type": "sec_policy.create",
             "desc_key": "rule_sec_policy.create_desc",
             "rec_key": "alert_rec_sec_policy_create"}
        ]
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_rules_to_keys.py"),
         "--config", str(cfg), "--dry-run"],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert result.returncode == 0
    assert "would migrate 0 rule" in result.stdout
