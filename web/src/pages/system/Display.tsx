import { type FormEvent, useEffect, useState } from "react";

import { type ApiError, call } from "../../api/client";
import type { DisplayView } from "../../api/generated";
import { t } from "../../i18n";
import { notifyMeChanged } from "../../shell/Shell";
import { registerNav } from "../../shell/nav";

export function Display() {
  const [view, setView] = useState<DisplayView | null>(null);
  const [language, setLanguage] = useState<DisplayView["language"]>("en");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void call("system.display.get").then((env) => {
      if (env.ok && env.data) {
        setView(env.data);
        setLanguage(env.data.language);
      } else setError(env.error);
    });
  }, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!view) return;
    setBusy(true);
    const env = await call("system.display.update", { revision: view.revision, language });
    setBusy(false);
    if (env.ok && env.data) {
      setView(env.data);
      setError(null);
      notifyMeChanged(); // the app reloads the dictionary for the new language
    } else setError(env.error);
  }

  return (
    <section className="page">
      <h1>{t("nav_system_display")}</h1>
      {error && <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>}
      {view && (
        <form className="card form-grid" onSubmit={save}>
          <label>
            {t("display_language")}
            <select name="language" value={language} onChange={(e) => setLanguage(e.target.value as DisplayView["language"])}>
              <option value="en">English</option>
              <option value="zh_TW">繁體中文</option>
            </select>
            <span className="hint">{t("display_language_hint")}</span>
          </label>
          <div className="actions">
            <button type="submit" className="btn-primary" disabled={busy}>{t("btn_save")}</button>
          </div>
        </form>
      )}
    </section>
  );
}

registerNav({ section: "system", path: "/system/display", labelKey: "nav_system_display", order: 50, component: Display });
