import { type FormEvent, useCallback, useEffect, useState } from "react";

import { type ApiError, call } from "../../api/client";
import type { CsrRequest, TlsStatus, TlsUpdate } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";

function ErrorLine({ error }: { error: ApiError | null }) {
  if (!error) return null;
  return <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>;
}

function CertCard({ status }: { status: TlsStatus }) {
  const lang = useLang();
  const cert = status.cert;
  const tone = !cert ? "neutral" : cert.days_remaining <= 0 ? "crit" : cert.days_remaining <= 30 ? "warn" : "ok";
  return (
    <div className="card">
      <h2>{t("tls_current_title")}</h2>
      {status.restart_required && <p className="banner" data-tone="warn" role="status">{t("tls_restart_required")}</p>}
      {!status.enabled && <p className="banner" data-tone="warn">{t("tls_disabled_note")}</p>}
      {cert ? (
        <dl className="kv-list">
          <dt>{t("tls_subject")}</dt>
          <dd>{cert.subject_cn}</dd>
          <dt>{t("tls_issuer")}</dt>
          <dd>{cert.self_signed ? t("tls_self_signed") : cert.issuer_cn}</dd>
          <dt>{t("tls_valid_until")}</dt>
          <dd>
            {formatTime(cert.not_after, lang)}{" "}
            <span className="badge" data-tone={tone}>{t("tls_days_left", { n: String(cert.days_remaining) })}</span>
          </dd>
          <dt>{t("tls_covers")}</dt>
          <dd className="wrap">{cert.san.join(", ") || "—"}</dd>
        </dl>
      ) : (
        <p className="muted">{t("tls_no_cert")}</p>
      )}
    </div>
  );
}

function SettingsCard({ status, onSaved }: { status: TlsStatus; onSaved: (s: TlsStatus) => void }) {
  const [form, setForm] = useState<TlsUpdate>({
    revision: status.revision, enabled: status.enabled, mode: status.mode, cert_file: status.cert_file,
    key_file: status.key_file, auto_renew: status.auto_renew, auto_renew_days: status.auto_renew_days,
    validity_days: status.validity_days, key_algorithm: status.key_algorithm, min_version: status.min_version,
  });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof TlsUpdate>(k: K, v: TlsUpdate[K]) => setForm({ ...form, [k]: v });

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const env = await call("system.tls.update", { ...form, revision: status.revision });
    setBusy(false);
    if (env.ok && env.data) {
      setError(null);
      onSaved(env.data);
    } else setError(env.error);
  }

  async function renew() {
    setBusy(true);
    const env = await call("system.tls.renew");
    setBusy(false);
    if (env.ok && env.data) {
      setError(null);
      onSaved(env.data);
    } else setError(env.error);
  }

  const fieldError = (name: string) =>
    error?.field === name ? <span className="field-error">{t(error.message_key, error.params)}</span> : null;

  return (
    <form className="card form-grid" onSubmit={save}>
      <h2 className="span-all">{t("tls_settings_title")}</h2>
      <label className="check">
        <input type="checkbox" name="enabled" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
        {t("tls_enabled")}
      </label>
      <label>
        {t("tls_source")}
        <select name="mode" value={form.mode} onChange={(e) => set("mode", e.target.value as TlsUpdate["mode"])}>
          <option value="self_signed">{t("tls_source_self_signed")}</option>
          <option value="provided">{t("tls_source_provided")}</option>
        </select>
      </label>
      {form.mode === "provided" ? (
        <>
          <label>
            {t("tls_cert_file")}
            <input name="cert_file" value={form.cert_file} onChange={(e) => set("cert_file", e.target.value)} />
            {fieldError("cert_file")}
          </label>
          <label>
            {t("tls_key_file")}
            <input name="key_file" value={form.key_file} onChange={(e) => set("key_file", e.target.value)} />
            {fieldError("key_file")}
          </label>
        </>
      ) : (
        <>
          <label>
            {t("tls_validity_days")}
            <input name="validity_days" type="number" min={1} max={825} value={form.validity_days}
                   onChange={(e) => set("validity_days", Number(e.target.value))} />
          </label>
          <label>
            {t("tls_key_algorithm")}
            <select name="key_algorithm" value={form.key_algorithm}
                    onChange={(e) => set("key_algorithm", e.target.value as TlsUpdate["key_algorithm"])}>
              <option value="ecdsa-p256">ECDSA P-256</option>
              <option value="rsa-2048">RSA 2048</option>
            </select>
          </label>
          <label className="check">
            <input type="checkbox" name="auto_renew" checked={form.auto_renew}
                   onChange={(e) => set("auto_renew", e.target.checked)} />
            {t("tls_auto_renew")}
          </label>
          <label>
            {t("tls_auto_renew_days")}
            <input name="auto_renew_days" type="number" min={1} max={365} value={form.auto_renew_days}
                   onChange={(e) => set("auto_renew_days", Number(e.target.value))} />
          </label>
        </>
      )}
      <label>
        {t("tls_min_version")}
        <select name="min_version" value={form.min_version}
                onChange={(e) => set("min_version", e.target.value as TlsUpdate["min_version"])}>
          <option value="TLSv1.2">TLS 1.2</option>
          <option value="TLSv1.3">TLS 1.3</option>
        </select>
      </label>
      {error && !error.field && <div className="span-all"><ErrorLine error={error} /></div>}
      <div className="actions">
        <button type="submit" className="btn-primary" disabled={busy}>{t("btn_save")}</button>
        {status.mode === "self_signed" && (
          <button type="button" className="btn-quiet" disabled={busy} onClick={() => void renew()}>
            {t("tls_renew_now")}
          </button>
        )}
        <span className="hint">{t("tls_restart_hint")}</span>
      </div>
    </form>
  );
}

