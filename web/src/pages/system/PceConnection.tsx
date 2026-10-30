import { type FormEvent, useCallback, useEffect, useState } from "react";

import { type ApiError, call } from "../../api/client";
import type { PceConnection as Conn, ProbeRun } from "../../api/generated";
import { ProbeResults } from "../../components/ProbeResults";
import { t } from "../../i18n";
import { registerNav } from "../../shell/nav";

type TlsMode = "system" | "bundle" | "off";

const SAAS_CONSOLE = "https://console.illum.io";

interface Form {
  url: string;
  org_id: string;
  api_key: string;
  api_secret: string;
  deployment_type: Conn["deployment_type"];
  console_url: string;
  tls: TlsMode;
  ca_path: string;
  write_api_key: string;
  write_api_secret: string;
  write_saved: boolean;
  clear_write_key: boolean;
}

function toForm(c: Conn): Form {
  const tls: TlsMode = typeof c.verify_tls === "string" ? "bundle" : c.verify_tls ? "system" : "off";
  return {
    url: c.url,
    org_id: c.org_id,
    api_key: c.api_key,
    api_secret: c.api_secret,
    deployment_type: c.deployment_type,
    console_url: c.console_url ?? "",
    tls,
    ca_path: typeof c.verify_tls === "string" ? c.verify_tls : "",
    write_api_key: c.write_api_key,
    write_api_secret: c.write_api_secret,
    write_saved: Boolean(c.write_api_key || c.write_api_secret),
    clear_write_key: false,
  };
}

/** Server field paths ("pce.url" from settings validation, "url" from request validation) → form field. */
function fieldOf(error: ApiError | null): string | null {
  if (!error?.field) return null;
  return error.field.replace(/^pce\./, "").replace(/^verify_tls.*/, "ca_path");
}

function FieldError({ name, error }: { name: string; error: ApiError | null }) {
  if (fieldOf(error) !== name || !error) return null;
  return <span className="field-error">{t(error.message_key, error.params)}</span>;
}

