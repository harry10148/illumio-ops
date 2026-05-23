"""統一的 rule_id 產生器，脫離時鐘相依。"""
import uuid


def gen_rule_id() -> str:
    """Return a 32-char hex UUID4, independent of the system clock."""
    return uuid.uuid4().hex
