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

/** Close on Escape / outside click. Returns a dispose() that is safe to re-run. */
export function dismissible(node, onDismiss) {
  let live = true;
  function onKey(e) { if (e.key === "Escape") { e.stopPropagation(); dispose(); onDismiss(); } }
  function onDown(e) { if (live && !node.contains(e.target)) { dispose(); onDismiss(); } }
  function dispose() {
    if (!live) return;
    live = false;
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("mousedown", onDown, true);
  }
  document.addEventListener("keydown", onKey, true);
  document.addEventListener("mousedown", onDown, true);
  return dispose;
}
