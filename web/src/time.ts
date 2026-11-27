let configuredZone: string | null = null;

/** Set by the authenticated server settings; null uses the browser's configured zone. */
export function setDisplayZone(zone: string | null): void {
  configuredZone = zone;
}

type Parts = { year: number; month: number; day: number; hour: number; minute: number; second: number };

function parts(date: Date, zone: string): Parts {
  const fixed = /^([+-])(\d{2}):(\d{2})$/.exec(zone);
  if (fixed) {
    const minutes = (Number(fixed[2]) * 60 + Number(fixed[3])) * (fixed[1] === "+" ? 1 : -1);
    const shifted = new Date(date.getTime() + minutes * 60_000);
    return { year: shifted.getUTCFullYear(), month: shifted.getUTCMonth() + 1, day: shifted.getUTCDate(),
      hour: shifted.getUTCHours(), minute: shifted.getUTCMinutes(), second: shifted.getUTCSeconds() };
  }
  const options: Intl.DateTimeFormatOptions = {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    hourCycle: "h23",
  };
  if (zone !== "browser") options.timeZone = zone;
  const fields = Object.fromEntries(new Intl.DateTimeFormat("en-CA", options).formatToParts(date)
    .filter((p) => p.type !== "literal").map((p) => [p.type, Number(p.value)]));
  return { year: Number(fields.year), month: Number(fields.month), day: Number(fields.day), hour: Number(fields.hour),
    minute: Number(fields.minute), second: Number(fields.second) };
}

function zone(): string {
  return configuredZone ?? "browser";
}

const pad = (n: number) => String(n).padStart(2, "0");
const datePart = (p: Parts) => `${p.year}-${pad(p.month)}-${pad(p.day)}`;
const timePart = (p: Parts, seconds = false) => `${pad(p.hour)}:${pad(p.minute)}${seconds ? `:${pad(p.second)}` : ""}`;

export function formatTime(iso: string, _lang?: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const p = parts(date, zone());
  return `${datePart(p)} ${timePart(p)}`;
}

export function formatTimeSeconds(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const p = parts(date, zone());
  return `${datePart(p)} ${timePart(p, true)}`;
}

/** The calendar date of a time in the display zone ("YYYY-MM-DD"); anything unparsable is returned as given. */
export function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return datePart(parts(date, zone()));
}

export function today(): string {
  return datePart(parts(new Date(), zone()));
}

export function shortTime(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const p = parts(date, zone());
  const n = parts(now, zone());
  if (p.year === n.year && p.month === n.month && p.day === n.day) return timePart(p);
  if (p.year === n.year) return `${pad(p.month)}-${pad(p.day)} ${timePart(p)}`;
  return datePart(p);
}
