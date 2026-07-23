"""data_integrity 儲存：截斷事件落地 logs/data_integrity.json 供面板消費。"""
from __future__ import annotations

import pytest

from src import data_integrity


@pytest.fixture()
def di_file(tmp_path, monkeypatch):
    path = str(tmp_path / "data_integrity.json")
    monkeypatch.setattr(data_integrity, "_data_integrity_file", lambda: path)
    return path


def test_record_and_load_roundtrip(di_file):
    data_integrity.record_truncation("/orgs/1/labels", 500, 1200)
    data = data_integrity.load_data_integrity()
    entry = data["/orgs/1/labels"]
    assert entry["got"] == 500
    assert entry["total"] == 1200
    assert entry["last_seen"].endswith("Z")


def test_record_overwrites_same_path(di_file):
    data_integrity.record_truncation("/orgs/1/labels", 500, 1200)
    data_integrity.record_truncation("/orgs/1/labels", 500, 1300)
    data = data_integrity.load_data_integrity()
    assert data["/orgs/1/labels"]["total"] == 1300
    assert len(data) == 1


def test_clear_truncation_removes_entry(di_file):
    data_integrity.record_truncation("/orgs/1/labels", 500, 1200)
    data_integrity.clear_truncation("/orgs/1/labels")
    assert data_integrity.load_data_integrity() == {}
    data_integrity.clear_truncation("/orgs/1/labels")  # idempotent


def test_record_failure_is_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(data_integrity, "_data_integrity_file",
                        lambda: str(tmp_path / "no" * 300 / "x.json"))
    data_integrity.record_truncation("/orgs/1/labels", 500, 1200)  # must not raise
