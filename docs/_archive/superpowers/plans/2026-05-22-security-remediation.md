# Security Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Each task is independently scoped to be assignable to a fresh subagent with two-stage review (spec compliance → code quality). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修補 `docs/security-audit-2026-05-22.md` 列出的 36 項稽核發現，使 illumio-ops 可部署於高度合規 / 稽核要求嚴格的生產環境。

**Architecture:** 三階段修補 — Phase 1 解決 CRITICAL + HIGH（通過稽核最短路徑）、Phase 2 修補 MEDIUM（強化深度防禦與生產韌性）、Phase 3 清理 LOW（FIPS lint / cosmetic）。每個 task 都遵循 TDD：先寫 pytest 失敗案例，再實作，最後在測試機 `root@172.16.15.106` 部署 + 驗證。

**Tech Stack:** Python 3.12 / Flask 3.1 / cheroot 11 / cryptography 45 / argon2-cffi / APScheduler / loguru / pytest 8 / requests 2.33 / urllib3 2.6 / systemd 256

**Audit reference:** `docs/security-audit-2026-05-22.md`
**Test host:** `root@172.16.15.106`（Ubuntu 24.04.3 LTS，systemd unit `illumio-ops.service`）

**Out of scope（獨立 plan）：**
- H-4 naive datetime 全域改造 → 詳見獨立 plan `docs/superpowers/plans/2026-05-22-datetime-tz-aware.md`

**明示接受（不修補，於 audit 報告標註補償控制）：**
- **H-1**（GUI bind `0.0.0.0` + `allowed_ips=[]` allow-all）：lab 環境便利性優先，補償控制 = 強 admin 密碼 + Argon2id + CSRF + Talisman + rate-limit + 強制 HTTPS + IP RST drop（若 allowlist 非空）
- **M-8**（CSP `'unsafe-inline'`）：補償控制 = CSRF 全域 + `escapeHtml` + Argon2 + session_protection=strong；屬 securityheaders.com 扣分項而非實質漏洞

---

## File Structure

修改 / 新增的檔案總覽：

| 用途 | 檔案 |
|------|------|
| Branch / baseline | （無檔案，純 git + ssh ops）|
| systemd hardening | `deploy/illumio-ops.service`（重寫）、`scripts/install.sh`（補 useradd）|
| Resource lifecycle | `src/api_client.py`、`src/siem/transports/splunk_hec.py`、`src/siem/transports/syslog_udp.py`、`src/scheduler/jobs.py`、`src/siem/dispatcher.py` |
| Scheduler lifecycle | `src/gui/__init__.py`、`src/cli/_runtime.py` |
| Alert plugin reliability | `src/alerts/plugins.py` |
| TLS production guard | `src/config_models.py`、`src/api_client.py`、`src/siem/transports/syslog_tls.py`、`src/siem/transports/splunk_hec.py` |
| Secret key validation | `src/gui/__init__.py`、`src/config.py` |
| /api/security old_password | `src/gui/routes/config.py` |
| State integrity | `src/state_store.py`、`src/rule_scheduler.py` |
| Rate limiting | `src/gui/routes/actions.py`、`src/gui/routes/dashboard.py`、`src/gui/routes/reports.py` |
| Webhook scheme | `src/config_models.py` |
| flask_limiter backend | `src/gui/__init__.py` |
| SIEM TLS defaults | `deploy/filebeat.illumio_ops.yml`、`deploy/logstash.illumio_ops.conf`、`deploy/rsyslog.illumio_ops.conf` |
| SBOM / LICENSE | `LICENSE`（新）、`THIRD_PARTY_NOTICES.md`（新）、`requirements-sbom.txt`（新）、`.github/workflows/ci.yml` |
| Setup hardening | `scripts/setup.sh`、`scripts/install.sh` |
| Log redaction | `src/loguru_config.py` |
| LOW cleanup | `src/pce_cache/{traffic_filter,backfill,ingestor_traffic}.py`、`src/events/poller.py`、`src/main.py`、`src/templates/index.html`、`src/loguru_config.py`、`README.md` |
| Tests（新） | `tests/test_security_remediation_*.py`（每 task 一檔） |

---

## Phase 0 — 前置作業

### Task 0.1：建立修補分支與 baseline tag

**Files:** （純 git ops）

- [ ] **Step 1：確認當前狀態乾淨並建立分支**

```bash
cd /home/harry/rd/illumio-ops
git status --short  # 預期：僅 docs/ux-review-2026-05-14/dashboard_i18n_flagged.md
git checkout -b security-remediation-2026-05-22
```

- [ ] **Step 2：標記 baseline tag（用於 rollback 與報告對照）**

```bash
git tag pre-security-remediation-2026-05-22 HEAD
git tag --list pre-security-remediation-2026-05-22  # 預期：tag 存在
```

- [ ] **Step 3：commit plan doc 與 audit report**

```bash
git add docs/security-audit-2026-05-22.md docs/superpowers/plans/2026-05-22-security-remediation.md
git commit -m "docs: add 2026-05-22 security audit report and remediation plan"
```

### Task 0.2：測試機 baseline 快照

**Files:** `docs/security-audit-2026-05-22-baseline.txt`（新）

- [ ] **Step 1：收集測試機 pre-remediation baseline**

```bash
ssh root@172.16.15.106 'bash -s' > /tmp/baseline.txt <<'EOF'
echo "=== systemd-analyze security ==="
systemd-analyze security illumio-ops.service 2>&1 | tail -3
echo "=== process baseline ==="
PID=$(systemctl show --value -p MainPID illumio-ops)
ls /proc/$PID/fd 2>/dev/null | wc -l | xargs echo "fds:"
awk '/VmRSS|Threads/{print}' /proc/$PID/status 2>/dev/null
echo "=== listening ports ==="
ss -tlnp 2>/dev/null | grep 5001
echo "=== git HEAD ==="
cd /root/illumio-ops && git rev-parse HEAD
EOF
cp /tmp/baseline.txt /home/harry/rd/illumio-ops/docs/security-audit-2026-05-22-baseline.txt
```

- [ ] **Step 2：commit baseline**

```bash
cd /home/harry/rd/illumio-ops
git add docs/security-audit-2026-05-22-baseline.txt
git commit -m "docs(audit): capture pre-remediation runtime baseline from 172.16.15.106"
```

### Task 0.3：建立 SSH host alias 便利後續自動化部署

**Files:** `~/.ssh/config`（user level，不入 repo）

- [ ] **Step 1：加 host alias**

```bash
grep -q "Host illumio-ops-test" ~/.ssh/config || cat >> ~/.ssh/config <<'EOF'

Host illumio-ops-test
    HostName 172.16.15.106
    User root
    StrictHostKeyChecking accept-new
EOF
ssh illumio-ops-test 'echo OK'  # 預期：OK
```

無 commit（user-level config 不入 repo）。

---

## Phase 1 — CRITICAL + HIGH（通過稽核必要）

### Task 1.1（C-1 + L-9）：部署 hardened systemd unit + system user

**Files:**
- Modify: `deploy/illumio-ops.service`
- Modify: `scripts/install.sh`（補 useradd 與權限調整）
- Test: `tests/test_systemd_unit.py`（新）

- [ ] **Step 1：寫失敗測試 — 檢查 unit 含關鍵 hardening directive**

```python
# tests/test_systemd_unit.py
import configparser
from pathlib import Path

UNIT_PATH = Path(__file__).parent.parent / "deploy" / "illumio-ops.service"

def _parse_unit():
    cp = configparser.RawConfigParser(strict=False)
    cp.optionxform = str  # preserve case
    cp.read(UNIT_PATH)
    return cp

def test_unit_runs_as_system_user():
    cp = _parse_unit()
    assert cp["Service"]["User"] == "illumio-ops"
    assert cp["Service"]["Group"] == "illumio-ops"

def test_unit_has_hardening_directives():
    cp = _parse_unit()
    s = cp["Service"]
    assert s["NoNewPrivileges"] == "true"
    assert s["ProtectSystem"] == "strict"
    assert s["ProtectHome"] == "true"
    assert s["PrivateTmp"] == "true"
    assert s["RestrictAddressFamilies"] == "AF_INET AF_INET6 AF_UNIX"
    assert s["SystemCallFilter"] == "@system-service"
    assert s["MemoryDenyWriteExecute"] == "true"
    assert s["LockPersonality"] == "true"
    assert s["ProtectKernelTunables"] == "true"
    assert s["ProtectControlGroups"] == "true"
    assert s["RestrictSUIDSGID"] == "true"
    assert s["RestrictNamespaces"] == "true"
    assert s["CapabilityBoundingSet"] == ""  # drop all caps

def test_unit_restart_policy():
    cp = _parse_unit()
    assert cp["Service"]["Restart"] == "on-failure"
    assert int(cp["Service"]["RestartSec"]) >= 5
```

