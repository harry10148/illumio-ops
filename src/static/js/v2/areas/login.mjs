// login.mjs — the standalone v2 login page (login.html). Anchors LG-01/LG-02
// (design/v2/coverage.yaml — that gate only runs against the frozen mockup,
// see gate_coverage.py, so data-cov here is kept for idiom consistency with
// every other ported area, not because any CI gate reads it from this file).
//
// PORT OF design/v2/mockup/js/areas/login.mjs against the live backend, with
// every ?demo=* / mock-only surface deleted. Differences from the frozen
// mockup:
//   1. The mockup drove all UI state off an outcome PICKER
//      (?demo=ok|first-login|invalid|invalid-form|signed-out — its
//      OUTCOMES/RESPONSES tables and apply(outcome)) instead of a real
//      response. That whole mechanism — the picker chrome, the RESPONSES
//      echo table, the mock request-pane (verifyPane, "POST /api/login\n...
//      "+ canned response text) and the LG-03 "signed out" card — is
//      deleted. There is no distinct signed-out *screen* in the real
//      product: POST /logout 302s straight back to this same page
//      (auth.py:141-145), so LG-03 has no real counterpart to build.
//      LG-01/LG-02 are now driven directly by the real POST /api/login and
//      POST /api/security responses.
//   2. must_change_password comes from auth.py's real response field
//      (auth.py:129-137), not a picked outcome; LG-02 only ever appears
//      when the server actually says so, and only after a real
//      username/password pair has authenticated.
//   3. The "appliance plate" aside (status/tls_status snapshots) and its
//      quiet request-pane card are both dropped, not ported: their backing
//      endpoints (/api/status, /api/tls_status) sit behind the same
//      before_request auth gate as every other /api/* route
//      (src/gui/__init__.py's security_check), so an anonymous visitor
//      cannot reach them. The mockup calls the plate "already available
//      before authentication" — true in its snapshot world, false against
//      this backend. A v2 user sees the same appliance details once
//      authenticated, at #/system/pce.
//   4. store.load(id) -> api.load()/api.post() (core/api.mjs); the one
//      shared CSRF-refresh-and-retry implementation lives there (see that
//      file's header) — no second CSRF mechanism is added here. The
//      csrf-token <meta> this page renders server-side (login.html) stays
//      valid across POST /api/login (flask-login's login_user() only adds
//      keys to the existing session, per flask_login/utils.py:180-187 — it
//      never clears session['csrf_token']), so the immediate follow-up
//      POST /api/security for the first-login branch needs no special
//      token handling either.
//   5. i18n: the runtime catalogue (GET /api/ui_translations) is itself an
//      authenticated /api/* route (same gate as #3), so the one, anonymous
//      i18n.init() call this page ever makes (at boot, before login) is
//      EXPECTED to fail and every t() call below falls back to its own
//      English `fallback` argument for the page's entire lifetime,
//      including LG-02 — core/i18n.mjs's own documented degrade path (see
//      its initI18n() comment), not a bug here. A second, post-login
//      i18n.init() call was tried and reverted: while must_change_password
//      is still true, /api/ui_translations sits behind
//      src/gui/__init__.py's SEPARATE must_change_password 423 gate (not
//      just the anonymous-401 one), whose exemption list is
//      config.api_security_get/post + auth.logout/api_csrf_token only — and
//      api.mjs's own rawRequest() treats ANY 423 must_change_password
//      response as "navigate the whole page to /login" (core/api.mjs's
//      documented 423 handling). Verified directly: calling i18n.init()
//      here mid-first-login does not just fail to localize LG-02, it
//      force-navigates the browser away to the legacy /login page before
//      the operator ever sees the change-password form. So this module
//      calls api.* for exactly two things — POST /api/login and POST
//      /api/security — and nothing else while must_change_password could be
//      pending.
//   6. i18n keys: the mockup's login_* fallback keys are the product's own
//      SPA-facing keys, rendered server-side by src/gui/routes/auth.py's
//      Jinja login.html — but src/gui/_helpers.py:_ui_translation_dict only
//      ships gui_/sched_/status_/error_/pd_-prefixed keys through
//      /api/ui_translations, so a login_* key can never resolve through
//      t() here (regardless of auth state). Every visible string below is
//      either an existing gui_-prefixed product key reused verbatim
//      (gui_theme*, gui_density*, gui_err_invalid_auth, gui_err_network,
//      gui_err_generic, gui_field_required) or a newly minted gui_login_*
//      key carrying the exact text of its login_* sibling
//      (src/i18n_en.json / src/i18n_zh_TW.json).
//   7. Field-level errors returned by the server are already localized text
//      (auth.py and config.py's api_security_post both call
//      t(..., lang=lang) before responding) — shown as-is, not re-run
//      through client t(). The one exception is auth.py:98's literal,
//      untranslated "invalid_form" string: the server intentionally
//      withholds detail there (a pydantic validation message can embed the
//      submitted password, per auth.py's own comment), so the client maps
//      that literal to a generic, already-existing gui_err_generic string.
//   8. Teardown: none needed. This module owns the whole page for its
//      entire lifetime — there is no router here and no other area is ever
//      mounted alongside it.

