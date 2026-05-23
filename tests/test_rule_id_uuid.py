"""B.1 驗證：gen_rule_id() 回傳 32-char hex UUID4。"""
import re
import time

from src.rule_id import gen_rule_id


def test_gen_rule_id_returns_hex_string():
    rid = gen_rule_id()
    assert isinstance(rid, str)
    assert re.fullmatch(r"[0-9a-f]{32}", rid), f"unexpected format: {rid}"


def test_gen_rule_id_unique():
    ids = {gen_rule_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_gen_rule_id_no_clock_dependence():
    """同一毫秒內呼叫多次仍唯一。"""
    t0 = time.monotonic()
    ids = []
    while time.monotonic() - t0 < 0.01:
        ids.append(gen_rule_id())
    assert len(set(ids)) == len(ids)
