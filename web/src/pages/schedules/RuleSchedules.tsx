// Rule scheduling (UI redesign spec §4.5, sample 05): enable or disable an active PCE rule or rule set by a weekly
// window or an expiry; the engine checks every five minutes and provisions with the write key.
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { type ApiError, call } from "../../api/client";
import type { CheckResult, DeleteResult, RuleSchedulesView, RunView, ScheduleView, TargetHit, Weekly, Expiry } from "../../api/generated";
import { formatTime } from "../../components/ProbeResults";
import { DataTable, DetailPane, KpiStrip, ModeMark, PageHead, Panel, Tag, shortTime } from "../../components/ui";
import { t, useLang } from "../../i18n";
import { registerNav } from "../../shell/nav";

type Day = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
const DAYS: Day[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_KEYS: Record<Day, string> = {
  mon: "rs_day_mon", tue: "rs_day_tue", wed: "rs_day_wed", thu: "rs_day_thu", fri: "rs_day_fri", sat: "rs_day_sat",
  sun: "rs_day_sun",
};
const ACTION_KEYS: Record<string, string> = {
  enable: "rs_run_enable", disable: "rs_run_disable", expire: "rs_run_expire", skip_draft: "rs_run_skip_draft",
  not_found: "rs_run_not_found", error: "rs_run_error", note: "rs_run_note", note_cleared: "rs_run_note_cleared",
};
const RESULT_KEYS: Record<string, string> = { ok: "rs_result_ok", failed: "rs_result_failed", skipped: "rs_result_skipped" };
const LIVE_KEYS: Record<string, string> = { enabled: "rs_live_enabled", disabled: "rs_live_disabled", unknown: "rs_live_unknown" };
const PREVIEW_KEYS: Record<string, string> = {
  rs_preview_weekly_enable: "rs_preview_weekly_enable", rs_preview_weekly_disable: "rs_preview_weekly_disable",
  rs_preview_expiry: "rs_preview_expiry",
};

function word(map: Record<string, string>, value: string): string {
  const key = map[value];
  return key ? t(key) : value;
}

function daysText(days: string[]): string {
  return DAYS.filter((d) => days.includes(d)).map((d) => t(DAY_KEYS[d])).join("");
}

/** The sentence a plan reads as, from the same key and parameters the server gives (domain/rule_schedule.preview). */
function previewText(key: string, params: Record<string, string>): string {
  const p = { ...params };
  if (p.days !== undefined) p.days = daysText(p.days.split(","));
  if (p.next_day !== undefined) p.next_day = p.next_day === "1" ? t("rs_next_day") : "";
  return t(PREVIEW_KEYS[key] ?? "rs_preview_expiry", p);
}

function weeklyOf(s: ScheduleView): Weekly | null {
  return "days" in s.plan ? s.plan : null;
}

function planText(s: ScheduleView, lang: string): string {
  const w = weeklyOf(s);
  if (!w) return "expire_at" in s.plan ? t("rs_type_expiry_text", { at: formatTime(s.plan.expire_at, lang) }) : "";
  return `${daysText(w.days)} ${w.start}–${w.end}`;
}

/** This week's windows: one row per weekly schedule, a bar per day across 24 hours (green enable, red disable). */
function Week({ items }: { items: ScheduleView[] }) {
  const weekly = items.filter((s) => weeklyOf(s) !== null && !s.paused);
  if (weekly.length === 0) return <p className="muted">{t("rs_week_none")}</p>;
  const pct = (hhmm: string) => {
    const [h = 0, m = 0] = hhmm.split(":").map(Number);
    return ((h * 60 + m) / 1440) * 100;
  };
  return (
    <div className="rs-week" data-role="rs-week">
      <div className="rs-week-row rs-week-head"><span />{DAYS.map((d) => <span key={d}>{t(DAY_KEYS[d])}</span>)}</div>
      {weekly.map((s) => {
        const plan = weeklyOf(s);
        if (!plan) return null;
        const tone = plan.action === "enable_in_window" ? "ok" : "crit";
        return (
          <div key={s.id} className="rs-week-row">
            <span className="rs-week-name" title={s.summary}>{s.name}</span>
            {DAYS.map((d, i) => {
              const prev = DAYS[(i + 6) % 7] ?? "sun";
              const bars: [number, number][] = [];
              const a = pct(plan.start), b = pct(plan.end);
              if (a < b) {
                if (plan.days.includes(d)) bars.push([a, b]);
              } else {
                if (plan.days.includes(d)) bars.push([a, 100]);
                if (plan.days.includes(prev)) bars.push([0, b]);
              }
              return (
                <span key={d} className="rs-week-cell">
                  {bars.map(([x, y], j) => <i key={j} data-tone={tone} style={{ left: `${x}%`, width: `${y - x}%` }} />)}
                </span>
              );
            })}
          </div>
        );
      })}
      <p className="hint">{t("rs_week_legend")}</p>
    </div>
  );
}

/** datetime-local text ("YYYY-MM-DDTHH:MM") of an instant, in the browser's zone. */
function localInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** The plan being written: a new schedule starts from office hours in the browser's zone; an edit from its plan (a
 * weekly window keeps its zone, since its times are that zone's; an expiry is shown and saved in the browser's). */