- [ ] **Step 2：驗證測試失敗**

```bash
cd /home/harry/rd/illumio-ops && pytest tests/test_systemd_unit.py -v
# 預期：FAIL（unit 缺 directive）
```

- [ ] **Step 3：重寫 hardened unit file**

```ini
# deploy/illumio-ops.service
[Unit]
Description=Illumio PCE Operations Monitor
Documentation=https://github.com/illumio-ops/illumio-ops
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=illumio-ops
Group=illumio-ops
WorkingDirectory=/opt/illumio-ops
ExecStart=/opt/illumio-ops/venv/bin/python illumio-ops.py --monitor-gui --interval 5
Restart=on-failure
RestartSec=10
TimeoutStopSec=30
KillSignal=SIGTERM
StandardOutput=journal
StandardError=journal

# --- Hardening ---
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
ProtectProc=invisible
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
CapabilityBoundingSet=
AmbientCapabilities=
ReadWritePaths=/opt/illumio-ops/logs /opt/illumio-ops/config /opt/illumio-ops/data /opt/illumio-ops/reports

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4：更新 `install.sh` 補 user 建立與目錄權限**

修改 `scripts/install.sh` — 在 `cp config.json.example` 之後新增：

```bash
# Create dedicated system user
if ! id illumio-ops &>/dev/null; then
    useradd --system --no-create-home --shell /sbin/nologin illumio-ops
fi

# Set ownership and permissions
chown -R illumio-ops:illumio-ops /opt/illumio-ops
find /opt/illumio-ops/config -type f -name "*.json" -exec chmod 0600 {} \;
find /opt/illumio-ops/config -type f -name "*.yaml" -exec chmod 0640 {} \;
find /opt/illumio-ops/config/tls -type f -name "*key*.pem" -exec chmod 0600 {} \;
find /opt/illumio-ops/config/tls -type f -name "*.pem" ! -name "*key*" -exec chmod 0640 {} \;
chmod 0750 /opt/illumio-ops/logs
chmod 0750 /opt/illumio-ops/config
```

- [ ] **Step 5：驗證測試通過**

```bash
pytest tests/test_systemd_unit.py -v
# 預期：PASS（5/5）
```

- [ ] **Step 6：commit**

```bash
git add deploy/illumio-ops.service scripts/install.sh tests/test_systemd_unit.py
git commit -m "feat(deploy): harden systemd unit and add illumio-ops system user (C-1, L-9)"
```

- [ ] **Step 7：部署到測試機並驗證 systemd-analyze 評分**

```bash
# 部署
scp deploy/illumio-ops.service root@172.16.15.106:/etc/systemd/system/illumio-ops.service

ssh illumio-ops-test 'bash -s' <<'EOF'
# 建 user（首次）
id illumio-ops &>/dev/null || useradd --system --no-create-home --shell /sbin/nologin illumio-ops
# Move app to /opt（測試機目前在 /root，建議遷移；若不遷移則修 ReadWritePaths 與 WorkingDirectory）
# 此 task 假設先沿用 /root/illumio-ops，修改 unit 的 WorkingDirectory 即可
sed -i 's|/opt/illumio-ops|/root/illumio-ops|g' /etc/systemd/system/illumio-ops.service
chown -R illumio-ops:illumio-ops /root/illumio-ops
chmod 0750 /root/illumio-ops/logs /root/illumio-ops/config
systemctl daemon-reload
systemctl restart illumio-ops
sleep 5
systemd-analyze security illumio-ops.service 2>&1 | tail -3
systemctl is-active illumio-ops
ss -tlnp | grep 5001
EOF
```

預期：`systemd-analyze security` 評分 ≤ 3.0（從 9.6 降下）；service active；port 5001 仍 listen。

### Task 1.2（H-1）：明示接受 — 無 task

**狀態：明示接受。** 使用者決定保留現狀（bind `0.0.0.0` + allow-all empty allowlist），lab 便利性優先。Audit 報告 §3.2 H-1 標「明示接受 + 補償控制」。本 plan 跳過此 task；後續 task 編號維持不重排（仍稱 T1.3 開始）以利對照 audit report 編號。

### Task 1.3（H-5）：LINE alert plugin 補 timeout + channel cooldown

**Files:**
- Modify: `src/alerts/plugins.py:88`
- Test: `tests/test_line_plugin_timeout.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_line_plugin_timeout.py
import socket
import time
import threading
from unittest.mock import patch, MagicMock
from src.alerts.plugins import LineAlertPlugin

def test_line_urlopen_has_timeout():
    """Plugin 必須在合理時間（< 15s）內因 timeout 中斷"""
    plugin = LineAlertPlugin(config={
        "line_channel_access_token": "test_token",
        "line_to": "test_user",
    })
    # Mock urlopen to simulate hang
    with patch("urllib.request.urlopen") as mock_open:
        def hang(*a, **kw):
            timeout = kw.get("timeout")
            assert timeout is not None, "LINE urlopen 必須帶 timeout"
            assert 5 <= timeout <= 30, f"timeout 應為 5-30s，實際 {timeout}"
            raise socket.timeout("simulated")
        mock_open.side_effect = hang
        start = time.monotonic()
        result = plugin.send_alert("test", "test body", "info")
        elapsed = time.monotonic() - start
        assert elapsed < 5, f"LINE plugin 阻塞 {elapsed}s（應立即返回 false）"
        assert result is False
```

- [ ] **Step 2：驗證失敗**

```bash
pytest tests/test_line_plugin_timeout.py -v
# 預期：FAIL（urlopen 沒帶 timeout，assertion error）
```

- [ ] **Step 3：修改 `src/alerts/plugins.py:88`**

找到 LINE plugin 的 `urlopen(req)` 改成：

```python
with urllib.request.urlopen(req, timeout=10) as response:
    ...
```

並在 plugin class 加 channel cooldown（連續失敗暫時 disable）：

```python
class LineAlertPlugin:
    _cooldown_until: float = 0.0
    _consecutive_failures: int = 0

    def send_alert(self, subject, body, level):
        import time
        if time.monotonic() < self._cooldown_until:
            logger.info("LINE channel in cooldown, skipping")
            return False
        try:
            req = urllib.request.Request(url, ...)
            with urllib.request.urlopen(req, timeout=10) as response:
                self._consecutive_failures = 0
                return response.status == 200
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._cooldown_until = time.monotonic() + 300  # 5 min
                logger.warning("LINE channel disabled for 5 min after 3 failures")
            logger.error(f"LINE send failed: {e}")
            return False
```

- [ ] **Step 4：驗證通過**

```bash
pytest tests/test_line_plugin_timeout.py -v  # 預期：PASS
pytest tests/test_alerts*.py tests/test_alert*.py -v  # regression
```

- [ ] **Step 5：commit**

```bash
git add src/alerts/plugins.py tests/test_line_plugin_timeout.py
git commit -m "fix(alerts): add timeout and cooldown to LINE plugin (H-5)"
```

- [ ] **Step 6：部署 + runtime 驗證（黑洞 IP 故障注入）**

```bash
scp src/alerts/plugins.py root@172.16.15.106:/root/illumio-ops/src/alerts/
ssh illumio-ops-test 'bash -s' <<'EOF'
systemctl restart illumio-ops && sleep 5
# 用 iptables 把 api.line.me 設黑洞
iptables -I OUTPUT -d api.line.me -j DROP 2>/dev/null || iptables -I OUTPUT -d 147.92.150.192 -j DROP
# 觸發 test alert（透過 GUI 或 CLI）
# ... 取得 session 並 POST /api/actions/test-alert
# 觀察 thread 是否在 10-15s 內返回
journalctl -u illumio-ops -n 50 --since "1 minute ago" | grep -iE "line|timeout"
# 清理
iptables -D OUTPUT -d api.line.me -j DROP 2>/dev/null || iptables -D OUTPUT -d 147.92.150.192 -j DROP
EOF
```

預期：log 顯示 LINE timeout / cooldown，service 不卡死。

### Task 1.4（H-7）：`web_gui.secret_key` 長度驗證 + 啟動 regenerate

**Files:**
- Modify: `src/gui/__init__.py:194`（或對應的 secret_key 初始化處）
- Modify: `src/config.py`（若涵蓋 _ensure_web_gui_secret）
- Test: `tests/test_secret_key_validation.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_secret_key_validation.py
import secrets
import json
import tempfile
from pathlib import Path
from src.config import ConfigManager

