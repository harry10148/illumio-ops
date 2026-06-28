"""Event deep-link host resolution for on-prem vs Illumio SaaS.

On-prem the API host also serves the web console. SaaS serves the API from a
regional SCP cluster (e.g. *.ap-scp1.illumio.com) but the web console is the
region-agnostic console.illum.io — a different host — so the API-derived base
would 404. The link must target console.illum.io for SaaS.
"""
from unittest.mock import MagicMock
from src.reporter import Reporter


def _reporter_with_api(url: str) -> Reporter:
    cm = MagicMock()
    cm.config = {"api": {"url": url}, "email": {}, "alerts": {"active": []}}
    return Reporter(cm)


def test_event_console_link_onprem_uses_api_host():
    r = _reporter_with_api("https://pce.lab.local:8443/api/v2")
    link = r._event_console_link({"href": "/orgs/1/events/evt-1"})
    assert link == "https://pce.lab.local:8443/#/events/evt-1"


def test_event_console_link_saas_ap_scp_maps_to_console():
    r = _reporter_with_api("https://pce.ap-scp1.illumio.com/api/v2")
    link = r._event_console_link({"href": "/orgs/1/events/evt-1"})
    assert link == "https://console.illum.io/#/events/evt-1"


def test_event_console_link_saas_other_region_scp_also_maps():
    r = _reporter_with_api("https://us-scp1.illumio.com")
    link = r._event_console_link({"href": "/orgs/2/events/x"})
    assert link == "https://console.illum.io/#/events/x"


def test_event_console_link_onprem_illumio_com_without_scp_unchanged():
    # A non-SCP host (even on illumio.com) is not SaaS — keep the API host.
    r = _reporter_with_api("https://pce.demo.illumio.com:8443")
    link = r._event_console_link({"href": "/orgs/1/events/evt-1"})
    assert link == "https://pce.demo.illumio.com:8443/#/events/evt-1"
