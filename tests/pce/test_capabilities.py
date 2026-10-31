from illumio_ops.domain.values import CapabilityState
from illumio_ops.pce.capabilities import (
    CAPABILITIES,
    detect_from_status,
    detect_from_workloads,
    detect_tamper_signal,
)


def test_registry_names():
    assert set(CAPABILITIES) == {"ransomware_risk", "ransomware_org_summary", "visibility_level",
                                 "tamper_signal", "draft_recompute"}


def test_capability_detection_from_workload_fields():
    rows = [{"href": "a", "risk_summary": None, "visibility_level": "flow_summary"},
            {"href": "b", "risk_summary": {"ransomware": {}}, "visibility_level": "flow_summary"}]
    assert detect_from_workloads(rows) == {"ransomware_risk": CapabilityState.SUPPORTED,
                                           "visibility_level": CapabilityState.SUPPORTED}
    old = [{"href": "a"}]
    assert detect_from_workloads(old) == {"ransomware_risk": CapabilityState.UNSUPPORTED,
                                          "visibility_level": CapabilityState.UNSUPPORTED}
    assert detect_from_workloads([]) == {"ransomware_risk": CapabilityState.UNKNOWN,
                                         "visibility_level": CapabilityState.UNKNOWN}


def test_tamper_signal_only_proves_presence():
    assert detect_tamper_signal(["confirmed", "signal"]) is CapabilityState.SUPPORTED
    assert detect_tamper_signal(["confirmed"]) is None  # absence of signals proves nothing


def test_status_detection():
    assert detect_from_status(200) is CapabilityState.SUPPORTED
    assert detect_from_status(404) is CapabilityState.UNSUPPORTED
    assert detect_from_status(500) is CapabilityState.UNKNOWN
