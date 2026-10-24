import { NavLink, Route, Routes } from "react-router-dom";

import { call, setCsrfToken } from "../api/client";
import { t } from "../i18n";
import { Home } from "../pages/Home";
import { allNavItems, navItems } from "./nav";

interface Props {
  username: string;
  onSignedOut: () => void;
}

export function Shell({ username, onSignedOut }: Props) {
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
        <span className="user">{username}</span>
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
