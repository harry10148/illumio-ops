"""B.2 驗證：int(datetime.now().timestamp()) 模式不再存在於目標檔案。"""
from pathlib import Path

TARGETS = [
    "src/gui/routes/rules.py",
    "src/cli/menus/bandwidth.py",
    "src/cli/menus/system_health.py",
    "src/cli/menus/event.py",
    "src/cli/menus/traffic.py",
]

BAD_PATTERN = "int(datetime.datetime.now().timestamp())"


def test_no_timestamp_based_rule_id():
    """確保沒有 int(datetime.datetime.now().timestamp()) 殘留。"""
    for path in TARGETS:
        content = Path(path).read_text()
        assert BAD_PATTERN not in content, (
            f"{path} 仍含 timestamp-based rule_id"
        )
        # 應已改用 gen_rule_id()
        assert "gen_rule_id" in content, (
            f"{path} 缺少 gen_rule_id import/usage"
        )
