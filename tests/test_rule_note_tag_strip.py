"""排程註記清除的 emoji 前綴對稱性（backlog fix 1）。

GUI 建立 one_time 排程寫入鬧鐘符號（U+23F0）前綴的註記
（src/gui/routes/rule_scheduler.py），CLI 寫沙漏符號（U+23F3，
src/rule_scheduler_cli.py）；清除與顯示裁切必須三種前綴
（行事曆 U+1F4C5／沙漏／鬧鐘）都認得，否則 GUI 建的註記
刪除與到期都清不掉、永久殘留在 PCE rule description。
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient
from src.rule_scheduler import truncate

_CAL = "\U0001F4C5"    # 行事曆符號
_HOURGLASS = "⏳"  # 沙漏符號（CLI one_time）
_ALARM = "⏰"      # 鬧鐘符號（GUI one_time）


def _make_client():
    cm = MagicMock()
    cm.config = {
        "api": {
            "url": "https://pce.example.com:8443",
            "org_id": "1",
            "key": "key",
            "secret": "secret",
            "verify_ssl": False,
        }
    }
    return ApiClient(cm)


class TestUpdateRuleNoteStripsAllTagPrefixes(unittest.TestCase):
    def _run_remove(self, description):
        client = _make_client()
        client._api_get = MagicMock(return_value=(200, {"description": description}))
        client.has_draft_changes = MagicMock(return_value=True)  # 避免 provision 分支
        captured = {}

        def fake_put(href, body):
            captured["body"] = body
            return 204

        client._api_put = MagicMock(side_effect=fake_put)
        ok = client.update_rule_note("/orgs/1/sec_policy/active/rule_sets/1/sec_rules/1", "", remove=True)
        self.assertTrue(ok)
        return captured.get("body", {}).get("description")

    def test_removes_gui_alarm_prefixed_one_time_tag(self):
        desc = f"My rule [{_ALARM} Expires: 2026-08-01 00:00]"
        self.assertEqual(self._run_remove(desc), "My rule")

    def test_removes_cli_hourglass_prefixed_one_time_tag(self):
        desc = f"My rule [{_HOURGLASS} Expires: 2026-08-01 00:00]"
        self.assertEqual(self._run_remove(desc), "My rule")

    def test_removes_calendar_prefixed_recurring_tag(self):
        desc = f"My rule [{_CAL} Recurring: Mon 08:00-18:00 Enable in window]"
        self.assertEqual(self._run_remove(desc), "My rule")


class TestTruncateStripsAllTagPrefixes(unittest.TestCase):
    def test_truncate_strips_alarm_tag(self):
        text = f"My rule [{_ALARM} Expires: 2026-08-01 00:00]"
        self.assertEqual(truncate(text, 20).strip(), "My rule")

    def test_truncate_strips_hourglass_tag(self):
        text = f"My rule [{_HOURGLASS} Expires: 2026-08-01 00:00]"
        self.assertEqual(truncate(text, 20).strip(), "My rule")


if __name__ == "__main__":
    unittest.main()
