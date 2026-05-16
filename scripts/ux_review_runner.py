"""UX review harness — runs flows on the test machine and saves screenshots.

Usage:
    python ux_review_runner.py <flow> [args...]

Flows:
    login                 -> log in and dump dashboard
    nav <slug>            -> click main nav <slug>, snapshot
    page <route>          -> visit /<route> after login
    settings_tour         -> tour every settings panel
    reports_traffic       -> open Reports section, snapshot
    generate_traffic      -> kick off a traffic report
    full_capture          -> walk every visible top-level tab
"""
from __future__ import annotations

import sys
import json
import time
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, Page, expect

import os

BASE = os.environ.get("ILLUMIO_OPS_E2E_BASE_URL", "https://127.0.0.1:5001")
USER = os.environ.get("ILLUMIO_OPS_E2E_USER", "")
PASS = os.environ.get("ILLUMIO_OPS_E2E_PASSWORD", "")
EXE = os.environ.get("ILLUMIO_OPS_E2E_CHROME", "")
if not (USER and PASS):
    raise SystemExit(
        "ux_review_runner: set ILLUMIO_OPS_E2E_USER and ILLUMIO_OPS_E2E_PASSWORD "
        "(also ILLUMIO_OPS_E2E_BASE_URL / ILLUMIO_OPS_E2E_CHROME as needed)."
    )
