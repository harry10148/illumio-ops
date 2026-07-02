// CSP-friendly event delegation. Replaces inline on*= attributes.
//
// Click (M1 backward compat):
//   <button data-action="switchTab" data-args='["dashboard"]'>...</button>
//
// Other events (M1 follow-up):
//   <select data-on-change="onUiThemeModeChange" data-arg-source="value">
//   <input  data-on-keydown="rsDoSearch" data-on-keydown-key="Enter">
//   <input type="checkbox" data-on-change="toggleAll" data-arg-source="self">
//   <input  data-on-change="loadEventViewer" data-args='[true]'>
//
// data-arg-source overrides data-args. Values: "value" | "checked" | "self".
// Functions are looked up on window.* so existing globals keep working.
//
// data-pass-event="1"（opt-in，極少數情境用，例如需要 stopImmediatePropagation
// 或以觸發元素定位 popover）：在 data-args/data-arg-source 算出的參數尾端，
// 額外附加原生 event 與觸發元素兩個參數。不開這個屬性時行為完全不變，
// 避免既有 handler 的可選參數（如 body = {}）被意外覆蓋。
(function () {
    'use strict';

    function dispatch(target, eventName, e) {
        // Resolve function name. data-action is the click-only legacy form.
        var fnName;
        if (eventName === 'click' && target.dataset.action) {
            fnName = target.dataset.action;
        } else {
            var dsKey = 'on' + eventName.charAt(0).toUpperCase() + eventName.slice(1);
            fnName = target.dataset[dsKey];
        }
        if (!fnName) return;

        // keydown can filter by key name (e.g. data-on-keydown-key="Enter").
        if (eventName === 'keydown') {
            var wantKey = target.dataset.onKeydownKey;
            if (wantKey && e.key !== wantKey) return;
        }

        var fn = window[fnName];
        if (typeof fn !== 'function') {
            console.warn('[dispatcher] no function:', fnName);
            return;
        }

        // Build args. data-arg-source takes precedence over data-args.
        var args = [];
        if (target.dataset.args) {
            try {
                args = JSON.parse(target.dataset.args);
            } catch (err) {
                console.warn('[dispatcher] bad data-args:', target.dataset.args);
                return;
            }
        }
        var src = target.dataset.argSource;
        if (src === 'value') args = [target.value];
        else if (src === 'checked') args = [target.checked];
        else if (src === 'self') args = [target];

        if (target.dataset.passEvent) args = args.concat([e, target]);

        fn.apply(target, args);
    }

    function delegate(eventName) {
        document.addEventListener(eventName, function (e) {
            // For click, also accept the legacy data-action selector.
            var selector = eventName === 'click'
                ? '[data-action], [data-on-click]'
                : '[data-on-' + eventName + ']';
            var target = e.target.closest(selector);
            if (!target) return;
            dispatch(target, eventName, e);
        });
    }

    delegate('click');
    delegate('change');
    delegate('input');
    delegate('keydown');
})();