function usePlan(initial: Weekly | Expiry | null) {
  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const weekly = initial && "days" in initial ? initial : null;
  const [kind, setKind] = useState<"weekly" | "expiry">(initial && !weekly ? "expiry" : "weekly");
  const [days, setDays] = useState<Day[]>(weekly ? [...weekly.days] as Day[] : ["mon", "tue", "wed", "thu", "fri"]);
  const [start, setStart] = useState(weekly?.start ?? "09:00");
  const [end, setEnd] = useState(weekly?.end ?? "18:00");
  const [action, setAction] = useState<"enable_in_window" | "disable_in_window">(weekly?.action ?? "enable_in_window");
  const [expireAt, setExpireAt] = useState(initial && "expire_at" in initial ? localInput(initial.expire_at) : "");
  const zone = kind === "weekly" && weekly ? weekly.timezone : browserZone;
  const plan: Weekly | Expiry = kind === "weekly"
    ? { kind: "weekly", days: days as Weekly["days"], start, end, timezone: zone, action }
    : { kind: "expiry", expire_at: expireAt ? new Date(expireAt).toISOString() : "", timezone: zone };
  const preview = kind === "weekly"
    ? previewText(action === "enable_in_window" ? "rs_preview_weekly_enable" : "rs_preview_weekly_disable",
      { days: DAYS.filter((d) => days.includes(d)).join(","), start, end, next_day: start > end ? "1" : "0" })
    : expireAt ? previewText("rs_preview_expiry", { at: expireAt.replace("T", " "), timezone: zone }) : "";
  const valid = kind === "weekly" ? days.length > 0 && start !== end : expireAt !== "";
  const fields = (
    <>
      <div className="chips-row" role="group">
        <button type="button" className="chip-btn" aria-pressed={kind === "weekly"} onClick={() => setKind("weekly")}>{t("rs_type_weekly")}</button>
        <button type="button" className="chip-btn" aria-pressed={kind === "expiry"} onClick={() => setKind("expiry")}>{t("rs_type_expiry")}</button>
      </div>
      {kind === "weekly" ? (
        <>
          <div className="chips-row" role="group" aria-label={t("rs_days")}>
            {DAYS.map((d) => (
              <label key={d} className="check">
                <input type="checkbox" name={`rs_day_${d}`} checked={days.includes(d)}
                       onChange={(e) => setDays(e.target.checked ? [...days, d] : days.filter((x) => x !== d))} />
                {t(DAY_KEYS[d])}
              </label>
            ))}
          </div>
          <div className="row">
            <label>{t("rs_start")}<input type="time" name="rs_start" value={start} onChange={(e) => setStart(e.target.value)} /></label>
            <label>{t("rs_end")}<input type="time" name="rs_end" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
            <span className="hint">{start > end ? t("rs_across_midnight", { zone }) : zone}</span>
          </div>
          <div className="row">
            <label className="check"><input type="radio" name="rs_action" checked={action === "enable_in_window"}
              onChange={() => setAction("enable_in_window")} />{t("rs_enable_in_window")}</label>
            <label className="check"><input type="radio" name="rs_action" checked={action === "disable_in_window"}
              onChange={() => setAction("disable_in_window")} />{t("rs_disable_in_window")}</label>
          </div>
        </>
      ) : (
        <label>{t("rs_expire_at", { zone })}
          <input type="datetime-local" name="rs_expire_at" value={expireAt} onChange={(e) => setExpireAt(e.target.value)} />
        </label>
      )}
      {preview && <p data-role="rs-preview">{t("rs_preview_label")}{preview}{t("rs_preview_note")}</p>}
    </>
  );
  return { plan, valid, fields };
}