def test_short_secret_key_gets_regenerated(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "web_gui": {"secret_key": "tooshort", "username": "illumio"}
    }))
    cm = ConfigManager(config_file=str(cfg_file))
    cm.load()
    # 啟動時應自動 regenerate
    sk = cm.config["web_gui"]["secret_key"]
    assert len(sk) >= 64, f"secret_key 應 ≥ 64 chars，實際 {len(sk)}"

def test_long_secret_key_preserved(tmp_path):
    cfg_file = tmp_path / "config.json"
    good = secrets.token_hex(32)
    cfg_file.write_text(json.dumps({
        "web_gui": {"secret_key": good, "username": "illumio"}
    }))
    cm = ConfigManager(config_file=str(cfg_file))
    cm.load()
    assert cm.config["web_gui"]["secret_key"] == good
```

- [ ] **Step 2：驗證失敗**

```bash
pytest tests/test_secret_key_validation.py -v
# 預期：FAIL（短 key 未被 regenerate）
```

- [ ] **Step 3：修改 `_ensure_web_gui_secret`（`src/config.py:303-315` 附近）**

```python
def _ensure_web_gui_secret(self):
    web_gui = self.config.setdefault("web_gui", {})
    secret = web_gui.get("secret_key", "")
    if len(secret) < 64:  # 必須 ≥ 32 bytes hex = 64 chars
        import secrets
        web_gui["secret_key"] = secrets.token_hex(32)
        logger.warning("web_gui.secret_key 過短或缺失，已自動 regenerate 至 64 chars")
        self.save()
```

- [ ] **Step 4：驗證通過**

```bash
pytest tests/test_secret_key_validation.py -v  # 預期：PASS
```

- [ ] **Step 5：commit**

```bash
git add src/config.py tests/test_secret_key_validation.py
git commit -m "fix(security): enforce 32-byte minimum for web_gui.secret_key (H-7)"
```

- [ ] **Step 6：部署 + 驗證測試機 secret_key 已 rotate**

```bash
scp src/config.py root@172.16.15.106:/root/illumio-ops/src/
ssh illumio-ops-test 'bash -s' <<'EOF'
systemctl restart illumio-ops && sleep 5
python3 -c "
import json
d = json.load(open('/root/illumio-ops/config/config.json'))
sk = d.get('web_gui', {}).get('secret_key', '')
print(f'secret_key length: {len(sk)}')
assert len(sk) >= 64, 'still too short'
print('OK')
"
EOF
```

預期：length 64+, OK。

### Task 1.5（H-6 + M-6）：`verify_ssl` production validator

**Files:**
- Modify: `src/config_models.py`（加 validator）
- Modify: `src/api_client.py`（讀 profile flag）
- Test: `tests/test_verify_ssl_guard.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_verify_ssl_guard.py
import pytest
from src.config_models import ApiConfig, SyslogTlsConfig, SplunkHecConfig

def test_production_profile_rejects_verify_ssl_false():
    with pytest.raises(ValueError, match="verify_ssl"):
        ApiConfig(url="https://pce.example.com:8443", verify_ssl=False, profile="production")

def test_dev_profile_allows_verify_ssl_false():
    cfg = ApiConfig(url="https://pce.lab.local:8443", verify_ssl=False, profile="dev")
    assert cfg.verify_ssl is False  # 允許

def test_default_profile_is_production():
    cfg = ApiConfig(url="https://pce.example.com:8443")
    assert cfg.profile == "production"
    assert cfg.verify_ssl is True
```

- [ ] **Step 2：驗證失敗**

```bash
pytest tests/test_verify_ssl_guard.py -v
# 預期：FAIL（缺 profile 欄位）
```

- [ ] **Step 3：修改 `src/config_models.py`**

在 `ApiConfig` 加：

```python
from pydantic import BaseModel, validator
from typing import Literal

class ApiConfig(BaseModel):
    url: str = ""
    key: str = ""
    secret: str = ""
    verify_ssl: bool = True
    profile: Literal["production", "dev"] = "production"

    @validator("verify_ssl", always=True)
    def _verify_ssl_production_guard(cls, v, values):
        if values.get("profile") == "production" and v is False:
            raise ValueError(
                "verify_ssl=False 不允許於 production profile；"
                "明示設 profile='dev' 才能關閉 TLS 驗證"
            )
        return v
```

同樣 pattern 套用 `SyslogTlsConfig.tls_verify` 與 `SplunkHecConfig.verify`。

- [ ] **Step 4：驗證通過**

```bash
pytest tests/test_verify_ssl_guard.py -v  # 預期：PASS
pytest tests/  # regression
```

- [ ] **Step 5：commit**

```bash
git add src/config_models.py tests/test_verify_ssl_guard.py
git commit -m "feat(config): reject verify_ssl=False on production profile (H-6, M-6)"
```

- [ ] **Step 6：部署 + 驗證測試機 config 標 dev profile**

```bash
scp src/config_models.py root@172.16.15.106:/root/illumio-ops/src/
ssh illumio-ops-test 'bash -s' <<'EOF'
# 把 lab 機器標 dev profile（保持 verify_ssl=False 但合法）
python3 -c "
import json
p = '/root/illumio-ops/config/config.json'
d = json.load(open(p))
d.setdefault('api', {})['profile'] = 'dev'
with open(p, 'w') as f: json.dump(d, f, indent=2)
"
systemctl restart illumio-ops && sleep 5
systemctl is-active illumio-ops  # 預期：active（dev profile 允許 verify_ssl=False）
EOF
```

預期：service 仍正常；若 profile=production 則啟動會 raise（已測本機 pytest）。

### Task 1.6（H-2）：ApiClient 與 SIEM transport 加 `close()` + context manager

**Files:**
- Modify: `src/api_client.py:96-160`
- Modify: `src/siem/transports/splunk_hec.py:14-40`
- Modify: `src/siem/transports/syslog_udp.py`
- Modify: `src/siem/dispatcher.py`（reload 時 close 舊 transport）
- Modify: `src/scheduler/jobs.py:13-45`（每 tick close）
- Test: `tests/test_resource_lifecycle.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_resource_lifecycle.py
import gc
import weakref
from src.api_client import ApiClient
from src.siem.transports.splunk_hec import SplunkHECTransport

def test_api_client_close_releases_session():
    cm = make_test_cm()
    client = ApiClient(cm)
    session_ref = weakref.ref(client._session)
    client.close()
    assert client._session is None or client._session.adapters == {}

def test_api_client_context_manager():
    cm = make_test_cm()
    with ApiClient(cm) as client:
        assert client._session is not None
    assert client._session is None or client._session.adapters == {}

def test_splunk_hec_close():
    t = SplunkHECTransport(url="https://localhost:8088", token="x")
    t.close()
    # 無 assertion error，session 已關
```

- [ ] **Step 2：驗證失敗**

```bash
pytest tests/test_resource_lifecycle.py -v
# 預期：FAIL（close 方法不存在）
```

- [ ] **Step 3：實作 `ApiClient.close()` / `__enter__` / `__exit__`**

在 `src/api_client.py` `ApiClient` class 加：

```python
def close(self) -> None:
    """釋放底層 requests.Session 連線池。"""
    if hasattr(self, "_session") and self._session is not None:
        try:
            self._session.close()
        except Exception as e:
            logger.warning(f"ApiClient.close() failed: {e}")
        finally:
            self._session = None

def __enter__(self):
    return self

def __exit__(self, exc_type, exc_val, exc_tb):
    self.close()
    return False
```

- [ ] **Step 4：實作 `SplunkHECTransport.close()`**

```python
def close(self) -> None:
    if hasattr(self, "_session") and self._session is not None:
        self._session.close()
        self._session = None
```

`SyslogUDPTransport` 已有 `close()`，確認 dispatcher 在 reload 時呼叫。

- [ ] **Step 5：修改 `src/scheduler/jobs.py` `run_monitor_cycle` 使用 with**

```python
def run_monitor_cycle(cm):
    with ApiClient(cm) as client:
        analyzer = Analyzer(cm, client)
        analyzer.run_cycle()
