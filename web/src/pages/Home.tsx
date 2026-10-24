import { t } from "../i18n";

export function Home() {
  return (
    <section className="page">
      <h1>{t("nav_home")}</h1>
      <div className="card">
        <h2>{t("home_pce_title")}</h2>
        <p className="muted">{t("home_pce_not_checked")}</p>
      </div>
    </section>
  );
}
