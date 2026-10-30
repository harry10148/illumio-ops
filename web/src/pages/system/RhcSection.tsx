import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { EnableResult, RhcState, RhcStatus } from "../../api/generated";
import { t } from "../../i18n";

// Literal maps: i18n keys are never built from data (i18n gate).
const STATE_LABEL: Record<RhcState, string> = {
  enabled: "rhc_state_enabled",
  partial: "rhc_state_partial",
  disabled: "rhc_state_disabled",
  unsupported: "rhc_state_unsupported",
  unknown: "rhc_state_unknown",
};
const STEP_LABEL: Record<string, string> = {
  pce_report_template: "rhc_step_pce_report_template",
  ven_firewall_settings_draft: "rhc_step_ven_firewall_settings_draft",
  provisioned: "rhc_step_provisioned",
};

function half(on: boolean | null): string {
  return t(on === null ? "rhc_half_unknown" : on ? "rhc_half_on" : "rhc_half_off");
}

/** Rule Hit Count (spec §6.5 RHC): the report needs it on in two places; turning it on provisions firewall_settings,
 * so it runs only after the person confirms the listed steps. */
export function RhcSection() {
  const [status, setStatus] = useState<RhcStatus | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<EnableResult | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const check = useCallback(async () => {
    setBusy(true);
    const env = await call("rhc.status");
    setBusy(false);
    if (env.ok && env.data) {
      setStatus(env.data);
      setError(null);
    } else setError(env.error);
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  async function enable() {
    setConfirming(false);
    setBusy(true);
    const env = await call("rhc.enable", { confirm: true });
    setBusy(false);
    if (env.ok && env.data) {
      setResult(env.data.result);
      setStatus(env.data.status);
      setError(null);
    } else setError(env.error);
  }

  const off = status !== null && status.state !== "enabled" && status.state !== "unsupported";
  const steps = (names: string[]) => names.map((s) => t(STEP_LABEL[s] ?? s)).join(" → ");

  return (
    <div className="card stack" data-role="rhc">
      <h2>Rule Hit Count</h2>
      <p className="hint">{t("rhc_intro")}</p>
      {error && <p className="form-error" role="alert">{t(error.message_key, error.params)}</p>}
      {status && (
        <>
          <p data-role="rhc-state">
            <strong>{t(STATE_LABEL[status.state])}</strong>
            {" — "}{t("rhc_halves", { pce: half(status.pce_report), vens: half(status.ven_scopes) })}
          </p>
          {status.reason_key && (
            <p className="notice">
              {t(status.reason_key)}{status.detail && <> ({status.detail})</>}
              {(status.reason_key === "rhc_reason_needs_write_key" || status.reason_key === "rhc_reason_write_key_denied") && (
                <> <Link to="/system/pce">{t("nav_system_pce")}</Link></>
              )}
            </p>
          )}
          {off && status.saas && <p className="notice">{t("rhc_saas_note")}</p>}
          {off && !status.write_key && <p className="hint">{t("rhc_err_no_write_key")} <Link to="/system/pce">{t("nav_system_pce")}</Link></p>}
        </>
      )}
      {result && (
        result.ok ? (
          <p className="form-ok" role="status">
            {t("rhc_enable_ok")}
            {result.steps_done.length > 0 && <> {t("rhc_steps_done", { steps: steps(result.steps_done) })}</>}
          </p>
        ) : (
          <p className="form-error" role="alert" data-role="rhc-error">
            {t(result.error_key ?? "rhc_err_step_failed")}{result.detail && <> ({result.detail})</>}
            {" "}{t("rhc_steps_done", { steps: result.steps_done.length ? steps(result.steps_done) : t("rhc_steps_none") })}
          </p>
        )
      )}
      {confirming ? (
        <div className="stack" data-role="rhc-confirm">
          <p>{t("rhc_confirm_intro")}</p>
          <ol>
            {status?.pce_report !== true && <li>{t("rhc_step_pce_report_template")}</li>}
            {status?.ven_scopes !== true && <li>{t("rhc_step_ven_firewall_settings_draft")}</li>}
            {status?.ven_scopes !== true && <li>{t("rhc_step_provisioned")}</li>}
          </ol>
          {status?.ven_scopes !== true && <p className="notice">{t("rhc_confirm_provision")}</p>}
          <div className="row">
            <button type="button" className="btn-primary" disabled={busy} onClick={() => void enable()}>{t("btn_confirm")}</button>
            <button type="button" className="btn-quiet" onClick={() => setConfirming(false)}>{t("btn_cancel")}</button>
          </div>
        </div>
      ) : (
        <div className="row">
          {off && status?.write_key && (
            <button type="button" className="btn-primary" disabled={busy} onClick={() => setConfirming(true)}>
              {t("rhc_btn_enable")}
            </button>
          )}
          <button type="button" className="btn-quiet" disabled={busy} onClick={() => void check()}>{t("rhc_btn_check")}</button>
        </div>
      )}
    </div>
  );
}
