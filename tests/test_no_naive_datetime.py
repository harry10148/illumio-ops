"""C.1 驗證：allowlist 外的 src/ 無 naive datetime.now() 使用。"""
import subprocess
import sys
from pathlib import Path


def test_no_naive_datetime_in_src():
    """執行 lint script，確認 allowlist 外無 naive datetime.now()。"""
    script = Path(__file__).parent.parent / "scripts" / "check_no_naive_datetime.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"naive datetime.now() lint failed:\n{result.stderr}"
    )
