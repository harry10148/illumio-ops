import { Link, NavLink, Route, Routes } from "react-router-dom";

import { call, setCsrfToken } from "../api/client";
import type { Me } from "../api/generated";
import { t } from "../i18n";
import { Home } from "../pages/Home";
import { allNavItems, navItems } from "./nav";

/** Pages fire this after changing something /api/auth/me reports (password, language). */
export const ME_CHANGED_EVENT = "illumio-ops:me-changed";

export function notifyMeChanged(): void {
  window.dispatchEvent(new Event(ME_CHANGED_EVENT));
}

interface Props {
  me: Me;
  onSignedOut: () => void;
}

export function Shell({ me, onSignedOut }: Props) {
  const system = navItems("system");

  async function signOut() {
    await call("auth.logout");
    setCsrfToken(null);
    onSignedOut();
  }

  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">{t("app_name")}</span>
        <span className="topbar-spacer" />
        <span className="user">{me.username}</span>
        <button type="button" className="btn-quiet" onClick={signOut}>
          {t("user_menu_logout")}
        </button>
      </header>
      <nav className="sidenav">
        <NavLink to="/" end className="nav-item">
          {t("nav_home")}
        </NavLink>
        {system.length > 0 && (
          <>
            <div className="nav-section">{t("nav_section_system")}</div>
            {system.map((item) => (
              <NavLink key={item.path} to={item.path} className="nav-item">
                {t(item.labelKey)}
              </NavLink>
            ))}
          </>
        )}
      </nav>
      <main className="content">
        {me.default_password_in_use && (
          <p className="shell-banner banner" data-tone="warn" role="status">
            {t("banner_default_password")} <Link to="/system/security">{t("banner_default_password_link")}</Link>
          </p>
        )}
        <Routes>
          <Route path="/" element={<Home />} />
          {allNavItems().map(({ path, component: Page }) => (
            <Route key={path} path={path} element={<Page />} />
          ))}
          <Route path="*" element={<Home />} />
        </Routes>
      </main>
    </div>
  );
}
