"""Static assertions for the filter-bar pill component (Phase 3 Task 2).

Mirrors tests/test_component_filter_bar.py's pattern: read the shipped
files as text and regex/substring assert rather than executing the JS
(no JS runtime in the Python test suite).
"""
from pathlib import Path

_JS = Path("src/static/js/filter-bar.js")
_CSS = Path("src/static/css/app.css")
_EN = Path("src/i18n_en.json")
_ZH = Path("src/i18n_zh_TW.json")
_INDEX = Path("src/templates/index.html")


def test_filter_bar_js_exists_and_exports_factory():
    src = _JS.read_text(encoding="utf-8")
    assert "window.createFilterBar" in src


def test_filter_bar_handlers_on_window():
    src = _JS.read_text(encoding="utf-8")
    for fn in ("_objfbInput", "_objfbKeydown", "_objfbPillClick", "_objfbAddDir"):
        assert f"window.{fn}" in src, f"{fn} must be on window for CSP dispatcher"


def test_filter_bar_no_inline_onclick():
    src = _JS.read_text(encoding="utf-8")
    # 元件不得用 inline on-click 屬性（CSP）；事件走 data-action/data-on-* 委派
    assert "onclick=" not in src


def test_filter_bar_css_class_present():
    css = _CSS.read_text(encoding="utf-8")
    assert ".objfb-bar" in css
    assert ".objfb-pill" in css


def test_filter_bar_css_bar_wraps_hint_row():
    # .objfb-hint 是 width:100% 的整列提示；.objfb-bar 必須 flex-wrap: wrap，
    # 否則 hint 顯示時（任一側 pill 存在）會擠進同列把 .objfb-fbar 壓扁、pill 文字被裁掉
    css = _CSS.read_text(encoding="utf-8")
    bar_block = css.split(".objfb-bar {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: wrap" in bar_block


def test_filter_bar_i18n_keys_present():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_placeholder", "gui_fb_add_ipcidr", "gui_fb_any_slow",
              "gui_fb_offline", "gui_fb_or"):
        assert k in en and k in zh, f"{k} missing in i18n"


def test_filter_bar_loaded_in_index_html():
    html = _INDEX.read_text(encoding="utf-8")
    assert "filter-bar.js" in html


def test_filter_bar_serialize_deserialize_present():
    src = _JS.read_text(encoding="utf-8")
    assert "function _objfbSerialize(state)" in src
    assert "function _objfbDeserialize(state, dict)" in src


def test_filter_bar_or_marker_for_same_key_labels():
    src = _JS.read_text(encoding="utf-8")
    assert "objfb-or" in src


def test_filter_bar_any_dir_distinct_style_and_hint():
    src = _JS.read_text(encoding="utf-8")
    assert "objfb-any" in src
    assert "gui_fb_any_slow" in src


def test_filter_bar_uses_suggest_endpoint():
    src = _JS.read_text(encoding="utf-8")
    assert "/api/filter-objects/suggest" in src


def test_filter_bar_uses_debounce_and_abort():
    src = _JS.read_text(encoding="utf-8")
    assert "AbortController" in src
    assert "debounce" in src


def test_filter_bar_handles_offline():
    src = _JS.read_text(encoding="utf-8")
    # 消費 workload 的 pce_unreachable error 欄
    assert "pce_unreachable" in src


def test_traffic_analyzer_modal_mounts_filter_bar():
    """Phase 3 Task 4: qt-src/qt-dst/qt-any-*/qt-ex* 分欄已換成單一 FilterBar 掛載點。"""
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="qt-filter-bar"' in html
    for removed_id in (
        "qt-src", "qt-dst", "qt-any-label", "qt-any-ip",
        "qt-exsrc", "qt-exdst", "qt-ex-any-label", "qt-ex-any-ip",
    ):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed from modal-qt-filters"
    # Task 11：qt-port/qt-proto scalar 欄位已收斂進 FilterBar 的 port pill；
    # PD radio 不屬 FilterBar 範圍，保留。
    assert 'name="qt-pd-radio"' in html


def test_quarantine_js_uses_filter_bar_for_traffic_analyzer():
    js = Path("src/static/js/quarantine.js").read_text(encoding="utf-8")
    assert "createFilterBar(document.getElementById('qt-filter-bar')" in js
    assert "_ensureQtFilterBar().getFilters()" in js
    for removed_id in ("qt-src", "qt-dst", "qt-exsrc", "qt-exdst", "qt-any-label", "qt-any-ip"):
        assert f"getElementById('{removed_id}')" not in js


