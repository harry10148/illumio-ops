"""CLI 物件選擇器：questionary 兩段式（類別 → autocomplete），與 Web FilterBar 同語意。
候選直呼 ApiClient（cached 三類 + workload 即時）；PCE 離線或非 TTY 降級手動輸入。"""
import ipaddress
import sys

import questionary

from src.i18n import t

try:
    from src.cli._render import _QUESTIONARY_STYLE as _STYLE
except ImportError:  # pragma: no cover - 極端情況下 _render 不可用時的保底
    _STYLE = None

_CAT_ORDER = ("label", "label_group", "iplist", "workload", "ip", "port", "service")

# 類別選單顯示名稱：與現有技術詞彙一致（中英文皆保留原文，同 gui_fb_cat_* 慣例）
_CAT_TITLES = {
    "label": "Label",
    "label_group": "Label Group",
    "iplist": "IP List",
    "workload": "Workload",
    "ip": "IP/CIDR (manual)",
    "service": "Service",
    "port": "Port (manual)",
}

_DONE = "__done__"
_CLEAR_PREFIX = "__clear__"


def _interactive_ok():
    # 與 _render.py 同慣例：非 TTY（pipe/CI/測試）不走 questionary
    return sys.stdin.isatty() and sys.stdout.isatty()


def _valid_ip_or_cidr(text):
    try:
        if "/" in text:
            ipaddress.ip_network(text, strict=False)
        elif "-" in text:
            # IPv4 range：a.b.c.d-a.b.c.d，兩側各自須為合法 IP（from>to 由展開端對調）
            left, _, right = text.partition("-")
            ipaddress.IPv4Address(left.strip())
            ipaddress.IPv4Address(right.strip())
        else:
            ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _load_candidates(api, cat, label_key_filter=None):
    # 回傳 [(display, value)]；value 是要存進 filter 的字串（label 用 key=value、物件用 href、label_group 用名稱）
    # label_key_filter：只保留 key 相符的 label 候選（如 "env"）——供 pce_cache_cli 的
    # workload_label_env 槽等單一 dimension 呼叫端使用；預設 None＝不過濾（現行為，僅影響 TTY 候選載入）。
    if cat == "label":
        labels = api.get_all_labels()
        if label_key_filter is not None:
            labels = [l for l in labels if l.get("key") == label_key_filter]
        return [(f"{l['key']}={l['value']}", f"{l['key']}={l['value']}") for l in labels]
    if cat == "iplist":
        return [(ipl["name"], ipl["href"]) for ipl in api.get_ip_lists()]
    if cat == "label_group":
        return [(g["name"], g["name"]) for g in api.get_label_groups()]
    if cat == "workload":
        return [(f"{w.get('name') or w.get('hostname')} ({w.get('hostname', '')})", w["href"])
                for w in api.search_workloads({"max_results": 200})]
    if cat == "service":
        from src.gui.filter_object_cache import _service_summary
        out = []
        for s in api.get_services():
            summary = _service_summary(s)
            display = f"{s['name']} ({summary})" if summary else s["name"]
            out.append((display, s["href"]))
        return out
    return []


_CAT_RESULT_KEY = {"label": "labels", "label_group": "label_groups",
                   "iplist": "iplists", "workload": "workloads", "ip": "ips",
                   "service": "services", "port": "ports"}


def _append_unique(result, key, value):
    lst = result.setdefault(key, [])
    if value not in lst:
        lst.append(value)


def _split_values(raw):
    return [v.strip() for v in raw.split(",") if v.strip()]


def _pick_non_tty(api, cats, result, lang):
    # 非 TTY：對 cats（依 _CAT_ORDER 排序）逐類別 input()，空輸入=保留既有值，comma 拆 list。
    for cat in (c for c in _CAT_ORDER if c in cats):
        key = _CAT_RESULT_KEY[cat]
        current = result.get(key, [])
        prompt = t(
            "cli_pick_manual_input", lang=lang, cat=cat, current=", ".join(current),
            default="{cat} (comma-separated, current: {current}): ",
        )
        try:
            raw = input(prompt)
        except EOFError:
            # Input stream ended (piped/non-TTY): stop prompting, keep what we have.
            break
        if not raw.strip():
            continue
        values = _split_values(raw)
        if cat == "ip":
            values = [v for v in values if _valid_ip_or_cidr(v)]
        if cat == "port":
            from src.port_token import parse_port_token
            values = [v for v in values if parse_port_token(v)]
        if values:
            result[key] = values
        else:
            result.pop(key, None)
    return result


