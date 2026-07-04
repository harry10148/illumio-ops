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

_CAT_ORDER = ("label", "label_group", "iplist", "workload", "ip")

# 類別選單顯示名稱：與現有技術詞彙一致（中英文皆保留原文，同 gui_fb_cat_* 慣例）
_CAT_TITLES = {
    "label": "Label",
    "label_group": "Label Group",
    "iplist": "IP List",
    "workload": "Workload",
    "ip": "IP/CIDR (manual)",
}

_DONE = "__done__"


def _interactive_ok():
    # 與 _render.py 同慣例：非 TTY（pipe/CI/測試）不走 questionary
    return sys.stdin.isatty() and sys.stdout.isatty()


def _valid_ip_or_cidr(text):
    try:
        if "/" in text:
            ipaddress.ip_network(text, strict=False)
        else:
            ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _load_candidates(api, cat):
    # 回傳 [(display, value)]；value 是要存進 filter 的字串（label 用 key=value、物件用 href、label_group 用名稱）
    if cat == "label":
        return [(f"{l['key']}={l['value']}", f"{l['key']}={l['value']}") for l in api.get_all_labels()]
    if cat == "iplist":
        return [(ipl["name"], ipl["href"]) for ipl in api.get_ip_lists()]
    if cat == "label_group":
        return [(g["name"], g["name"]) for g in api.get_label_groups()]
    if cat == "workload":
        return [(f"{w.get('name') or w.get('hostname')} ({w.get('hostname', '')})", w["href"])
                for w in api.search_workloads({"max_results": 200})]
    return []


_CAT_RESULT_KEY = {"label": "labels", "label_group": "label_groups",
                   "iplist": "iplists", "workload": "workloads", "ip": "ips"}


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
        raw = input(prompt)
        if not raw.strip():
            continue
        values = _split_values(raw)
        if cat == "ip":
            values = [v for v in values if _valid_ip_or_cidr(v)]
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
    for v in values:
        _append_unique(result, key, v)


def _pick_tty(api, cats, result, title, lang):
    choices = [questionary.Choice(title=_CAT_TITLES[c], value=c) for c in _CAT_ORDER if c in cats]
    choices.append(questionary.Choice(title=t("cli_pick_done", lang=lang, default="-- Done --"), value=_DONE))

    while True:
        selection = questionary.select(
            t("cli_pick_category", lang=lang, title=title, default="Select object category for '{title}':"),
            choices=choices,
            style=_STYLE,
        ).unsafe_ask()
        if selection is None or selection == _DONE:
            break

        cat = selection
        key = _CAT_RESULT_KEY[cat]

        if cat == "ip":
            _manual_text_entry(cat, key, result, lang)
        else:
            try:
                candidates = _load_candidates(api, cat)
            except Exception:
                print(t("cli_pick_offline_hint", lang=lang, cat=cat,
                        default="PCE unreachable while loading '{cat}' candidates; falling back to manual input."))
                _manual_text_entry(cat, key, result, lang)
            else:
                if not candidates:
                    print(t("cli_pick_offline_hint", lang=lang, cat=cat,
                            default="No '{cat}' candidates found; falling back to manual input."))
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


def pick_objects(api, cats, title, preselected=None, lang=None):
    """兩段式物件選擇器：TTY 走 questionary（類別 → autocomplete/手動），非 TTY 走 input() 降級。

    回傳只含非空類別的 dict，key 為 labels/label_groups/iplists/workloads/ips。
    """
    result = dict(preselected or {})

    if _interactive_ok():
        _pick_tty(api, cats, result, title, lang)
    else:
        _pick_non_tty(api, cats, result, lang)

    return {k: v for k, v in result.items() if v}
