// CSP-safe bootstrap: 從 #i18n-data / #gui-init-data 兩個 application/json
// script 讀出初始化資料，掛到 window 供後續各模組使用。
// 原本是 index.html 內的 inline <script>，因 CSP script-src 移除
// 'unsafe-inline' 而外移成獨立檔案。
(function () {
  'use strict';
  var i18nEl = document.getElementById('i18n-data');
  window._INIT_TRANSLATIONS = i18nEl ? JSON.parse(i18nEl.textContent) : {};

  var initEl = document.getElementById('gui-init-data');
  var initData = initEl ? JSON.parse(initEl.textContent) : {};
  window._CACHE_AVAILABLE = !!initData.cache_available;
})();
