import { type FormEvent, useCallback, useEffect, useState } from "react";

import { type ApiError, call } from "../../api/client";
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
          <div className="card">
            <h2>{t("security_account_title")}</h2>
            <dl className="kv-list">
              <dt>{t("login_username")}</dt>
              <dd>{view.username}</dd>
            </dl>
          </div>
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

registerNav({ section: "system", path: "/system/security", labelKey: "nav_system_security", order: 40, component: Security });
