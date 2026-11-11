import { useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { call, setCsrfToken } from "../api/client";
import type { Me, ShellStatus } from "../api/generated";
import { t } from "../i18n";
import { type NavItem, allNavItems, navItems } from "./nav";
import { ShellStatusContext, useShellStatusPoll } from "./status";

/** Pages fire this after changing something /api/auth/me reports (password, language). */
export const ME_CHANGED_EVENT = "illumio-ops:me-changed";

export function notifyMeChanged(): void {
  window.dispatchEvent(new Event(ME_CHANGED_EVENT));
}

interface Props {
  me: Me;
  onSignedOut: () => void;
}

const COLLECTION_KEYS: Record<ShellStatus["collection"], string> = {
  ok: "shell_collection_ok", degraded: "shell_collection_degraded", failing: "shell_collection_failing",
  not_started: "shell_collection_not_started",
};
const COLLECTION_TONES: Record<ShellStatus["collection"], string> = {
  ok: "ok", degraded: "high", failing: "crit", not_started: "muted",
};

function StatusLine({ status }: { status: ShellStatus | null }) {
  if (!status) return <div className="nav-status muted">…</div>;
  const mode = status.mode === "basic" ? `● ${t("mode_basic")}` : `◆ ${t("mode_advanced")}`;
  return (
    <div className="nav-status" data-role="shell-status">
      <span data-tone={status.mode === "basic" ? "ok" : "adv"} className="nav-status-mode">{mode}</span>
      <span>・</span>
      <span data-tone={COLLECTION_TONES[status.collection]} className="nav-status-collection">
        {t(COLLECTION_KEYS[status.collection])}
      </span>
    </div>
  );
}

function Item({ item, status, onPick }: { item: NavItem; status: ShellStatus | null; onPick: () => void }) {
  const dimmed = item.needs === "advanced" && status?.mode === "basic";
  const count = item.badge === "new" ? status?.new_alerts ?? 0 : 0;
  return (
    <NavLink to={item.to ?? item.path} end={item.path === "/"} className="nav-item" onClick={onPick}
             data-dimmed={dimmed || undefined} data-nav={item.path}>
      <span>{t(item.labelKey)}{dimmed && <span className="nav-mark" title={t("needs_advanced_title")}> ◆</span>}</span>
      {count > 0 && (
        <span className="nav-badge num" data-role="nav-new" aria-label={t("nav_alerts_new_label", { n: String(count) })}>
          {t("nav_alerts_new", { n: String(count) })}
        </span>
      )}
    </NavLink>
  );
}

/** The System page's own list: every system page, in the order the spec gives (§3). */
function SystemNav() {
  return (
    <nav className="subnav" aria-label={t("nav_system")}>
      {navItems("system").map((item) => (
        <NavLink key={item.path} to={item.path} className="subnav-item">{t(item.labelKey)}</NavLink>
      ))}
    </nav>
  );
}

export function Shell({ me, onSignedOut }: Props) {
  const status = useShellStatusPoll();
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const systemFirst = navItems("system")[0]?.path;
  const inSystem = location.pathname.startsWith("/system");

  async function signOut() {
    await call("auth.logout");
    setCsrfToken(null);
    onSignedOut();
  }

  const close = () => setMenuOpen(false);
  return (
    <ShellStatusContext.Provider value={status}>
      <div className="shell">
        <nav className="sidenav" aria-label={t("nav_main")} data-open={menuOpen || undefined}>
          <div className="nav-brand">
            <span className="brand">{t("app_name")}</span>
            <button type="button" className="btn-quiet nav-toggle" aria-expanded={menuOpen}
                    onClick={() => setMenuOpen((o) => !o)}>{t("nav_menu")}</button>
          </div>
          <StatusLine status={status} />
          <div className="nav-items">
            {navItems("main").map((item) => <Item key={item.path} item={item} status={status} onPick={close} />)}
            {navItems("output").length > 0 && <div className="nav-section">{t("nav_section_output")}</div>}
            {navItems("output").map((item) => <Item key={item.path} item={item} status={status} onPick={close} />)}
            <div className="nav-spacer" />
            {navItems("bottom").map((item) => <Item key={item.path} item={item} status={status} onPick={close} />)}
            {systemFirst && (
              <NavLink to={systemFirst} className={inSystem ? "nav-item active" : "nav-item"} onClick={close}
                       data-nav="/system">
                <span>{t("nav_system")}</span>
              </NavLink>
            )}
            <div className="nav-user">
              <span>{me.username}</span>
              <button type="button" className="btn-link" onClick={signOut}>{t("user_menu_logout")}</button>
            </div>
            {status && (
              <div className="nav-version num" data-role="product-version">{t("shell_version", { version: status.version })}</div>
            )}
          </div>
        </nav>
        <main className="content">
          {me.default_password_in_use && (
            <p className="shell-banner banner" data-tone="high" role="status">
              {t("banner_default_password")} <Link to="/system/security">{t("banner_default_password_link")}</Link>
            </p>
          )}
          {inSystem && <SystemNav />}
          <Routes>
            {allNavItems().map(({ path, component: Page }) => (
              <Route key={path} path={path} element={<Page />} />
            ))}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </ShellStatusContext.Provider>
  );
}
