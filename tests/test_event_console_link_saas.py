"""Event deep links use the deployment's resolved PCE Console URL."""
from urllib.parse import urlsplit
from unittest.mock import MagicMock

import pytest

from src.reporter import Reporter


def _reporter_with_api(
    url: str,
    *,
    deployment_type: str,
    console_url: str = "",
) -> Reporter:
    cm = MagicMock()
    cm.config = {
        "api": {
            "url": url,
            "deployment_type": deployment_type,
            "console_url": console_url,
        },
        "email": {},
        "alerts": {"active": []},
    }
    return Reporter(cm)


def test_event_console_link_saas_uses_default_console_for_real_api_host():
    r = _reporter_with_api(
        "https://ap-scp45.illum.io/api/v2",
        deployment_type="saas",
        console_url="",
    )
    link = r._event_console_link({"href": "/orgs/1/events/evt-1"})
    assert link == "https://console.illum.io/#/events/evt-1"


def test_event_console_link_saas_uses_custom_console_url():
    r = _reporter_with_api(
        "https://poc3.illum.io/api/v2",
        deployment_type="saas",
        console_url="https://tenant.illumio.ai/",
    )
    link = r._event_console_link({"href": "/orgs/7/events/evt-2"})
    assert link == "https://tenant.illumio.ai/#/events/evt-2"


def test_event_console_link_onprem_uses_api_origin_when_console_url_empty():
    r = _reporter_with_api(
        "https://pce.lab.local:8443/api/v2",
        deployment_type="on_prem",
        console_url="",
    )
    link = r._event_console_link({"href": "/orgs/1/events/evt-3"})
    assert link == "https://pce.lab.local:8443/#/events/evt-3"


def test_event_console_link_without_href_returns_resolved_console_landing_page():
    r = _reporter_with_api(
        "https://poc3.illum.io/api/v2",
        deployment_type="saas",
        console_url="https://tenant.illumio.ai/",
    )
    assert r._event_console_link({}) == "https://tenant.illumio.ai"


@pytest.mark.parametrize("href", [
    "https://fake-user:fake-pass@evil.invalid/events/evt-hostile",
    "//fake-user:fake-pass@evil.invalid/events/evt-hostile",
    "javascript:alert('evt-hostile')",
])
def test_hostile_event_href_cannot_change_console_authority(href):
    r = _reporter_with_api(
        "https://ap-scp45.illum.io/api/v2",
        deployment_type="saas",
        console_url="",
    )

    parts = urlsplit(r._event_console_link({"href": href}))

    assert parts.scheme == "https"
    assert parts.hostname == "console.illum.io"
    assert parts.username is None
    assert parts.password is None
