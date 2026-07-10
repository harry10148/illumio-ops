"""CLI wizard for adding or editing bandwidth/volume alert rules."""
from __future__ import annotations
import os
import datetime

from src.config import ConfigManager
from src.i18n import t
from src.rule_id import gen_rule_id
from src.utils import Colors, safe_input, draw_panel, get_last_input_action
from src.cli.menus._helpers import (
    _menu_hints,
    _wizard_step,
    _wizard_confirm,
    _empty_uses_default,
)
from src.cli.object_picker import (
    pick_objects,
    legacy_rule_to_preselected,
    picked_to_flat_filters,
    preserve_any_filters,
    legacy_service_to_preselected,
    picked_to_service_filters,
)

_PICK_CATS = ("label", "iplist", "workload", "ip")  # 4c 規則不支援 label_group，故不含


def _pick_or_cancel(api, cats, title, preselected=None, lang=None):
    """包 pick_objects：TTY 下 questionary 的 unsafe_ask() 遇 Ctrl-C 會拋
    KeyboardInterrupt（BaseException），沒有本地 except 就會穿透精靈直達
    main.py 頂層 handler、整個 CLI 結束。這裡接住並回傳 None，鏡射舊版
    safe_input(allow_cancel=True) 遇 Ctrl-C 的取消語意（見 _render.py:256-258：
    接住、不印訊息、回 None），呼叫端一律以 `if picked is None: return` 退回選單。
    """
    try:
        return pick_objects(api, cats=cats, title=title, preselected=preselected, lang=lang)
    except KeyboardInterrupt:
        return None


def _fmt_picked(picked):
    # 精靈回顧摘要用：把 pick_objects 回傳 dict 攤平成一行文字
    parts = [f"{k}={','.join(v)}" for k in ("labels", "iplists", "workloads", "ips", "services", "ports")
             for v in [picked.get(k, [])] if v]
    return "; ".join(parts) if parts else "-"


