"""parse_port_token：port token（單一/範圍/proto 別名）解析的行為契約。"""
import pytest

from src.port_token import parse_port_token


@pytest.mark.parametrize("text,expected", [
    ("80", {"port": 80}),
    ("443/tcp", {"port": 443, "proto": 6}),
    ("53/UDP", {"port": 53, "proto": 17}),
    ("53/17", {"port": 53, "proto": 17}),
    ("1000-2000", {"port": 1000, "to_port": 2000}),
    ("1000-2000/tcp", {"port": 1000, "to_port": 2000, "proto": 6}),
    ("2000-1000/tcp", {"port": 1000, "to_port": 2000, "proto": 6}),  # 顛倒自動校正（沿用舊行為）
    ("8080-8080", {"port": 8080}),  # 退化範圍收斂成單一 port
])
def test_valid_tokens(text, expected):
    assert parse_port_token(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "0", "65536", "80/xyz", "80-", "-80", "1-70000", "80//tcp"])
def test_invalid_tokens(text):
    assert parse_port_token(text) is None


def test_tuple_forms_preserved():
    # 舊 _parse_port_range_entry 的 list/tuple 形式必須保留
    assert parse_port_token((80, 90)) == {"port": 80, "to_port": 90}
    assert parse_port_token((80, 90, 6)) == {"port": 80, "to_port": 90, "proto": 6}
    assert parse_port_token((80, 90, "udp")) == {"port": 80, "to_port": 90, "proto": 17}
    assert parse_port_token((1, 2, 3, 4)) is None


def test_colon_range_form_preserved():
    # 舊語法 "80-90:6"（: 分隔 proto，僅限含 - 的範圍）保留
    assert parse_port_token("80-90:6") == {"port": 80, "to_port": 90, "proto": 6}


def test_default_proto():
    assert parse_port_token("80-90", default_proto=6) == {"port": 80, "to_port": 90, "proto": 6}


def test_labels_delegation():
    from src.api.labels import LabelResolver
    assert LabelResolver._parse_port_range_entry("443/tcp") == {"port": 443, "proto": 6}
    assert LabelResolver._parse_port_range_entry("80-90", default_proto=17) == {"port": 80, "to_port": 90, "proto": 17}
