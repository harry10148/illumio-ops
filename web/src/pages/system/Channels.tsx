import { type FormEvent, useEffect, useState } from "react";

import { type ApiError, call } from "../../api/client";
import type { ChannelsInput, ChannelsView } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";

type Kind = keyof ChannelsInput;
const KINDS: Kind[] = ["smtp", "line", "telegram", "teams", "webhook"];
const TITLE_KEYS: Record<Kind, string> = {
  smtp: "channel_smtp", line: "channel_line", telegram: "channel_telegram", teams: "channel_teams", webhook: "channel_webhook",
};
const HINT_KEYS: Record<Kind, string> = {
  smtp: "channel_smtp_hint", line: "channel_line_hint", telegram: "channel_telegram_hint", teams: "channel_teams_hint",
  webhook: "channel_webhook_hint",
};
// One row per field: [field, label key, secret]
const FIELDS: Record<Kind, [string, string, boolean][]> = {
  smtp: [["host", "smtp_host", false], ["port", "smtp_port", false], ["username", "smtp_username", false],
         ["password", "smtp_password", true], ["sender", "smtp_sender", false], ["recipients", "smtp_recipients", false]],
  line: [["access_token", "line_access_token", true], ["target_id", "line_target_id", false]],
  telegram: [["bot_token", "telegram_bot_token", true], ["chat_id", "telegram_chat_id", false]],
  teams: [["webhook_url", "teams_webhook_url", true]],
  webhook: [["url", "webhook_url", true]],
};
const SECURITY_KEYS: Record<string, string> = { none: "smtp_security_none", starttls: "smtp_security_starttls", tls: "smtp_security_tls" };

type Result = { ok: boolean; error: string | null } | ApiError;

export function Channels() {
  const lang = useLang();
  const [view, setView] = useState<ChannelsView | null>(null);
  const [channels, setChannels] = useState<ChannelsInput | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [results, setResults] = useState<Partial<Record<Kind, Result>>>({});

  const load = (v: ChannelsView) => { setView(v); setChannels(v.channels); };
  useEffect(() => {
    void call("system.channels.get").then((env) => {
      if (env.ok && env.data) load(env.data);
      else setError(env.error);
    });
  }, []);

  if (!view || !channels) {
    return (
      <section className="page">
        <h1>{t("nav_system_channels")}</h1>
        {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      </section>
    );
  }

  const set = (kind: Kind, field: string, value: unknown) => {
    setChannels({ ...channels, [kind]: { ...channels[kind], [field]: value } });
    setSaved(false);
  };

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!view || !channels) return;
    const env = await call("system.channels.update", { revision: view.revision, channels });
    if (env.ok && env.data) { load(env.data); setError(null); setSaved(true); }
    else { setError(env.error); setSaved(false); }
  }

  async function test(kind: Kind) {
    if (!channels) return;
    const env = await call("system.channels.test", { channel: kind, channels });
    setResults({ ...results, [kind]: env.ok && env.data ? env.data : (env.error as ApiError) });
  }

  return (
    <section className="page stack">
      <h1>{t("nav_system_channels")}</h1>
      <p className="hint">{t("channels_intro")}</p>
      <form className="stack" onSubmit={save} data-role="channels">
        {KINDS.map((kind) => {
          const c = channels[kind] as unknown as Record<string, unknown>;
          const state = view.state.find((s) => s.channel === kind);
          const result = results[kind];
          return (
            <div key={kind} className="card stack" data-channel={kind}>
              <h2>{t(TITLE_KEYS[kind])}</h2>
              <p className="hint">{t(HINT_KEYS[kind])}</p>
              <label className="check">
                <input type="checkbox" name={`${kind}_enabled`} checked={Boolean(c.enabled)}
                       onChange={(e) => set(kind, "enabled", e.target.checked)} />
                {t("channel_enabled")}
              </label>
              <div className="form-grid">
                {FIELDS[kind].map(([field, labelKey, secret]) => (
                  <label key={field}>
                    {t(labelKey)}
                    {field === "recipients" ? (
                      <textarea name={`${kind}_${field}`} rows={2} value={(c.recipients as string[]).join("\n")}
                                onChange={(e) => set(kind, field, e.target.value.split(/[\s,;]+/).filter(Boolean))} />
                    ) : (
                      <input name={`${kind}_${field}`} type={secret ? "password" : "text"} autoComplete="off"
                             value={String(c[field] ?? "")}
                             onChange={(e) => set(kind, field, field === "port" ? Number(e.target.value) : e.target.value)} />
                    )}
                    {secret && <span className="hint">{t("channel_secret_hint")}</span>}
                  </label>
                ))}
                {kind === "smtp" && (
                  <label>
                    {t("smtp_security")}
                    <select name="smtp_security" value={String(c.security)} onChange={(e) => set(kind, "security", e.target.value)}>
                      {Object.keys(SECURITY_KEYS).map((s) => <option key={s} value={s}>{t(SECURITY_KEYS[s] ?? s)}</option>)}
                    </select>
                  </label>
                )}
              </div>
              {state?.last_error && (
                <p className="hint" data-role="channel-last-error">
                  {t("channel_last_error", { error: state.last_error })}
                  {state.cooldown_until && ` · ${t("channel_resting", { until: formatTime(state.cooldown_until, lang) })}`}
                </p>
              )}
              <div className="row">
                <button type="button" className="btn-quiet" onClick={() => void test(kind)}>{t("channel_test")}</button>
                {result && ("message_key" in result
                  ? <span className="form-error" data-role="test-result">{t(result.message_key, result.params)}</span>
                  : <span className={result.ok ? "form-ok" : "form-error"} data-role="test-result">
                      {result.ok ? t("channel_test_ok") : t("channel_test_failed", { error: result.error ?? "" })}
                    </span>)}
              </div>
            </div>
          );
        })}
        {error && <p className="form-error" data-field={error.field ?? ""}>{t(error.message_key, error.params)}</p>}
        {saved && <p className="form-ok" role="status">{t("saved_ok")}</p>}
        <div className="actions">
          <button type="submit" className="btn-primary">{t("btn_save")}</button>
        </div>
      </form>
    </section>
  );
}

registerNav({ section: "system", path: "/system/channels", labelKey: "nav_system_channels", order: 25, component: Channels });