def add_bandwidth_volume_menu(cm: ConfigManager, edit_rule=None) -> None:
    os.system("cls" if os.name == "nt" else "clear")

    def should_restart_flow():
        return get_last_input_action() == "cancel"

    title = (
        t("menu_add_bw_vol_title")
        if not edit_rule
        else t("modify_rule", name=edit_rule.get('name', ''))
    )
    draw_panel(
        title,
        _menu_hints("Rules > Bandwidth/Volume"),
    )
    _wizard_step(1, 5, t("wiz_basic_setup"))
    print("")

    def_name = edit_rule.get("name", "") if edit_rule else ""
    name = safe_input(t("rule_name_bw"), str, allow_cancel=True, hint=def_name)
    if name is None:
        if should_restart_flow():
            add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
        return
    if name == "":
        name = def_name
    if not name:
        return

    _wizard_step(2, 5, t("wiz_select_metric"))
    print(f"\n{Colors.CYAN}{t('step_1_metric')}{Colors.ENDC}")
    print(t("metric_1"))
    print(t("metric_2"))

    def_msel = (
        1
        if edit_rule and edit_rule.get("type") == "bandwidth"
        else (2 if edit_rule else None)
    )
    m_sel = safe_input(
        t("please_select"), int, range(0, 3), allow_cancel=True, hint=str(def_msel)
    )
    if m_sel is None:
        if _empty_uses_default(def_msel):
            m_sel = def_msel
        else:
            if should_restart_flow():
                add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
            return
    if not m_sel or m_sel not in (1, 2):
        return

    rtype = "bandwidth" if m_sel == 1 else "volume"
    unit_prompt = "Mbps" if m_sel == 1 else "MB"

    _wizard_step(3, 5, t("wiz_filters"))
    print(f"\n{Colors.CYAN}{t('step_2_filters')}{Colors.ENDC}")
    print(f"{Colors.DARK_GRAY}{t('hint_return')}{Colors.ENDC}")

    from src.api_client import ApiClient

    api = ApiClient(cm)
    svc_picked = _pick_or_cancel(
        api, cats=("service", "port"), title=t("wiz_svc_include"),
        preselected=legacy_service_to_preselected(edit_rule) if edit_rule else None,
    )
    if svc_picked is None:
        return
    ex_svc_picked = _pick_or_cancel(
        api, cats=("service", "port"), title=t("wiz_svc_exclude"),
        preselected=legacy_service_to_preselected(edit_rule, exclude=True) if edit_rule else None,
    )
    if ex_svc_picked is None:
        return

    src_picked = _pick_or_cancel(
        api, cats=_PICK_CATS, title=t("src_input"),
        preselected=legacy_rule_to_preselected(edit_rule, "src", exclude=False) if edit_rule else None,
    )
    if src_picked is None:
        return
    dst_picked = _pick_or_cancel(
        api, cats=_PICK_CATS, title=t("dst_input"),
        preselected=legacy_rule_to_preselected(edit_rule, "dst", exclude=False) if edit_rule else None,
    )
    if dst_picked is None:
        return

    _wizard_step(4, 5, t("wiz_threshold"))
    print(f"\n{Colors.CYAN}{t('step_3_threshold')}{Colors.ENDC}")
    def_th = edit_rule.get("threshold_count", "") if edit_rule else ""
    th_in = safe_input(
        t("trigger_threshold_unit", unit=unit_prompt),
        float,
        allow_cancel=True,
        hint=str(def_th) if def_th else "",
        help_text=t("def_traffic_vol"),
    )
    if th_in is None:
        if _empty_uses_default(def_th):
            th_in = float(def_th)
        else:
            if should_restart_flow():
                add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
            return
    th = float(th_in)
    if th is None:
        return

    def_win = edit_rule.get("threshold_window", 5) if edit_rule else 5
    win_in = safe_input(
        t("time_window_mins")
        .replace("[{win}]", "")
        .replace("[Default: 5]", "")
        .strip(),
        int,
        allow_cancel=True,
        hint=str(def_win),
    )
    if win_in is None:
        if _empty_uses_default(def_win):
            win_in = def_win
        else:
            if should_restart_flow():
                add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
            return
    win = win_in

    def_cd = edit_rule.get("cooldown_minutes", win) if edit_rule else win
    cd_in = safe_input(
        t("cooldown_mins").format(win=def_win),
        int,
        allow_cancel=True,
        hint=str(def_cd),
        help_text=t("def_cooldown"),
    )
    if cd_in is None:
        if _empty_uses_default(def_cd):
            cd_in = def_cd
        else:
            if should_restart_flow():
                add_bandwidth_volume_menu(cm, edit_rule=edit_rule)
            return
    cd = cd_in

    print(f"\n{Colors.CYAN}{t('excludes_optional')}{Colors.ENDC}")

    ex_src_picked = _pick_or_cancel(
        api, cats=_PICK_CATS, title=t("ex_src_input"),
        preselected=legacy_rule_to_preselected(edit_rule, "src", exclude=True) if edit_rule else None,
    )
    if ex_src_picked is None:
        return
    ex_dst_picked = _pick_or_cancel(
        api, cats=_PICK_CATS, title=t("ex_dst_input"),
        preselected=legacy_rule_to_preselected(edit_rule, "dst", exclude=True) if edit_rule else None,
    )
    if ex_dst_picked is None:
        return

    rid = edit_rule.get("id", gen_rule_id()) if edit_rule else gen_rule_id()
    preserved_any = preserve_any_filters(edit_rule)

    _wizard_step(5, 5, t("wiz_review_save"))
    summary = [
        f"{t('sum_type')}: {rtype}",
        f"{t('sum_name')}: {name}",
        f"{t('sum_unit_threshold')}: {unit_prompt} / {th}",
        f"{t('sum_port_proto')}: {_fmt_picked(svc_picked)}",
        f"{t('sum_src_dst')}: {_fmt_picked(src_picked)} -> {_fmt_picked(dst_picked)}",
        f"{t('sum_window_cooldown')}: {win}m / {cd}m",
        f"{t('sum_exclude')}: svc={_fmt_picked(ex_svc_picked)}, src={_fmt_picked(ex_src_picked)}, dst={_fmt_picked(ex_dst_picked)}",
    ]
    if preserved_any:
        summary.append(t("cli_pick_any_preserved", keys=", ".join(preserved_any.keys())))
    if not _wizard_confirm(summary):
        return

    new_rule = {
        "id": rid,
        "type": rtype,
        "name": name,
        "pd": edit_rule.get("pd", -1) if edit_rule else -1,
        "threshold_type": "immediate",
        "threshold_count": th,
        "threshold_window": win,
        "cooldown_minutes": cd,
        "desc": t("alert_desc", type=rtype, threshold=th, unit=unit_prompt),
        "rec": t("check_network"),
    }
    new_rule.update(picked_to_flat_filters(src_picked, "src", exclude=False))
    new_rule.update(picked_to_flat_filters(dst_picked, "dst", exclude=False))
    new_rule.update(picked_to_flat_filters(ex_src_picked, "src", exclude=True))
    new_rule.update(picked_to_flat_filters(ex_dst_picked, "dst", exclude=True))
    new_rule.update(picked_to_service_filters(svc_picked, exclude=False))
    new_rule.update(picked_to_service_filters(ex_svc_picked, exclude=True))
    new_rule.update(preserved_any)
    cm.add_or_update_rule(new_rule)
    input(
        f"\n{Colors.CYAN}[?]{Colors.ENDC} {t('rule_saved')} {Colors.GREEN}❯{Colors.ENDC} "
    )