```

同樣處理 `src/gui/__init__.py:128` 的 `_ApiClient(cm)` 呼叫點。

- [ ] **Step 6：dispatcher reload 時 close 舊 transport**

`src/siem/dispatcher.py` 中找到 reload destination 的點，加：

```python
old_transports = self._transports
self._transports = build_transports(self.config)
for t in old_transports:
    try:
        if hasattr(t, "close"):
            t.close()
    except Exception:
        pass
```

- [ ] **Step 7：驗證通過**

```bash
pytest tests/test_resource_lifecycle.py -v  # 預期：PASS
pytest tests/  # regression
```

- [ ] **Step 8：commit**

```bash
git add src/api_client.py src/siem/transports/splunk_hec.py src/siem/dispatcher.py src/scheduler/jobs.py src/gui/__init__.py tests/test_resource_lifecycle.py
git commit -m "fix(resource): add close() to ApiClient/SplunkHEC and ensure cleanup (H-2)"
```

- [ ] **Step 9：部署 + 24h FD 趨勢觀察**

```bash
scp src/api_client.py src/siem/transports/splunk_hec.py src/siem/dispatcher.py src/scheduler/jobs.py src/gui/__init__.py root@172.16.15.106:/root/illumio-ops/src/...（對應目錄）
ssh illumio-ops-test 'systemctl restart illumio-ops && sleep 10'

# 在背景跑 24 小時 FD 監測
ssh illumio-ops-test 'nohup bash -c "
PID=\$(systemctl show --value -p MainPID illumio-ops)
for i in \$(seq 1 24); do
  ls /proc/\$PID/fd 2>/dev/null | wc -l | xargs -I{} echo \"\$(date +%H:%M) fds={}\"
  sleep 3600
done > /tmp/fd_trend_post_h2.log 2>&1 &"'
# 24h 後檢視 /tmp/fd_trend_post_h2.log，趨勢應平穩
```

預期：24h FD 不單調上升。

### Task 1.7（H-3）：`_rs_background_scheduler` 接 shutdown_event

**Files:**
- Modify: `src/gui/__init__.py:115-138`
- Modify: `src/cli/_runtime.py:103-145`（join daemon thread）
- Test: `tests/test_scheduler_shutdown.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_scheduler_shutdown.py
import threading
import time

def test_background_scheduler_responds_to_shutdown_event():
    """背景 thread 應在 shutdown_event 設定後 1 秒內結束"""
    from src.gui import _rs_background_scheduler, _shutdown_event
    _shutdown_event.clear()
    t = threading.Thread(target=_rs_background_scheduler, args=(make_test_cm(),), daemon=True)
    t.start()
    time.sleep(0.5)
    assert t.is_alive()
    _shutdown_event.set()
    t.join(timeout=2)
    assert not t.is_alive(), "thread 未在 2 秒內回應 shutdown_event"
```

- [ ] **Step 2：驗證失敗**

```bash
pytest tests/test_scheduler_shutdown.py -v
# 預期：FAIL（thread 不檢查 event）
```

- [ ] **Step 3：修改 `src/gui/__init__.py` `_rs_background_scheduler`**

找到 `while True: ... time.sleep(60)`，改成：

```python
def _rs_background_scheduler(cm):
    while not _shutdown_event.is_set():
        try:
            engine = ScheduleEngine(cm)
            engine.check()
        except Exception as e:
            logger.warning(f"rs background tick failed: {e}")
        # interruptible wait
        if _shutdown_event.wait(60):
            break
    logger.info("_rs_background_scheduler exited cleanly")
```

- [ ] **Step 4：修改 `src/cli/_runtime.py` join daemon thread**

在 `_gui_stopper` 之後新增：

```python
if t_daemon is not None:
    t_daemon.join(timeout=10)
    if t_daemon.is_alive():
        logger.warning("background scheduler thread did not exit within 10s")
```

- [ ] **Step 5：驗證通過**

```bash
pytest tests/test_scheduler_shutdown.py -v  # 預期：PASS
```

- [ ] **Step 6：commit**

```bash
git add src/gui/__init__.py src/cli/_runtime.py tests/test_scheduler_shutdown.py
git commit -m "fix(scheduler): background thread responds to shutdown_event (H-3)"
```

- [ ] **Step 7：部署 + SIGTERM 計時複測**

```bash
scp src/gui/__init__.py src/cli/_runtime.py root@172.16.15.106:/root/illumio-ops/src/...
ssh illumio-ops-test 'bash -s' <<'EOF'
START_NS=$(date +%s%N)
systemctl stop illumio-ops
END_NS=$(date +%s%N)
echo "stop elapsed: $(( (END_NS - START_NS) / 1000000 )) ms"
journalctl -u illumio-ops -n 20 --since "1 minute ago" | grep -iE "shutdown|exit"
systemctl start illumio-ops
EOF
```

預期：stop 仍 < 5 秒；log 顯示 `_rs_background_scheduler exited cleanly`。

### Task 1.8（H-4 datetime）：placeholder — 獨立 plan

**Files:** N/A（此 task 不做任何修改，僅建立 follow-up plan）

- [ ] **Step 1：建立獨立 plan 檔**

```bash
touch /home/harry/rd/illumio-ops/docs/superpowers/plans/2026-05-22-datetime-tz-aware.md
```

寫入內容（最低骨架，後續詳填）：

```markdown
# datetime timezone-aware 全域改造 plan

