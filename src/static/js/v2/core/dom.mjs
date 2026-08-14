// dom.mjs — the only DOM construction helper in the mockup.
// Everything is built with createElement/textContent: no innerHTML anywhere in
// design/v2/mockup, so snapshot strings can never become markup.

/**
 * el(tag, attrs?, ...children) -> HTMLElement
 *   attrs keys:
 *     class      -> className
 *     text       -> textContent
 *     on<Event>  -> addEventListener(event.toLowerCase(), fn)
 *     anything else -> setAttribute(key, String(value)); null/undefined/false skips
 *   children: Node | string | number | array | null (nullish skipped)
 */
export function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = String(v);
      else if (k.length > 2 && k.slice(0, 2) === "on" && typeof v === "function") {
        node.addEventListener(k.slice(2).toLowerCase(), v);
      } else node.setAttribute(k, v === true ? "" : String(v));
    });
  }
  append(node, children);
  return node;
}

const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * svg(tag, attrs?, ...children) -> SVGElement
 * Same contract as el(), in the SVG namespace — createElementNS is mandatory
 * there, and the no-innerHTML rule applies to charts exactly as it does to
 * panels. `class` goes through setAttribute because SVGElement.className is a
 * read-only SVGAnimatedString.
 */
export function svg(tag, attrs, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      const v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "text") node.textContent = String(v);
      else if (k.length > 2 && k.slice(0, 2) === "on" && typeof v === "function") {
        node.addEventListener(k.slice(2).toLowerCase(), v);
      } else node.setAttribute(k, v === true ? "" : String(v));
    });
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  children.forEach(function (c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) append(node, c);
    else if (c instanceof Node) node.appendChild(c);
    else node.appendChild(document.createTextNode(String(c)));
  });
  return node;
}

export function clear(node) {
  while (node && node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/** Replace the contents of `node` with `children`. */
export function fill(node, ...children) {
  clear(node);
  return append(node, children);
}

/** <span class="mono"> for numerals — every figure in the console is tabular. */
export function mono(value) {
  return el("span", { class: "mono", text: value });
}

/** A flex spacer, used by every footer/header row. */
export function spacer() {
  return el("span", { class: "spacer" });
}

/** The × affordance shared by drawer and modal headers. */
export function closeButton(label, onClick) {
  const b = el("button", { class: "iconbtn", type: "button", "aria-label": label, text: "×" });
  b.addEventListener("click", onClick);
  return b;
}

// Stack of live dismissible() entries, oldest first. Only the LAST entry
// (the most recently opened, still-open dialog) is "topmost" and allowed to
// react to Escape / an outside click — see dismissible()'s own doc comment
// for why this has to be stack-aware, not just per-instance.
const dismissStack = [];

/**
 * Close on Escape / outside click. Returns a dispose() that is safe to re-run.
 *
 * Stack-aware: every open dialog (drawer.mjs, modal.mjs, palette.mjs,
 * healthbar.mjs's popovers) calls this once. Dialogs nest — Tasks 4-9 open a
 * confirm modal on top of a drawer immediately (rule editing, destructive
 * actions) — and two bugs showed up as soon as that happens:
 *
 *   1. Escape closed BOTH layers. Each call adds its own capture-phase
 *      `keydown` listener on `document`; `stopPropagation()` does not stop
 *      sibling listeners registered on the *same* node, only
 *      `stopImmediatePropagation()` does. With two listeners live, one
 *      Escape press ran both handlers — and since the drawer registered
 *      first, IT closed first, which is backwards (the top layer should
 *      close first).
 *   2. A mousedown inside the modal closed the drawer underneath it. The
 *      modal is mounted on `document.body`, not inside the drawer's
 *      `<aside>`, so `!node.contains(e.target)` was true for the drawer's
 *      own outside-click check on every click inside the modal.
 *
 * Fix: a shared stack of entries. Only the topmost entry's handlers act;
 * everyone else no-ops until they become topmost again. `dispose()` removes
 * ITS OWN entry wherever it is in the stack (not just the top), so a drawer
 * closed programmatically while its modal is still open does not leave a
 * stale reference at the top — the modal (or whatever is now newest) simply
 * becomes topmost.
 */
export function dismissible(node, onDismiss) {
  let live = true;
  const entry = {};
  function isTop() { return live && dismissStack[dismissStack.length - 1] === entry; }
  function onKey(e) {
    if (e.key !== "Escape" || !isTop()) return;
    e.stopImmediatePropagation();
    dispose();
    onDismiss();
  }
  function onDown(e) {
    if (!isTop() || node.contains(e.target)) return;
    dispose();
    onDismiss();
  }
  function dispose() {
    if (!live) return;
    live = false;
    const i = dismissStack.indexOf(entry);
    if (i >= 0) dismissStack.splice(i, 1);
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("mousedown", onDown, true);
  }
  document.addEventListener("keydown", onKey, true);
  document.addEventListener("mousedown", onDown, true);
  dismissStack.push(entry);
  return dispose;
}

const FOCUSABLE_SELECTOR = [
  "a[href]", "button:not([disabled])", "textarea:not([disabled])",
  "input:not([disabled])", "select:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function focusableIn(root) {
  return Array.from(root.querySelectorAll(FOCUSABLE_SELECTOR)).filter(function (n) {
    return n.offsetWidth > 0 || n.offsetHeight > 0 || n === document.activeElement;
  });
}

/**
 * trapFocus(el) -> dispose()
 * Confines Tab / Shift+Tab to `el`'s focusable descendants (wrapping at both
 * ends) and moves focus onto the first one immediately. Shared by drawer.mjs
 * and modal.mjs so both dialogs implement exactly one focus trap.
 *
 * dispose() only removes the keydown listener — it does NOT restore focus.
 * Only the caller knows what "the opener" was (it captured
 * document.activeElement before building the dialog), so restoring focus is
 * the caller's job, done from its own close().
 */
export function trapFocus(el) {
  function onKey(e) {
    if (e.key !== "Tab") return;
    const items = focusableIn(el);
    if (!items.length) { e.preventDefault(); return; }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey) {
      if (active === first || !el.contains(active)) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (active === last || !el.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    }
  }
  el.addEventListener("keydown", onKey);
  const items = focusableIn(el);
  if (items.length) items[0].focus();
  else if (typeof el.focus === "function") el.focus();
  return function dispose() {
    el.removeEventListener("keydown", onKey);
  };
}