import { el, spacer } from "../core/dom.mjs";
import { t, i18n } from "../core/i18n.mjs";
import { api } from "../core/api.mjs";
import { initDisplay, theme, density } from "../core/theme.mjs";

function field(key, labelText, type, autocomplete) {
  const input = el("input", { class: "field", type: type });
  input.dataset.field = key;
  input.autocomplete = autocomplete || "off";
  const err = el("div", { class: "fld-err", role: "alert", "aria-live": "assertive", hidden: true });
  const box = el("div", { class: "fld" }, el("label", null, el("span", { text: labelText })), input, err);
  box.input = input;
  box.err = err;
  return box;
}

function setError(box, message) {
  box.err.hidden = !message;
  box.err.textContent = message || "";
  if (message) box.input.classList.add("bad");
  else box.input.classList.remove("bad");
}

function btn(cls, text, onClick) {
  return el("button", { class: cls, type: "button", text: text, onClick: onClick });
}

function segmented(labelText, options, get, set) {
  const box = el("div", { class: "seg" });
  const buttons = [];
  options.forEach(function (pair) {
    const b = el("button", { type: "button", text: pair[1] });
    b.addEventListener("click", function () {
      set(pair[0]);
      buttons.forEach(function (p) { p[1].setAttribute("aria-pressed", p[0] === get() ? "true" : "false"); });
    });
    buttons.push([pair[0], b]);
    box.appendChild(b);
  });
  buttons.forEach(function (p) { p[1].setAttribute("aria-pressed", p[0] === get() ? "true" : "false"); });
  return el("div", { class: "grp" }, el("div", { class: "eyebrow", text: labelText }), box);
}