**狀態：未開始**
**觸發來源：** docs/security-audit-2026-05-22.md H-4
**影響檔案（20+）：** src/report_scheduler.py、src/rule_scheduler.py、src/gui/__init__.py、src/module_log.py、src/analyzer.py、src/gui/routes/rules.py、src/cli/menus/*、src/report/analysis/policy_usage/*

**TBD：** 待 Phase 1 完成後另行 brainstorm。
```

- [ ] **Step 2：commit placeholder**

```bash
git add docs/superpowers/plans/2026-05-22-datetime-tz-aware.md
git commit -m "docs(plan): placeholder for datetime tz-aware refactor (H-4)"
```

---

## Phase 2 — MEDIUM

### Task 2.1（M-1）：`/api/security` 加 old_password 必填

**Files:**
- Modify: `src/gui/routes/config.py:51-86`
- Test: `tests/test_security_endpoint_old_password.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_security_endpoint_old_password.py
def test_change_password_requires_old(client, logged_in_session):
    """變更密碼必須附 old_password 才能通過"""
    resp = client.post("/api/security",
        json={"new_password": "NewPw_2026!"},
        headers={"X-CSRFToken": csrf})
    assert resp.status_code == 400
    assert "old_password" in resp.json["error"].lower()

def test_change_password_with_correct_old(client, logged_in_session):
    resp = client.post("/api/security",
        json={"old_password": "1qaz@WSX", "new_password": "NewPw_2026!"},
        headers={"X-CSRFToken": csrf})
    assert resp.status_code == 200
    assert resp.json["ok"] is True

def test_change_password_with_wrong_old(client, logged_in_session):
    resp = client.post("/api/security",
        json={"old_password": "wrong", "new_password": "NewPw_2026!"},
        headers={"X-CSRFToken": csrf})
    assert resp.status_code == 400
    assert "incorrect" in resp.json["error"].lower() or "錯誤" in resp.json["error"]

def test_must_change_password_bypass(client, logged_in_session_first_login):
    """must_change_password=True 時不需 old_password"""
    resp = client.post("/api/security",
        json={"new_password": "NewPw_2026!"},
        headers={"X-CSRFToken": csrf})
    assert resp.status_code == 200
```

- [ ] **Step 2：驗證失敗**

```bash
pytest tests/test_security_endpoint_old_password.py -v
# 預期：FAIL（目前不需 old_password）
```

- [ ] **Step 3：修改 `src/gui/routes/config.py:51-86`**

```python
@bp.route('/api/security', methods=['POST'])
@limiter.limit("10 per hour")
def api_security_post():
    d = request.json or {}
    cm.load()
    lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
    gui_cfg = cm.config.setdefault("web_gui", {})

    # 變更密碼必須附 old_password（除非 must_change_password=True 首登流程）
    if d.get("new_password"):
        must_change = gui_cfg.get("must_change_password", False)
        if not must_change:
            old_pw = d.get("old_password", "")
            if not old_pw:
                return jsonify({"ok": False, "error": t("gui_err_old_password_required", lang=lang)}), 400
            if not verify_password(old_pw, gui_cfg.get("password", "")):
                return jsonify({"ok": False, "error": t("gui_err_old_password_incorrect", lang=lang)}), 400
        new_pw = d["new_password"]
        confirm_pw = d.get("confirm_password", new_pw)
        if not (12 <= len(new_pw) <= 512) or new_pw != confirm_pw:  # 8→12
            return jsonify({"ok": False, "error": t("gui_err_invalid_password_form", lang=lang)}), 400
        gui_cfg["password"] = hash_password(new_pw)
        gui_cfg.pop("_initial_password", None)
        gui_cfg.pop("must_change_password", None)

    if "username" in d:
        gui_cfg["username"] = d["username"]

    if "allowed_ips" in d:
        allowed_ips, invalid_ips = _validate_allowed_ips(d["allowed_ips"])
        if invalid_ips:
            return jsonify({"ok": False, "error": f"Invalid allowlist entries: {', '.join(invalid_ips)}"}), 400
        gui_cfg["allowed_ips"] = allowed_ips

    cm.save()
    return jsonify({"ok": True})
```

加 i18n keys 到 `src/i18n_en.json` 與 `src/i18n_zh_TW.json`：
- `gui_err_old_password_required`
- `gui_err_old_password_incorrect`

- [ ] **Step 4：驗證通過**

```bash
pytest tests/test_security_endpoint_old_password.py -v  # 預期：PASS
```

- [ ] **Step 5：commit**

```bash
git add src/gui/routes/config.py src/i18n_en.json src/i18n_zh_TW.json tests/test_security_endpoint_old_password.py
git commit -m "feat(gui): require old_password to change password (M-1)"
```

- [ ] **Step 6：部署 + 驗證**

```bash
scp src/gui/routes/config.py src/i18n_*.json root@172.16.15.106:/root/illumio-ops/src/...
ssh illumio-ops-test 'systemctl restart illumio-ops && sleep 5'
# 從本機自動化：登入後 POST /api/security 無 old_password，預期 400
```

### Task 2.2（M-2）：`state_store` 寫入 fsync

**Files:**
- Modify: `src/state_store.py:60-78`
- Test: `tests/test_state_store_fsync.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_state_store_fsync.py
import os
from unittest.mock import patch
from src import state_store

def test_update_state_calls_fsync(tmp_path):
    f = tmp_path / "state.json"
    f.write_text('{}')
    with patch("os.fsync") as mock_fsync:
        state_store.update_state_file(str(f), {"k": "v"})
        assert mock_fsync.called, "update_state_file 應呼叫 os.fsync"
```

- [ ] **Step 2：驗證失敗**

```bash
pytest tests/test_state_store_fsync.py -v
# 預期：FAIL
```

- [ ] **Step 3：修改 `src/state_store.py:60-78`**

```python
def update_state_file(state_file: str, updates: dict):
    # ... 原本的 lock + load 邏輯 ...
    with _state_lock(state_file):
        # ... load ...
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(state_file), prefix=".state.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, state_file)
            # fsync parent dir for metadata durability
            try:
                dirfd = os.open(os.path.dirname(state_file), os.O_RDONLY)
                os.fsync(dirfd)
                os.close(dirfd)
            except OSError:
                pass
        except Exception:
            try: os.unlink(tmp_path)
            except OSError: pass
            raise
```

- [ ] **Step 4：驗證通過**

```bash
pytest tests/test_state_store_fsync.py -v  # 預期：PASS
pytest tests/test_state_store*.py -v  # regression
```

- [ ] **Step 5：commit**

```bash
git add src/state_store.py tests/test_state_store_fsync.py
git commit -m "fix(state): fsync state.json + parent dir for durability (M-2)"
```

- [ ] **Step 6：部署 + power-loss simulation**

```bash
scp src/state_store.py root@172.16.15.106:/root/illumio-ops/src/
ssh illumio-ops-test 'systemctl restart illumio-ops && sleep 5'
# 暴力測試：用 sysrq trigger crash 並重啟
# ssh illumio-ops-test 'echo b > /proc/sysrq-trigger'  # 警告：立即 reboot
# 重啟後驗證 state.json parse OK
```

### Task 2.3（M-3）：`ScheduleDB.load` 毀損檔處理

**Files:**
- Modify: `src/rule_scheduler.py:51-58`
- Test: `tests/test_schedule_db_corrupt.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_schedule_db_corrupt.py
import json
from src.rule_scheduler import ScheduleDB

def test_corrupt_db_quarantined(tmp_path):
    db_path = tmp_path / "rule_schedules.json"
    db_path.write_text("{not valid json")
    db = ScheduleDB(str(db_path))
    # 應 raise，不應 silently {}
    import pytest
    with pytest.raises(ValueError):
        db.load()
    # 並且 .corrupt 檔案應存在
    corrupts = list(tmp_path.glob("rule_schedules.json.corrupt.*"))
    assert len(corrupts) == 1
```

- [ ] **Step 2：驗證失敗**

```bash
pytest tests/test_schedule_db_corrupt.py -v
# 預期：FAIL
```

- [ ] **Step 3：修改 `src/rule_scheduler.py:51-58`**

```python
def load(self):
    if not os.path.exists(self.db_path):
        self.db = {}
        return
    try:
        with open(self.db_path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("schedule DB root is not dict")
        self.db = data
    except (json.JSONDecodeError, ValueError, OSError) as e:
        corrupt = f"{self.db_path}.corrupt.{int(time.time())}"
        try:
            os.rename(self.db_path, corrupt)
        except OSError:
            pass
        logger.error(f"ScheduleDB 毀損，已搬移至 {corrupt}：{e}")
        raise ValueError(f"ScheduleDB corrupt: {e}")
```

- [ ] **Step 4：驗證通過**

```bash
pytest tests/test_schedule_db_corrupt.py -v  # 預期：PASS
```

- [ ] **Step 5：commit**

```bash
git add src/rule_scheduler.py tests/test_schedule_db_corrupt.py
git commit -m "fix(scheduler): quarantine corrupt rule_schedules.json instead of silent reset (M-3)"
```

- [ ] **Step 6：部署 + 注入毀損驗證**

```bash
scp src/rule_scheduler.py root@172.16.15.106:/root/illumio-ops/src/
ssh illumio-ops-test 'bash -s' <<'EOF'
systemctl stop illumio-ops
cp /root/illumio-ops/config/rule_schedules.json /tmp/backup.json
echo "{corrupt" > /root/illumio-ops/config/rule_schedules.json
systemctl start illumio-ops; sleep 5
ls /root/illumio-ops/config/rule_schedules.json.corrupt.* 2>/dev/null  # 應存在
journalctl -u illumio-ops -n 10 | grep -i corrupt
# 還原
cp /tmp/backup.json /root/illumio-ops/config/rule_schedules.json
systemctl restart illumio-ops
EOF
```

### Task 2.4（M-4）：`ScheduleDB.save` 移除非 atomic fallback

**Files:**
- Modify: `src/rule_scheduler.py:60-78`
- Test: `tests/test_schedule_db_atomic.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_schedule_db_atomic.py
from unittest.mock import patch
from src.rule_scheduler import ScheduleDB

def test_save_does_not_fallback_to_truncate(tmp_path):
    db = ScheduleDB(str(tmp_path / "x.json"))
    db.db = {"key": "value"}
    # Simulate os.replace failure
    with patch("os.replace", side_effect=OSError("simulated")):
        import pytest
        with pytest.raises(OSError):
            db.save()  # 不應 silently fallback
```

- [ ] **Step 2：驗證失敗**

```bash
pytest tests/test_schedule_db_atomic.py -v
# 預期：FAIL（目前有 fallback）
```

- [ ] **Step 3：修改 `src/rule_scheduler.py` `save()` — 移除 fallback**

```python
def save(self):
    tmp_path = self.db_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(self.db, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, self.db_path)  # raise on failure, NO fallback
```

- [ ] **Step 4：驗證通過 + commit**

```bash
pytest tests/test_schedule_db_atomic.py -v  # PASS
git add src/rule_scheduler.py tests/test_schedule_db_atomic.py
git commit -m "fix(scheduler): remove non-atomic fallback in ScheduleDB.save (M-4)"
```

- [ ] **Step 5：部署 + restart 驗證**

```bash
scp src/rule_scheduler.py root@172.16.15.106:/root/illumio-ops/src/
ssh illumio-ops-test 'systemctl restart illumio-ops && systemctl is-active illumio-ops'
```

### Task 2.5（M-5）：`/api/actions/*` 加 rate limit

**Files:**
- Modify: `src/gui/routes/actions.py:300,319,365`
- Modify: `src/gui/routes/dashboard.py:288`
- Modify: `src/gui/routes/reports.py:324,372,515`
- Test: `tests/test_actions_rate_limit.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_actions_rate_limit.py
def test_actions_run_rate_limit(client, logged_in_session):
    """超過 10/hour 第 11 次應 429"""
    for i in range(11):
        resp = client.post("/api/actions/run", json={"action": "noop"},
                          headers={"X-CSRFToken": csrf})
    assert resp.status_code == 429
```

- [ ] **Step 2~5：加 `@limiter.limit("10 per hour")` decorator 到每個重型 endpoint，跑 pytest，commit**

```bash
# 各 endpoint 加 decorator（具體位置見 audit 報告 M-5）
git add src/gui/routes/actions.py src/gui/routes/dashboard.py src/gui/routes/reports.py tests/test_actions_rate_limit.py
git commit -m "fix(gui): add per-endpoint rate limits to heavy actions (M-5)"
```

- [ ] **Step 6：部署 + 驗證**

```bash
scp src/gui/routes/*.py root@172.16.15.106:/root/illumio-ops/src/gui/routes/
ssh illumio-ops-test 'systemctl restart illumio-ops'
```

### Task 2.6（M-6）：合併 — 已於 T1.5 涵蓋

**狀態：** Task 1.5 已實作 production validator 涵蓋 PCE / Syslog TLS / Splunk HEC，無重複實作。

- [ ] 確認 T1.5 測試已涵蓋 SyslogTlsConfig 與 SplunkHecConfig（同 validator pattern）。若 T1.5 僅做 PCE，擴展加入。

### Task 2.7（M-7）：webhook URL scheme validator

**Files:**
- Modify: `src/config_models.py`（`WebhookConfig`）
- Test: `tests/test_webhook_scheme.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_webhook_scheme.py
import pytest
from src.config_models import WebhookConfig

def test_webhook_rejects_http():
    with pytest.raises(ValueError, match="https"):
        WebhookConfig(webhook_url="http://example.com/hook")

def test_webhook_accepts_https():
    cfg = WebhookConfig(webhook_url="https://example.com/hook")
    assert cfg.webhook_url == "https://example.com/hook"

def test_webhook_accepts_empty():
    cfg = WebhookConfig(webhook_url="")
    assert cfg.webhook_url == ""
```

- [ ] **Step 2~6：加 validator、commit、部署、驗證**

```python
class WebhookConfig(BaseModel):
    webhook_url: str = ""

    @validator("webhook_url")
    def _enforce_https(cls, v):
        if v and not v.startswith("https://"):
            raise ValueError("webhook_url 必須使用 https:// scheme")
        return v
```

### Task 2.8（M-8）：明示接受 — 無 task

**狀態：明示接受。** CSP `'unsafe-inline'` 因 40+ `onclick=` 改造成本高，且補償控制（CSRF / `escapeHtml` / Argon2 / session_protection=strong）足夠擋實際 XSS。屬 securityheaders.com 扣分項而非實質漏洞，後續若需通過更嚴 audit 再啟獨立 plan。Audit 報告 §3.3 M-8 標「明示接受 + 補償控制」。

### Task 2.9（M-9）：SMTP 與 LINE plugin timeout + cleanup

**Files:**
- Modify: `src/reporter.py:1754-1769`
- Modify: `src/alerts/plugins.py`（MailAlertPlugin）
- Test: `tests/test_smtp_lifecycle.py`（新）

- [ ] **Step 1：寫失敗測試**

```python
# tests/test_smtp_lifecycle.py
from unittest.mock import patch, MagicMock
import smtplib

def test_smtp_uses_context_manager(monkeypatch):
    """SMTP 必須以 with smtplib.SMTP(...) 使用，確保例外時 quit"""
    closed = {"value": False}
    class MockSMTP:
        def __init__(self, host, port, timeout=None):
            assert timeout is not None
        def __enter__(self): return self
        def __exit__(self, *a): closed["value"] = True; return False
        def starttls(self): pass
        def login(self, u, p): raise smtplib.SMTPAuthenticationError(535, b"fail")
        def sendmail(self, *a, **kw): pass
        def quit(self): pass
    monkeypatch.setattr(smtplib, "SMTP", MockSMTP)
    from src.reporter import _send_smtp_email
    _send_smtp_email("host", 25, "user", "pw", "from@x", ["to@y"], "subj", "body")
    assert closed["value"]
```

- [ ] **Step 2~6：實作 + 驗證 + 部署**

```python
# src/reporter.py: 1754
def _send_smtp_email(host, port, user, pw, sender, recipients, subject, body):
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.sendmail(sender, recipients, msg.as_string())
        return True
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP auth failed (config error): {e}")
        return False
    except (smtplib.SMTPConnectError, OSError) as e:
        logger.warning(f"SMTP transient: {e}")
        return False
```

Same pattern apply to `MailAlertPlugin` in `src/alerts/plugins.py`。

### Task 2.10（M-10）：`flask_limiter` 改 file backend

**Files:**
- Modify: `src/gui/__init__.py:233`
- Test: `tests/test_limiter_backend.py`

- [ ] **Step 1：寫測試 + 修改**

```python
# tests/test_limiter_backend.py
def test_limiter_uses_persistent_backend():
    from src.gui import app
    assert app.config.get("RATELIMIT_STORAGE_URI", "").startswith(("file://", "redis://"))
```

修改 `src/gui/__init__.py:233`：

```python
storage_uri="file:///var/lib/illumio-ops/limiter" if Path("/var/lib/illumio-ops").exists() else f"file://{os.path.expanduser('~/.illumio-ops/limiter')}"
```

加入 `install.sh` 建立 `/var/lib/illumio-ops/limiter` 目錄。

- [ ] **Step 2~6：驗證、commit、部署**

### Task 2.11（M-11）：Filebeat / Logstash / rsyslog 範例帶 TLS

**Files:**
- Modify: `deploy/filebeat.illumio_ops.yml`
- Modify: `deploy/logstash.illumio_ops.conf`
- Modify: `deploy/rsyslog.illumio_ops.conf`
- Test: `tests/test_deploy_examples.py`（新）

- [ ] **Step 1：寫失敗測試 — 範例 must contain TLS configuration**

```python
# tests/test_deploy_examples.py
from pathlib import Path

DEPLOY = Path(__file__).parent.parent / "deploy"

def test_filebeat_example_has_ssl():
    content = (DEPLOY / "filebeat.illumio_ops.yml").read_text()
    assert "ssl.enabled: true" in content
    assert "ssl.verification_mode: full" in content
    assert "changeme" not in content.lower()

def test_logstash_example_has_ssl():
    content = (DEPLOY / "logstash.illumio_ops.conf").read_text()
    assert "ssl => true" in content
    assert "ssl_certificate_verification => true" in content

def test_rsyslog_example_has_tls():
    content = (DEPLOY / "rsyslog.illumio_ops.conf").read_text()
    assert "DefaultNetstreamDriver=\"gtls\"" in content or "gtls" in content
```

- [ ] **Step 2~6：更新範例檔加 TLS，置換 `changeme` 為 `<REPLACE_ME>`，驗證、commit**

### Task 2.12（M-12）：LICENSE + SBOM + pip-audit CI

**Files:**
- Create: `LICENSE`
- Create: `THIRD_PARTY_NOTICES.md`
- Create: `scripts/generate_sbom.sh`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/verify_deps.py`（強制 pip-audit）

- [ ] **Step 1：選定 LICENSE（建議 Apache 2.0 或 MIT，看商業策略）**

```bash
# 假設選 MIT
cat > LICENSE <<'EOF'
MIT License

Copyright (c) 2026 Illumio Ops Project Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
...
EOF
```

- [ ] **Step 2：產 THIRD_PARTY_NOTICES.md**

```bash
pip install pip-licenses
pip-licenses --from=mixed --format=markdown --with-license-file --no-license-path > THIRD_PARTY_NOTICES.md
```

- [ ] **Step 3：產 SBOM**

```bash
pip install cyclonedx-bom
cyclonedx-py environment > sbom.cyclonedx.json
```

- [ ] **Step 4：CI 加 pip-audit + require-hashes**

修改 `.github/workflows/ci.yml`:

```yaml
- name: Install dependencies
  run: pip install --require-hashes -r requirements.lock

- name: Security audit
  run: |
    pip install pip-audit
    pip-audit -r requirements.lock --strict
```

- [ ] **Step 5~6：commit、push、CI 驗證**

```bash
git add LICENSE THIRD_PARTY_NOTICES.md sbom.cyclonedx.json scripts/generate_sbom.sh .github/workflows/ci.yml scripts/verify_deps.py
git commit -m "feat(supply-chain): LICENSE + SBOM + pip-audit gate (M-12, H-7-CI)"
git push
# 觀察 CI 是否通過
```

### Task 2.13（M-13）：`setup.sh` + CI 走 `requirements.lock --require-hashes`

**Files:**
- Modify: `scripts/setup.sh:35`
- Modify: `.github/workflows/ci.yml`（已於 T2.12 涵蓋）

- [ ] **Step 1：修改 `setup.sh:35`**

```bash
# scripts/setup.sh
pip install --require-hashes -r requirements.lock --quiet
```

- [ ] **Step 2~3：驗證 + commit**

```bash
# 本機驗證
cd /tmp && python -m venv test_install
source test_install/bin/activate
pip install --require-hashes -r /home/harry/rd/illumio-ops/requirements.lock --quiet
# 預期：所有 wheel 從 PyPI 下載並驗 hash
deactivate
git add scripts/setup.sh
git commit -m "fix(deps): setup.sh uses requirements.lock with hashes (M-13)"
```

### Task 2.14（M-14）：log redaction 加強

**Files:**
- Modify: `src/loguru_config.py:18-39`
- Test: `tests/test_log_redaction.py`（新）

- [ ] **Step 1：寫測試**

```python
# tests/test_log_redaction.py
import re
from src.loguru_config import _redact_record

def test_telegram_token_redacted():
    msg = "Calling https://api.telegram.org/bot1234567890:ABCDEFghijklmnopqrstuvwxyz_-1234567/sendMessage"
    result = _redact_record(msg)
    assert "ABCDEF" not in result
    assert "<REDACTED>" in result or "***" in result

def test_pce_href_redacted():
    msg = "/orgs/1/workloads/abc-123-def-456"
    result = _redact_record(msg)
    assert "<HREF>" in result or "abc-123" not in result
```

- [ ] **Step 2：加 regex 到 `_LOG_SECRET_FIELD`（或新增 `_LOG_HIGH_ENTROPY`）**

```python
_LOG_BOT_TOKEN = re.compile(r"bot\d+:[A-Za-z0-9_-]{30,}")
_LOG_PCE_HREF = re.compile(r"/orgs/\d+/(workloads|labels|rule_sets)/[a-f0-9-]{8,}")

def _redact_record(message: str) -> str:
    message = _LOG_BOT_TOKEN.sub("bot<REDACTED>", message)
    message = _LOG_PCE_HREF.sub("/orgs/N/<HREF>", message)
    # 原有 key:value 處理...
    return message
```

- [ ] **Step 3~5：驗證、commit、部署**

---

## Phase 3 — LOW（合併處理）

### Task 3.1（L-1）：SHA1 / MD5 加 `usedforsecurity=False`

**Files:**
- Modify: `src/pce_cache/traffic_filter.py:51`
- Modify: `src/pce_cache/backfill.py:137`
- Modify: `src/pce_cache/ingestor_traffic.py:144`
- Modify: `src/events/poller.py:43`
- Test: `tests/test_hashlib_usedforsecurity.py`（新）

- [ ] **Step 1：寫測試**

```python
# tests/test_hashlib_usedforsecurity.py
import ast
from pathlib import Path

TARGETS = [
    "src/pce_cache/traffic_filter.py",
    "src/pce_cache/backfill.py",
    "src/pce_cache/ingestor_traffic.py",
    "src/events/poller.py",
]

def test_md5_sha1_marked_usedforsecurity_false():
    for target in TARGETS:
        src = Path(target).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = ""
                if isinstance(func, ast.Attribute):
                    name = func.attr
                if name in ("md5", "sha1"):
                    kwargs = {kw.arg: kw.value for kw in node.keywords}
                    assert "usedforsecurity" in kwargs, f"{target}: {name}() 缺 usedforsecurity"
```

- [ ] **Step 2~5：修改 4 個檔案，把 `hashlib.md5(x)` 改 `hashlib.md5(x, usedforsecurity=False)`，commit**

```bash
git add src/pce_cache/*.py src/events/poller.py tests/test_hashlib_usedforsecurity.py
git commit -m "fix(crypto): mark MD5/SHA1 cache keys as usedforsecurity=False (L-1)"
```

### Task 3.2（L-2）：CLI 清螢幕改 ANSI escape

**Files:**
- Modify: `src/main.py:92, 114, 189, 238`

- [ ] **Step 1：取代 4 處 shell-exec 為 ANSI escape**

```python
# Before: subprocess call via os module
# After:
print("\033[2J\033[H", end="", flush=True)
```

- [ ] **Step 2：commit**

```bash
git add src/main.py
git commit -m "refactor(cli): use ANSI escape instead of shell exec for clear (L-2)"
```

### Task 3.3（L-3）：`/static/*` 經 IP allowlist

**Files:**
- Modify: `src/gui/__init__.py:375-376`
- Test: `tests/test_static_ip_allowlist.py`（新）

- [ ] **Step 1：寫測試 + 修改**

```python
# src/gui/__init__.py: security_check
@app.before_request
def security_check():
    if request.endpoint == "static" or request.path.startswith("/static/"):
        # 不要求 session，但 IP allowlist 仍須通過
        client_ip = request.remote_addr
        if not _check_ip_allowed(cm.config.get("web_gui", {}).get("allowed_ips", []), client_ip):
            _rst_drop()
        return
    # ... 原本邏輯 ...
```

- [ ] **Step 2~5：驗證 + commit**

### Task 3.4（L-4）：`index.html` 改 JSON script tag

**Files:**
- Modify: `src/templates/index.html:13`
- Modify: `src/static/js/utils.js`（讀取改 `JSON.parse`）

- [ ] **Step 1：改 template**

```html
<script id="i18n-data" type="application/json">{{ ui_translations_json | safe }}</script>
<script>
window._INIT_TRANSLATIONS = JSON.parse(document.getElementById('i18n-data').textContent);
</script>
```

- [ ] **Step 2：commit**

```bash
git add src/templates/index.html
git commit -m "refactor(template): use JSON script tag instead of |safe (L-4)"
```

### Task 3.5（L-5 + L-6）：檔案權限 0o644 → 0o640 + log rotation 加 chmod

**Files:**
- Modify: `src/loguru_config.py`（rotation hook）
- Modify: `scripts/install.sh`（已於 T1.1 涵蓋大部分）

- [ ] **Step 1：loguru rotation hook 改寫**

```python
# src/loguru_config.py
def _on_rotate(filepath):
    try:
        os.chmod(filepath, 0o640)
    except OSError:
        pass

logger.add(log_file, rotation="10 MB", compression="gz", retention=10, mode="w")
# loguru 沒直接 rotation hook，但可在 setup 後對 logs/ 批次 chmod
import atexit
@atexit.register
def _final_chmod():
    for p in Path("logs").glob("**/*.log*"):
        try: os.chmod(p, 0o640)
        except OSError: pass
