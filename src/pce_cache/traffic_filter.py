from __future__ import annotations

import hashlib


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
        self._excl_src = set(exclude_src_ips) if exclude_src_ips else set()

    def passes(self, flow: dict) -> bool:
        if self._actions is not None and flow.get("action") not in self._actions:
            return False
        if self._ports is not None and flow.get("port") not in self._ports:
            return False
        if self._protos is not None and flow.get("protocol") not in self._protos:
            return False
        if flow.get("src_ip") in self._excl_src:
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
