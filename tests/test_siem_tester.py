from unittest.mock import MagicMock, patch
from src.config_models import SiemDestinationSettings
from src.siem.tester import send_test_event, TestResult


def _dest(**kw):
    base = dict(name="demo", enabled=True, transport="udp",
                format="cef", endpoint="127.0.0.1:514")
    base.update(kw); return SiemDestinationSettings(**base)


def test_send_test_event_success():
    with patch("src.siem.tester._build_transport") as bt:
        tx = MagicMock(); bt.return_value = tx
        r = send_test_event(_dest())
    assert isinstance(r, TestResult) and r.ok is True and r.error is None
    tx.send.assert_called_once(); tx.close.assert_called_once()


def test_send_test_event_failure():
    with patch("src.siem.tester._build_transport") as bt:
        tx = MagicMock(); tx.send.side_effect = RuntimeError("refused")
        bt.return_value = tx
        r = send_test_event(_dest())
    assert r.ok is False and "refused" in r.error


def test_send_test_event_hec_format():
    dest = _dest(format="json", transport="hec",
                 hec_token="abc", endpoint="https://splunk:8088")
    with patch("src.siem.tester._build_transport") as bt:
        bt.return_value = MagicMock()
        r = send_test_event(dest)
    assert r.ok is True