SHOTS = Path("/home/harry/rd/illumio-ops/docs/ux-review-2026-05-14/screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)
STATE = Path("/tmp/illumio_ops_ux_state.json")


def login(page: Page) -> None:
    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.fill("input[name=username], input#username", USER)
    page.fill("input[name=password], input#password", PASS)
    page.click("button[type=submit], button:has-text('Sign in'), button:has-text('登入')")
    page.wait_for_load_state("networkidle", timeout=20000)


def shot(page: Page, name: str, full: bool = True) -> str:
    p = SHOTS / f"{name}.png"
    page.screenshot(path=str(p), full_page=full)
    return str(p)


def dump_console(page: Page, slot: list):
    page.on("console", lambda msg: slot.append(f"{msg.type}: {msg.text}"))
    page.on("pageerror", lambda err: slot.append(f"pageerror: {err}"))


def run(flow: str, *args):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=EXE,
            headless=True,
            args=["--ignore-certificate-errors", "--no-sandbox"],
        )
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
        if STATE.exists():
            try:
                ctx = browser.new_context(
                    ignore_https_errors=True,
                    viewport={"width": 1440, "height": 900},
                    storage_state=str(STATE),
                )
            except Exception:
                pass
        page = ctx.new_page()
        console_log: list = []
        dump_console(page, console_log)

        if flow == "login_page":
            # capture pre-login pages (login + first-login-must-change-pw etc.)
            ctx2 = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
            p2 = ctx2.new_page()
            p2.goto(BASE + "/login", wait_until="domcontentloaded")
            p2.wait_for_load_state("networkidle", timeout=10000)
            shot(p2, "00_login_empty")
            # invalid login attempt for error UI
            p2.fill("input[name=username], input#username", "illumio")
            p2.fill("input[name=password], input#password", "wrong-pass")
            p2.click("button[type=submit]")
            p2.wait_for_timeout(2000)
            shot(p2, "00_login_invalid")
            ctx2.close()
        elif flow == "login":
            login(page)
            ctx.storage_state(path=str(STATE))
            print("dashboard URL:", page.url)
            shot(page, "01_dashboard")
        elif flow == "page":
            route = args[0] if args else "/"
            page.goto(urljoin(BASE, route), wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            shot(page, f"page_{route.strip('/').replace('/', '_') or 'root'}")
            print("title:", page.title())
        elif flow == "nav":
            slug = args[0]
            name = args[1] if len(args) > 1 else slug
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            # try nav button click via data attribute
            try:
                page.click(f"[data-section='{slug}'], [data-page='{slug}'], a[href='#{slug}'], a[href='/{slug}']", timeout=4000)
            except Exception:
                page.evaluate(f"location.hash='#{slug}'")
            page.wait_for_timeout(2000)
            shot(page, f"nav_{name}")
        elif flow == "snapshot":
            label = args[0] if args else "ad-hoc"
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            # Dump full DOM outerHTML for static analysis
            html_path = SHOTS.parent / f"dom_{label}.html"
            html_path.write_text(page.content())
            shot(page, f"snap_{label}")
        elif flow == "tab":
            tabname = args[0]
            label = args[1] if len(args) > 1 else tabname
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            # close any toasts/modals
            try:
                page.evaluate("document.querySelectorAll('.toast, .modal-backdrop, [role=dialog] .close, .toast .close').forEach(el => el.click && el.click())")
            except Exception:
                pass
            page.click(f"button.tab[data-tab='{tabname}']", timeout=5000)
            page.wait_for_timeout(2500)
            shot(page, f"tab_{label}")
            print("tab", tabname, "captured")
        elif flow == "subnav":
            tabname = args[0]
            sub = args[1]
            label = args[2] if len(args) > 2 else f"{tabname}_{sub}"
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.click(f"button.tab[data-tab='{tabname}']", timeout=5000)
            page.wait_for_timeout(800)
            try:
                page.click(f"#{sub}", timeout=4000)
            except Exception:
                try:
                    page.click(f"button.sub-nav-btn:has-text('{sub}')", timeout=4000)
                except Exception as e:
                    print("subnav click failed:", e)
            page.wait_for_timeout(2200)
            shot(page, f"sub_{label}")
        elif flow == "section":
            # scroll to a sub-section in current tab by selector or text
            tab = args[0]
            selector = args[1]
            label = args[2] if len(args) > 2 else f"{tab}_{selector}"
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.click(f"button.tab[data-tab='{tab}']", timeout=5000)
            page.wait_for_timeout(1200)
            try:
                page.evaluate(f"document.querySelector(`{selector}`)?.scrollIntoView({{block:'start'}})")
                page.wait_for_timeout(700)
            except Exception:
                pass
            shot(page, f"section_{label}", full=False)
        elif flow == "settings_scroll":
            # scroll thru settings by anchors
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.click("button.tab[data-tab='settings']", timeout=5000)
            page.wait_for_timeout(1500)
            anchors = page.evaluate(
                """() => {
                    const sec = [];
                    document.querySelectorAll('#settings h2, #settings h3, #settings details > summary, #settings .section-title, #settings .card-title').forEach(el => {
                        sec.push({tag: el.tagName, text: el.innerText.trim().slice(0,80), id: el.id || el.closest('[id]')?.id || null});
                    });
                    return sec;
                }"""
            )
            print(json.dumps(anchors, ensure_ascii=False, indent=2))
        elif flow == "visible_floats":
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            floats = page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll('body *').forEach(el => {
                        const cs = getComputedStyle(el);
                        if (cs.position !== 'fixed' && cs.position !== 'sticky') return;
                        const r = el.getBoundingClientRect();
                        if (r.width<30 || r.height<20) return;
                        out.push({
                          tag: el.tagName, id: el.id || null,
                          cls: (el.className && el.className.toString && el.className.toString().slice(0,120)) || null,
                          rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
                          z: cs.zIndex, bg: cs.background.slice(0,40),
                          text: (el.innerText||'').trim().slice(0,140),
                        });
                    });
                    return out.slice(0,30);
                }"""
            )
            print(json.dumps(floats, ensure_ascii=False, indent=2))
        elif flow == "toast":
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            toast = page.evaluate(
                """() => {
                    const items = [];
                    document.querySelectorAll('.toast, .modal, .dialog, [role=dialog], [role=alert], .alert-banner').forEach(el => {
                        const r = el.getBoundingClientRect();
                        items.push({
                          cls: el.className && el.className.toString && el.className.toString().slice(0,140),
                          tag: el.tagName,
                          visible: r.width>0 && r.height>0 && getComputedStyle(el).visibility !== 'hidden',
                          rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
                          text: (el.innerText||'').slice(0,200),
                        });
                    });
                    return items;
                }"""
            )
            print(json.dumps(toast, ensure_ascii=False, indent=2))
        elif flow == "tour":
            tabs = [
                ("dashboard", "01_overview"),
                ("traffic-workload", "02_traffic"),
                ("events", "03_events"),
                ("rules", "04_rules"),
                ("reports", "05_reports"),
                ("rule-scheduler", "06_rule_scheduler"),
                ("integrations", "07_integrations"),
                ("settings", "08_settings"),
            ]
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            # hide bulk action bar that appears on dashboard with 0 selected
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            for tab, label in tabs:
                try:
                    page.click(f"button.tab[data-tab='{tab}']", timeout=5000)
                    page.wait_for_timeout(2500)
                    shot(page, f"clean_{label}")
                    print("captured:", tab)
                except Exception as e:
                    print("FAIL", tab, e)
        elif flow == "viewport_tour":
            # capture only above-the-fold viewport per tab, no full page
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            for tab, label in [
                ("dashboard", "01_dashboard_fold"),
                ("traffic-workload", "02_traffic_fold"),
                ("events", "03_events_fold"),
                ("rules", "04_rules_fold"),
                ("reports", "05_reports_fold"),
                ("rule-scheduler", "06_scheduler_fold"),
                ("integrations", "07_integrations_fold"),
                ("settings", "08_settings_fold"),
            ]:
                try:
                    page.click(f"button.tab[data-tab='{tab}']", timeout=5000)
                    page.wait_for_timeout(2500)
                    page.evaluate("window.scrollTo(0,0)")
                    shot(page, f"vp_{label}", full=False)
                    print("captured", tab)
                except Exception as e:
                    print("FAIL", tab, e)
        elif flow == "quarantine_search":
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            # Quarantine likely under traffic-workload -> Workload search
            page.click("button.tab[data-tab='traffic-workload']", timeout=5000)
            page.wait_for_timeout(1000)
            page.click("#qbtn-workloads", timeout=4000)
            page.wait_for_timeout(1500)
            shot(page, "workload_search_panel", full=False)
            # try entering an IP
            try:
                page.fill("input[type=text], input[type=search]", "10.10.10.1")
                page.wait_for_timeout(500)
                page.click("text=搜尋", timeout=3000)
                page.wait_for_timeout(2500)
                shot(page, "workload_search_results", full=False)
            except Exception as e:
                print("workload search fail:", e)
        elif flow == "event_viewer":
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            page.click("button.tab[data-tab='events']", timeout=5000)
            page.wait_for_timeout(2500)
            shot(page, "events_full", full=True)
            # click first event row
            try:
                page.click("tr:nth-child(2)", timeout=4000)
                page.wait_for_timeout(1500)
                shot(page, "event_detail", full=False)
            except Exception:
                pass
        elif flow == "rule_detail":
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            page.click("button.tab[data-tab='rules']", timeout=5000)
            page.wait_for_timeout(2500)
            shot(page, "rules_full", full=True)
            # click first rule row
            try:
                page.click("tbody tr:nth-child(2)", timeout=4000)
                page.wait_for_timeout(1500)
                shot(page, "rule_detail", full=False)
            except Exception:
                pass
        elif flow == "lang_switch":
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            page.click("button.tab[data-tab='settings']", timeout=5000)
            page.wait_for_timeout(1500)
            # find English radio
            try:
                page.click("input[type=radio][value=en], label:has-text('ENGLISH')", timeout=3000)
                page.wait_for_timeout(800)
                # click save
                page.click("text=儲存所有設定", timeout=3000)
                page.wait_for_timeout(2500)
                shot(page, "lang_en_after_save", full=False)
                # switch back
                page.click("button.tab[data-tab='dashboard']", timeout=3000)
                page.wait_for_timeout(2500)
                shot(page, "dashboard_en", full=False)
            except Exception as e:
                print("lang switch fail:", e)
        elif flow == "view_report":
            substr = args[0]
            label = args[1] if len(args) > 1 else substr
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            page.click("button.tab[data-tab='reports']", timeout=5000)
            page.wait_for_timeout(2000)
            # find first row whose filename contains substr and click "檢視"
            page.evaluate(
                f"""() => {{
                    const rows = document.querySelectorAll('tr, .report-row, .card, li');
                    for (const r of rows) {{
                        if ((r.innerText || '').includes('{substr}')) {{
                            const btn = r.querySelector('button:contains("檢視"), button[onclick*=view], a:has(text="檢視")') ||
                                Array.from(r.querySelectorAll('button, a')).find(b => (b.innerText||'').trim() === '檢視');
                            if (btn) {{ btn.click(); return; }}
                        }}
                    }}
                }}"""
            )
            page.wait_for_timeout(3000)
            shot(page, f"viewed_{label}", full=True)
            # also dump report URL
            print("url:", page.url)
        elif flow == "raw_report":
            # navigate directly to /reports/<filename>
            filename = args[0]
            label = args[1] if len(args) > 1 else filename[:20]
            page.goto(BASE + f"/reports/{filename}", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            shot(page, f"raw_{label}", full=True)
        elif flow == "report_scroll":
            filename = args[0]
            label = args[1] if len(args) > 1 else filename[:20]
            page.goto(BASE + f"/reports/{filename}", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            # capture viewport at 4 scroll positions
            doc_h = page.evaluate("document.body.scrollHeight")
            print("doc height:", doc_h)
            positions = [0, doc_h // 4, doc_h // 2, doc_h * 3 // 4]
            for i, y in enumerate(positions):
                page.evaluate(f"window.scrollTo(0,{y})")
                page.wait_for_timeout(700)
                shot(page, f"rep_{label}_{i:02d}_y{y}", full=False)
        elif flow == "report_toc":
            filename = args[0]
            page.goto(BASE + f"/reports/{filename}", wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            toc = page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll('h1, h2, h3, .toc a, .nav a').forEach(el => {
                        const t = (el.innerText||'').trim();
                        if (t && t.length < 120) out.push({tag: el.tagName, text: t});
                    });
                    return out.slice(0, 80);
                }"""
            )
            print(json.dumps(toc, ensure_ascii=False, indent=2))
        elif flow == "list_reports":
            page.goto(BASE + "/api/reports", wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            print(page.evaluate("document.body.innerText"))
        elif flow == "report_run":
            kind = args[0]
            label = args[1] if len(args) > 1 else kind
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            page.click("button.tab[data-tab='reports']", timeout=5000)
            page.wait_for_timeout(1500)
            label_text = {
                "traffic": "流量報表",
                "audit": "稽核報表",
                "ven_status": "VEN 狀態報表",
                "policy_usage": "Policy 使用報表",
            }[kind]
            page.click(f"button:has-text('{label_text}')", timeout=5000)
            page.wait_for_timeout(1500)
            # click 產生
            page.click("button:has-text('產生')", timeout=5000)
            print("submitted", kind)
            page.wait_for_timeout(45000)
            shot(page, f"report_{label}_after_submit", full=True)
        elif flow == "report_gen":
            kind = args[0]  # traffic / audit / ven_status / policy_usage
            label = args[1] if len(args) > 1 else kind
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            page.click("button.tab[data-tab='reports']", timeout=5000)
            page.wait_for_timeout(1500)
            # open the relevant report dialog
            label_text = {
                "traffic": "流量報表",
                "audit": "稽核報表",
                "ven_status": "VEN 狀態報表",
                "policy_usage": "Policy 使用報表",
            }[kind]
            try:
                page.click(f"button:has-text('{label_text}')", timeout=5000)
                page.wait_for_timeout(1500)
                shot(page, f"report_{label}_modal", full=False)
            except Exception as e:
                print("dialog open failed:", e)
                shot(page, f"report_{label}_failed", full=False)
        elif flow == "csr_flow":
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            page.click("button.tab[data-tab='settings']", timeout=5000)
            page.wait_for_timeout(1500)
            # find CSR button and scroll/click
            page.evaluate(
                """() => {
                    const btn = Array.from(document.querySelectorAll('button')).find(b => (b.innerText||'').trim().startsWith('產生 CSR'));
                    if (btn) btn.scrollIntoView({block:'center'});
                }"""
            )
            page.wait_for_timeout(1000)
            shot(page, "csr_form_collapsed", full=False)
            # look for collapsible expander
            expander = page.evaluate(
                """() => {
                    const all = document.querySelectorAll('summary, .details-summary, [data-toggle], details');
                    return Array.from(all).map(e => ({tag:e.tagName, text: (e.innerText||'').trim().slice(0,40), open: e.open}));
                }"""
            )
            print(json.dumps(expander, ensure_ascii=False, indent=2)[:1500])
            # try opening all details around the TLS section
            page.evaluate(
                """() => {
                    document.querySelectorAll('details').forEach(d => { if ((d.querySelector('summary')?.innerText||'').includes('CSR') || (d.querySelector('summary')?.innerText||'').includes('匯入')) d.open = true; });
                }"""
            )
            page.wait_for_timeout(500)
            # Open all details forcibly and take full page
            page.evaluate("document.querySelectorAll('details').forEach(d => d.open=true)")
            page.wait_for_timeout(700)
            shot(page, "csr_settings_full_open", full=True)
        elif flow == "csr":
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            page.click("button.tab[data-tab='settings']", timeout=5000)
            page.wait_for_timeout(1500)
            # scroll to TLS section
            try:
                page.evaluate(
                    """() => {
                        const el = Array.from(document.querySelectorAll('*')).find(e => (e.innerText||'').trim().startsWith('TLS / HTTPS') || (e.innerText||'').trim().startsWith('憑證匯入'));
                        if (el) el.scrollIntoView({block:'start'});
                    }"""
                )
                page.wait_for_timeout(600)
            except Exception:
                pass
            shot(page, "settings_tls_section", full=True)
            # look for CSR button
            buttons = page.evaluate(
                """() => {
                    return Array.from(document.querySelectorAll('button')).filter(b => {
                        const t = (b.innerText||'').trim();
                        return t.includes('CSR') || t.includes('憑證') || t.includes('匯入');
                    }).map(b => (b.innerText||'').trim().slice(0,40));
                }"""
            )
            print("csr-related buttons:", json.dumps(buttons, ensure_ascii=False, indent=2))
        elif flow == "click_text":
            text = args[0]
            label = args[1] if len(args) > 1 else "clicked"
            wait = int(args[2]) if len(args) > 2 else 2000
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            page.click(f"text={text}", timeout=6000)
            page.wait_for_timeout(wait)
            shot(page, f"click_{label}", full=True)
        elif flow == "section_scroll":
            tab = args[0]
            label = args[1]
            scroll_px = int(args[2]) if len(args) > 2 else 700
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            page.click(f"button.tab[data-tab='{tab}']", timeout=5000)
            page.wait_for_timeout(2000)
            page.evaluate(f"window.scrollTo(0,{scroll_px})")
            page.wait_for_timeout(800)
            shot(page, f"ss_{label}", full=False)
        elif flow == "subnav_tour":
            # tour every visible sub-nav under each tab
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.add_style_tag(content="#bulk-bar{display:none !important}")
            for tab, label in [
                ("dashboard", "ov"),
                ("traffic-workload", "tw"),
                ("events", "ev"),
                ("rules", "ru"),
                ("reports", "re"),
                ("rule-scheduler", "rs"),
                ("integrations", "in"),
                ("settings", "se"),
            ]:
                try:
                    page.click(f"button.tab[data-tab='{tab}']", timeout=4000)
                    page.wait_for_timeout(1200)
                except Exception:
                    continue
                subs = page.evaluate(
                    """() => Array.from(document.querySelectorAll('.sub-nav-btn, .subtab')).filter(b => b.offsetParent !== null).map(b => ({id: b.id, text: (b.innerText||'').trim().slice(0,32)}))"""
                )
                for i, sub in enumerate(subs):
                    try:
                        if sub.get("id"):
                            page.click(f"#{sub['id']}", timeout=3000)
                        else:
                            page.click(f"text={sub['text']}", timeout=3000)
                        page.wait_for_timeout(1800)
                        shot(page, f"sub_{label}_{i:02d}_{sub.get('id') or sub['text'][:12]}")
                    except Exception as e:
                        print("sub fail", tab, sub, e)
        elif flow == "list_nav":
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            nav = page.evaluate(
                """() => {
                    // dump every clickable nav-ish element with text under 24 chars
                    const out = [];
                    const seen = new Set();
                    document.querySelectorAll('button, a, [role=tab], [role=button], [data-tab], [data-view], [data-target]').forEach(el => {
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (!txt || txt.length > 24) return;
                        const key = txt + '|' + (el.id || '') + '|' + (el.getAttribute('data-tab') || el.getAttribute('data-view') || el.getAttribute('data-target') || '');
                        if (seen.has(key)) return;
                        seen.add(key);
                        out.push({
                          text: txt,
                          id: el.id || null,
                          cls: (el.className && el.className.toString && el.className.toString().slice(0,80)) || null,
                          tab: el.getAttribute('data-tab') || el.getAttribute('data-view') || el.getAttribute('data-target'),
                          href: el.getAttribute('href'),
                          tag: el.tagName,
                        });
                    });
                    return out.slice(0, 200);
                }"""
            )
            print(json.dumps(nav, ensure_ascii=False, indent=2))
        else:
            print("unknown flow", flow)

        if console_log:
            (SHOTS.parent / "console.log").write_text("\n".join(console_log[-200:]))
        browser.close()


if __name__ == "__main__":
    flow = sys.argv[1] if len(sys.argv) > 1 else "login"
    run(flow, *sys.argv[2:])
