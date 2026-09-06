"""互動選單的統一畫面 chrome（Phase 2C，cli-flows.md DD-1/WZ-3/§3.5）。

區數從六變成五（Phase 3C：告警＋自動化併為「規則」，與 GUI 同一組區域），
chrome 本身與區數無關，這裡不再寫死數字。

三個表面：`menu_screen` 是每個選單與精靈共用的框（麵包屑、可選的健康列、
快捷鍵說明），`confirm_box` 是破壞性動作的確認框，`clear_screen` 是兩者
共用的清畫面。全部只負責畫，不持有狀態、不決定流程。
"""
from __future__ import annotations

from src.i18n import t
from src.cli._render import Colors, draw_panel, safe_input


def clear_screen() -> None:
    """POSIX escape sequence，不走 os.system（a8720452 的既有裁決）。"""
    print("\033[2J\033[H", end="", flush=True)


def menu_screen(path: str, lines: list, health: str | None = None,
                title: str = "Illumio PCE Ops") -> None:
    """清畫面＋統一標頭框：麵包屑＋（可選）健康列＋快捷鍵＋內容。

    `lines` 為空時不畫分隔線——`_wizard_step` 會以空清單呼叫本函式，只為了
    重畫標頭，此時一條懸空的分隔線下面什麼都沒有。
    """
    clear_screen()
    header: list = [f"{Colors.DARK_GRAY}{t('cli_path_label', path=path)}{Colors.ENDC}"]
    if health:
        header.append(health)
    header.append(f"{Colors.DARK_GRAY}{t('cli_shortcuts_compact')}{Colors.ENDC}")
    body = header + (["-"] + list(lines) if lines else [])
    draw_panel(title, body)


def confirm_box(title: str, impact_lines: list[str], ok_label: str) -> bool:
    """破壞性動作確認框（spec 2.3）：標題＋條列後果＋[N]/[Y]，預設 N。

    只有兩態。需要「做／不做／取消整筆」三態的流程（例如換 PCE 前問要不要
    清快取）不可用它——那會把其中一條路徑摺掉。
    """
    body = list(impact_lines) + [
        "-",
        f"{t('cli_confirm_cancel')}      [Y] {ok_label}",
    ]
    draw_panel(title, body)
    ans = safe_input(t("cli_confirm_prompt"), str, allow_cancel=False)
    if not ans:
        return False
    # "y"/"yes" always work; each language adds its own affirmative through
    # cli_confirm_yes (zh: 是). Keeping that character in the source would be
    # a hardcoded string in a non-i18n file, which the i18n audit rejects.
    accepted = {"y", "yes", (t("cli_confirm_yes") or "").strip().lower()}
    return ans.strip().lower() in (accepted - {""})
