// fmt.mjs — number/time/tone formatting shared by every area.
// Tone vocabulary is fixed: ok | warn | crit | info | neutral (see tokens.css).

const NF = new Intl.NumberFormat("en-US");

export function num(v) {
  const n = Number(v);
  return NF.format(isFinite(n) ? n : 0);
}

/** Seconds -> compact duration ("42s", "7m", "3h", "2d"). */
export function dur(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  if (s < 90) return s + "s";
  if (s < 5400) return Math.round(s / 60) + "m";
  if (s < 172800) return Math.round(s / 3600) + "h";
  return Math.round(s / 86400) + "d";
}

/** ISO -> "YYYY-MM-DD HH:MM:SS" (snapshots are already timezone-stamped). */
export function stamp(iso) {
  return String(iso || "")
    .replace("T", " ").replace(/\.\d+/, "").replace("Z", "").replace(/\+00:00$/, "").trim();
}

/** Age of `iso` measured against a reference instant (the snapshot's as_of). */
export function since(iso, refIso) {
  const a = Date.parse(iso), b = Date.parse(refIso);
  if (!isFinite(a) || !isFinite(b)) return "—";
  return dur((b - a) / 1000);
}

export function firstLine(s, max) {
  const cap = max || 80;
  const one = String(s || "").split("\n")[0].trim();
  return one.length > cap ? one.slice(0, cap) + "…" : one;
}

/** Backend level words -> the five-tone vocabulary. */
export function tone(level) {
  const s = String(level || "").toLowerCase();
  if (s === "ok" || s === "success" || s === "online" || s === "pass" || s === "healthy") return "ok";
  if (s === "warn" || s === "warning" || s === "degraded" || s === "medium" || s === "overdue") return "warn";
  if (s === "crit" || s === "critical" || s === "error" || s === "err" || s === "fail"
    || s === "failed" || s === "offline" || s === "high") return "crit";
  if (s === "info" || s === "low") return "info";
  return "neutral";
}

const RANK = ["ok", "info", "neutral", "warn", "crit"];

/** Worst tone wins — the rail never under-reports. */
export function worst(levels) {
  let out = "ok";
  (levels || []).forEach(function (l) {
    const tn = tone(l);
    if (RANK.indexOf(tn) > RANK.indexOf(out)) out = tn;
  });
  return out;
}

/** Escalate a tone to at least `floor`. */
export function atLeast(current, floor) {
  return RANK.indexOf(tone(floor)) > RANK.indexOf(tone(current)) ? tone(floor) : tone(current);
}