def _manual_text_entry(cat, key, result, lang):
    # TTY 手動輸入（離線降級 or ip 類別）：questionary.text，comma 拆 list，ip 類過濾非法值。
    raw = questionary.text(
        t("cli_pick_manual", lang=lang, cat=cat, default="Enter {cat} value(s) manually (comma-separated):"),
        style=_STYLE,
    ).unsafe_ask()
    if not raw:
        return
    values = _split_values(raw)
    if cat == "ip":
        values = [v for v in values if _valid_ip_or_cidr(v)]
    if cat == "port":
        from src.port_token import parse_port_token
        values = [v for v in values if parse_port_token(v)]
    for v in values:
        _append_unique(result, key, v)


def _pick_tty(api, cats, result, title, lang, label_key_filter=None):
    while True:
        choices = [questionary.Choice(title=_CAT_TITLES[c], value=c) for c in _CAT_ORDER if c in cats]
        for c in _CAT_ORDER:
            if c not in cats:
                continue
            n = len(result.get(_CAT_RESULT_KEY[c], []))
            if n:
                # 已有選值的類別才附加「清空」選項（不做逐項移除，見 Task 1 report follow-up）
                choices.append(questionary.Choice(
                    title=t("cli_pick_clear_cat", lang=lang, cat=_CAT_TITLES[c], n=n,
                            default="Clear {cat} ({n} items)"),
                    value=_CLEAR_PREFIX + c,
                ))
        choices.append(questionary.Choice(title=t("cli_pick_done", lang=lang, default="-- Done --"), value=_DONE))

        selection = questionary.select(
            t("cli_pick_category", lang=lang, title=title, default="Select object category for '{title}':"),
            choices=choices,
            style=_STYLE,
        ).unsafe_ask()
        if selection is None or selection == _DONE:
            break

        if isinstance(selection, str) and selection.startswith(_CLEAR_PREFIX):
            result.pop(_CAT_RESULT_KEY[selection[len(_CLEAR_PREFIX):]], None)
            continue

        cat = selection
        key = _CAT_RESULT_KEY[cat]

        if cat in ("ip", "port"):
            _manual_text_entry(cat, key, result, lang)
        else:
            try:
                candidates = _load_candidates(api, cat, label_key_filter=label_key_filter)
            except (ConnectionError, TimeoutError, OSError):
                print(t("cli_pick_offline_hint", lang=lang, cat=cat,
                        default="PCE unreachable while loading '{cat}' candidates; falling back to manual input."))
                _manual_text_entry(cat, key, result, lang)
            except Exception as exc:
                # Not a connectivity failure — surface the real error instead of
                # mislabelling it "PCE unreachable", then still allow manual entry.
                print(t("cli_pick_load_error", lang=lang, cat=cat, error=exc,
                        default="Failed to load '{cat}' candidates: {error}. Falling back to manual input."))
                _manual_text_entry(cat, key, result, lang)
            else:
                if not candidates:
                    # 候選載入成功但為空 ≠ PCE 離線，需獨立訊息（避免誤報 offline_hint）
                    print(t("cli_pick_no_candidates", lang=lang, cat=cat))
                    _manual_text_entry(cat, key, result, lang)
                else:
                    cand_map = {display: value for display, value in candidates}
                    chosen = questionary.autocomplete(
                        t("cli_pick_search", lang=lang, cat=cat, default="Search {cat}:"),
                        choices=list(cand_map.keys()),
                        style=_STYLE,
                    ).unsafe_ask()
                    if chosen in cand_map:
                        _append_unique(result, key, cand_map[chosen])

        print(t("cli_pick_selected", lang=lang, field=key, values=", ".join(result.get(key, [])),
                default="Selected {field}: {values}"))

    return result


def pick_objects(api, cats, title, preselected=None, lang=None, label_key_filter=None):
    """兩段式物件選擇器：TTY 走 questionary（類別 → autocomplete/手動），非 TTY 走 input() 降級。

    回傳只含非空類別的 dict，key 為 labels/label_groups/iplists/workloads/ips。

    label_key_filter：僅過濾 label 候選的 dimension（如 "env"），只影響 TTY 候選載入；
    非 TTY 路徑（手動輸入）不受影響。預設 None＝現行為（不過濾，全 dimension 皆可選）。
    """
    result = {k: list(v) for k, v in (preselected or {}).items() if v}  # 斷開別名，避免就地修改污染呼叫端

    if _interactive_ok():
        _pick_tty(api, cats, result, title, lang, label_key_filter=label_key_filter)
    else:
        _pick_non_tty(api, cats, result, lang)

    return {k: v for k, v in result.items() if v}