const splitList = (v: string) => v.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);

function CaSignedCard({ onImported }: { onImported: (s: TlsStatus) => void }) {
  const [req, setReq] = useState({ cn: "", o: "", ou: "", c: "", san_dns: "", san_ip: "",
                                   key_algorithm: "rsa-2048" as CsrRequest["key_algorithm"] });
  const [csr, setCsr] = useState<string | null>(null);
  const [pem, setPem] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function generate(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const env = await call("system.tls.csr", { ...req, san_dns: splitList(req.san_dns), san_ip: splitList(req.san_ip) });
    setBusy(false);
    if (env.ok && env.data) {
      setCsr(env.data.csr_pem);
      setError(null);
    } else setError(env.error);
  }

  async function importCert(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const env = await call("system.tls.import", { cert_pem: pem });
    setBusy(false);
    if (env.ok && env.data) {
      setError(null);
      setPem("");
      onImported(env.data);
    } else setError(env.error);
  }

  return (
    <div className="card">
      <h2>{t("tls_ca_title")}</h2>
      <p className="muted">{t("tls_ca_intro")}</p>
      <form className="form-grid" onSubmit={generate}>
        <label>{t("tls_csr_cn")}<input name="cn" required value={req.cn} onChange={(e) => setReq({ ...req, cn: e.target.value })} /></label>
        <label>{t("tls_csr_o")}<input name="o" value={req.o} onChange={(e) => setReq({ ...req, o: e.target.value })} /></label>
        <label>{t("tls_csr_ou")}<input name="ou" value={req.ou} onChange={(e) => setReq({ ...req, ou: e.target.value })} /></label>
        <label>{t("tls_csr_c")}<input name="c" maxLength={2} value={req.c} onChange={(e) => setReq({ ...req, c: e.target.value })} /></label>
        <label>{t("tls_csr_san_dns")}<input name="san_dns" value={req.san_dns} onChange={(e) => setReq({ ...req, san_dns: e.target.value })} /></label>
        <label>{t("tls_csr_san_ip")}<input name="san_ip" value={req.san_ip} onChange={(e) => setReq({ ...req, san_ip: e.target.value })} /></label>
        <div className="actions">
          <button type="submit" className="btn-quiet" disabled={busy}>{t("tls_csr_generate")}</button>
        </div>
      </form>
      {csr && (
        <label className="block">
          {t("tls_csr_result")}
          <textarea readOnly rows={8} value={csr} className="mono" onFocus={(e) => e.currentTarget.select()} />
        </label>
      )}
      <form onSubmit={importCert} className="block">
        <label>
          {t("tls_import_label")}
          <textarea name="cert_pem" rows={8} className="mono" value={pem} onChange={(e) => setPem(e.target.value)}
                    placeholder="-----BEGIN CERTIFICATE-----" />
        </label>
        <div className="actions">
          <button type="submit" className="btn-quiet" disabled={busy || !pem.trim()}>{t("tls_import")}</button>
        </div>
      </form>
      <ErrorLine error={error} />
    </div>
  );
}

export function Tls() {
  const [status, setStatus] = useState<TlsStatus | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    const env = await call("system.tls.status");
    if (env.ok && env.data) setStatus(env.data);
    else setError(env.error);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="page stack">
      <h1>{t("nav_system_tls")}</h1>
      <ErrorLine error={error} />
      {status && (
        <>
          <CertCard status={status} />
          <SettingsCard key={status.revision} status={status} onSaved={setStatus} />
          <CaSignedCard onImported={setStatus} />
        </>
      )}
    </section>
  );
}

registerNav({ section: "system", path: "/system/tls", labelKey: "nav_system_tls", order: 30, component: Tls });
