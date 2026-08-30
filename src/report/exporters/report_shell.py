"""
src/report/exporters/report_shell.py
design/v2 report shell — the shared skeleton every v2 HTML report renders into.

SHELL_CSS below is a port of ``design/v2/reports/shell.css``. That file stays
the design authority for the report shell: it is what the prototype renderer
(``design/v2/tools/reskin_report.py``) loads, and what the reviewed PDFs in
``design/v2/reports/reskinned/`` were produced from. Any change made on the
product side must be annotated back into ``design/v2/reports/shell.css`` so the
two do not silently drift apart.

Deliberate deltas from the design file (everything else is a verbatim port).
``tests/test_report_shell_renderer.py`` rebuilds SHELL_CSS from the design file
by applying exactly this list and asserts equality, so the list below and that
test are the drift guard — prose alone is not:
  * a provenance header carrying ``SHELL_CSS_PORT_MARKER``;
  * the "hide the old print cover" rule is dropped — the product no longer
    emits a second cover, so there is nothing to defend against. The screen
    half of the ``.print-only`` / ``.screen-only`` pair is kept;
  * ``.print-btn`` is added (screen-only; hidden in the print block);
  * ``.score-num`` gains ``color: var(--ink)`` so the maturity score picks up
    the grade tone from the ``data-tone`` on its wrapper;
  * ``.mat-fill.warn`` / ``.progress-fill.warn`` is restored from the old
    product shell (``report_css.py:529``). The design file never had it, but
    the old shell did; without it the 40-70% band falls back to the info blue
    and the three-level semantic colour collapses to two. A gap the design file
    shares is still a regression against the shipped output;
  * the print block gains the wide-table release rules carried over from the
    old product shell (``report_css.py``) plus ``!important`` on the four
    column-width floors that must survive them — see the comment on the
    release block itself for why both halves are required.

``src`` must never import from ``design/`` — the design tree is not shipped in
the offline bundle — so the severity/tone tables below are copies of
``reskin_report.py``'s, not imports of them.
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from typing import Sequence

from src.i18n import t

from .grade_colors import grade_tone
from .report_css import TABLE_JS

__all__ = [
    "SHELL_CSS",
    "ShellCover",
    "ShellSection",
    "build_shell_document",
    "wide_table_attrs",
]

SHELL_CSS = """\
/* ===========================================================================
   PORTED FROM design/v2/reports/shell.css — that file stays the design
   authority for the report shell. Any product-side edit must be annotated
   back into it; see report_shell.py's module docstring for the deltas.
   port-marker: shell-css-port-v2
   (Do not remove or reword the marker: scripts/audit_i18n_usage.py scopes its
   Cat C exemption to the literal containing this exact token, and the design
   commentary below is CJK.)
   =========================================================================== */

/* ============================================================================
   design/v2 報表殼 — 「儀表印本 (instrument printout)」
   spec §4「HTML 報表」的視覺原型；Phase 2 據此重寫 report_css.py。

   設計立場
     · GUI 是深色監控台，報表是它的紙本對應：恆亮、白紙、髮絲線，
       沒有陰影劇場、沒有大圓角——資訊是主角，容器要退到後面。
     · tone 標記（LED）在紙上與螢幕上同一個色相：直接沿用
       design/v2/mockup/assets/tokens.css 的 --tone-*-border 定值，
       墨色/底色改用 tokens.css [data-theme="light"] 那一套（列印安全）。
     · 簽名元素＝章節左側的「tone 導軌 + 等寬章號」：跨頁時導軌延續，
       讀者在任何一頁都能認出自己在哪一章、那一章多嚴重。
     · 所有數字、代碼、欄名走等寬 tabular——這是報表的性格所在。

   本檔只用 tokens.css 契約內的 token 名（tone、surface、text、space、font、
   radius、line、track、accent 各族），值取亮色那一套。
   ============================================================================ */

/* == 1. 列印安全 token 子集（tokens.css 的亮色投影，恆亮） =================== */
:root {
  color-scheme: light;

  --font-ui: "Noto Sans", "Noto Sans CJK TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
  --font-mono: "Noto Sans Mono", "DejaVu Sans Mono", "SFMono-Regular", Consolas, monospace;

  --radius-s: 2px;
  --radius-m: 3px;
  --radius-l: 6px;

  --space-1: 2px;
  --space-2: 4px;
  --space-3: 6px;
  --space-4: 8px;
  --space-5: 12px;
  --space-6: 16px;
  --space-7: 24px;
  --space-8: 32px;

  --fs-micro: 9.5px;
  --fs-mini: 10.5px;
  --fs-body: 11.5px;
  --fs-ui: 13px;
  --fs-lead: 15px;
  --fs-num: 19px;
  --fs-display: 30px;
  --lead: 1.45;

  /* 紙面：sheet 恆為白紙，canvas 只活在螢幕上 */
  --paper: #FFFFFF;
  --canvas: #EEF1F5;
  --surface-1: #FFFFFF;
  --surface-2: #F5F7FA;

  --text-1: #12161C;
  --text-2: #414B59;
  --text-3: #6E7A8A;

  --line: #DDE2E9;
  --line-soft: #E7EBF0;
  --track: #E9EDF2;

  --accent: #2A78D6;
  --accent-fg: #1C5CAB;
  --accent-on: #FFFFFF;

  /* tone 標記色相＝深色主題定值（LED 在紙上也是同一顆） */
  --tone-ok-border: #0CA30C;
  --tone-warn-border: #FAB219;
  --tone-crit-border: #D03B3B;
  --tone-info-border: #3987E5;
  --tone-neutral-border: #8B929E;

  /* 墨色/底色＝亮色主題 */
  --tone-ok-fg: #0A7D0A;
  --tone-ok-bg: #E4F3E4;
  --tone-warn-fg: #8A5D00;
  --tone-warn-bg: #FBF0D8;
  --tone-crit-fg: #C22F2F;
  --tone-crit-bg: #FAE6E6;
  --tone-info-fg: #1C5CAB;
  --tone-info-bg: #E3EEFB;
  --tone-neutral-fg: #5C6472;
  --tone-neutral-bg: #EDF0F4;
}

[data-tone] {
  --mark: var(--tone-neutral-border);
  --ink: var(--tone-neutral-fg);
  --fill: var(--tone-neutral-bg);
}
[data-tone="ok"] { --mark: var(--tone-ok-border); --ink: var(--tone-ok-fg); --fill: var(--tone-ok-bg); }
[data-tone="warn"] { --mark: var(--tone-warn-border); --ink: var(--tone-warn-fg); --fill: var(--tone-warn-bg); }
[data-tone="crit"] { --mark: var(--tone-crit-border); --ink: var(--tone-crit-fg); --fill: var(--tone-crit-bg); }
[data-tone="info"] { --mark: var(--tone-info-border); --ink: var(--tone-info-fg); --fill: var(--tone-info-bg); }
[data-tone="neutral"] { --mark: var(--tone-neutral-border); --ink: var(--tone-neutral-fg); --fill: var(--tone-neutral-bg); }

