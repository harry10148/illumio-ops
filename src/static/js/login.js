// 登入頁的表單處理邏輯。原本是 login.html 內的 inline <script>，因 CSP
// script-src 移除 'unsafe-inline'（見 src/gui/__init__.py）而外移成獨立檔案。
// i18n 字串改由 #login-i18n-data（application/json，不受 CSP script-src 影響）
// 提供，於 src/gui/routes/auth.py 的 login_page() 產生。
(function () {
  'use strict';

  const form = document.getElementById('login-form');
  const changeForm = document.getElementById('change-pw-form');
  const btn = document.getElementById('login-btn');
  const changeBtn = document.getElementById('change-pw-btn');

  const i18nEl = document.getElementById('login-i18n-data');
  const i18n = i18nEl ? JSON.parse(i18nEl.textContent) : {};

  // First-run state: capture CSRF token from /api/login so the inline
  // change-password POST to /api/security can satisfy CSRF.
  let _csrfToken = '';

  function showFieldError(inputId, errId, message) {
    const input = document.getElementById(inputId);
    const errEl = document.getElementById(errId);
    input.classList.add('error');
    errEl.textContent = message;
    errEl.classList.add('visible');
  }

  function clearFieldErrors() {
    document.querySelectorAll('.input.error').forEach(el => el.classList.remove('error'));
    document.querySelectorAll('.err.visible').forEach(el => {
      el.classList.remove('visible');
      el.textContent = '';
    });
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;

    clearFieldErrors();
    btn.textContent = i18n.signing_in;
    btn.disabled = true;

    try {
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (data.ok) {
        if (data.must_change_password) {
          // Capture CSRF token, swap the page to the change-password form,
          // then POST /api/security with the new password.
          _csrfToken = data.csrf_token || '';
          btn.textContent = i18n.btn_default;
          btn.disabled = false;
          form.style.display = 'none';
          changeForm.style.display = '';
          document.getElementById('new-password').focus();
          return;
        }
        btn.textContent = i18n.success;
        setTimeout(() => { window.location.href = '/'; }, 300);
      } else {
        showFieldError('password', 'err-password', data.error || i18n.invalid_auth);
        btn.textContent = i18n.btn_default;
        btn.disabled = false;
        document.getElementById('password').value = '';
        document.getElementById('password').focus();
      }
    } catch {
      showFieldError('password', 'err-password', i18n.network_error);
      btn.textContent = i18n.btn_default;
      btn.disabled = false;
    }
  });

  changeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const newPw = document.getElementById('new-password').value;
    const confirmPw = document.getElementById('confirm-password').value;

    clearFieldErrors();

    if (newPw.length < 8) {
      showFieldError('new-password', 'err-new-password', i18n.pw_too_short);
      return;
    }
    if (newPw !== confirmPw) {
      showFieldError('confirm-password', 'err-confirm-password', i18n.mismatch);
      return;
    }

    changeBtn.textContent = i18n.changing;
    changeBtn.disabled = true;

    try {
      const res = await fetch('/api/security', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': _csrfToken
        },
        body: JSON.stringify({
          new_password: newPw,
          confirm_password: confirmPw
        })
      });
      const data = await res.json();
      if (data.ok) {
        changeBtn.textContent = i18n.success;
        setTimeout(() => { window.location.href = '/'; }, 300);
      } else {
        showFieldError('new-password', 'err-new-password', data.error || i18n.invalid_auth);
        changeBtn.textContent = i18n.change_btn_default;
        changeBtn.disabled = false;
      }
    } catch {
      showFieldError('new-password', 'err-new-password', i18n.network_error);
      changeBtn.textContent = i18n.change_btn_default;
      changeBtn.disabled = false;
    }
  });
})();
