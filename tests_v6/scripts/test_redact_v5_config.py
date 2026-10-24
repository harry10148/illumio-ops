import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "v6" / "redact_v5_config.py"

SECRETS = [
    "k3yID-aaaa1111", "s3cretValueThatIsLong0123456789abcdef", "$argon2id$v=19$m=131072,t=4,p=4$abc$def",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "hec-TOKEN-998877",
    "smtpPassw0rd!", "linechanneltokenABCDEFGHIJKLMNOPQRSTUVWXYZ012345", "123456:AAbbCCddEEff-telegram",
    "https://hooks.example.com/services/T000/B000/XXXXSECRET", "pce.customer.local", "10.20.30.40",
    "172.16.15.106", "ops@customer.example", "7654321", "internal-host-01",
]

SAMPLE = {
    "api": {"url": "https://pce.customer.local:8443", "org_id": "7654321", "key": "k3yID-aaaa1111",
            "secret": "s3cretValueThatIsLong0123456789abcdef", "verify_ssl": True},
    "web_gui": {"username": "admin", "password": "$argon2id$v=19$m=131072,t=4,p=4$abc$def",
                "secret_key": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "allowed_ips": ["10.20.30.40", "172.16.15.0/24"], "port": 5001},
    "siem": {"destinations": [{"name": "graylog", "host": "internal-host-01", "port": 514,
                               "hec_token": "hec-TOKEN-998877"}]},
    "smtp": {"host": "10.20.30.40", "user": "ops@customer.example", "password": "smtpPassw0rd!"},
    "alerts": {"line_channel_access_token": "linechanneltokenABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
               "telegram_bot_token": "123456:AAbbCCddEEff-telegram",
               "webhook_url": "https://hooks.example.com/services/T000/B000/XXXXSECRET",
               "recipients": ["ops@customer.example"]},
    "rules": [{"name": "r1", "threshold_count": 5, "enabled": True, "desc": "from 172.16.15.106"}],
    "settings": {"language": "zh_TW", "timezone": "Asia/Taipei"},
}


def _keys(node, prefix=""):
    if isinstance(node, dict):
        out = set()
        for k, v in node.items():
            out |= {f"{prefix}{k}"} | _keys(v, f"{prefix}{k}.")
        return out
    if isinstance(node, list):
        return set().union(*(_keys(v, f"{prefix}[].") for v in node)) if node else set()
    return set()


def _run(tmp_path):
    src, dst = tmp_path / "in.json", tmp_path / "out.json"
    src.write_text(json.dumps(SAMPLE))
    r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(src), str(dst)], capture_output=True, text=True,
                       timeout=60, check=False)
    return r, dst


def test_secrets_hosts_ips_org_replaced(tmp_path):
    r, dst = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    text = dst.read_text()
    leaked = [s for s in SECRETS if s in text]
    assert leaked == []
    out = json.loads(text)
    assert _keys(out) == _keys(SAMPLE)
    assert out["rules"][0]["threshold_count"] == 5 and out["web_gui"]["port"] == 5001
    assert out["settings"] == SAMPLE["settings"]
    assert out["api"]["verify_ssl"] is True and out["api"]["url"].startswith("https://")
    assert out["web_gui"]["password"].startswith("$argon2")  # shape kept so the migrator sees a hash


def test_prints_nothing_to_stdout(tmp_path):
    r, _ = _run(tmp_path)
    assert r.stdout == ""