/* == 2. 版面骨架 ============================================================ */
* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--canvas);
  color: var(--text-1);
  font-family: var(--font-ui);
  font-size: var(--fs-ui);
  line-height: var(--lead);
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}

.sheet {
  max-width: 1180px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-7) var(--space-8);
  background: var(--paper);
  border-left: 1px solid var(--line);
  border-right: 1px solid var(--line);
}

.doc {
  display: grid;
  grid-template-columns: 208px minmax(0, 1fr);
  column-gap: var(--space-8);
  align-items: start;
}

.cover,
.exec,
.appendix { grid-column: 1 / -1; }

.toc { grid-column: 1; }
.chapters { grid-column: 2; min-width: 0; }

h1, h2, h3, h4 { font-weight: 650; letter-spacing: -0.01em; }

.eyebrow,
.chapter-eyebrow,
.kpi-label,
.ev-label,
.cov-label,
.summary-pill-label,
.th-label {
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-3);
}

/* 數字一律等寬 tabular */
.kpi-value,
.cov-value,
.sev-count,
.mat-val,
.score-num,
.concern-count,
.summary-pill-value,
.trend-chip,
.report-table td,
.toc-page {
  font-variant-numeric: tabular-nums;
}

/* == 3. 封面 =============================================================== */
.cover {
  border-top: 3px solid var(--mark, var(--tone-neutral-border));
  border-bottom: 1px solid var(--line);
  padding: var(--space-7) 0 var(--space-7);
  margin-bottom: var(--space-8);
}

.cover-eyebrow {
  font-family: var(--font-mono);
  font-size: var(--fs-mini);
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--text-3);
}

.cover h1 {
  margin: var(--space-3) 0 var(--space-2);
  font-size: var(--fs-display);
  line-height: 1.15;
}

.cover-kicker {
  font-size: var(--fs-lead);
  color: var(--text-2);
  margin: 0 0 var(--space-6);
}

.cover-badges {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-bottom: var(--space-6);
}

.cover-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--space-5) var(--space-7);
  border-top: 1px solid var(--line-soft);
  padding-top: var(--space-5);
}

.cover-meta dt {
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-3);
  margin-bottom: var(--space-1);
}

.cover-meta dd {
  margin: 0;
  font-size: var(--fs-body);
  color: var(--text-1);
  overflow-wrap: anywhere;
}

/* == 4. 執行摘要 =========================================================== */
.exec {
  border-left: 3px solid var(--accent-fg);
  background: var(--surface-2);
  padding: var(--space-6) var(--space-7);
  margin-bottom: var(--space-8);
}

.exec > h2 {
  margin: 0 0 var(--space-5);
  font-size: var(--fs-lead);
}

.exec-summary { padding: 0; border: 0; background: none; }
.exec-summary > h2 { margin: 0 0 var(--space-5); font-size: var(--fs-lead); }

.kpi-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--space-5);
}

.kpi {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-left: var(--space-4);
  border-left: 2px solid var(--line);
}

.kpi-value {
  font-family: var(--font-mono);
  font-size: var(--fs-num);
  font-weight: 600;
  line-height: 1.1;
  overflow-wrap: anywhere;
}

/* == 5. 目錄（螢幕 sticky 側欄 / 列印頁碼型） ================================ */
.toc {
  position: sticky;
  top: var(--space-6);
  border-top: 1px solid var(--line);
  padding-top: var(--space-4);
  font-size: var(--fs-body);
}

.toc h2 {
  margin: 0 0 var(--space-4);
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--text-3);
  font-weight: 600;
}

.toc ol { list-style: none; margin: 0; padding: 0; }

.toc li { border-bottom: 1px solid var(--line-soft); }

.toc a {
  display: grid;
  grid-template-columns: 2.4em 1fr auto;
  gap: var(--space-3);
  align-items: baseline;
  padding: var(--space-3) 0;
  color: var(--text-2);
  text-decoration: none;
}

.toc a:hover { color: var(--accent-fg); }
.toc a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

/* 列印按鈕：螢幕限定，字級與 accent 色比照 .toc a；列印時自己不上紙。 */
.print-btn {
  display: block;
  width: 100%;
  margin-bottom: var(--space-5);
  padding: var(--space-3) var(--space-4);
  font-family: var(--font-mono);
  font-size: var(--fs-body);
  letter-spacing: 0.06em;
  color: var(--accent-fg);
  background: var(--surface-1);
  border: 1px solid var(--line);
  border-radius: var(--radius-s);
  text-align: left;
  cursor: pointer;
}

.print-btn:hover { border-color: var(--accent); }
.print-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.toc-num {
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  color: var(--text-3);
}

.toc-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--mark);
  align-self: center;
}

.toc-page { display: none; }

/* == 6. 章節殼（簽名元素：tone 導軌 + 等寬章號） ============================= */
.chapters { counter-reset: chapter; }

.chapter {
  position: relative;
  padding: 0 0 var(--space-8) var(--space-6);
  border-left: 3px solid var(--mark);
  margin-bottom: var(--space-8);
}

.chapter-index {
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.08em;
  color: var(--paper);
  background: var(--mark);
  border-radius: var(--radius-s);
  padding: 1px var(--space-3);
}

.chapter-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--line);
  padding-bottom: var(--space-4);
  margin-bottom: var(--space-6);
}

.chapter-eyebrow { color: var(--ink); }

h2.chapter-title {
  margin: 0;
  padding: 0;
  border: 0;
  font-size: var(--fs-lead);
  flex: 1 1 260px;
}

.chapter-marks {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.mark-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.06em;
  color: var(--ink);
  background: var(--fill);
  border: 1px solid var(--mark);
  border-radius: var(--radius-s);
  padding: 1px var(--space-3);
}

/* 章內原生標題（章名已抽到 chapter-head，其餘一律保留） */
.chapter h2 {
  margin: var(--space-7) 0 var(--space-4);
  font-size: var(--fs-ui);
  padding-left: var(--space-4);
  border-left: 3px solid var(--line);
}
.chapter h3 {
  margin: var(--space-7) 0 var(--space-4);
  font-size: var(--fs-ui);
  padding-left: var(--space-4);
  border-left: 2px solid var(--line);
}
.chapter h4 {
  margin: var(--space-6) 0 var(--space-3);
  font-size: var(--fs-body);
  color: var(--text-2);
  font-family: var(--font-mono);
  letter-spacing: 0.04em;
}
.chapter p { margin: var(--space-3) 0; }

