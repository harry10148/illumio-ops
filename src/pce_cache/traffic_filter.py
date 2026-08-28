from __future__ import annotations

import hashlib
import ipaddress


def _parse_addr(value):
    """Parse a flow's source IP; empty or malformed values yield None (never raise).

    _flatten_flow() produces `flow.get("src_ip","") or src.get("ip","")`, so ""
    is a reachable input even though the appliance currently has none.
    """
    if not value:
        return None
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


class TrafficFilter:
    def __init__(
        self,
        actions: list[str] | None = None,
        workload_label_env: list[str] | None = None,
        ports: list[int] | None = None,
        protocols: list[str] | None = None,
        exclude_src_ips: list[str] | None = None,
    ):
        self._actions = set(actions) if actions else None
        self._envs = set(workload_label_env) if workload_label_env else None
        self._ports = set(ports) if ports else None
        self._protos = set(protocols) if protocols else None
        # 混合語意：含 "/" → 網段，否則 → 精確 IP。分類規則與
        # src/config_models.py 的 TrafficFilterSettings._validate_ips 相同。
        # 精確 IP 留在原本的字串 set 走 O(1)，現有設定行為逐位元不變；
        # 只有網段需要線性掃描，且按版本分開存放，跨版本永遠掃不到對方。
        # 解析只在這裡做一次——passes() 每輪 fetch 會被呼叫 300+ 次。
        # 格式錯誤在此故意不吞：設定已由 pydantic 驗證過，能走到這裡就該炸。
        self._excl_src: set[str] = set()
        self._excl_nets: dict[int, list] = {4: [], 6: []}
        for entry in exclude_src_ips or []:
            if "/" in entry:
                net = ipaddress.ip_network(entry, strict=False)
                self._excl_nets[net.version].append(net)
            else:
                self._excl_src.add(entry)
        self._has_excl_nets = bool(self._excl_nets[4] or self._excl_nets[6])

    def passes(self, flow: dict) -> bool:
        if self._actions is not None and flow.get("action") not in self._actions:
            return False
        if self._ports is not None and flow.get("port") not in self._ports:
            return False
        if self._protos is not None and flow.get("protocol") not in self._protos:
            return False
        src_ip = flow.get("src_ip")
        if src_ip in self._excl_src:
            return False
        if self._has_excl_nets:
            # 設定的網段已在 __init__ 解析完畢；這裡只解析本筆 flow 自己的來源位址
            # （無法預先解析）。空字串／無法解析一律視為不匹配，不得拋例外。
            addr = _parse_addr(src_ip)
            if addr is not None:
                for net in self._excl_nets[addr.version]:
                    if addr in net:
                        return False
        if self._envs is not None:
            env = flow.get("workload_env")
            if env is not None and env not in self._envs:
                return False
        return True


class TrafficSampler:
    """Deterministic 1:N drop for allowed flows using stable hash."""

    def __init__(self, ratio_allowed: int = 1):
        if ratio_allowed < 1:
            raise ValueError("ratio_allowed must be >= 1")
        self._ratio = ratio_allowed

    def keep(self, flow: dict) -> bool:
        if flow.get("action") != "allowed":
            return True
        if self._ratio == 1:
            return True
        key = f"{flow.get('src_ip')}|{flow.get('dst_ip')}|{flow.get('port')}"
        h = int(hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest(), 16)
        return (h % self._ratio) == 0
