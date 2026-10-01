import pytest
import responses as responses_lib


@responses_lib.activate
def test_hec_sends_post_with_token():
    from src.siem.transports.splunk_hec import SplunkHECTransport
    responses_lib.add(
        responses_lib.POST,
        "https://splunk.example.com/services/collector/event",
        json={"text": "Success", "code": 0},
        status=200,
    )
    tr = SplunkHECTransport("https://splunk.example.com", token="mytoken", verify_tls=False)
    tr.send("test event payload")
    assert len(responses_lib.calls) == 1
    assert "Splunk mytoken" in responses_lib.calls[0].request.headers["Authorization"]


@responses_lib.activate
def test_hec_raises_on_400():
    from src.siem.transports.splunk_hec import SplunkHECTransport
    responses_lib.add(
        responses_lib.POST,
        "https://splunk.example.com/services/collector/event",
        json={"text": "Invalid token", "code": 4},
        status=400,
    )
    tr = SplunkHECTransport("https://splunk.example.com", token="bad", verify_tls=False)
    with pytest.raises(Exception):
        tr.send("payload")


@responses_lib.activate
def test_hec_retries_on_503():
    from src.siem.transports.splunk_hec import SplunkHECTransport
    # First two attempts fail with 503, third succeeds
    for _ in range(2):
        responses_lib.add(
            responses_lib.POST,
            "https://splunk.example.com/services/collector/event",
            status=503,
        )
    responses_lib.add(
        responses_lib.POST,
        "https://splunk.example.com/services/collector/event",
        json={"text": "Success", "code": 0},
        status=200,
    )
    tr = SplunkHECTransport("https://splunk.example.com", token="tok", verify_tls=False)
    tr.send("retry payload")
    assert len(responses_lib.calls) == 3


@responses_lib.activate
def test_hec_send_record_carries_event_time():
    """沒帶 time 時 Splunk 以收到時間為事件時間；send_record 必須帶上記錄時間。"""
    import json as _json
    from src.siem.transports.splunk_hec import SplunkHECTransport
    responses_lib.add(responses_lib.POST,
                      "https://splunk.example.com/services/collector/event",
                      json={"text": "Success", "code": 0}, status=200)
    tr = SplunkHECTransport("https://splunk.example.com", token="t", verify_tls=False)
    tr.send_record('{"a": 1}', event_time=1757559845.123)
    body = _json.loads(responses_lib.calls[0].request.body)
    assert body["time"] == 1757559845.123
    assert body["event"] == {"a": 1}


def test_hec_uses_ca_bundle_when_verifying():
    """tls_ca_bundle 舊版沒有傳進 HEC：私有 CA 簽發的 Splunk 只能關掉驗證。"""
    from src.siem.transports.splunk_hec import SplunkHECTransport
    tr = SplunkHECTransport("https://splunk.example.com", token="t",
                            verify_tls=True, ca_bundle="/etc/ssl/private-ca.pem")
    assert tr._verify == "/etc/ssl/private-ca.pem"
    off = SplunkHECTransport("https://splunk.example.com", token="t",
                             verify_tls=False, ca_bundle="/etc/ssl/private-ca.pem")
    assert off._verify is False


def test_hec_retries_only_when_event_was_not_accepted():
    """500/502/504 與讀取逾時時事件可能已進 Splunk，urllib3 不得自動重送（會重複）。"""
    from src.siem.transports.splunk_hec import SplunkHECTransport
    tr = SplunkHECTransport("https://splunk.example.com", token="t", verify_tls=False)
    retry = tr._session.get_adapter("https://splunk.example.com").max_retries
    assert set(retry.status_forcelist) == {429, 503}
    assert retry.read == 0


def test_build_dispatcher_passes_ca_bundle_to_hec():
    from unittest.mock import MagicMock
    from src.config_models import SiemDestinationSettings
    from src.siem.dispatcher import build_dispatcher
    cfg = SiemDestinationSettings(name="splunk", transport="hec", format="json",
                                  host="splunk.example.com", port=8088, hec_token="t",
                                  tls_ca_bundle="/etc/ssl/private-ca.pem")
    d = build_dispatcher(cfg, MagicMock())
    assert d._transport._verify == "/etc/ssl/private-ca.pem"
