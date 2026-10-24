import { type FormEvent, useState } from "react";

import { type ApiError, call, setCsrfToken } from "../api/client";
import { t } from "../i18n";

interface Props {
  requireOld: boolean;
  onChanged: () => void;
}

const LIMITS = { min: "12", max: "512" };

export function PasswordChange({ requireOld, onChanged }: Props) {
  const [oldPassword, setOld] = useState("");
  const [newPassword, setNew] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const env = await call("auth.password", {
      old_password: requireOld ? oldPassword : null,
      new_password: newPassword,
      confirm_password: confirm,
    });
    setBusy(false);
    if (env.ok && env.data) {
      setCsrfToken(env.data.csrf_token);
      onChanged();
    } else {
      setError(env.error);
    }
  }

  return (
    <form className="card auth-card" onSubmit={submit}>
      <h1>{t("pw_change_title")}</h1>
      {!requireOld && <p className="muted">{t("pw_change_intro")}</p>}
      {requireOld && (
        <label>
          {t("pw_old")}
          <input type="password" autoComplete="current-password" value={oldPassword}
                 onChange={(e) => setOld(e.target.value)} required />
        </label>
      )}
      <label>
        {t("pw_new")}
        <input type="password" autoComplete="new-password" value={newPassword}
               onChange={(e) => setNew(e.target.value)} required minLength={12} maxLength={512} />
        <span className="hint">{t("pw_rule", LIMITS)}</span>
      </label>
      <label>
        {t("pw_confirm")}
        <input type="password" autoComplete="new-password" value={confirm}
               onChange={(e) => setConfirm(e.target.value)} required />
      </label>
      {error && (
        <p className="form-error" role="alert">
          {t(error.message_key, error.params)}
        </p>
      )}
      <button type="submit" className="btn-primary" disabled={busy}>
        {t("pw_submit")}
      </button>
    </form>
  );
}
