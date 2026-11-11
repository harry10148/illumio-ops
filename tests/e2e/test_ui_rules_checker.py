"""The rule checker itself: each rule catches a planted defect and passes the clean case. Without this, a walk that
finds nothing proves nothing."""
import pytest

from tests.e2e import ui_rules

sync_api = pytest.importorskip("playwright.sync_api")


def _main(body: str) -> str:
    return f"<!doctype html><body style='margin:0;font:14px/20px sans-serif'><main>{body}</main></body>"


_FILL = f"background:{ui_rules.PRIMARY_FILL}"
_BTN = "font-size:14px"

BAD = {
    "one_primary": _main(f"<div class='card'><button style='{_FILL};{_BTN}'>Save</button>"
                         f"<button style='{_FILL};{_BTN}'>Apply</button></div>"),
    "styled_checkbox": _main("<input type='checkbox'>"),
    "tag_not_button": _main("<span class='tag' style='border:1px solid #999'>recorded only</span>"),
    "cards_apart": _main("<div class='card' style='height:40px'>a</div><div class='card' style='height:40px'>b</div>"),
    # the fleet page as measured on the test box: the action bar ends at 467px, the table head starts at 455px
    "no_overlap": _main(f"<button style='position:absolute;top:433px;left:40px;height:34px;width:120px;{_BTN}'>Change</button>"
                        "<table style='position:absolute;top:455px;left:0;width:600px'><thead><tr>"
                        "<th style='height:49px'>Host</th></tr></thead></table>"),
    "header_one_line": _main("<table><thead><tr><th style='width:30px;word-break:break-all'>Severity level</th></tr></thead></table>"),
    "no_overflow_x": _main("<div style='width:3000px'>wide</div>"),
    "button_font": _main("<button style='font-size:13px'>Run</button>"),
    "link_not_accent": _main(f"<a href='#' style='color:{ui_rules.ACCENT_TEXT}'>a host</a>"),
    # the report schedule row as seen on the test box: Run now, Edit and Delete with nothing between them
    "buttons_apart": _main(f"<td><button style='border:1px solid #999;{_BTN}'>Run now</button>"
                           f"<button style='border:1px solid #999;{_BTN}'>Edit</button></td>"),
}

GOOD = {
    "one_primary": _main(f"<div class='card'><button style='{_FILL};{_BTN}'>Save</button><button style='{_BTN}'>Cancel</button></div>"
                         f"<div class='card' style='margin-top:16px'><button style='{_FILL};{_BTN}'>Apply</button></div>"),
    "styled_checkbox": _main("<input type='checkbox' style='appearance:none;width:16px;height:16px;border:1px solid #999'>"),
    "tag_not_button": _main("<span class='tag' style='background:#eee;white-space:nowrap'>recorded only</span>"),
    "cards_apart": _main("<div class='card' style='height:40px'>a</div>"
                         "<div class='card' style='height:40px;margin-top:16px'>b</div>"),
    "no_overlap": _main(f"<button style='position:absolute;top:400px;left:40px;height:34px;width:120px;{_BTN}'>Change</button>"
                        "<table style='position:absolute;top:455px;left:0;width:600px'><thead><tr>"
                        "<th style='height:49px'>Host</th></tr></thead></table>"),
    "header_one_line": _main("<table><thead><tr><th style='white-space:nowrap'>Severity level</th></tr></thead></table>"),
    "no_overflow_x": _main("<div style='max-width:100%'>fits</div>"),
    "button_font": _main(f"<button style='{_BTN}'>Run</button><div data-seg><button style='font-size:12px'>All</button></div>"),
    "link_not_accent": _main("<a href='#' style='color:rgb(49, 54, 56)'>a host</a>"),
    "buttons_apart": _main(f"<td><button style='border:1px solid #999;{_BTN}'>Run now</button>"
                           f"<button style='border:1px solid #999;margin-left:6px;{_BTN}'>Edit</button></td>"
                           f"<div data-seg><button style='border:1px solid #999;{_BTN}'>All</button>"
                           f"<button style='border:1px solid #999;{_BTN}'>New</button></div>"),
}


def test_every_rule_has_both_cases():
    assert set(BAD) == set(GOOD) == set(ui_rules.RULES)


@pytest.mark.parametrize("rule", ui_rules.RULES)
def test_each_rule_catches_its_defect_and_passes_the_clean_case(rule, context):
    page = context.new_page()
    page.set_content(BAD[rule])
    assert rule in ui_rules.violations(page), f"{rule} did not catch its planted defect"
    page.set_content(GOOD[rule])
    assert rule not in ui_rules.violations(page), ui_rules.violations(page).get(rule)


def test_what_a_closed_disclosure_holds_is_not_measured(context):
    page = context.new_page()
    page.set_content(_main("<details><summary>What is this</summary><input type='checkbox'></details>"))
    assert ui_rules.violations(page) == {}


def test_a_dialog_over_the_page_is_not_an_overlap(context):
    page = context.new_page()
    page.set_content(_main(f"<button style='position:absolute;top:10px;left:10px;width:100px;height:34px;{_BTN}'>Under</button>"
                           f"<div role='dialog' style='position:absolute;top:0;left:0'><button style='width:100px;height:34px;{_BTN}'>"
                           "Over</button></div>"))
    assert "no_overlap" not in ui_rules.violations(page)