def test_instant_report_modal_mounts_filter_bar():
    """Phase 4a Task 3: rpt-src/rpt-dst/rpt-ex-*/rpt-any-* 分欄已換成單一 FilterBar 掛載點。"""
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="rpt-filter-bar"' in html
    for removed_id in (
        "rpt-src", "rpt-dst", "rpt-ex-src", "rpt-ex-dst",
        "rpt-any-label", "rpt-any-ip", "rpt-ex-any-label", "rpt-ex-any-ip",
    ):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed from m-gen-filters"
    # pd checkbox/proto/port/ex-port 保留（不屬 FilterBar 範圍）
    assert 'id="rpt-pd-blocked"' in html
    assert 'id="rpt-proto"' in html
    assert 'id="rpt-port"' in html
    assert 'id="rpt-ex-port"' in html


def test_dashboard_js_uses_filter_bar_for_instant_report():
    js = Path("src/static/js/dashboard.js").read_text(encoding="utf-8")
    assert "function _ensureRptFilterBar()" in js
    assert "createFilterBar(document.getElementById('rpt-filter-bar')" in js
    assert "_ensureRptFilterBar().getFilters()" in js
    for removed_id in (
        "rpt-src", "rpt-dst", "rpt-ex-src", "rpt-ex-dst",
        "rpt-any-label", "rpt-any-ip", "rpt-ex-any-label", "rpt-ex-any-ip",
    ):
        assert f"getElementById('{removed_id}')" not in js
        assert f"'{removed_id}'" not in js


def test_scheduled_report_modal_mounts_filter_bar():
    """Phase 4a Task 4: sched-src/dst/ex-*/any-* 分欄已換成單一 FilterBar 掛載點。"""
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="sched-filter-bar"' in html
    for removed_id in (
        "sched-src", "sched-dst", "sched-ex-src", "sched-ex-dst",
        "sched-any-label", "sched-any-ip", "sched-ex-any-label", "sched-ex-any-ip",
    ):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed from sched-filter-section"
    # pd checkbox/proto/port/ex-port 保留（不屬 FilterBar 範圍）
    assert 'id="sched-pd-blocked"' in html
    assert 'id="sched-proto"' in html
    assert 'id="sched-port"' in html
    assert 'id="sched-ex-port"' in html


def test_dashboard_js_uses_filter_bar_for_scheduled_report():
    js = Path("src/static/js/dashboard.js").read_text(encoding="utf-8")
    assert "function _ensureSchedFilterBar()" in js
    assert "createFilterBar(document.getElementById('sched-filter-bar')" in js
    assert "_ensureSchedFilterBar().getFilters()" in js
    assert "_ensureSchedFilterBar().setFilters(" in js
    for removed_id in (
        "sched-src", "sched-dst", "sched-ex-src", "sched-ex-dst",
        "sched-any-label", "sched-any-ip", "sched-ex-any-label", "sched-ex-any-ip",
    ):
        assert f"getElementById('{removed_id}')" not in js
        assert f"'{removed_id}'" not in js


def test_filter_bar_deserialize_accepts_legacy_scalar_ip():
    """既有排程存的是舊格式 src_ip/dst_ip scalar（非 src_ip_in list）；
    _objfbDeserialize 須認得這個 scalar key 才能讓 setFilters 正確回填舊排程。"""
    js = _JS.read_text(encoding="utf-8")
    assert "asList(d[`${dir}_ip_in`]).concat(asList(d[`${dir}_ip`]))" in js


def test_dashboard_query_modal_mounts_filter_bar():
    """Phase 4b Task 3: dq-src/dst/exsrc/exdst/any-*/ex-any-* 8 分欄已換成單一 FilterBar 掛載點。"""
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="dq-filter-bar"' in html
    for removed_id in (
        "dq-src", "dq-dst", "dq-exsrc", "dq-exdst",
        "dq-any-label", "dq-any-ip", "dq-ex-any-label", "dq-ex-any-ip",
    ):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed from m-query"
    # name/rank/pd radio/port/proto/ex-port/idx 保留（不屬 FilterBar 範圍）
    assert 'id="dq-name"' in html
    assert 'id="dq-rank"' in html
    assert 'name="dq-pd"' in html
    assert 'id="dq-port"' in html
    assert 'id="dq-proto"' in html
    assert 'id="dq-expt"' in html
    assert 'id="dq-idx"' in html


def test_dashboard_js_uses_filter_bar_for_saved_query():
    js = Path("src/static/js/dashboard.js").read_text(encoding="utf-8")
    assert "function _ensureDqFilterBar()" in js
    assert "createFilterBar(document.getElementById('dq-filter-bar')" in js
    assert "_ensureDqFilterBar().getFilters()" in js
    assert "_ensureDqFilterBar().setFilters(" in js
    for removed_id in (
        "dq-src", "dq-dst", "dq-exsrc", "dq-exdst",
        "dq-any-label", "dq-any-ip", "dq-ex-any-label", "dq-ex-any-ip",
    ):
        assert f"getElementById('{removed_id}')" not in js
        assert f"'{removed_id}'" not in js


