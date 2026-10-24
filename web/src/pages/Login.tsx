import { type FormEvent, useState } from "react";

import { type ApiError, call, setCsrfToken } from "../api/client";
import type { LoginResult } from "../api/generated";
import { t } from "../i18n";

interface Props {
  onSignedIn: (result: LoginResult) => void;
}

export function Login({ onSignedIn }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const env = await call("auth.login", { username, password });
    setBusy(false);
    if (env.ok && env.data) {
      setCsrfToken(env.data.csrf_token);
      onSignedIn(env.data);
    } else {
      setError(env.error);
      setPassword("");
    }
  }

  return (
    <div className="center-page">
      <form className="card auth-card" onSubmit={submit}>
        <div className="brand">{t("app_name")}</div>
        <h1>{t("login_title")}</h1>
        <label>
          {t("login_username")}
          <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label>
          {t("login_password")}
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {t(error.message_key, error.params)}
          </p>
        )}
        <button type="submit" className="btn-primary" disabled={busy}>
          {t("login_submit")}
        </button>
      </form>
    </div>
  );
}