function NewSchedule({ writeKey, onCreated }: { writeKey: boolean; onCreated: () => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<TargetHit[] | null>(null);
  const [found, setFound] = useState<{ pce_url: string; org_id: string } | null>(null);
  const searchSeq = useRef(0);
  const [target, setTarget] = useState<TargetHit | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const { plan, valid: planValid, fields } = usePlan(null);

  async function search(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setTarget(null);  // a new search: the earlier pick is no longer on screen (Codex review of plan B)
    setHits(null);
    const seq = ++searchSeq.current;
    const env = await call("rule_schedules.targets", undefined, undefined, { q });
    if (seq !== searchSeq.current) return;  // a newer search was sent: this answer is not on screen (review round 2)
    if (env.ok && env.data) {
      setHits(env.data.items);
      setFound({ pce_url: env.data.pce_url ?? "", org_id: env.data.org_id ?? "" });
    } else setError(env.error);
  }

  const valid = target !== null && planValid;

  async function create() {
    if (!target) return;
    setBusy(true);
    const env = await call("rule_schedules.create", { href: target.href, plan, name: target.name,
      ruleset_name: target.ruleset_name, summary: target.summary, pce_url: found?.pce_url ?? "", org_id: found?.org_id ?? "" });
    setBusy(false);
    if (env.ok) {
      setTarget(null);
      setHits(null);
      setQ("");
      setError(null);
      onCreated();
    } else setError(env.error);
  }

  return (
    <div className="stack" data-role="rs-new">
      <h2>{t("rs_new_title")}</h2>
      {!writeKey && <p className="notice">{t("rs_no_write_key")}</p>}
      <form className="row" onSubmit={(e) => void search(e)}>
        <label className="block">
          {t("rs_target_search")}
          <input name="rs_q" value={q} maxLength={200} onChange={(e) => setQ(e.target.value)} disabled={!writeKey} />
        </label>
        <button type="submit" className="btn-quiet" disabled={!writeKey || !q.trim()}>{t("rs_search")}</button>
      </form>
      {hits && (hits.length === 0 ? <p className="muted">{t("rs_targets_none")}</p> : (
        <ul className="plain-list rs-targets" data-role="rs-targets">
          {hits.map((h) => {
            const why = h.draft_pending ? t("rs_target_draft") : h.scheduled ? t("rs_target_scheduled") : null;
            return (
              <li key={h.href}>
                <label className="check">
                  <input type="radio" name="rs_target" disabled={why !== null} checked={target?.href === h.href}
                         onChange={() => setTarget(h)} />
                  <span>{h.is_ruleset ? t("rs_whole_ruleset", { name: h.name }) : `${h.name} · ${h.ruleset_name}`}</span>
                  <Tag tone={h.enabled ? "ok" : "muted"}>{h.enabled ? t("rs_live_enabled") : t("rs_live_disabled")}</Tag>
                </label>
                <div className="hint">{h.summary}</div>
                {why && <div className="hint" data-role="rs-target-why">{why}</div>}
              </li>
            );
          })}
        </ul>
      ))}
      {target && (
        <>
          {fields}
          <div className="actions">
            <button type="button" className="btn-primary" disabled={!valid || busy || !writeKey} onClick={() => void create()}>
              {t("rs_create")}
            </button>
          </div>
        </>
      )}
      {error && (
        <p className="form-error" data-role="rs-error">
          {t(error.message_key, error.params)}
        </p>
      )}
    </div>
  );
}

/** 5.x edited a schedule in place: the new plan's note is written to the PCE first (as a new schedule's is). */
function EditSchedule({ schedule, writeKey, onDone }: { schedule: ScheduleView; writeKey: boolean; onDone: (saved: boolean) => void }) {
  const { plan, valid, fields } = usePlan(schedule.plan);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    const env = await call("rule_schedules.update", { plan }, { schedule_id: String(schedule.id) });
    setBusy(false);
    if (env.ok) onDone(true);
    else setError(env.error);
  }

  return (
    <div className="stack" data-role="rs-edit">
      <h2>{t("rs_edit_title")}</h2>
      <p>{schedule.is_ruleset ? t("rs_whole_ruleset", { name: schedule.name }) : `${schedule.name} · ${schedule.ruleset_name}`}</p>
      <p className="hint">{schedule.summary}</p>
      {!writeKey && <p className="notice">{t("rs_no_write_key")}</p>}
      {fields}
      <div className="actions">
        <button type="button" className="btn-primary" disabled={!valid || busy || !writeKey} onClick={() => void save()}>
          {t("rs_edit_save")}
        </button>
        <button type="button" className="btn-quiet" onClick={() => onDone(false)}>{t("btn_cancel")}</button>
      </div>
      {error && <p className="form-error" data-role="rs-error">{t(error.message_key, error.params)}</p>}
    </div>
  );
}