def test_save_dashboard_query_sends_filters_dict():
    """saveDashboardQuery 改送 filters dict，不再逐欄讀 src/dst/ex_*/any_* scalar。"""
    js = Path("src/static/js/dashboard.js").read_text(encoding="utf-8")
    fn_src = js.split("async function saveDashboardQuery()", 1)[1].split("\nasync function ", 1)[0]
    assert "filters:" in fn_src
    assert "_ensureDqFilterBar().getFilters()" in fn_src
    for removed_key in ("src:", "dst:", "ex_src:", "ex_dst:", "any_label:", "any_ip:", "ex_any_label:", "ex_any_ip:"):
        assert removed_key not in fn_src, f"{removed_key} should no longer be read directly in saveDashboardQuery"


def test_filter_bar_deserialize_restores_label_group_pills():
    """序列化端會送 {ex_}{dir}_label_groups；deserialize 漏認會使編輯回填時
    label_group pill 靜默消失、再存檔即永久遺失（排程報表/儲存查詢/modal 重開共用）。"""
    js = _JS.read_text(encoding="utf-8")
    assert "asList(d[`${dir}_label_groups`])" in js
    assert "asList(d[`ex_${dir}_label_groups`])" in js


def test_traffic_rule_modal_mounts_filter_bar():
    """Phase 4c Task 3: tr-src/tr-dst/tr-exsrc/tr-exdst 已換成單一 FilterBar 掛載點。"""
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="tr-filter-bar"' in html
    for removed_id in ("tr-src", "tr-dst", "tr-exsrc", "tr-exdst"):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed from m-traffic"
    # name/pd/port/proto/ex-port/threshold/window/cooldown 保留（不屬 FilterBar 範圍）
    assert 'id="tr-name"' in html
    assert 'name="tr-pd"' in html
    assert 'id="tr-port"' in html
    assert 'id="tr-proto"' in html
    assert 'id="tr-expt"' in html
    assert 'id="tr-cnt"' in html
    assert 'id="tr-win"' in html
    assert 'id="tr-cd"' in html


def test_bw_rule_modal_mounts_filter_bar():
    """Phase 4c Task 3: bw-src/bw-dst/bw-exsrc/bw-exdst 已換成單一 FilterBar 掛載點。"""
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="bw-filter-bar"' in html
    for removed_id in ("bw-src", "bw-dst", "bw-exsrc", "bw-exdst"):
        assert f'id="{removed_id}"' not in html, f"{removed_id} should be removed from m-bw"
    assert 'id="bw-name"' in html
    assert 'name="bw-mt"' in html
    assert 'name="bw-pd"' in html
    assert 'id="bw-port"' in html
    assert 'id="bw-expt"' in html
    assert 'id="bw-val"' in html
    assert 'id="bw-win"' in html
    assert 'id="bw-cd"' in html


def test_filter_bar_suggest_types_derived_from_cats():
    """cats 選項必須貫穿到 suggest 請求：無 scope 時 types 不可寫死含 label_group，
    須由 state.cats 交集 suggest 支援類別導出。否則規則 modal（cats 排除 label_group）
    自由輸入時 label_group 候選仍會出現，選取成 pill 後儲存被後端 400。"""
    js = _JS.read_text(encoding="utf-8")
    fn_src = js.split("function _objfbQuerySuggest(state, q)", 1)[1].split("\nfunction ", 1)[0]
    assert "'label,label_group,iplist,workload'" not in fn_src, "types 不可寫死 fallback 字串"
    assert "state.cats" in fn_src, "types 須由 state.cats 導出"


def test_filter_bar_dropdown_render_filters_by_cats():
    """下拉候選分類迭代須照 state.cats 過濾，與 _objfbUpdateDropdown 的分類快選鈕契約一致
    （後者已經照 state.cats 過濾，此為補齊另一半）。"""
    js = _JS.read_text(encoding="utf-8")
    fn_src = js.split("function _objfbRenderDropdown(state, q)", 1)[1].split("\nfunction ", 1)[0]
    assert "state.cats.includes(c)" in fn_src


def test_filter_bar_suggest_cats_order_locked():
    """suggest 支援類別的固定順序鎖定：未傳 cats 的既有實例（流量分析器/報表/排程/
    dashboard）預設 cats 含全類別，types 字串與下拉分類順序須與現行逐位相同。"""
    js = _JS.read_text(encoding="utf-8")
    assert "const _OBJFB_SUGGEST_CATS = ['label', 'label_group', 'iplist', 'workload', 'service'];" in js


