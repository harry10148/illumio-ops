import os
import datetime
from unittest.mock import MagicMock
import pandas as pd
from src.report.audit_generator import AuditGenerator

class DummyApiClient:
    def fetch_events(self, start_time_str, end_time_str=None, max_results=1000):
        # Fake some recent events
        now = datetime.datetime.now(datetime.timezone.utc)
        return [
            {'timestamp': (now - datetime.timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
             'event_type': 'user.login', 'severity': 'info', 'created_by': {'href': '/users/1'}},
            {'timestamp': (now - datetime.timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
             'event_type': 'user.login_failed', 'severity': 'error'},
            {'timestamp': (now - datetime.timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
             'event_type': 'system_health', 'severity': 'warning'},
            {'timestamp': (now - datetime.timedelta(minutes=40)).isoformat().replace("+00:00", "Z"),
             'event_type': 'sec_rule.create', 'severity': 'info'}
        ]

cm = MagicMock()
cm.config = {'report': {'output_dir': 'reports'}}
api = DummyApiClient()

gen = AuditGenerator(cm, api_client=api, config_dir='config')
res = gen.generate_from_api()

print(f"Record Count: {res.record_count}")
print(f"Mod01 Total Health Events: {res.module_results['mod01']['total_health_events']}")
print(f"Mod02 Failed Logins: {res.module_results['mod02']['failed_logins']}")
print(f"Mod03 Total Policy Events: {res.module_results['mod03']['total_policy_events']}")

paths = gen.export(res, fmt='excel', output_dir='reports')
print(f"Exported to: {paths}")
