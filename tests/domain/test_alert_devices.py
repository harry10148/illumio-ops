"""Which hosts an alert is about (purpose-led UI spec §8): read from a detection's fingerprint or from the events that
fired the rule — a part that is not a host is left out, never guessed."""
import pytest

from illumio_ops.domain.alert_devices import (
    MAX_DEVICES,
    Device,
    capped,
    devices_of_detection,
    devices_of_events,
)

W = "/orgs/1/workloads/"


@pytest.mark.parametrize("fingerprint, expected", [
    (f"xenv|{W}a|{W}b|22|6", [(W + "a", "source"), (W + "b", "destination")]),
    (f"nag|{W}a|{W}b|3389|6", [(W + "a", "source"), (W + "b", "destination")]),
    (f"new|{W}a|ip:10.0.0.9|22|6", [(W + "a", "source"), ("ip:10.0.0.9", "destination")]),
    (f"authdst|{W}a|{W}b|88", [(W + "a", "source"), (W + "b", "destination")]),
    (f"reverse|{W}a|{W}b", [(W + "a", "source"), (W + "b", "destination")]),
    (f"pairport|{W}a|ip:10.0.0.9|many", [(W + "a", "source"), ("ip:10.0.0.9", "destination")]),
    (f"fanout|{W}a", [(W + "a", "source")]),
    ("blocked|ip:10.0.0.7", [("ip:10.0.0.7", "source")]),
    (f"newproc|{W}a|psexesvc.exe", [(W + "a", "source")]),
    (f"proc|{W}a|cmd.exe|445|6", [(W + "a", "source")]),
    (f"peer|{W}a|sig123|445|6", [(W + "a", "source")]),           # the signature is not a host
    (f"chain|{W}a|{W}b|{W}c", [(W + "a", "source"), (W + "b", "destination"), (W + "c", "destination")]),
    (f"staging|{W}d", [(W + "d", "destination")]),
    ("acct|CORP\\svc", []),                                         # about an account
    (f"acctsrc|CORP\\svc|{W}a", [(W + "a", "source")]),
    (f"surge|{W}a", [(W + "a", "source")]),                         # a two-part fingerprint of any prefix: its host
    ("something_new|x|y", []),                                      # nothing here is a host
    ("", []),
])
def test_the_hosts_a_detection_is_about(fingerprint, expected):
    assert [(d.key, d.role) for d in devices_of_detection(fingerprint)] == expected


def test_a_host_named_twice_is_listed_once_per_role():
    assert devices_of_detection(f"reverse|{W}a|{W}a") == (Device(W + "a", "source"), Device(W + "a", "destination"))


def test_event_hosts_are_listed_once_in_order_and_what_is_not_a_host_is_left_out():
    assert devices_of_events([W + "a", None, W + "b", W + "a", "", "not-a-host"]) == (
        Device(W + "a", "subject"), Device(W + "b", "subject"))


def test_more_than_the_most_are_cut_and_counted():
    many = devices_of_events(f"{W}h{i}" for i in range(MAX_DEVICES + 5))
    kept, more = capped(many)
    assert len(kept) == MAX_DEVICES and more == 5 and kept[0].key == W + "h0"
    assert capped(many[:3]) == (many[:3], 0)
