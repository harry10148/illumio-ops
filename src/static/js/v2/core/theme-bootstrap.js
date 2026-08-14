// theme-bootstrap.js — paints the persisted theme/density before first paint.
//
// This is the FOUC-prevention half of theme.mjs (same "ov2.theme" /
// "ov2.density" localStorage keys, applied to the same
// document.documentElement.dataset attributes theme.mjs owns after boot).
// It is deliberately NOT an ES module and NOT an inline <script> block:
//
//   - not inline: this app's CSP (src/gui/__init__.py's Talisman config) is
//     `script-src: ["'self'"]` with no 'unsafe-inline' and no nonce
//     injection (`content_security_policy_nonce_in=[]`). The mockup's
//     equivalent (design/v2/mockup/index.html:9-19) is an inline <script>
//     block, which this CSP silently blocks in a real browser — copying it
//     verbatim into base.html would look fixed in a diff and do nothing at
//     runtime. An external same-origin file is the only CSP-compatible way
//     to run something this early.
//   - not a module: `type="module"` scripts are deferred by spec (they run
//     after the document is parsed) — that defeats the point. This must
//     block HTML parsing and run before <body> paints, so base.html loads
//     it as a plain classic `<script src="...">` in <head>, before the
//     stylesheet links, with no `type`/`defer`/`async`.
//
// theme.mjs owns every change after this point; this file only ever reads.
(function () {
  try {
    var th = window.localStorage.getItem("ov2.theme");
    var de = window.localStorage.getItem("ov2.density");
    if (th === "light" || th === "dark") document.documentElement.dataset.theme = th;
    if (de === "cozy" || de === "compact") document.documentElement.dataset.density = de;
  } catch (e) { /* private mode: fall back to the markup defaults */ }
})();