export function PceConnection() {
  const [revision, setRevision] = useState<number | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [resetNote, setResetNote] = useState<{ moved: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<ProbeRun | null>(null);

  const load = useCallback(async () => {
    const [conn, latest] = await Promise.all([call("system.pce.get"), call("system.pce.latest")]);
    if (conn.ok && conn.data) {
      setForm(toForm(conn.data));
      setRevision(conn.data.revision);
      setError(null);
    } else {
      setError(conn.error);
    }
    if (latest.ok && latest.data) setRun(latest.data.run);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!form || revision === null) {
    return error ? <p className="form-error">{t(error.message_key, error.params)}</p> : <p className="muted">{t("loading")}</p>;
  }

  const set = <K extends keyof Form>(key: K, value: Form[K]) => {
    setForm({ ...form, [key]: value });
    setSaved(false);
  };

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form || revision === null) return;
    setBusy(true);
    const verify_tls = form.tls === "bundle" ? form.ca_path : form.tls === "system";
    const env = await call("system.pce.update", {
      revision,
      url: form.url.trim(),
      org_id: form.org_id.trim(),
      api_key: form.api_key,
      api_secret: form.api_secret,
      deployment_type: form.deployment_type,
      console_url: form.console_url.trim() || null,
      verify_tls,
      write_api_key: form.clear_write_key ? "" : form.write_api_key,
      write_api_secret: form.clear_write_key ? "" : form.write_api_secret,
      clear_write_key: form.clear_write_key,
    });
    setBusy(false);
    if (env.ok && env.data) {
      setForm(toForm(env.data));
      setRevision(env.data.revision);
      setError(null);
      setSaved(true);
      setResetNote(env.data.reset ? { moved: env.data.reset.archive_moved_to } : null);
    } else {
      setError(env.error);
      setSaved(false);
    }
  }

  async function test() {
    setBusy(true);
    const env = await call("system.pce.probe");
    setBusy(false);
    if (env.ok && env.data) {
      setRun(env.data);
      setError(null);
    } else {
      setError(env.error);
    }
  }

  const generalError = error && !fieldOf(error) ? error : null;
  // SaaS: the API lives on a regional host and people sign in through Illumio Console;
  // on-prem: one PCE address for both (spec §6.5, health check and URLs).
  const saas = form.deployment_type === "saas";

  return (
    <section className="page">
      <h1>{t("nav_system_pce")}</h1>
      <form className="card form-grid" onSubmit={save}>
        <label>
          {t("pce_url")}
          <input name="url" value={form.url} onChange={(e) => set("url", e.target.value)}
                 placeholder={saas ? "https://xx-scpN.illum.io:443" : "https://pce.example.com:8443"} />
          <span className="hint">{t(saas ? "pce_url_hint_saas" : "pce_url_hint_on_prem")}</span>
          <FieldError name="url" error={error} />
        </label>
        <label>
          {t("pce_org_id")}
          <input name="org_id" inputMode="numeric" value={form.org_id} onChange={(e) => set("org_id", e.target.value)} />
          <FieldError name="org_id" error={error} />
        </label>
        <label>
          {t("pce_api_key")}
          <input name="api_key" autoComplete="off" value={form.api_key} onChange={(e) => set("api_key", e.target.value)} />
          <span className="hint">{t("pce_key_role_hint")}</span>
          <span className="hint">{t("pce_secret_hint")}</span>
          <FieldError name="api_key" error={error} />
        </label>
        <label>
          {t("pce_api_secret")}
          <input name="api_secret" type="password" autoComplete="new-password" value={form.api_secret}
                 onChange={(e) => set("api_secret", e.target.value)} />
          <span className="hint">{t("pce_secret_hint")}</span>
        </label>
        <label>
          {t("pce_deployment")}
          <select name="deployment_type" value={form.deployment_type}
                  onChange={(e) => set("deployment_type", e.target.value as Form["deployment_type"])}>
            <option value="on_prem">{t("deployment_on_prem")}</option>
            <option value="saas">{t("deployment_saas")}</option>
          </select>
        </label>
        <label>
          {t("pce_console_url")}
          <input name="console_url" value={form.console_url} onChange={(e) => set("console_url", e.target.value)}
                 placeholder={saas ? SAAS_CONSOLE : form.url} />
          <span className="hint">{t(saas ? "pce_console_url_hint_saas" : "pce_console_url_hint_on_prem")}</span>
          <FieldError name="console_url" error={error} />
        </label>
        <label>
          {t("pce_verify_tls")}
          <select name="tls" value={form.tls} onChange={(e) => set("tls", e.target.value as TlsMode)}>
            <option value="system">{t("verify_system")}</option>
            <option value="bundle">{t("verify_bundle")}</option>
            <option value="off">{t("verify_off")}</option>
          </select>
        </label>
        {form.tls === "bundle" && (
          <label>
            {t("pce_ca_path")}
            <input name="ca_path" value={form.ca_path} onChange={(e) => set("ca_path", e.target.value)}
                   placeholder="/etc/pki/tls/certs/pce-ca.pem" />
            <FieldError name="ca_path" error={error} />
          </label>
        )}
        <fieldset>
          <legend>{t("pce_write_key_title")}</legend>
          <p className="hint">{t("pce_write_key_hint")}</p>
          <label>
            {t("pce_write_api_key")}
            <input name="write_api_key" autoComplete="off" value={form.write_api_key} disabled={form.clear_write_key}
                   onChange={(e) => set("write_api_key", e.target.value)} />
            <FieldError name="write_api_key" error={error} />
          </label>
          <label>
            {t("pce_write_api_secret")}
            <input name="write_api_secret" type="password" autoComplete="new-password" value={form.write_api_secret}
                   disabled={form.clear_write_key} onChange={(e) => set("write_api_secret", e.target.value)} />
            <span className="hint">{t("pce_secret_hint")}</span>
          </label>
          {form.write_saved && (
            <label>
              <input type="checkbox" name="clear_write_key" checked={form.clear_write_key}
                     onChange={(e) => set("clear_write_key", e.target.checked)} /> {t("pce_write_key_clear")}
            </label>
          )}
        </fieldset>
        {generalError && (
          <div className="form-error" role="alert">
            {t(generalError.message_key, generalError.params)}
            {generalError.code === "stale_revision" && (
              <button type="button" className="btn-quiet inline-action" onClick={() => void load()}>
                {t("btn_reload")}
              </button>
            )}
          </div>
        )}
        {saved && <p className="form-ok" role="status">{t("saved_ok")}</p>}
        {resetNote && (
          <p className="notice" role="status">
            {t("pce_reset_notice")}
            {resetNote.moved && <> {t("pce_reset_archive_moved", { folder: resetNote.moved })}</>}
          </p>
        )}
        <div className="actions">
          <button type="submit" className="btn-primary" disabled={busy}>{t("btn_save")}</button>
          <button type="button" className="btn-quiet" disabled={busy} onClick={() => void test()}>
            {t("btn_test_connection")}
          </button>
          <span className="hint">{t("pce_test_hint")}</span>
        </div>
      </form>
      <div className="card">
        <h2>{t("probe_results_title")}</h2>
        <ProbeResults checkedAt={run?.checked_at ?? null} results={run?.results ?? []} />
      </div>
    </section>
  );
}

registerNav({ section: "system", path: "/system/pce", labelKey: "nav_system_pce", order: 10, component: PceConnection });