def _as_list(v):
    # 純量轉單元素 list；None/"" 視為無值（供 legacy 轉換共用）
    if v is None or v == "":
        return []
    return list(v) if isinstance(v, list) else [v]


def legacy_rule_to_preselected(rule, dir_prefix, exclude=False):
    """把規則 dict 轉為 pick_objects 用的 preselected dict，供 traffic/bandwidth 精靈編輯既有規則回填。

    同時支援兩種來源：舊版純量 key（src_label/ex_src_ip 等）與既有 4c flat key
    （src_labels/src_iplists/... 等）——後者直接照鍵餵，前者轉為單元素 list。
    dir_prefix 固定傳 "src"/"dst"；exclude=True 時轉換 ex_src/ex_dst 方向。
    """
    if not rule:
        return None
    prefix = f"ex_{dir_prefix}" if exclude else dir_prefix

    result = {}
    labels = _as_list(rule.get(f"{prefix}_labels", rule.get(f"{prefix}_label")))
    if labels:
        result["labels"] = labels
    iplists = _as_list(rule.get(f"{prefix}_iplists"))
    if iplists:
        result["iplists"] = iplists
    workloads = _as_list(rule.get(f"{prefix}_workloads"))
    if workloads:
        result["workloads"] = workloads
    ip_key = f"{dir_prefix}_ip_in" if not exclude else f"ex_{dir_prefix}_ip"
    ips = _as_list(rule.get(ip_key))
    if ips:
        result["ips"] = ips
    return result or None


_ANY_FILTER_KEYS = (
    "any_label", "any_ip", "any_iplist", "any_workload",
    "ex_any_label", "ex_any_ip", "ex_any_iplist", "ex_any_workload",
)


def preserve_any_filters(edit_rule):
    """回傳 edit_rule 中 8 個 either-side（any_*/ex_any_*）filter key 的非空子集。

    CLI 精靈的 picker 無任一側槽位可編輯這些 GUI FilterBar 專屬 key，故編輯時
    應原樣保留、而非隨 new_rule 從零重建而靜默消失。呼叫端於 new_rule.update(...)。
    """
    if not edit_rule:
        return {}
    return {k: edit_rule[k] for k in _ANY_FILTER_KEYS if edit_rule.get(k)}


def picked_to_flat_filters(picked, dir_prefix, exclude=False):
    """把 pick_objects 回傳的 dict 轉為要合併進規則的 4c flat filter key（只含非空）。"""
    prefix = f"ex_{dir_prefix}" if exclude else dir_prefix
    out = {}
    if picked.get("labels"):
        out[f"{prefix}_labels"] = picked["labels"]
    if picked.get("iplists"):
        out[f"{prefix}_iplists"] = picked["iplists"]
    if picked.get("workloads"):
        out[f"{prefix}_workloads"] = picked["workloads"]
    if picked.get("ips"):
        ip_key = f"{dir_prefix}_ip_in" if not exclude else f"ex_{dir_prefix}_ip"
        out[ip_key] = picked["ips"]
    return out


def picked_to_service_filters(picked, exclude=False):
    """pick_objects 回傳 dict → 無方向的 service/port filter key（只含非空）。"""
    prefix = "ex_" if exclude else ""
    out = {}
    if picked.get("services"):
        out[f"{prefix}services"] = picked["services"]
    if picked.get("ports"):
        out[f"{prefix}ports"] = picked["ports"]
    return out


def legacy_service_to_preselected(rule, exclude=False):
    """規則 dict → service/port 類別的 preselected（新 list key 優先，
    舊 scalar port/proto/ex_port 轉 token；零遷移讀取相容）。"""
    if not rule:
        return None
    result = {}
    if exclude:
        if rule.get("ex_services"):
            result["services"] = _as_list(rule["ex_services"])
        ports = _as_list(rule.get("ex_ports"))
        if not ports and rule.get("ex_port"):
            ports = [str(rule["ex_port"])]
        if ports:
            result["ports"] = ports
        return result or None
    if rule.get("services"):
        result["services"] = _as_list(rule["services"])
    ports = _as_list(rule.get("ports"))
    if not ports and rule.get("port"):
        proto_name = {6: "tcp", 17: "udp"}.get(rule.get("proto"))
        ports = [f"{rule['port']}/{proto_name}" if proto_name else str(rule["port"])]
    if ports:
        result["ports"] = ports
    return result or None