/* == 7. 發現卡 ============================================================= */
.finding-card,
.concern-card,
.audit-attn-item {
  border: 1px solid var(--line);
  border-left: 3px solid var(--mark);
  border-radius: var(--radius-m);
  background: var(--surface-1);
  padding: var(--space-5) var(--space-6);
  margin: var(--space-5) 0;
  break-inside: avoid;
}

.finding-header,
.concern-header,
.audit-attn-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.finding-rule-id,
.concern-event,
.audit-attn-event-code {
  font-family: var(--font-mono);
  font-size: var(--fs-mini);
  color: var(--text-2);
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-s);
  padding: 0 var(--space-3);
}

.finding-title {
  font-size: var(--fs-ui);
  font-weight: 650;
  flex: 1 1 auto;
}

.concern-count,
.audit-attn-count {
  font-family: var(--font-mono);
  font-size: var(--fs-mini);
  color: var(--ink);
}

.finding-desc,
.concern-summary,
.audit-attn-summary {
  font-size: var(--fs-body);
  color: var(--text-2);
  margin: 0 0 var(--space-4);
}

.finding-evidence {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.ev-pill {
  min-width: 0;
  max-width: 100%;
  background: var(--surface-2);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-s);
  padding: var(--space-2) var(--space-4);
  font-size: var(--fs-body);
}

.ev-pill b {
  display: block;
  font-family: var(--font-mono);
  font-weight: 600;
  overflow-wrap: anywhere;
}

.ev-label { display: block; }

/* 「所以呢」行：建議永遠在卡的底部，靠 tone 墨色點題 */
.finding-rec,
.concern-rec,
.audit-attn-rec {
  border-top: 1px solid var(--line-soft);
  padding-top: var(--space-4);
  font-size: var(--fs-body);
  color: var(--text-1);
}

.finding-rec b,
.concern-rec b,
.audit-attn-rec b { color: var(--ink); }

.concern-meta,
.audit-attn-meta {
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  color: var(--text-3);
  margin-bottom: var(--space-3);
  overflow-wrap: anywhere;
}

.mitre-chip {
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  color: var(--accent-fg);
  border: 1px solid var(--line);
  border-radius: var(--radius-s);
  padding: 0 var(--space-2);
  text-decoration: none;
}

.cat-group { margin-top: var(--space-7); }
.cat-group > h3 { margin-top: 0; }

/* == 8. 徽章與標記 ========================================================= */
.badge,
.risk-badge {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.06em;
  border-radius: var(--radius-s);
  padding: 1px var(--space-3);
  margin-right: var(--space-2);
  white-space: nowrap;
  border: 1px solid var(--mark);
  background: var(--fill);
  color: var(--ink);
}

/* CRITICAL 實心、HIGH 描邊——同 tone 下仍分得出兩級 */
[data-tone="crit"][data-sev="CRITICAL"].badge,
[data-tone="crit"][data-sev="CRITICAL"].risk-badge {
  background: var(--tone-crit-border);
  color: var(--paper);
  border-color: var(--tone-crit-border);
}

.trend-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--fs-mini);
  color: var(--ink);
  background: var(--fill);
  border: 1px solid var(--mark);
  border-radius: var(--radius-s);
  padding: 0 var(--space-3);
}

.trend-arrow { font-size: var(--fs-mini); }

.trend-empty-note { color: var(--text-3); font-size: var(--fs-body); }
.trend-empty-dot { color: var(--tone-neutral-border); }

.report-profile-badge,
.report-draft-pill {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  border: 1px solid var(--mark);
  background: var(--fill);
  color: var(--ink);
  border-radius: var(--radius-s);
  padding: var(--space-1) var(--space-4);
}

.grade-chip {
  display: inline-flex;
  align-items: center;
  font-family: var(--font-mono);
  font-size: var(--fs-lead);
  font-weight: 700;
  color: var(--ink);
  background: var(--fill);
  border: 1px solid var(--mark);
  border-radius: var(--radius-m);
  padding: var(--space-2) var(--space-5);
}

/* == 9. 說明區塊 =========================================================== */
.note,
.section-intro {
  font-size: var(--fs-body);
  color: var(--text-2);
}

.note-warn,
.bp-box {
  border-left: 3px solid var(--mark, var(--tone-warn-border));
  background: var(--fill, var(--tone-warn-bg));
  padding: var(--space-4) var(--space-5);
  margin: var(--space-4) 0;
  font-size: var(--fs-body);
  color: var(--text-1);
}

.bp-box { --mark: var(--tone-info-border); --fill: var(--tone-info-bg); }
.bp-box b { color: var(--tone-info-fg); }

.section-guidance {
  display: grid;
  gap: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius-m);
  background: var(--surface-2);
  padding: var(--space-5) var(--space-6);
  margin: var(--space-5) 0 var(--space-6);
  font-size: var(--fs-body);
  color: var(--text-2);
}

.section-guidance b { color: var(--text-1); }

.subtable-label {
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-3);
  margin: var(--space-5) 0 var(--space-2);
}

/* == 10. 量表與小型資料圖元 ================================================= */
.summary-pill-row,
.coverage-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.summary-pill,
.cov-stat {
  border: 1px solid var(--line);
  border-left: 3px solid var(--mark);
  border-radius: var(--radius-s);
  background: var(--surface-1);
  padding: var(--space-3) var(--space-5);
  min-width: 0;
}

.summary-pill-value,
.cov-value {
  display: block;
  font-family: var(--font-mono);
  font-size: var(--fs-lead);
  font-weight: 600;
}

.mat-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(90px, 3fr) auto;
  gap: var(--space-5);
  align-items: center;
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--line-soft);
  break-inside: avoid;
}

.mat-name { font-size: var(--fs-body); color: var(--text-2); overflow-wrap: anywhere; }

.mat-bar,
.progress-bar {
  height: 8px;
  background: var(--track);
  border-radius: var(--radius-s);
  overflow: hidden;
}

.mat-fill,
.progress-fill {
  display: block;
  height: 100%;
  background: var(--tone-info-border);
  border-radius: var(--radius-s);
}