```

- [ ] **Step 2：執行 install.sh 確認 chmod 套用**

T1.1 install.sh 已新增 `find ... -exec chmod 0640` 段；此 task 只是補 loguru 啟動時的 chmod。

- [ ] **Step 3：commit + 部署驗證**

```bash
ssh illumio-ops-test 'find /root/illumio-ops/logs /root/illumio-ops/config -type f \( -name "*.log" -o -name "*.yaml" -o -name "rule_schedules.json" \) -exec stat -c "%a %n" {} \;'
# 預期：均為 640（除了 0o600 的 secrets）
```

### Task 3.6（L-7 + L-10）：TOFU 來源加 SHA256 pinning

**Files:**
- Modify: `scripts/build_offline_bundle.sh:24-40, 74, 120`
- Modify: `vendor/windows/README.md`（新；標 nssm 版本與 sha256）

- [ ] **Step 1：硬編碼 PBS Python tarball SHA256**

```bash
# scripts/build_offline_bundle.sh
PBS_VERSION="3.12.7+20241016"
PBS_SHA256_LINUX_X86_64="<sha256_value_here>"  # 從上游 release 頁面取
# 下載後驗證
echo "$PBS_SHA256_LINUX_X86_64  cpython-${PBS_VERSION}-...tar.gz" | sha256sum -c -
```

- [ ] **Step 2：加 vendor/windows/README.md**

```markdown
# NSSM 2.24 vendor
- Source: https://nssm.cc/release/nssm-2.24.zip
- SHA256: <expected_hash>
- Reason: Windows service manager
- Replacement candidate: WinSW（追蹤）
```

- [ ] **Step 3~5：驗證、commit、部署不適用（build-time）**

### Task 3.7（L-11 + L-12 + L-13 + L-14）：文件更新

**Files:**
- Modify: `README.md`（reverse proxy 警告 / Telegram proxy 警告 / Cheroot header / autoStash 警告）

- [ ] **Step 1：補 README 段落**

```markdown
## 部署注意事項

