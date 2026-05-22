from pathlib import Path


def test_main_does_not_shell_exec_clear():
    content = (Path(__file__).resolve().parent.parent / "src" / "main.py").read_text()
    bad_patterns = [
        'os.system("clear")',
        "os.system('clear')",
    ]
    for pat in bad_patterns:
        assert pat not in content, f"Found forbidden shell exec pattern: {pat!r}"
    # Also ensure the cls/clear conditional form is gone
    assert '"cls"' not in content or 'os.system' not in content, \
        'os.system with cls/clear still present in main.py'