.mat-fill.bad, .progress-fill.bad { background: var(--tone-crit-border); }
.mat-fill.good, .progress-fill.good { background: var(--tone-ok-border); }
/* 舊殼 report_css.py:529 有 .mat-fill.warn（var(--gold-110)），設計檔漏了這一條。
   缺它會讓 40-70% 的中段長條退回 .mat-fill 的預設 info 藍，語意色從三級塌成兩級
   ——這是移植回歸，不是新設計，所以補回來並登記成授權 delta。 */
.mat-fill.warn, .progress-fill.warn { background: var(--tone-warn-border); }

.mat-val {
  font-family: var(--font-mono);
  font-size: var(--fs-body);
  color: var(--text-1);
  text-align: right;
  white-space: nowrap;
}

.sev-summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin: var(--space-5) 0;
}

.sev-box {
  border: 1px solid var(--line);
  border-radius: var(--radius-s);
  background: var(--surface-1);
  padding: var(--space-3) var(--space-5);
  text-align: center;
  min-width: 92px;
}

.sev-count {
  display: block;
  font-family: var(--font-mono);
  font-size: var(--fs-num);
  font-weight: 600;
  margin-top: var(--space-2);
}

.score-hero {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-5) 0;
}

.score-num {
  font-family: var(--font-mono);
  font-size: 44px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.03em;
  color: var(--ink);
}

.score-denom { font-family: var(--font-mono); color: var(--text-3); }

/* 版式容器（原 exporter 的 layout 類別） */
.section-top { display: flex; flex-wrap: wrap; gap: var(--space-6); align-items: flex-start; }
.section-top > * { flex: 1 1 320px; min-width: 0; }
.section-bottom { margin-top: var(--space-6); }
.tri-grid { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: var(--space-6); align-items: start; }
.tri-grid > div { min-width: 0; }
.tri-grid > div > h4:first-child { margin-top: 0; }

/* == 11. 圖表框（server-side SVG 原樣保留，只重繪外框） ====================== */
figure.chart-static {
  margin: var(--space-5) 0 var(--space-6);
  padding: var(--space-4);
  border: 1px solid var(--line);
  border-radius: var(--radius-m);
  background: var(--surface-1);
  break-inside: avoid;
  min-width: 0;
}

figure.chart-static svg {
  display: block;
  width: 100%;
  height: auto;
  max-width: 100%;
}

figure.chart-static figcaption {
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-3);
  margin-top: var(--space-3);
}

/* == 12. 表格 ==============================================================
   截斷政策（CLAUDE.md 硬規則，逐欄明定）：
     a. 一般儲存格：white-space normal + overflow-wrap break-word → 一律換行，
        永不裁切、永不省略。用 break-word 而非 anywhere，欄寬才不會被壓到
        逐字折行（「ACTO / R」）；列印再放寬成 anywhere 以保證塞得進紙面。
     b. 欄名 th：換行顯示全名，另保留原 exporter 的 title 全文。
     c. 長文欄（.cell-long，例如 change_detail）：螢幕收合成摘要＋可展開，
        摘要限 44ch 並一定帶 title 全文；列印時摘要隱藏、全文 pre-wrap 展開
        （必須同時解 ::details-content，見列印段的註解）。長文欄在列印的寬表
        裡另給寬度上限（見列印段 .col-long），否則它會以 max-content 吃掉整
        個版面，把 meta 欄壓成逐字直排。
     e. 時間戳欄（.col-ts，reskin_report._mark_column_kinds 標記）：時間戳是
        一個沒有空白的長 token，逐字拆等於讀不到時間。reskin 在日期與時間之
        間插一個 <wbr/>，這裡只給 break-word（永不 anywhere），最差折成
        「日期／時間」兩行。
     d. 寬表（--wide，8–9 欄留在直式縮排版；欄數 ≥ 10 才切橫式）：螢幕水平
        捲動＋欄數提示；列印切橫式頁 @page wide（實測 Chromium 147 生效，
        audit 6 頁轉橫式：p8/p10/p19/p20/p21/p22）。
   ========================================================================= */
.report-table-panel {
  margin: var(--space-4) 0 var(--space-6);
  border: 1px solid var(--line);
  border-radius: var(--radius-m);
  background: var(--surface-1);
  overflow: hidden;
  min-width: 0;
}

.report-table-wrap { overflow-x: auto; max-width: 100%; }

.report-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-body);
  table-layout: auto;
}

.report-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
  border-right: 1px solid var(--line-soft);
  padding: var(--space-3) var(--space-4);
  text-align: left;
  vertical-align: bottom;
  white-space: normal;
}

.report-table thead th:last-child { border-right: 0; }

.th-label {
  display: inline-block;
  max-width: 100%;
  white-space: normal;
  overflow-wrap: break-word;
  color: var(--text-2);
}

.table-hint {
  margin: 0;
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--line-soft);
  background: var(--surface-2);
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.06em;
  color: var(--text-3);
}

.report-table tbody td {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--line-soft);
  border-right: 1px solid var(--line-soft);
  vertical-align: top;
  white-space: normal;
  overflow-wrap: break-word;
  color: var(--text-1);
}

/* 整欄數值：等寬靠右對齊，且永不斷行——數字被折行等於讀不到量級 */
.report-table th.num,
.report-table td.num {
  text-align: right;
  white-space: nowrap;
  overflow-wrap: normal;
  font-variant-numeric: tabular-nums;
}

.report-table td.num { font-family: var(--font-mono); }
.report-table th.num .th-label { text-align: right; }

/* 時間戳欄：只在 reskin 插的 <wbr/>（日期↔時間之間）折行，永不逐字拆 */
.report-table th.col-ts,
.report-table td.col-ts,
.report-table th.col-ts .th-label {
  overflow-wrap: break-word;
  word-break: normal;
}

.report-table tbody td:last-child { border-right: 0; }
.report-table tbody tr:nth-child(even) td { background: var(--surface-2); }
.report-table tbody tr:last-child td { border-bottom: 0; }

.report-table td code {
  font-family: var(--font-mono);
  font-size: var(--fs-mini);
  background: var(--surface-2);
  border-radius: var(--radius-s);
  padding: 0 var(--space-2);
}

.report-table-panel--compact { max-width: 640px; }
.report-table-panel--wide .report-table { font-size: var(--fs-mini); }

/* 長文欄：螢幕收合、列印展開 */
.cell-long > summary {
  display: block;
  max-width: 44ch;
  overflow-wrap: anywhere;
  cursor: pointer;
  list-style: none;
  color: var(--text-1);
}

.cell-long > summary::-webkit-details-marker { display: none; }

.cell-long > summary::after {
  content: " ⌄";
  font-family: var(--font-mono);
  color: var(--accent-fg);
}

.cell-long[open] > summary::after { content: " ⌃"; }

