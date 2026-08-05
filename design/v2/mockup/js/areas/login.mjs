// login.mjs — the standalone login surface (login.html). Anchors LG-01/02/03.
//
// The product serves this page from Jinja (src/templates/login.html), not from
// the SPA, which is why its eighteen login_* strings never reach the runtime
// catalogue (_helpers.py:326-332 filters to gui_/sched_/status_/error_/pd_).
// They are therefore all in i18n-supplement.json — the login page is the single
// largest block of the Phase-2 i18n backlog.
//
// Three states, one page, transcribed from routes/auth.py + static/js/login.js:
//   LG-01  the sign-in form           POST /api/login {username, password}
//                                     401 -> gui_err_invalid_auth (auth.py:139)
//                                     400 -> the literal "invalid_form" (:98)
//   LG-02  first-login password change  the 200 response carries
//                                     must_change_password (auth.py:129-137); the
//                                     client hides the sign-in form and posts
//                                     POST /api/security {new_password,
//                                     confirm_password} with the csrf_token the
//                                     login response returned (login.js:52-63,
//                                     :100-109)
//   LG-03  signed out                 POST /logout -> session.clear() -> 302 to
//                                     /login (auth.py:141-145)
//
// HONESTY: this page authenticates nothing. "登入" does not decide an outcome —
// the outcome selector does, and every branch below is the real UI for the
// response it names. ?demo=first-login / ?demo=signed-out preselect a branch so
// a reviewer can link straight to one.
//
// The plate under the card is DESIGN-ADDED: the product's login page says
// nothing about which appliance you are signing into. On a console that can hold
// several PCE profiles, the address, version and TLS posture are the first thing
// worth knowing — and all three are already available before authentication.

import { el, clear, spacer } from "../core/dom.mjs";
import { t, initI18n } from "../core/i18n.mjs";
import { store } from "../core/store.mjs";
import { initDisplay, theme, density } from "../core/theme.mjs";
import { toast } from "../core/toast.mjs";
import { errorCard } from "../components/errorcard.mjs";
import { verifyPane } from "../components/verifypane.mjs";

// The three server outcomes the page has to render, in the order a first-time
// operator meets them.
const OUTCOMES = [
  ["ok", "v2_lg_out_ok"],
  ["first-login", "v2_lg_out_first"],
  ["invalid", "v2_lg_out_invalid"],
  ["invalid-form", "v2_lg_out_form"],
  ["signed-out", "v2_lg_out_signed"],
];

// The response line the request pane prints for each outcome. Kept as a lookup
// rather than composed from the outcome id, so no i18n key is ever built from a
// string that contains a hyphen.
const RESPONSES = [
  ["ok", "v2_lg_resp_ok"],
  ["first-login", "v2_lg_resp_first"],
  ["invalid", "v2_lg_resp_invalid"],
  ["invalid-form", "v2_lg_resp_form"],
  ["signed-out", "v2_lg_resp_signed"],
];

function btn(cls, text, onClick) {
  return el("button", { class: cls, type: "button", text: text, onClick: onClick });
}

function note(text) { return el("p", { class: "note", text: text }); }

