// All times are shown in the institute timezone, always labelled (spec 12). Input wall-clock times are
// converted with the zone's real offset, so this keeps working if the institute zone ever has DST.

export const TZ = (import.meta.env.VITE_TIMEZONE as string | undefined) ?? "Asia/Kolkata";

const parts = (d: Date, opts: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat("en-IN", { timeZone: TZ, ...opts }).format(d);

export const tzLabel = () =>
  new Intl.DateTimeFormat("en-IN", { timeZone: TZ, timeZoneName: "short" }).formatToParts(new Date()).find((p) => p.type === "timeZoneName")
    ?.value ?? TZ;

export const fmtTime = (iso: string | Date) => parts(new Date(iso), { hour: "2-digit", minute: "2-digit", hour12: false });
export const fmtDay = (iso: string | Date) => parts(new Date(iso), { weekday: "short", day: "numeric", month: "short" });
export const fmtDate = (iso: string | Date) => parts(new Date(iso), { day: "numeric", month: "short", year: "numeric" });
export const fmtDateTime = (iso: string | Date) => `${fmtDay(iso)}, ${fmtTime(iso)}`;
export const fmtRange = (a: string, b: string) => `${fmtDay(a)} · ${fmtTime(a)}–${fmtTime(b)} ${tzLabel()}`;

/** YYYY-MM-DD of an instant, in the institute zone. */
export function localDate(d: Date = new Date()): string {
  const p = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  return p;
}

export function localHHMM(d: Date): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false }).format(d);
}

function offsetMinutes(at: Date): number {
  const p = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(at);
  const get = (t: string) => Number(p.find((x) => x.type === t)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return Math.round((asUtc - at.getTime()) / 60000);
}

/** Wall-clock date + time in the institute zone -> Date. */
export function zoned(date: string, time: string): Date {
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  const guess = new Date(Date.UTC(y, m - 1, d, hh, mm));
  const first = new Date(guess.getTime() - offsetMinutes(guess) * 60000);
  return new Date(guess.getTime() - offsetMinutes(first) * 60000);
}

export const addMinutes = (d: Date, m: number) => new Date(d.getTime() + m * 60000);
export const iso = (d: Date) => d.toISOString();

export function humanMinutes(m: number): string {
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

export function relative(isoStr: string): string {
  const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return fmtDate(isoStr);
}