.cell-long-full {
  margin: var(--space-3) 0 0;
  padding: var(--space-3) var(--space-4);
  background: var(--surface-2);
  border-left: 2px solid var(--line);
  border-radius: var(--radius-s);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: var(--font-mono);
  font-size: var(--fs-mini);
}

/* == 13. 附錄 ============================================================== */
.appendix {
  margin-top: var(--space-8);
  border-top: 1px solid var(--line);
  padding-top: var(--space-6);
}

.appendix h2 {
  margin: 0 0 var(--space-5);
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--text-3);
  font-weight: 600;
}

.appendix h3 {
  margin: var(--space-6) 0 var(--space-3);
  font-size: var(--fs-body);
  font-family: var(--font-mono);
  letter-spacing: 0.06em;
  color: var(--text-2);
}

.appendix-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-5) var(--space-7);
}

.appendix dl { margin: 0; }
.appendix dt {
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-3);
}
.appendix dd {
  margin: 0 0 var(--space-4);
  font-size: var(--fs-body);
  overflow-wrap: anywhere;
}

.rule-index { list-style: none; margin: 0; padding: 0; }

.rule-index li {
  display: grid;
  grid-template-columns: minmax(4.5em, max-content) minmax(0, 1fr) auto;
  gap: var(--space-4);
  align-items: baseline;
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--line-soft);
  border-left: 3px solid var(--mark);
  padding-left: var(--space-4);
  font-size: var(--fs-body);
}

.rule-index code {
  font-family: var(--font-mono);
  font-size: var(--fs-mini);
  color: var(--text-2);
}

.rule-index .rule-sev {
  font-family: var(--font-mono);
  font-size: var(--fs-micro);
  letter-spacing: 0.08em;
  color: var(--ink);
}

.colophon {
  margin-top: var(--space-7);
  padding-top: var(--space-4);
  border-top: 1px solid var(--line-soft);
  font-size: var(--fs-mini);
  color: var(--text-3);
}

.colophon footer { display: inline; }

.print-only { display: none; }

/* == 14. 窄視窗（≤1000px：目錄轉為頂部區塊） ================================ */
@media screen and (max-width: 1000px) {
  .sheet { padding: var(--space-6) var(--space-5); }
  .doc { grid-template-columns: minmax(0, 1fr); }
  .toc, .chapters { grid-column: 1; }
  .toc {
    position: static;
    margin-bottom: var(--space-7);
    border-bottom: 1px solid var(--line);
    padding-bottom: var(--space-4);
  }
  .toc ol {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 0 var(--space-6);
  }
  .tri-grid { grid-template-columns: minmax(0, 1fr); }
  .chapter { padding-left: var(--space-6); }
  .chapter::before { left: calc(-3px - var(--space-6)); width: var(--space-6); font-size: 8.5px; }
}

/* == 15. 列印（A4；寬表切橫式命名頁） ======================================= */
@page {
  size: A4 portrait;
  margin: 15mm 13mm 14mm;
}

@page wide {
  size: A4 landscape;
  margin: 12mm 11mm 12mm;
}

