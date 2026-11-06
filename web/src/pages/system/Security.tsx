import { type FormEvent, useCallback, useEffect, useState } from "react";

import { type ApiError, call, setCsrfToken } from "../../api/client";
import type { SecurityView } from "../../api/generated";
import { t } from "../../i18n";
import { notifyMeChanged } from "../../shell/Shell";
import { registerNav } from "../../shell/nav";
import { PasswordChange } from "../PasswordChange";

const toList = (text: string) => text.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);

interface AllowedProps {
  view: SecurityView;
  onSaved: (v: SecurityView) => void;
  onReload: () => void;
}

function AllowedAddresses({ view, onSaved, onReload }: AllowedProps) {
  const [text, setText] = useState(view.allowed_ips.join("\n"));
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function save(confirmLockout: boolean) {
    setBusy(true);
    const env = await call("system.security.update", {
      revision: view.revision, allowed_ips: toList(text), confirm_lockout: confirmLockout,
    });
    setBusy(false);
    if (env.ok && env.data) {
      setError(null);
      setSaved(true);
      onSaved(env.data);
    } else {
      setSaved(false);
      setError(env.error);
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void save(false);
  };

  return (
    <form className="card" onSubmit={submit}>
      <h2>{t("security_allowed_title")}</h2>
      <p className="muted">{t("security_allowed_intro")}</p>
      <label className="block">
        {t("security_allowed_label")}
        <textarea name="allowed_ips" rows={6} className="mono" value={text}
                  onChange={(e) => { setText(e.target.value); setSaved(false); }}
                  placeholder={"192.168.1.10\n10.0.0.0/8"} />
        <span className="hint">{t("security_your_address", { ip: view.requester_ip })}</span>
      </label>
      {error && (
        <div className="form-error" role="alert">
          {t(error.message_key, error.params)}
          {error.code === "would_lock_out" && (
            <button type="button" className="btn-quiet inline-action" disabled={busy} onClick={() => void save(true)}>
              {t("security_save_anyway")}
            </button>
          )}
          {error.code === "stale_revision" && (
            <button type="button" className="btn-quiet inline-action" onClick={onReload}>
              {t("btn_reload")}
            </button>
          )}
        </div>
      )}
      {saved && <p className="form-ok" role="status">{t("saved_ok")}</p>}
      <div className="actions spaced">
        <button type="submit" className="btn-primary" disabled={busy}>{t("security_save_addresses")}</button>
      </div>
    </form>
  );
}

/** 5.x changed the admin name in its security settings; here it takes the current password and, like a password
 * change, signs everyone else out. */
function Username({ view, onChanged }: { view: SecurityView; onChanged: () => void }) {
  const [name, setName] = useState(view.username);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const env = await call("auth.username", { username: name, current_password: password });
    setBusy(false);
    setPassword("");
    if (env.ok && env.data) {
      setCsrfToken(env.data.csrf_token);
      setError(null);
      setDone(true);
      onChanged();
    } else {
      setDone(false);
      setError(env.error);
    }
  }

  return (
    <form className="card" onSubmit={submit} data-role="username-change">
      <h2>{t("security_account_title")}</h2>
      <label className="block">
        {t("login_username")}
        <input name="username" autoComplete="username" value={name} maxLength={256}
               onChange={(e) => { setName(e.target.value); setDone(false); }} />
        {error?.field === "username" && <span className="field-error">{t(error.message_key, error.params)}</span>}
      </label>
      <label className="block">
        {t("pw_old")}
        <input name="current_password" type="password" autoComplete="current-password" value={password}
               onChange={(e) => setPassword(e.target.value)} />
        {error?.field === "current_password" && <span className="field-error">{t(error.message_key, error.params)}</span>}
      </label>
      <p className="hint">{t("security_username_hint")}</p>
      {error && error.field !== "username" && error.field !== "current_password" && (
        <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>
      )}
      {done && <p className="form-ok" role="status">{t("security_username_changed")}</p>}
      <div className="actions spaced">
        <button type="submit" className="btn-primary"
                disabled={busy || !password || name.trim() === "" || name.trim() === view.username}>
          {t("security_username_save")}
        </button>
      </div>
    </form>
  );
}

export function Security() {
  const [view, setView] = useState<SecurityView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [changed, setChanged] = useState(false);

  const load = useCallback(async () => {
    const env = await call("system.security.get");
    if (env.ok && env.data) setView(env.data);
    else setError(env.error);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="page stack">
      <h1>{t("nav_system_security")}</h1>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {view && (
        <>
          {/* a rename saves the settings too: reload so the next save is not stale */}
          <Username view={view} onChanged={() => { notifyMeChanged(); void load(); }} />
          <div>
            {/* a password change saves the settings too: reload so the next save is not stale */}
            <PasswordChange requireOld onChanged={() => { setChanged(true); notifyMeChanged(); void load(); }} />
            {changed && <p className="form-ok" role="status">{t("security_password_changed")}</p>}
          </div>
          <AllowedAddresses view={view} onSaved={setView} onReload={() => void load()} />
        </>
      )}
    </section>
  );
}

registerNav({ section: "system", path: "/system/security", labelKey: "nav_system_security", order: 60, component: Security });