function build(root) {
  // ── chrome: brand + theme/density, same as every other v2 page ──
  const brand = el("a", { class: "brand", href: "/v2/login" },
    el("b", { text: "illumio" }), el("i"), el("span", { text: "ops" }));
  const skin = el("div", { class: "topright" },
    segmented(t("gui_theme", "Theme"),
      [["dark", t("gui_theme_dark", "Dark")], ["light", t("gui_theme_light", "Light")]],
      function () { return theme.get(); }, function (v) { theme.set(v); }),
    segmented(t("gui_density", "Density"),
      [["cozy", t("gui_density_cozy", "Cozy")], ["compact", t("gui_density_compact", "Compact")]],
      function () { return density.get(); }, function (v) { density.set(v); }));
  root.appendChild(el("header", { class: "chrome" }, el("div", { class: "topbar" }, brand, spacer(), skin)));

  const wrap = el("div", { class: "loginwrap" });
  root.appendChild(wrap);

  // ── LG-01 sign-in ────────────────────────────────────────────────────
  const userBox = field("username", t("gui_login_username", "Username"), "text", "username");
  userBox.input.placeholder = t("gui_login_username_placeholder", "Enter username");
  userBox.input.required = true;
  const passBox = field("password", t("gui_login_password", "Password"), "password", "current-password");
  passBox.input.placeholder = t("gui_login_password_placeholder", "Enter password");
  passBox.input.required = true;
  const signIn = btn("btn primary wide", t("gui_login_btn", "Sign in"), submit);
  const loginForm = el("form", { class: "loginform" }, userBox, passBox, signIn);
  loginForm.addEventListener("submit", function (e) { e.preventDefault(); submit(); });

  const cardHeading = el("h1", { text: t("gui_login_header", "PCE Ops") });
  const cardSub = el("p", { class: "sub", text: t("gui_login_subheader", "Illumio operations and monitoring portal") });
  const card = el("section", { class: "logincard", "data-cov": "LG-01" }, cardHeading, cardSub, loginForm);

  // ── LG-02 first-login password change (hidden until must_change_password) ──
  const newBox = field("new_password", t("gui_login_new_password", "New password"), "password", "new-password");
  const cfmBox = field("confirm_password", t("gui_login_confirm_password", "Confirm new password"), "password", "new-password");
  newBox.input.minLength = 12;
  cfmBox.input.minLength = 12;
  const changeBtn = btn("btn primary wide", t("gui_login_change_pw_btn", "Change password and continue"), changePassword);
  const pwForm = el("form", { class: "loginform" }, newBox, cfmBox, changeBtn);
  pwForm.addEventListener("submit", function (e) { e.preventDefault(); changePassword(); });

  const pwHeading = el("h1", { text: t("gui_login_header", "PCE Ops") });
  const pwBanner = el("p", { class: "banner", "data-tone": "warn", text: t("gui_login_must_change_banner",
    "First-time setup: please choose a new password to continue. The default 'illumio' password cannot be reused.") });
  const pwCard = el("section", { class: "logincard", "data-cov": "LG-02", hidden: true }, pwHeading, pwBanner, pwForm);

  wrap.appendChild(card);
  wrap.appendChild(pwCard);
  wrap.appendChild(el("footer", { class: "loginfoot" },
    el("span", { text: t("gui_login_footer", "Illumio PCE Ops | Security Operations") })));

  // No post-login i18n re-fetch here — see header note 5 for why that is
  // actively unsafe (not just unhelpful) while must_change_password is true.
  function showMustChange() {
    card.hidden = true;
    pwCard.hidden = false;
    newBox.input.focus();
  }

  /* auth.py:104-138 — the real POST /api/login. 401 -> gui_err_invalid_auth
   * (already localized server-side); 400 -> the literal "invalid_form"
   * (auth.py:98, intentionally untranslated — see header note 7); 200 ->
   * {ok:true, csrf_token, must_change_password}. */
  async function submit() {
    setError(userBox, "");
    setError(passBox, "");
    const username = userBox.input.value.trim();
    const password = passBox.input.value;
    if (!username) { setError(userBox, t("gui_field_required", "required")); return; }
    if (!password) { setError(passBox, t("gui_field_required", "required")); return; }

    signIn.disabled = true;
    signIn.textContent = t("gui_login_btn_signing_in", "Signing in...");

    let r;
    try {
      r = await api.post("/api/login", { username: username, password: password });
    } catch (e) {
      setError(passBox, t("gui_err_network", "Network error. Please try again later."));
      signIn.disabled = false;
      signIn.textContent = t("gui_login_btn", "Sign in");
      return;
    }

    if (r && r.ok === true) {
      if (r.must_change_password) {
        signIn.disabled = false;
        signIn.textContent = t("gui_login_btn", "Sign in");
        showMustChange();
        return;
      }
      signIn.textContent = t("gui_login_btn_success", "Signed in");
      window.location.href = "/v2";
      return;
    }

    const msg = (r && r.error === "invalid_form")
      ? t("gui_err_generic", "An error occurred. Please try again.")
      : (r && r.error) || t("gui_err_invalid_auth", "Invalid username or password.");
    setError(passBox, msg);
    passBox.input.value = "";
    passBox.input.focus();
    signIn.disabled = false;
    signIn.textContent = t("gui_login_btn", "Sign in");
  }

  /* login.js:87-118 / config.py:98-112 — 12 characters minimum and the two
   * boxes must match, both checked client-side before the POST; the server
   * repeats both checks and is the source of truth. must_change_password
   * true means the server does NOT require old_password here
   * (config.py:99-105), matching this form's fields exactly. */
  async function changePassword() {
    setError(newBox, "");
    setError(cfmBox, "");
    const newPw = newBox.input.value;
    const cfmPw = cfmBox.input.value;
    if (newPw.length < 12) {
      setError(newBox, t("gui_login_err_pw_short", "Password must be at least 12 characters."));
      return;
    }
    if (newPw !== cfmPw) {
      setError(cfmBox, t("gui_login_err_pw_mismatch", "Passwords do not match."));
      return;
    }

    changeBtn.disabled = true;
    changeBtn.textContent = t("gui_login_btn_changing", "Changing password...");

    let r;
    try {
      r = await api.post("/api/security", { new_password: newPw, confirm_password: cfmPw });
    } catch (e) {
      setError(newBox, t("gui_err_network", "Network error. Please try again later."));
      changeBtn.disabled = false;
      changeBtn.textContent = t("gui_login_change_pw_btn", "Change password and continue");
      return;
    }

    if (r && r.ok === true) {
      changeBtn.textContent = t("gui_login_btn_success", "Signed in");
      window.location.href = "/v2";
      return;
    }

    setError(newBox, (r && r.error) || t("gui_err_generic", "An error occurred. Please try again."));
    changeBtn.disabled = false;
    changeBtn.textContent = t("gui_login_change_pw_btn", "Change password and continue");
  }
}

async function boot() {
  initDisplay();
  await i18n.init(); // best-effort pre-auth; see header note 5
  const root = document.getElementById("login-root");
  build(root);
  document.body.dataset.booted = "true";
}

boot();