@media print {
  :root {
    --fs-micro: 6.5pt;
    --fs-mini: 7pt;
    --fs-body: 8pt;
    --fs-ui: 9pt;
    --fs-lead: 12pt;
    --fs-num: 15pt;
    --fs-display: 24pt;
    --lead: 1.4;
  }

  body { background: var(--paper); font-size: var(--fs-ui); }

  .sheet {
    max-width: none;
    margin: 0;
    padding: 0;
    border: 0;
  }

  .doc { display: block; }

  /* 封面獨佔一頁 */
  .cover {
    min-height: 62vh;
    padding-top: var(--space-8);
    break-after: page;
    margin-bottom: 0;
  }

  .exec { break-after: page; }

  /* 列印目錄：改頁碼型（頁碼由 render 兩趟量測後回填） */
  .toc {
    position: static;
    break-after: page;
    font-size: var(--fs-body);
  }
  .toc ol { columns: 2; column-gap: var(--space-8); }
  .toc li { break-inside: avoid; }
  .toc a { grid-template-columns: 2.4em 1fr auto auto; text-decoration: none; }
  .toc-page {
    display: inline-block;
    font-family: var(--font-mono);
    color: var(--text-2);
    min-width: 2.2em;
    text-align: right;
  }
  .toc-page::before {
    content: "";
    display: inline-block;
    width: 1.6em;
    border-bottom: 1px dotted var(--line);
    margin-right: var(--space-2);
    vertical-align: middle;
  }

  .chapter {
    break-before: page;
    padding-bottom: var(--space-6);
    margin-bottom: 0;
  }

  .chapter-head { break-after: avoid; }
  .chapter h3, .chapter h4 { break-after: avoid; }

  .finding-card,
  .concern-card,
  .audit-attn-item,
  .report-table-panel,
  .mat-row,
  .sev-box,
  figure.chart-static { break-inside: avoid; }

  /* 表格：表頭在每頁重複，捲動改為換行（anywhere＝塞得進紙面的保證） */
  .report-table-wrap { overflow: visible; }
  .report-table { table-layout: auto; width: 100%; }
  .report-table thead { display: table-header-group; }
  .report-table thead th { position: static; }
  .report-table tbody tr { break-inside: avoid; }
  /* 一般表格用 break-word：anywhere 會連數字都拆（tri-grid 裡實測把
     「1,132,920」折成兩行），只有寬表為了保證塞得下才放寬成 anywhere。 */
  .report-table tbody td,
  .report-table thead th,
  .th-label { overflow-wrap: break-word; }
  .table-hint { display: none; }

  /* 寬表列印保命（自舊殼 report_css.py 移植，勿刪）。
     TABLE_JS 的 measureColumnWidths() 在**螢幕**載入時量測後，把結果寫成
     inline style：table.style.width / table.style.minWidth、每個 th 的
     style.width、以及 col 的 style.width。inline style 不分 media，會原封
     不動帶進列印，把表格撐成螢幕自動寬度，再被 .report-table-panel 整段裁掉。
       · 2026-07-23 視覺實檢：發現與行動表近半內容消失（舊殼因此有這一段）；
       · 2026-08-30 於新殼重現：11 欄寬表在 A4 橫式量到 table 2479px / panel
         1014px，直式 2479px / 674px。
     只有 !important 蓋得過 inline style，所以這裡用 !important 把 JS 寫進去的
     寬度釋放掉。釋放規則只要 table / col / thead th 三條就是全部覆蓋：
     report_css.py 裡 12 個 .style.width / .style.minWidth 寫入點全落在
     table、th、col，沒有一個碰 td，所以 td 上無事可放。
     下面四組欄寬下限跟著升成 !important，是為了整組對稱一致；實測只有
     --landscape 的 .col-long { width: 30% } 真的 load-bearing——拿掉 !important
     之後 9 欄直式的欄寬逐欄與出貨版相同、PDF 缺漏 0，11 欄橫式也只有 col-long
     的份額從 305px 掉到 93px、缺漏 0。
     這裡刻意不碰 table-layout。版面政策（直式 auto、橫式 fixed）是設計檔明文
     的裁決（.report-table-panel--landscape .report-table { table-layout: fixed }），
     一條為了相容 JS 而移植進來的規則不該把它靜默翻掉。 */
  .report-table { width: 100% !important; min-width: 0 !important; }
  .report-table col { width: auto !important; min-width: 0 !important; }
  .report-table thead th { width: auto !important; min-width: 0 !important; }
  .report-table-panel { overflow: visible; }

  /* 寬表：8–9 欄留在直式縮排版；≥10 欄才切橫式命名頁（每切一次就多一個
     分頁，audit 全切會多出 5 頁近乎空白的紙）。橫式頁改 table-layout: fixed
     ——auto 佈局會被 change_detail 長文吃掉版面，把欄名壓成「SE VE RIT Y」。 */
  .report-table-panel--wide .report-table { font-size: 6.5pt; }
  .report-table-panel--wide .report-table tbody td,
  .report-table-panel--wide .report-table thead th { padding: 2px 4px; }

  /* 2026-08-05 使用者截圖實證的破版：這裡原本把寬表的每一格都設成
     overflow-wrap: anywhere（理由是「保證塞得進紙面」）。副作用是每一欄的
     min-content 都降到一個字元，auto 佈局於是把版面全讓給 max-content 最大
     的長文欄（change_detail），meta 欄被壓成逐字直排：「SEVERITY」印成
     「SE VE RI TY」、「success」印成「suc ces s」、時間戳印成六行。
     改法：anywhere 只留給長文欄自己（它本來就要逐字塞），meta 欄回到
     break-word ＋ 一個可讀下限，長文欄再給一個上限份額把版面還回去。 */
  .report-table-panel--wide .report-table tbody td,
  .report-table-panel--wide .report-table thead th,
  .report-table-panel--wide .th-label { overflow-wrap: break-word; }
  .report-table-panel--wide .report-table td.col-long,
  .report-table-panel--wide .report-table td.col-long .cell-long-full,
  .report-table-panel--wide .report-table th.col-long .th-label { overflow-wrap: anywhere; }
  /* 長文欄的份額。直式（table-layout: auto）用 em 下限——百分比的 min-width
     在表格儲存格上等同 auto（實測：給 24% 時 change_detail 仍只拿到 20px，
     版面全被同列另一個長值欄的 max-content 吃走），em 才是硬底線。
     橫式頁是 table-layout: fixed，改吃 width 百分比切欄。 */
  .report-table-panel--wide .report-table td.col-long,
  .report-table-panel--wide .report-table th.col-long { min-width: 14em !important; }
  .report-table-panel--landscape .report-table td.col-long,
  .report-table-panel--landscape .report-table th.col-long { width: 30% !important; }
  /* meta 欄的可讀下限（6.5pt 下 5.5em ≈ 48px，放得下 SEVERITY／success）；
     時間戳欄放寬到 7.5em，讓「T…Z」那半段整段留在一行。 */
  .report-table-panel--wide .report-table tbody td:not(.num):not(.col-long),
  .report-table-panel--wide .report-table thead th:not(.num):not(.col-long) {
    min-width: 5.5em !important;
    max-width: 12em !important;
  }
  .report-table-panel--wide .report-table td.col-ts,
  .report-table-panel--wide .report-table th.col-ts { min-width: 7.5em !important; }
  .report-table td.num, .report-table th.num { overflow-wrap: normal; }

  .report-table-panel--landscape { page: wide; }
  .report-table-panel--landscape .report-table {
    table-layout: fixed;
    width: 100%;
  }

  /* 長文欄：摘要收起、全文展開（列印不可只留省略號）。
     收合的 <details> 是靠 ::details-content 的 content-visibility: hidden 藏
     內容，只把子元素設 display:block 沒有用——2026-08-03 實測：不解這行，
     15 段 change_detail 全文完全不進 PDF 文字層（無聲截斷）。 */
  .cell-long::details-content { content-visibility: visible; }
  .cell-long > summary { display: none; }
  .cell-long > .cell-long-full {
    display: block;
    white-space: pre-wrap;
    margin: 0;
    border: 0;
    padding: 0;
    background: none;
  }

  /* 三欄版式在 A4 直式只有 ~695px：第三欄窄到表格 min-content 塞不下，
     panel 的 overflow:hidden 會把數字右半截無聲切掉（2026-08-03 逐頁實檢
     抓到「966,315」被切成「966,31」）。列印改兩欄。 */
  .tri-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }

  .toc a:hover { color: var(--text-2); }
  .print-btn { display: none; }
  .print-only { display: block; }
  .screen-only { display: none; }
  .appendix { break-before: page; }
}
"""


# Tone vocabulary of the shell. Anything outside this set degrades to
# "neutral" rather than emitting an attribute the CSS has no rule for.
TONES: tuple[str, ...] = ("ok", "warn", "crit", "info", "neutral")

# Report severity vocabulary -> the shell's five tones. Copied from
# design/v2/tools/reskin_report.py (src must not import from design/).
# CRITICAL and HIGH share a tone; the solid-vs-outlined badge rule in
# SHELL_CSS is what keeps the two levels apart.
SEVERITY_TONE: dict[str, str] = {
    "CRITICAL": "crit",
    "HIGH": "crit",
    "MEDIUM": "warn",
    "LOW": "info",
    "INFO": "neutral",
    "OK": "ok",
    "GOOD": "ok",
    "PASS": "ok",
}
SEVERITY_RANK: tuple[str, ...] = (
    "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "PASS", "GOOD", "OK",
)

# Column count at which a table stops fitting an A4 portrait page and gets its
# own landscape named page. 8-9 columns still read fine portrait; see the wide
# table policy in SHELL_CSS section 12.
WIDE_TABLE_LANDSCAPE_COLS = 10

_KIND_LABEL_KEY: dict[str, str] = {
    "exec": "rpt_shell_kind_exec",
    "finding": "rpt_shell_kind_finding",
    "detail": "rpt_shell_kind_detail",
}

# Section kinds the shell knows. Anything else degrades to "detail".
KINDS: tuple[str, ...] = tuple(_KIND_LABEL_KEY)

# Marker token embedded in SHELL_CSS. scripts/audit_i18n_usage.py scopes its
# Cat C exemption to the literal containing it, so it must not be edited away;
# tests/test_report_shell_renderer.py asserts it is still there.
SHELL_CSS_PORT_MARKER = "shell-css-port-v2"

# The section id the appendix element carries (see _render_appendix). A
# ShellSection must not reuse it or the in-page anchors collide.
APPENDIX_SECTION_ID = "appendix"


def _esc(value: object) -> str:
    """Escape an untrusted scalar for HTML text or attribute context."""
    return _html.escape("" if value is None else str(value), quote=True)


def _tone(value: str) -> str:
    return value if value in TONES else "neutral"


def _kind(value: str) -> str:
    """Whitelist a section kind the way ``_tone()`` whitelists a tone.

    Without this a typo would emit an unknown ``data-shell`` value and an
    empty ``.chapter-eyebrow`` — the kind label would silently disappear
    instead of failing loudly.
    """
    return value if value in KINDS else "detail"


def _kind_label(kind: str, lang: str) -> str:
    key = _KIND_LABEL_KEY.get(kind)
    return t(key, lang=lang) if key else ""


@dataclass(frozen=True)
class ShellCover:
    """Cover data. Every field is a PCE-sourced value and gets escaped here."""

    title: str
    doc_title: str
    type_label: str
    eyebrow: str = ""
    kicker: str = ""
    grade: str = ""
    score: str = ""
    badges: tuple[tuple[str, str], ...] = ()
    meta: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ShellSection:
    """One chapter. ``html`` is already-rendered, already-escaped markup."""

    id: str
    title: str
    html: str
    kind: str = "detail"
    tone: str = "neutral"
    marks: dict[str, int] = field(default_factory=dict)


def wide_table_attrs(n_cols: int, lang: str) -> tuple[str, str]:
    """Extra panel class + hint paragraph for a table with ``n_cols`` columns.

    Returns ``("", "")`` below the landscape threshold so callers can splice
    the result in unconditionally.

    This returns ``--landscape`` ONLY. It is not self-sufficient: every print
    column-width guarantee in SHELL_CSS (the long-text column's share, the
    readable floor for meta columns, the timestamp floor, the reduced font)
    hangs off ``--wide``, and ``--landscape`` on its own gets ``page: wide`` and
    ``table-layout: fixed`` with none of those floors. The prototype never
    emits ``--landscape`` without ``--wide``
    (``design/v2/tools/reskin_report.py:323``), and today
    ``table_renderer.py``'s threshold of 8 means every >=10 column table is
    already ``--wide``. Callers must keep it that way.
    """
    if n_cols < WIDE_TABLE_LANDSCAPE_COLS:
        return ("", "")
    hint = t("rpt_shell_table_hint_wide", lang=lang, cols=n_cols)
    return (" report-table-panel--landscape",
            f'<p class="table-hint">{_esc(hint)}</p>')


def _mark_chips(marks: dict[str, int]) -> str:
    """Every mark with a non-zero count gets a chip — no cap, no silent drop.

    ``.chapter-marks`` is flex-wrap, so there is no layout reason to truncate,
    and ``chips[:3]`` silently lost the lower severities in the prototype.
    Ranked severities come first in severity order; anything the rank list does
    not know about is appended rather than dropped.

    Zero counts are deliberately NOT rendered: ``{"CRITICAL": 0}`` means "no
    CRITICAL marks in this chapter", and a chip reading "CRITICAL 0" would read
    as a finding rather than the absence of one. This is a decision, not the
    truncation bug above — the number of chips varies with what is present, but
    nothing that is present is ever dropped.
    """
    if not marks:
        return ""
    chips: list[str] = []
    for sev in SEVERITY_RANK:
        count = marks.get(sev)
        if count:
            chips.append(_mark_chip(sev, count))
    for sev, count in marks.items():
        if sev in SEVERITY_RANK or not count:
            continue
        chips.append(_mark_chip(sev, count))
    return "".join(chips)


def _mark_chip(sev: str, count: int) -> str:
    tone = SEVERITY_TONE.get(str(sev).upper(), "neutral")
    return (f'<span class="mark-chip" data-tone="{tone}">'
            f"{_esc(sev)} {_esc(count)}</span>")


def _render_cover(cover: ShellCover, doc_tone: str) -> str:
    badges = "".join(
        f'<span class="badge" data-tone="{_tone(tone)}">{_esc(text)}</span>'
        for text, tone in cover.badges
    )
    if cover.grade:
        # A1: the chip carries data-tone and no inline colour; the grade -> tone
        # mapping is grade_colors.grade_tone(). The score rides along inside the
        # chip the way the original cover printed "F (25.8/100)".
        # .grade-chip is inline-flex, which collapses whitespace *between* its
        # children — a plain space here renders as "D52.4/100". The separator
        # has to live inside the span.
        score = (f'<span class="score-denom">&#160;{_esc(cover.score)}</span>'
                 if cover.score else "")
        badges += (
            f'<span class="grade-chip" data-tone="{grade_tone(cover.grade)}">'
            f"{_esc(cover.grade)}{score}</span>"
        )
    elif cover.score:
        # A score with no grade still has to reach the page. Nesting it inside
        # the `if cover.grade:` branch dropped it from the document entirely —
        # no chip, no text, no warning (the silent-truncation class this repo
        # keeps re-hitting). No chip is drawn because there is no grade to
        # colour it by, so the tone is neutral.
        badges += (f'<span class="score-denom" data-tone="neutral">'
                   f"{_esc(cover.score)}</span>")
    meta = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>"
                   for k, v in cover.meta.items())
    return (
        f'<header class="cover" data-shell="cover" data-tone="{_tone(doc_tone)}">'
        + (f'<p class="cover-eyebrow">{_esc(cover.eyebrow)}</p>'
           if cover.eyebrow else "")
        + f"<h1>{_esc(cover.title)}</h1>"
        + (f'<p class="cover-kicker">{_esc(cover.kicker)}</p>'
           if cover.kicker else "")
        + (f'<div class="cover-badges">{badges}</div>' if badges else "")
        + (f'<dl class="cover-meta">{meta}</dl>' if meta else "")
        + "</header>"
    )


def _render_toc(entries: Sequence[ShellSection], lang: str) -> str:
    title = t("rpt_shell_toc_title", lang=lang)
    items = "".join(
        f'<li data-tone="{_tone(section.tone)}">'
        f'<a href="#{_esc(section.id)}">'
        f'<span class="toc-num">{index:02d}</span>'
        f'<span class="toc-label">{_esc(section.title)}</span>'
        f'<span class="toc-dot"></span></a></li>'
        for index, section in enumerate(entries)
    )
    return (
        f'<nav class="toc" data-shell="toc" aria-label="{_esc(title)}">'
        f'<button class="print-btn" onclick="window.print()">'
        f'{_esc(t("rpt_nav_print_pdf", lang=lang))}</button>'
        f"<h2>{_esc(title)}</h2><ol>{items}</ol></nav>"
    )


def _render_appendix(*, lang: str, cover: ShellCover,
                     numbered: Sequence[ShellSection],
                     rule_index: Sequence[tuple[str, str, str]],
                     appendix_html: str) -> str:
    meta = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>"
                   for k, v in cover.meta.items())
    # Same sequence and same numbers as the TOC — the index covers every
    # section (brief: "章節索引(自 sections)"), exec chapters included.
    chapter_dl = "".join(
        f"<dt>{index:02d}</dt><dd>{_esc(section.title)}</dd>"
        for index, section in enumerate(numbered)
    )
    rules = ""
    if rule_index:
        items = "".join(
            f'<li data-tone="{SEVERITY_TONE.get(str(sev).upper(), "neutral")}">'
            f"<code>{_esc(code)}</code><span>{_esc(name)}</span>"
            f'<span class="rule-sev">{_esc(sev)}</span></li>'
            for code, name, sev in rule_index
        )
        rules = (f'<h3>{_esc(t("rpt_shell_appendix_rules", lang=lang))}</h3>'
                 f'<ol class="rule-index">{items}</ol>')
    return (
        f'<section class="appendix" data-shell="appendix"'
        f' id="{APPENDIX_SECTION_ID}">'
        f'<h2>{_esc(t("rpt_shell_appendix_title", lang=lang))}</h2>'
        '<div class="appendix-grid">'
        f'<div><h3>{_esc(t("rpt_shell_appendix_params", lang=lang))}</h3>'
        f"<dl>{meta}</dl></div>"
        f'<div><h3>{_esc(t("rpt_shell_appendix_chapters", lang=lang))}</h3>'
        f"<dl>{chapter_dl}</dl></div>"
        "</div>"
        + rules
        + (f'<div class="colophon">{appendix_html}</div>' if appendix_html else "")
        + "</section>"
    )


def build_shell_document(*, lang: str, cover: ShellCover,
                         sections: Sequence[ShellSection],
                         appendix_html: str = "",
                         rule_index: Sequence[tuple[str, str, str]] = (),
                         extra_head: str = "",
                         include_table_js: bool = True) -> str:
    """Render a complete, offline-openable v2 report document.

    Section order is the caller's order — the shell never re-sorts chapters.
    ``ShellSection.html`` and ``appendix_html``/``extra_head`` are trusted as
    already-escaped rendered markup; every scalar on ``ShellCover`` and
    ``ShellSection`` is escaped here.

    Numbering: there is exactly one sequence — ``exec`` sections first, then
    the chapters, both in caller order — and all three places a number is
    shown read from it. The TOC prints ``{i:02d}`` from 00 (brief), the chapter
    header prints the same digits with an ``S`` prefix, and the appendix index
    lists every section under the same digits. Numbering each of the three
    independently only looks consistent when there is exactly one exec section.

    ``id="appendix"`` is reserved for the appendix element; a ``ShellSection``
    must not use it or the in-page anchors collide.
    """
    ordered = list(sections)
    execs = [s for s in ordered if _kind(s.kind) == "exec"]
    chapters = [s for s in ordered if _kind(s.kind) != "exec"]
    # The single numbering sequence. Chapters start at len(execs).
    numbered = execs + chapters

    # Document tone — read from the FINDING chapters only, never from every
    # chapter (G1). The cover's tone is a claim about what the report found, and
    # a detail chapter's tint is not that claim: while this looked at all
    # chapters, a single CRITICAL cell in an unrelated table (unmanaged hosts,
    # vulnerability exposure, infrastructure scoring) tinted its chapter and,
    # because critical wins outright, dyed the cover of a report with zero
    # findings. Restricting the source decouples the two: a chapter is free to
    # colour itself from its own content without speaking for the document.
    #
    # No finding chapter at all -> neutral, not "the first chapter's tone". A
    # report that never looks for findings (traffic, network inventory) has made
    # no finding to report, and neutral says exactly that; borrowing chapter 1's
    # tint would make the cover assert a severity nothing measured.
    finding_chapters = [s for s in chapters if _kind(s.kind) == "finding"]
    doc_tone = next(
        (_tone(s.tone) for s in finding_chapters if _tone(s.tone) == "crit"),
        _tone(finding_chapters[0].tone) if finding_chapters else "neutral",
    )

    parts = [_render_cover(cover, doc_tone)]
    for section in execs:
        parts.append(
            f'<section class="exec" id="{_esc(section.id)}" data-shell="exec"'
            f' data-tone="{_tone(section.tone)}">'
            f"<h2>{_esc(section.title)}</h2>{section.html}</section>"
        )
    parts.append(_render_toc(numbered, lang))

    chapter_html = "".join(
        f'<section class="chapter" id="{_esc(section.id)}"'
        f' data-shell="{_kind(section.kind)}" data-tone="{_tone(section.tone)}">'
        '<div class="chapter-head">'
        # ASCII chapter number: CJK gets split and re-spaced in the PDF text
        # layer, so the two-pass page-number probe anchors on S00/S01/...
        f'<span class="chapter-index">S{len(execs) + offset:02d}</span>'
        f'<span class="chapter-eyebrow">'
        f'{_esc(_kind_label(_kind(section.kind), lang))}</span>'
        f'<h2 class="chapter-title">{_esc(section.title)}</h2>'
        f'<span class="chapter-marks">{_mark_chips(section.marks)}</span>'
        f"</div>{section.html}</section>"
        for offset, section in enumerate(chapters)
    )
    parts.append(f'<div class="chapters">{chapter_html}</div>')
    parts.append(_render_appendix(lang=lang, cover=cover, numbered=numbered,
                                  rule_index=rule_index,
                                  appendix_html=appendix_html))

    lang_attr = "zh-TW" if lang == "zh_TW" else "en"
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{lang_attr}"><head>\n'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{_esc(cover.doc_title)}</title>\n"
        f"<style>\n{SHELL_CSS}</style>\n"
        + extra_head
        + "</head>\n"
        + f'<body data-report-title="{_esc(cover.type_label)}">'
        + '<div class="sheet"><div class="doc">'
        + "".join(parts)
        + "</div></div>"
        + (TABLE_JS if include_table_js else "")
        + "</body></html>"
    )
