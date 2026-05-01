// CSP-friendly event delegation. Replaces inline onclick= attributes.
// Patterns:
//   <button data-action="switchTab" data-args='["dashboard"]'>...</button>
//
// Functions are looked up on window.* so existing globals keep working.
(function() {
    'use strict';
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;
        const fnName = target.dataset.action;
        const fn = window[fnName];
        if (typeof fn !== 'function') {
            console.warn('[dispatcher] no function:', fnName);
            return;
        }
        let args = [];
        if (target.dataset.args) {
            try {
                args = JSON.parse(target.dataset.args);
            } catch (err) {
                console.warn('[dispatcher] bad data-args:', target.dataset.args);
                return;
            }
        }
        fn.apply(target, args);
    });
})();
