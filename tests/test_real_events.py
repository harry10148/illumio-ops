import datetime
import os

import pytest

from src.api_client import ApiClient
from src.config import ConfigManager


pytestmark = pytest.mark.skipif(
    os.getenv("ILLUMIO_RUN_REAL_EVENTS_TEST") != "1",
    reason="manual integration test; set ILLUMIO_RUN_REAL_EVENTS_TEST=1 to enable",
)


def test_fetch_real_events_smoke():
    cm = ConfigManager()
    api = ApiClient(cm)

    end_date = datetime.datetime.now(datetime.timezone.utc)
    start_date = end_date - datetime.timedelta(days=7)

    events = api.fetch_events(
        start_time_str=start_date.isoformat().replace("+00:00", "Z"),
        end_time_str=end_date.isoformat().replace("+00:00", "Z"),
        max_results=100,
    )

    assert isinstance(events, list)