def test_rules_js_uses_filter_bar_for_traffic_and_bw():
    js = Path("src/static/js/rules.js").read_text(encoding="utf-8")
    assert "function _ensureTrFilterBar()" in js
    assert "function _ensureBwFilterBar()" in js
    assert "createFilterBar(document.getElementById('tr-filter-bar'), { cats:" in js
    assert "createFilterBar(document.getElementById('bw-filter-bar'), { cats:" in js
    # 規則路徑不支援 label_group（後端 400）；前端建構時排除該類別
    for fn_name in ("_ensureTrFilterBar", "_ensureBwFilterBar"):
        fn_src = js.split(f"function {fn_name}()", 1)[1].split("\n}", 1)[0]
        assert "cats:" in fn_src
        assert "label_group" not in fn_src
    assert "_ensureTrFilterBar().getFilters()" in js
    assert "_ensureTrFilterBar().setFilters(" in js
    assert "_ensureBwFilterBar().getFilters()" in js
    assert "_ensureBwFilterBar().setFilters(" in js
    for removed_id in ("tr-src", "tr-dst", "tr-exsrc", "tr-exdst", "bw-src", "bw-dst", "bw-exsrc", "bw-exdst"):
        assert f"getElementById('{removed_id}')" not in js
        assert f"'{removed_id}'" not in js


def test_save_traffic_and_bw_send_filters_dict():
    """saveTraffic/saveBW 改送 filters dict，不再逐欄讀 src/dst/ex_src/ex_dst scalar。"""
    js = Path("src/static/js/rules.js").read_text(encoding="utf-8")
    tr_src = js.split("async function saveTraffic()", 1)[1].split("\nasync function ", 1)[0]
    assert "filters:" in tr_src
    assert "_ensureTrFilterBar().getFilters()" in tr_src
    bw_src = js.split("async function saveBW()", 1)[1].split("\nasync function ", 1)[0]
    assert "filters:" in bw_src
    assert "_ensureBwFilterBar().getFilters()" in bw_src
    for removed_key in ("src:", "dst:", "ex_src:", "ex_dst:"):
        assert removed_key not in tr_src, f"{removed_key} should no longer be read directly in saveTraffic"
        assert removed_key not in bw_src, f"{removed_key} should no longer be read directly in saveBW"


def test_filter_bar_service_port_categories_defined():
    src = _JS.read_text(encoding="utf-8")
    assert "gui_fb_cat_service" in src and "gui_fb_cat_port" in src
    assert "objfb-dot-service" in src and "objfb-dot-port" in src


def test_filter_bar_serializes_services_and_ports_keys():
    src = _JS.read_text(encoding="utf-8")
    for key in ("services", "ex_services", "ports", "ex_ports"):
        assert f"'{key}'" in src or f"`${{ex}}{key.removeprefix('ex_')}`" in src, key


def test_filter_bar_port_like_validator_present():
    src = _JS.read_text(encoding="utf-8")
    assert "_objfbIsPortLike" in src


def test_filter_bar_dirless_cats():
    src = _JS.read_text(encoding="utf-8")
    assert "_OBJFB_DIRLESS" in src


def test_filter_bar_service_i18n_keys_bilingual():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_cat_service", "gui_fb_cat_port", "gui_fb_add_port"):
        assert k in en and k in zh


def test_filter_bar_browse_wiring_present():
    src = _JS.read_text(encoding="utf-8")
    assert "/api/filter-objects/browse" in src
    assert "window._objfbBrowseMore" in src
    assert "gui_fb_load_more" in src and "gui_fb_type_to_search" in src


def test_filter_bar_browse_i18n_bilingual():
    import json
    en = json.loads(_EN.read_text(encoding="utf-8"))
    zh = json.loads(_ZH.read_text(encoding="utf-8"))
    for k in ("gui_fb_load_more", "gui_fb_type_to_search", "gui_fb_browse_error"):
        assert k in en and k in zh


def test_qt_port_fields_removed():
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="qt-port"' not in html and 'id="qt-expt"' not in html and 'id="qt-proto"' not in html


def test_quarantine_js_no_qt_port_reads():
    src = Path("src/static/js/quarantine.js").read_text(encoding="utf-8")
    assert "qt-port" not in src and "qt-expt" not in src and "qt-proto" not in src


def test_rules_filter_bars_allow_service_port():
    src = Path("src/static/js/rules.js").read_text(encoding="utf-8")
    assert src.count("'service', 'port'") >= 2
