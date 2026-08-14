// theme.mjs — data-theme / data-density on <html>, persisted in localStorage.
// The shell writes data-theme before first paint (inline bootstrap in index.html);
// this module owns every change after that.

const KEY_THEME = "ov2.theme";
const KEY_DENSITY = "ov2.density";

const THEMES = ["dark", "light"];
const DENSITIES = ["cozy", "compact"];

const listeners = new Set();

function read(key, allowed, dflt) {
  let v = null;
  try { v = window.localStorage.getItem(key); } catch (e) { v = null; }
  return allowed.indexOf(v) >= 0 ? v : dflt;
}

function write(key, value) {
  try { window.localStorage.setItem(key, value); } catch (e) { /* private mode: in-memory only */ }
}

function emit() {
  listeners.forEach(function (fn) { fn(theme.get(), density.get()); });
}

export const theme = {
  get() { return document.documentElement.dataset.theme === "light" ? "light" : "dark"; },
  set(value) {
    const next = THEMES.indexOf(value) >= 0 ? value : "dark";
    document.documentElement.dataset.theme = next;
    write(KEY_THEME, next);
    emit();
    return next;
  },
  toggle() { return this.set(this.get() === "dark" ? "light" : "dark"); },
  stored() { return read(KEY_THEME, THEMES, "dark"); },
};

export const density = {
  get() { return document.documentElement.dataset.density === "compact" ? "compact" : "cozy"; },
  set(value) {
    const next = DENSITIES.indexOf(value) >= 0 ? value : "cozy";
    document.documentElement.dataset.density = next;
    write(KEY_DENSITY, next);
    emit();
    return next;
  },
  toggle() { return this.set(this.get() === "cozy" ? "compact" : "cozy"); },
  stored() { return read(KEY_DENSITY, DENSITIES, "cozy"); },
};

/** Apply the persisted preferences. Called once at boot. */
export function initDisplay() {
  document.documentElement.dataset.theme = theme.stored();
  document.documentElement.dataset.density = density.stored();
}

/** onDisplayChange(fn) -> unsubscribe. fn(theme, density). */
export function onDisplayChange(fn) {
  listeners.add(fn);
  return function () { listeners.delete(fn); };
}
