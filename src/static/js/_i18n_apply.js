// data-i18n / data-i18n-placeholder / data-i18n-title 套用翻譯文字。
// 原本是 index.html 內的 inline <script>，因 CSP script-src 移除
// 'unsafe-inline' 而外移成獨立檔案；依賴 _init_bootstrap.js 先設好
// window._INIT_TRANSLATIONS（deferred script 依 document 順序執行，故此檔
// 需排在 _init_bootstrap.js 之後載入）。
(function () {
  'use strict';
  var t = window._INIT_TRANSLATIONS;
  if (!t) return;
  function apply() {
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var v = t[el.getAttribute('data-i18n')];
      if (!v) return;
      var icon = el.querySelector('svg');
      if (icon) {
        var nodes = Array.from(el.childNodes).filter(function (n) { return n.nodeType === 3; });
        if (nodes.length) nodes[nodes.length - 1].textContent = ' ' + v;
        else el.appendChild(document.createTextNode(' ' + v));
      } else { el.textContent = v; }
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      var v = t[el.getAttribute('data-i18n-placeholder')];
      if (v) el.placeholder = v;
    });
    document.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      var v = t[el.getAttribute('data-i18n-title')];
      if (v) el.title = v;
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply);
  else apply();
})();