function field(key, labelText, type, autocomplete) {
  const input = el("input", { class: "field", type: type });
  input.dataset.field = key;
  input.autocomplete = autocomplete || "off";
  const err = el("div", { class: "fld-err", role: "alert", "aria-live": "assertive", hidden: true });
  const box = el("div", { class: "fld" },
    el("label", null, el("span", { text: labelText })), input, err);
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

function plateRow(k, v, tn) {
  const b = el("b", { text: v === null || v === undefined || v === "" ? "—" : String(v) });
  if (tn) b.dataset.tone = tn;
  return el("div", { class: "kv" }, el("span", { text: k }), b);
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

function build(root, snaps) {
  const params = new URLSearchParams(window.location.search);
  const state = {};
  const wanted = params.get("demo") || "ok";
  state.outcome = OUTCOMES.some(function (p) { return p[0] === wanted; }) ? wanted : "ok";

  const status = snaps.status || {};
  const tls = snaps.tls_status || {};
  const certInfo = tls.cert_info || {};

  // ── chrome: brand only. No nav — there is nothing to navigate to yet. ──
  const brand = el("a", { class: "brand", href: "index.html" },
    el("b", { text: "illumio" }), el("i"), el("span", { text: "ops" }));
  const skin = el("div", { class: "topright" },
    segmented(t("gui_theme"), [["dark", t("gui_theme_dark")], ["light", t("gui_theme_light")]],
      function () { return theme.get(); }, function (v) { theme.set(v); }),
    segmented(t("gui_density"), [["cozy", t("v2_density_cozy")], ["compact", t("v2_density_compact")]],
      function () { return density.get(); }, function (v) { density.set(v); }));
  root.appendChild(el("header", { class: "chrome" }, el("div", { class: "topbar" }, brand, spacer(), skin)));

  const wrap = el("div", { class: "loginwrap" });
  root.appendChild(wrap);

  // ── the outcome selector: the honest replacement for a real backend ──
  const picker = el("div", { class: "loginpick" }, el("span", { class: "eyebrow", text: t("v2_lg_demo") }));
  const pickButtons = [];
  OUTCOMES.forEach(function (pair) {
    const b = btn("btn ghost", t(pair[1]), function () {
      state.outcome = pair[0];
      paintPick();
      paint();
    });
    pickButtons.push([pair[0], b]);
    picker.appendChild(b);
  });
  function paintPick() {
    pickButtons.forEach(function (p) { p[1].setAttribute("aria-pressed", p[0] === state.outcome ? "true" : "false"); });
  }

  // ── LG-01 sign-in ───────────────────────────────────────────────────
  const card = el("section", { class: "logincard", "data-cov": "LG-01" });
  const userBox = field("username", t("login_username"), "text", "username");
  userBox.input.placeholder = t("login_username_placeholder");
  userBox.input.required = true;
  const passBox = field("password", t("login_password"), "password", "current-password");
  passBox.input.placeholder = t("login_password_placeholder");
  passBox.input.required = true;
  const signIn = btn("btn primary wide", t("login_btn"), submit);
  const loginForm = el("form", { class: "loginform" }, userBox, passBox, signIn);
  loginForm.addEventListener("submit", function (e) { e.preventDefault(); submit(); });

  card.appendChild(el("h1", { text: t("login_header") }));
  card.appendChild(el("p", { class: "sub", text: t("login_subheader") }));
  card.appendChild(loginForm);

  // ── LG-02 first-login password change ───────────────────────────────
  const pwCard = el("section", { class: "logincard", "data-cov": "LG-02", hidden: true });
  const newBox = field("new_password", t("login_new_password"), "password", "new-password");
  const cfmBox = field("confirm_password", t("login_confirm_password"), "password", "new-password");
  newBox.input.minLength = 12;
  cfmBox.input.minLength = 12;
  const changeBtn = btn("btn primary wide", t("login_change_pw_btn"), changePassword);
  pwCard.appendChild(el("h1", { text: t("login_header") }));
  pwCard.appendChild(el("p", { class: "banner", "data-tone": "warn", text: t("login_must_change_banner") }));
  pwCard.appendChild(el("form", { class: "loginform" }, newBox, cfmBox, changeBtn));
  pwCard.appendChild(note(t("v2_lg_pw_rule")));
  pwCard.appendChild(note(t("v2_lg_pw_endpoint")));
  pwCard.appendChild(note(t("v2_lg_pw_csrf")));

  // ── LG-03 signed out ────────────────────────────────────────────────
  const outCard = el("section", { class: "logincard", "data-cov": "LG-03", hidden: true });
  outCard.appendChild(el("h1", { text: t("v2_lg_signed_out") }));
  outCard.appendChild(el("p", { class: "sub", text: t("v2_lg_signed_out_body") }));
  outCard.appendChild(btn("btn primary wide", t("login_btn"), function () {
    state.outcome = "ok";
    paintPick();
    paint();
  }));
  outCard.appendChild(note(t("v2_lg_logout_route")));
  outCard.appendChild(note(t("v2_lg_logout_menu")));

  // ── the appliance plate (DESIGN-ADDED) ──────────────────────────────
  const tlsTone = certInfo.expired ? "crit" : (certInfo.expiring_soon ? "warn" : (tls.enabled ? "ok" : "neutral"));
  const plate = el("aside", { class: "plate" },
    el("div", { class: "eyebrow", text: t("v2_lg_plate") }),
    plateRow(t("v2_user_pce"), String(status.api_url || "").replace(/^https?:\/\//, "")),
    plateRow(t("v2_user_version"), status.version ? "v" + status.version : null),
    plateRow(t("v2_user_timezone"), status.timezone),
    plateRow(t("gui_tls_title"), tls.enabled ? (tls.self_signed ? t("gui_tls_self_signed") : t("v2_lg_tls_ca")) : t("gui_cache_disabled"), tlsTone),
    plateRow(t("gui_tls_days_remaining"), tls.days_remaining, tlsTone),
    note(t("v2_lg_plate_why")));

  const req = el("pre", { class: "codepane" });
  const reqCard = el("section", { class: "logincard quiet" },
    el("div", { class: "eyebrow", text: t("v2_lg_request") }), verifyPane(req), note(t("v2_lg_mock")));

  wrap.appendChild(picker);
  wrap.appendChild(el("div", { class: "logingrid" },
    el("div", null, card, pwCard, outCard),
    el("div", null, plate, reqCard)));
  wrap.appendChild(el("footer", { class: "loginfoot" }, el("span", { text: t("login_footer") })));

  function paintRequest() {
    const b = {};
    b.username = userBox.input.value;
    b.password = passBox.input.value ? t("v2_lg_pw_masked") : "";
    let respKey = "v2_lg_resp_ok";
    RESPONSES.forEach(function (pair) { if (pair[0] === state.outcome) respKey = pair[1]; });
    req.textContent = "POST /api/login\n" + JSON.stringify(b, null, 2) + "\n\n" + t(respKey);
  }
  userBox.input.addEventListener("input", paintRequest);
  passBox.input.addEventListener("input", paintRequest);

  /* login.js:36-77 — the client sends the two fields, then branches on the
   * response. There is no response here, so the selected outcome IS the branch;
   * the request pane always shows what would have been sent. */
  function submit() {
    setError(userBox, "");
    setError(passBox, "");
    if (!userBox.input.value.trim()) {
      setError(userBox, t("v2_lg_required"));
      return;
    }
    if (!passBox.input.value) {
      setError(passBox, t("v2_lg_required"));
      return;
    }
    signIn.textContent = t("login_btn_signing_in");
    window.setTimeout(function () {
      signIn.textContent = t("login_btn");
      apply(state.outcome);
    }, 320);
  }

  function apply(outcome) {
    if (outcome === "invalid") {
      setError(passBox, t("gui_err_invalid_auth"));
      passBox.input.value = "";
      passBox.input.focus();
      paintRequest();
      return;
    }
    if (outcome === "invalid-form") {
      // auth.py:98 returns the literal string "invalid_form", not an i18n key —
      // pydantic's message is withheld because it embeds the submitted password
      // (auth.py:92-94). The UI has nothing translatable to show.
      setError(userBox, t("v2_lg_invalid_form"));
      paintRequest();
      return;
    }
    if (outcome === "first-login") {
      state.outcome = "first-login";
      paintPick();
      paint();
      newBox.input.focus();
      return;
    }
    if (outcome === "signed-out") {
      state.outcome = "signed-out";
      paintPick();
      paint();
      return;
    }
    signIn.textContent = t("login_btn_success");
    toast.ok(t("v2_lg_ok_note"));
  }

  /* login.js:87-118 — 12 characters minimum and the two boxes must match, both
   * checked before the POST; the server repeats both (config.py:108-111). */
  function changePassword() {
    setError(newBox, "");
    setError(cfmBox, "");
    if (newBox.input.value.length < 12) {
      setError(newBox, t("login_err_pw_short"));
      return;
    }
    if (newBox.input.value !== cfmBox.input.value) {
      setError(cfmBox, t("login_err_pw_mismatch"));
      return;
    }
    changeBtn.textContent = t("login_btn_changing");
    window.setTimeout(function () {
      changeBtn.textContent = t("login_change_pw_btn");
      toast.ok(t("v2_lg_pw_ok_note"));
    }, 320);
  }

  function paint() {
    const first = state.outcome === "first-login";
    const signed = state.outcome === "signed-out";
    card.hidden = first || signed;
    pwCard.hidden = !first;
    outCard.hidden = !signed;
    paintRequest();
  }

  // The gate cannot press the selector, so the audit hook reveals all three
  // cards at once — the same three surfaces, no fabricated state.
  window.__openAllForAudit = function () {
    card.hidden = false;
    pwCard.hidden = false;
    outCard.hidden = false;
    const out = {};
    out.opened = 3;
    out.errors = [];
    return out;
  };

  paintPick();
  paint();
}

async function boot() {
  initDisplay();
  await initI18n();
  const root = document.getElementById("login-root");
  try {
    const list = await Promise.all([store.load("status"), store.load("tls_status")]);
    const snaps = {};
    snaps.status = list[0];
    snaps.tls_status = list[1];
    build(root, snaps);
  } catch (e) {
    clear(root);
    root.appendChild(el("div", { class: "loginwrap" }, errorCard({
      id: "status / tls_status",
      error: e,
      onRetry: function () { return boot(); },
    })));
  }
  document.body.dataset.booted = "true";
}

boot();