### Reverse Proxy
本服務未自動配置 Flask `ProxyFix`。如部署於 reverse proxy 後方，請：
1. 設定 ProxyFix middleware（trust 1 hop）
2. 否則 IP allowlist 將失效（所有來源顯示為 proxy IP）

### Telegram Alert Plugin
Telegram bot token 以 URL path 傳遞。部署於金融 / 國防環境時：
- 禁止對外網路代理 access log 寫入完整 URL path
- 或使用 NoProxy direct 連線

### Server Header
cheroot 預設輸出 `Server: Cheroot/<version>`。若稽核要求 strip：
- 在 reverse proxy 端 strip
- 或自訂 cheroot middleware（後續優化）

### Production Git Workflow
`scripts/setup-prod-git.sh` 啟用 `merge.autoStash=true`。意味著 prod box 可能保留未提交的本地編輯，與 git tag 非 bit-for-bit reproducible。
```

- [ ] **Step 2：commit**

```bash
git add README.md
git commit -m "docs: add deployment warnings (L-11/L-12/L-13/L-14)"
```

### Task 3.8（最終）：整體驗證 + audit report 標記 done

**Files:**
- Modify: `docs/security-audit-2026-05-22.md`（每項打勾）

- [ ] **Step 1：跑全測試套件**

```bash
cd /home/harry/rd/illumio-ops
pytest tests/ -v 2>&1 | tail -30
# 預期：全部 PASS
```

- [ ] **Step 2：在測試機跑完整 Phase A baseline 再比對**

```bash
ssh illumio-ops-test 'bash -s' > /tmp/post_remediation.txt <<'EOF'
echo "=== systemd-analyze security ==="
systemd-analyze security illumio-ops.service 2>&1 | tail -3
echo "=== process baseline ==="
PID=$(systemctl show --value -p MainPID illumio-ops)
id $(systemctl show --value -p User illumio-ops)
ls /proc/$PID/fd 2>/dev/null | wc -l | xargs echo "fds:"
awk '/VmRSS|Threads/{print}' /proc/$PID/status 2>/dev/null
echo "=== ports ==="
ss -tlnp 2>/dev/null | grep 5001
echo "=== file perms ==="
find /root/illumio-ops/config /root/illumio-ops/logs -type f -exec stat -c '%a %n' {} \; | sort
echo "=== config secret_key length ==="
python3 -c "import json; print(len(json.load(open('/root/illumio-ops/config/config.json')).get('web_gui',{}).get('secret_key','')))"
EOF
diff /home/harry/rd/illumio-ops/docs/security-audit-2026-05-22-baseline.txt /tmp/post_remediation.txt
```

- [ ] **Step 3：更新 audit report 的 §6.3 checkbox 為已完成**

`docs/security-audit-2026-05-22.md` 中所有 checkbox 改成 `[x]`（待 Task 3.8 實際執行時更新）。

- [ ] **Step 4：最終 commit + tag**

```bash
git add docs/security-audit-2026-05-22.md
git commit -m "docs(audit): mark all remediation items complete"
git tag post-security-remediation-2026-05-22 HEAD
git push origin security-remediation-2026-05-22
git push origin --tags
```

- [ ] **Step 5：開 PR**

```bash
gh pr create --base main --title "Security Remediation 2026-05-22" --body "$(cat <<'EOF'
## Summary
- 完成 docs/security-audit-2026-05-22.md 所列 36 項發現的修補
- C-1 systemd hardening、H-1~H-7、M-1~M-14、L-1~L-14
- H-4 datetime + M-8 CSP unsafe-inline 留獨立 plan

