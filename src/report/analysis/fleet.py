"""VEN 車隊分析：版本分布、compat 四態、推進管線、coverage gaps、健康分數。

移植自 illumio-plugger 的 ven-fleet-manager，但四態化了 compat（plugger 把
warning 併進 fail，於是「有疑慮」與「不能推」看起來一樣），並且分數在分量
缺席時重正規化而不是補零——把缺的分量當 0，會讓一個沒設定 target 版本的
健康車隊看起來像壞掉的。

純函式：不 import Flask、不碰 ApiClient、不讀檔。呼叫端（`run_ven_summary`）
負責把既有那一次 `fetch_managed_workloads` 的結果餵進來。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

__all__ = [
    "PIPELINE_BUCKETS",
    "VALID_PROGRESSIONS",
    "analyze_fleet",
    "compat_state",
    "parse_ven_version",
]

# 模式只能往前推。white-list 而非 black-list：新增一個 PCE 模式時，預設是
# 「不可推進」而不是「可推進到任何地方」。
VALID_PROGRESSIONS: dict[str, set[str]] = {
    "idle": {"visibility_only", "selective", "full"},
    "visibility_only": {"selective", "full"},
    "selective": {"full"},
}

PIPELINE_BUCKETS = (
    "idle_compat_pass", "idle_compat_warn", "idle_compat_fail", "idle_compat_unknown",
    "visibility_ready", "visibility_not_ready", "selective", "full",
)

# 與 ven_status_generator 同一組判定，刻意重述而非 import：那邊吃的是 DataFrame
# 的一列，這邊吃的是原始 workload dict。數值一旦分歧就是 bug，守門測試會比。
_ONLINE_STATUSES = {"active", "online"}
_ONLINE_HEARTBEAT_THRESHOLD_HOURS = 1.0

_HEARTBEAT_FRESH_H = 24.0
_HEARTBEAT_STALE_H = 48.0

_SEVERITY_ERROR = {"err", "error", "critical"}
_SEVERITY_WARN = {"warn", "warning"}

_VERSION_RE = re.compile(r"^\s*(\d+(?:[.\-]\d+)*)\s*$")

_SCORE_WEIGHTS = {
    "online": 0.30,
    "enforcement": 0.25,
    "version": 0.20,
    "heartbeat": 0.15,
    "compat": 0.10,
}


def parse_ven_version(s: Any) -> tuple[int, ...] | None:
    """"26.2.20-2063" -> (26, 2, 20, 2063)；無法解析 -> None。

    字串排序會把 "9.x" 排在 "26.x" 之後，所以排序一律走這個 tuple。
    """
    if not isinstance(s, str):
        return None
    m = _VERSION_RE.match(s)
    if not m:
        return None
    parts = re.split(r"[.\-]", m.group(1))
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def compat_state(agent_health: Any) -> str:
    """compat 四態：無 compat 項→unknown；任一 error→fail；任一 warning→warn；否則 pass。

    只看 type 帶 "compatibility" 的條目——其他健康訊號（心跳、憑證）不是
    「這台能不能推進 enforcement」的答案，混進來會讓 compat 說謊。
    """
    if not isinstance(agent_health, list):
        return "unknown"
    items = [x for x in agent_health
             if isinstance(x, dict) and "compatibility" in str(x.get("type") or "").lower()]
    if not items:
        return "unknown"
    sevs = {str(x.get("severity") or "").lower() for x in items}
    if sevs & _SEVERITY_ERROR:
        return "fail"
    if sevs & _SEVERITY_WARN:
        return "warn"
    return "pass"


def _status(w: dict) -> dict:
    agent = w.get("agent") or {}
    st = agent.get("status") or {}
    return st if isinstance(st, dict) else {}


def _agent_version(st: dict, w: dict) -> str:
    for v in (st.get("agent_version"),
              ((w.get("ven") or {}) if isinstance(w.get("ven"), dict) else {}).get("version"),
              ((w.get("agent") or {}).get("config") or {}).get("agent_version")):
        if v:
            return str(v)
    return ""


def _hours_since_heartbeat(st: dict, now: dt.datetime) -> float | None:
    """PCE 算好的 hours_since_last_heartbeat 優先；缺則由 last_heartbeat_on 推。"""
    hslh = st.get("hours_since_last_heartbeat")
    if hslh is not None:
        try:
            return float(hslh)
        except (TypeError, ValueError):
            pass
    raw = st.get("last_heartbeat_on")
    if not raw:
        return None
    try:
        stamp = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return (now - stamp).total_seconds() / 3600.0


def _is_online(st: dict, hslh: float | None) -> bool:
    if str(st.get("status") or "").lower() not in _ONLINE_STATUSES:
        return False
    # 心跳資訊完全缺席時視為離線：行政狀態 active 不代表連得上。
    return hslh is not None and hslh <= _ONLINE_HEARTBEAT_THRESHOLD_HOURS


def _labels(w: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for lbl in w.get("labels") or []:
        if isinstance(lbl, dict) and lbl.get("key"):
            out[str(lbl["key"]).lower()] = str(lbl.get("value") or "")
    return out


def _bucket(w: dict, mode: str, compat: str) -> str:
    if mode == "idle":
        return "idle_compat_" + compat
    if mode == "visibility_only":
        received = _status(w).get("security_policy_received_at") or \
            _status(w).get("security_policy_refresh_at")
        return "visibility_ready" if received else "visibility_not_ready"
    if mode in ("selective", "full"):
        return mode
    # 未知模式仍要進得了某一桶，否則 sum(pipeline) != total 而沒人會發現。
    return "selective"


def _score(*, total: int, online: int, non_idle: int, target: str | None,
           on_target: int, hb: dict[str, int], compat_counts: dict[str, int]) -> dict:
    """五個分量各自可能「不存在」；缺者剔除，其餘權重除以權重和。

    「不存在」與「是 0」是兩件事：沒設定 target 版本不代表沒人在目標版本上。
    """
    hb_known = hb["fresh"] + hb["stale_24h"] + hb["stale_48h"]
    compat_known = compat_counts["pass"] + compat_counts["warn"] + compat_counts["fail"]
    present: dict[str, float | None] = {
        "online": (online / total) if total else None,
        "enforcement": (non_idle / total) if total else None,
        "version": (on_target / total) if (target and total) else None,
        "heartbeat": (hb["fresh"] / hb_known) if hb_known else None,
        "compat": (compat_counts["pass"] / compat_known) if compat_known else None,
    }
    components = {k: {"present": v is not None, "value": (None if v is None else round(v, 4))}
                  for k, v in present.items()}
    live = {k: v for k, v in present.items() if v is not None}
    if not live:
        return {"score": None, "partial": True, "components": components}
    weight_sum = sum(_SCORE_WEIGHTS[k] for k in live)
    score = sum(_SCORE_WEIGHTS[k] * v for k, v in live.items()) / weight_sum * 100
    return {"score": round(score), "partial": len(live) < len(present), "components": components}


def analyze_fleet(workloads: list[dict], now: dt.datetime, target_version: str | None,
                  *, top_n: int = 50, index_cap: int = 20000) -> dict:
    """車隊層級的一包分析結果。呼叫端只讀這個 dict——GUI、報表、批次推進都是。"""
    target = (target_version or "").strip() or None

    pipeline: dict[str, dict] = {b: {"count": 0, "sample": []} for b in PIPELINE_BUCKETS}
    compat_counts = {"pass": 0, "warn": 0, "fail": 0, "unknown": 0}
    hb = {"fresh": 0, "stale_24h": 0, "stale_48h": 0, "no_heartbeat": 0}
    distribution: dict[str, dict] = {}
    by_app: dict[str, dict[str, int]] = {}
    by_env: dict[str, dict[str, int]] = {}
    unlabeled = {"count": 0, "sample": []}
    health = {"errors": {"count": 0, "sample": []}, "warnings": {"count": 0, "sample": []}}
    index: list[dict] = []
    online_n = 0
    non_idle_n = 0
    on_target_n = 0

    for w in workloads:
        st = _status(w)
        mode = str(w.get("enforcement_mode") or "")
        version = _agent_version(st, w)
        hslh = _hours_since_heartbeat(st, now)
        online = _is_online(st, hslh)
        compat = compat_state(st.get("agent_health"))
        labels = _labels(w)
        os_detail = str(w.get("os_id") or w.get("os_detail") or "")
        hostname = str(w.get("hostname") or w.get("name") or "")
        href = str(w.get("href") or "")

        if online:
            online_n += 1
        if mode and mode != "idle":
            non_idle_n += 1
        if target and version == target:
            on_target_n += 1

        if mode == "idle":
            compat_counts[compat] += 1

        if hslh is None:
            hb["no_heartbeat"] += 1
        elif hslh <= _HEARTBEAT_FRESH_H:
            hb["fresh"] += 1
        elif hslh <= _HEARTBEAT_STALE_H:
            hb["stale_24h"] += 1
        else:
            hb["stale_48h"] += 1

        entry = distribution.setdefault(version, {"count": 0, "os_breakdown": {}})
        entry["count"] += 1
        entry["os_breakdown"][os_detail] = entry["os_breakdown"].get(os_detail, 0) + 1

        brief = {"href": href, "hostname": hostname, "mode": mode, "compat": compat}
        bucket = pipeline[_bucket(w, mode, compat)]
        bucket["count"] += 1
        if len(bucket["sample"]) < top_n:
            bucket["sample"].append(brief)

        if labels.get("app"):
            by_app.setdefault(labels["app"], {})
            by_app[labels["app"]][mode] = by_app[labels["app"]].get(mode, 0) + 1
        if labels.get("env"):
            by_env.setdefault(labels["env"], {})
            by_env[labels["env"]][mode] = by_env[labels["env"]].get(mode, 0) + 1
        if not labels:
            unlabeled["count"] += 1
            if len(unlabeled["sample"]) < top_n:
                unlabeled["sample"].append(brief)

        for item in st.get("agent_health") or []:
            if not isinstance(item, dict):
                continue
            sev = str(item.get("severity") or "").lower()
            slot = health["errors"] if sev in _SEVERITY_ERROR else health["warnings"]
            slot["count"] += 1
            if len(slot["sample"]) < top_n:
                slot["sample"].append({"hostname": hostname, "href": href,
                                       "type": str(item.get("type") or ""), "severity": sev,
                                       "audit_event": item.get("audit_event")})
        ahe = st.get("agent_health_errors")
        if isinstance(ahe, dict):
            for key, slot in (("errors", health["errors"]), ("warnings", health["warnings"])):
                for item in ahe.get(key) or []:
                    slot["count"] += 1
                    if len(slot["sample"]) < top_n:
                        slot["sample"].append({"hostname": hostname, "href": href,
                                               "type": str(item), "severity": key[:-1],
                                               "audit_event": None})

        index.append({"href": href, "hostname": hostname, "mode": mode, "online": online,
                      "version": version, "compat": compat, "hslh": hslh,
                      "app": labels.get("app", ""), "env": labels.get("env", ""),
                      "os": os_detail})

    # 版本排序走數值 tuple；解析不出來的集中到最後，順序自身穩定。
    parsed = {v: parse_ven_version(v) for v in distribution}
    unparsable = sorted(v for v, p in parsed.items() if p is None)
    sortable = sorted((v for v, p in parsed.items() if p is not None),
                      key=lambda v: parsed[v], reverse=True)
    ordered = sortable + unparsable

    total = len(workloads)
    truncated = total > index_cap
    return {
        "generated_at": now.isoformat(),
        "total": total,
        "managed_online": online_n,
        "managed_offline": total - online_n,
        "versions": {
            "distribution": distribution,
            "ordered": ordered,
            "target": target,
            "on_target": on_target_n,
            "needs_upgrade": (total - on_target_n) if target else None,
            # oldest/newest 只在可解析的版本之間有意義：全是 "dev" 的車隊沒有
            # 「最舊」可言，回 None 比回一個任意字串誠實。
            "oldest": (sortable[-1] if sortable else None),
            "newest": (sortable[0] if sortable else None),
            "unparsable": unparsable,
        },
        "compat": compat_counts,
        "pipeline": pipeline,
        "heartbeat": hb,
        "coverage_gaps": {"by_app": by_app, "by_env": by_env, "unlabeled": unlabeled},
        "agent_health": health,
        "health_score": _score(total=total, online=online_n, non_idle=non_idle_n,
                               target=target, on_target=on_target_n, hb=hb,
                               compat_counts=compat_counts),
        "workloads_index": [] if truncated else index,
        "index_truncated": truncated,
    }