const OUTCOME_KEYS: Record<string, string> = {
  switched: "rs_check_switched", failed: "rs_check_failed", skipped: "rs_check_skipped", none: "rs_check_none",
};

export function RuleSchedules() {
  const lang = useLang();
  const [view, setView] = useState<RuleSchedulesView | null>(null);
  const [runs, setRuns] = useState<RunView[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [deleted, setDeleted] = useState<DeleteResult | null>(null);
  const [editing, setEditing] = useState<ScheduleView | null>(null);
  const [checked, setChecked] = useState<{ name: string; outcome: CheckResult["outcome"] } | null>(null);
  const [checking, setChecking] = useState<number | null>(null);

  const load = useCallback(async () => {
    const [env, r] = await Promise.all([call("rule_schedules.list"), call("rule_schedules.runs")]);
    if (env.ok && env.data) {
      setView(env.data);
      setError(null);
    } else setError(env.error);
    if (r.ok && r.data) setRuns(r.data.items);
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function pause(s: ScheduleView) {
    const id = { schedule_id: String(s.id) };
    const env = s.paused ? await call("rule_schedules.resume", {}, id) : await call("rule_schedules.pause", {}, id);
    if (!env.ok) setError(env.error);
    void load();
  }

  async function checkNow(s: ScheduleView) {
    setChecking(s.id);
    const env = await call("rule_schedules.check", {}, { schedule_id: String(s.id) });
    setChecking(null);
    if (env.ok && env.data) {
      setChecked({ name: s.name, outcome: env.data.outcome });
      setError(null);
    } else setError(env.error);
    void load();
  }

  async function remove(id: number) {
    const env = await call("rule_schedules.delete", undefined, { schedule_id: String(id) });
    setDeleting(null);
    if (env.ok && env.data) setDeleted(env.data);
    else setError(env.error);
    void load();
  }

  const o = view?.overview;
  return (
    <section className="page" data-role="rule-schedules">
      <PageHead title={t("nav_rule_schedules")} sub={t("rs_sub")}>
        <Link to="/rule-schedules/rulesets" data-role="rs-browse-rulesets">{t("rs_browse_rulesets")}</Link>
        <ModeMark needs="basic" />
      </PageHead>
      {error && <p className="form-error">{t(error.message_key, error.params)}</p>}
      {o && !o.write_key && <p className="notice" data-role="rs-no-write-key">{t("rs_no_write_key")}</p>}
      <KpiStrip items={[
        { key: "count", label: t("rs_kpi_schedules"), value: o ? o.schedules : null },
        { key: "switched", label: t("rs_kpi_switched"), value: o ? o.switched_24h : null, tone: "ok" },
        { key: "failed", label: t("rs_kpi_failed"), value: o ? o.failed_24h : null, tone: o && o.failed_24h ? "crit" : "muted" },
        { key: "skipped", label: t("rs_kpi_skipped"), value: o ? o.skipped_now : null, tone: o && o.skipped_now ? "high" : "muted" },
        { key: "next", label: t("rs_kpi_next"), value: o?.next_change ? shortTime(o.next_change) : null,
          reason: t("rs_kpi_next_none") },
      ]} />
      {checked && (
        <p className="notice" role="status" data-role="rs-checked">
          {t(OUTCOME_KEYS[checked.outcome] ?? "rs_check_none", { name: checked.name })}
        </p>
      )}
      {deleted && (
        <p className="notice" data-role="rs-deleted">
          {deleted.note_cleared ? t(deleted.provisioned ? "rs_deleted_ok" : "rs_deleted_note_draft")
            : t("rs_deleted_note_kept", { detail: deleted.detail ?? "—" })}
        </p>
      )}
      <div className="split">
        <div className="stack">
          <Panel title={t("rs_week_title")} role="rs-week-panel"><Week items={view?.items ?? []} /></Panel>
          <div data-role="rs-list">
            <DataTable<ScheduleView>
              rows={view?.items ?? []}
              rowKey={(s) => String(s.id)}
              empty={t("rs_none")}
              columns={[
                { key: "target", label: t("rs_col_target"), render: (s) => (
                  <div><div>{s.is_ruleset ? t("rs_whole_ruleset", { name: s.name }) : `${s.name} · ${s.ruleset_name}`}</div>
                    <div className="hint">{s.summary}</div></div>) },
                { key: "type", label: t("rs_col_type"), render: (s) => <span className="nowrap">{weeklyOf(s) ? t("rs_type_weekly") : t("rs_type_expiry")}</span> },
                { key: "time", label: t("rs_col_time"), render: (s) => (
                  <div><div>{planText(s, lang)}</div><div className="hint">{previewText(s.preview_key, s.preview_params)}</div></div>) },
                { key: "now", label: t("rs_col_now"), render: (s) => (
                  <span>
                    {s.paused ? <Tag tone="muted">{t("rs_paused")}</Tag> : <Tag tone={s.live === "enabled" ? "ok" : "muted"}>{word(LIVE_KEYS, s.live)}</Tag>}
                    {s.pce_status === "deleted" && <Tag tone="crit">{t("rs_target_deleted")}</Tag>}
                  </span>) },
                { key: "last", label: t("rs_col_last"), render: (s) => (s.last_run ? (
                  <div data-role="rs-last">
                    <Tag tone={s.last_run.result === "failed" ? "crit" : s.last_run.result === "skipped" ? "high" : "ok"}>
                      {word(ACTION_KEYS, s.last_run.action)}
                    </Tag> <span className="num hint">{shortTime(s.last_run.at)}</span>
                    {s.last_run.status !== null && <div className="hint">HTTP {s.last_run.status} {s.last_run.detail ?? ""}</div>}
                  </div>) : <span className="hint">{t("rs_never_checked")}</span>) },
                { key: "act", label: "", render: (s) => (
                  <div className="row nowrap">
                    <button type="button" className="btn-quiet" data-role="rs-check" disabled={s.paused || checking !== null}
                            title={s.paused ? t("rs_check_paused") : undefined} onClick={() => void checkNow(s)}>
                      {checking === s.id ? t("rs_checking") : t("rs_check_now")}
                    </button>
                    <button type="button" className="btn-quiet" data-role="rs-edit-open" onClick={() => setEditing(s)}>{t("rs_edit")}</button>
                    <button type="button" className="btn-quiet" onClick={() => void pause(s)}>{s.paused ? t("rs_resume") : t("rs_pause")}</button>
                    {deleting === s.id
                      ? <button type="button" className="btn-danger" data-role="rs-delete-confirm" onClick={() => void remove(s.id)}>{t("rs_delete_confirm")}</button>
                      : <button type="button" className="btn-danger" data-role="rs-delete" onClick={() => setDeleting(s.id)}>{t("rs_delete")}</button>}
                  </div>) },
              ]}
            />
          </div>
          <Panel title={t("rs_runs_title")} role="rs-runs">
            <DataTable<RunView>
              rows={runs.slice(0, 50)}
              rowKey={(r) => `${r.at}-${r.name}-${r.action}`}
              empty={t("rs_runs_none")}
              columns={[
                { key: "at", label: t("rs_col_at"), kind: "time", render: (r) => formatTime(r.at, lang) },
                { key: "name", label: t("rs_col_target"), render: (r) => r.name },
                { key: "action", label: t("rs_col_action"), render: (r) => word(ACTION_KEYS, r.action) },
                { key: "result", label: t("rs_col_result"), render: (r) => (
                  <span>{word(RESULT_KEYS, r.result)}{r.status !== null ? ` · HTTP ${r.status}` : ""}{r.detail ? ` · ${r.detail}` : ""}</span>) },
              ]}
            />
          </Panel>
        </div>
        <DetailPane label={editing ? t("rs_edit_title") : t("rs_new_title")}>
          {editing
            ? <EditSchedule key={editing.id} schedule={editing} writeKey={o?.write_key ?? false}
                            onDone={() => { setEditing(null); void load(); }} />
            : <NewSchedule writeKey={o?.write_key ?? false} onCreated={() => void load()} />}
        </DetailPane>
      </div>
    </section>
  );
}

registerNav({ section: "main", path: "/rule-schedules", labelKey: "nav_rule_schedules", order: 18, component: RuleSchedules });