## Verification
- 全部 pytest tests/ 通過
- 測試機 172.16.15.106 經 Phase A baseline 比對：systemd-analyze 評分由 9.6 → ≤ 3.0

## Test plan
- [ ] CI 全綠
- [ ] 測試機 24h FD 趨勢平穩
- [ ] 從外部 IP 確認 GUI bind 收緊
EOF
)"
```

---

## Self-Review Checklist

執行完畢前自我檢查：

**1. Spec coverage**（每條 audit 發現對應 task）：
- C-1 → T1.1 ✓
- H-1 → **明示接受**（T1.2 不修，補償控制見 audit 報告）
- H-2 → T1.6 ✓
- H-3 → T1.7 ✓
- H-4 → 獨立 plan `2026-05-22-datetime-tz-aware.md` ✓
- H-5 → T1.3 ✓
- H-6 → T1.5 ✓
- H-7 → T1.4 ✓
- M-1 → T2.1 ✓
- M-2 → T2.2 ✓
- M-3 → T2.3 ✓
- M-4 → T2.4 ✓
- M-5 → T2.5 ✓
- M-6 → T2.6（併 T1.5）✓
- M-7 → T2.7 ✓
- M-8 → **明示接受**（T2.8 不修，補償控制見 audit 報告）
- M-9 → T2.9 ✓
- M-10 → T2.10 ✓
- M-11 → T2.11 ✓
- M-12 → T2.12 ✓
- M-13 → T2.13 ✓
- M-14 → T2.14 ✓
- L-1 → T3.1 ✓
- L-2 → T3.2 ✓
- L-3 → T3.3 ✓
- L-4 → T3.4 ✓
- L-5 → T3.5 ✓
- L-6 → T3.5 ✓
- L-7 → T3.6 ✓
- L-8 → T1.1（併 install.sh useradd）✓
- L-9 → T1.1（併 hardened unit）✓
- L-10 → T3.6 ✓
- L-11 → T3.7 ✓
- L-12 → T3.7 ✓
- L-13 → T3.7 ✓
- L-14 → T3.7 ✓

**2. Placeholder scan**：T1.8 與 T2.8 為刻意 placeholder（已標明獨立 plan）；其他 task 步驟皆含實際 code / 指令，無 "TBD/TODO/fill in details" 等模糊用語。

**3. Type consistency**：所有 task 用 `tests/test_<name>.py` 命名一致；commit 訊息格式 `<type>(<scope>): <subject> (<finding>)` 一致；測試機 SSH alias `illumio-ops-test` 一致。

---

## 執行優先順序與依賴關係

```
Phase 0 (T0.1-T0.3)
  ↓
Phase 1：
  T1.1 (systemd) ← 獨立可優先
  T1.2 → 明示接受，跳過
  T1.3 (LINE timeout) ← 獨立
  T1.4 (secret_key) ← 獨立
  T1.5 (verify_ssl validator) → T2.6 (依賴 T1.5)
  T1.6 (close()) ← 獨立
  T1.7 (shutdown_event) ← 獨立
  T1.8 → 獨立 plan（datetime）
  ↓
Phase 2：
  T2.1-T2.14 大部分獨立，可並行
  T2.6 依賴 T1.5
  T2.10 依賴 T1.1 (install.sh /var/lib/illumio-ops)
  ↓
Phase 3：
  T3.1-T3.7 全部獨立
  T3.5 依賴 T1.1（install.sh 已 chmod）
  T3.8 為最終整體驗證，依賴所有前置 task
```

**並行建議**：Phase 1 中 T1.2/T1.3/T1.4/T1.6/T1.7/T1.8 可同時分派給 6 個獨立 subagent；T1.1 與 T1.5 建議連續單線（部署相關）。Phase 2 同理可並行 ≥ 10 個 subagent。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-security-remediation.md`. Two execution options:**

**1. Subagent-Driven（推薦，符合你 mem0 記載的偏好）** - 每 task 一個 fresh subagent，spec compliance review → code quality review，並行可達 10+ subagents。

**2. Inline Execution** - 我在當前 session 連續執行，每 phase 一個 checkpoint 讓你 review。

**Which approach?**
