import { useQuery } from "@tanstack/react-query";
import { BarChart3, Download, Table2 } from "lucide-react";
import { useMemo, useState } from "react";
import { api, errorMessage, qs } from "../api";
import { useAuth } from "../auth";
import { Alert, Card, Empty, Field, Input, PageHeader, Select, Skeleton, Stat } from "../components/ui";
import { fmtDay, iso, localDate, zoned } from "../time";
import type { Lab } from "../types";

interface Row {
  resource_id: number; resource_name: string; lab_name: string; type: string; booked_hours: number; open_hours: number;
  utilization_pct: number | null; maintenance_hours: number; bookings: number; unique_users: number; cancellations: number;
  late_cancellations: number; no_shows: number;
}
interface Report {
  scope: "all" | "managed" | "own";
  totals: { booked_hours: number; bookings: number; cancellations: number; late_cancellations: number; no_shows: number; utilization_pct: number | null };
  resources: Row[];
  daily: { date: string; hours: number }[];
}

const PRESETS = { "7": "Last 7 days", "30": "Last 30 days", "90": "Last 90 days", custom: "Custom" } as const;

export function ReportsPage() {
  const { me } = useAuth();
  const [preset, setPreset] = useState<keyof typeof PRESETS>("30");
  const [from, setFrom] = useState(localDate(new Date(Date.now() - 29 * 86400000)));
  const [to, setTo] = useState(localDate());
  const [labId, setLabId] = useState("");
  const managing = !!me && (me.is_superadmin || me.is_professor || me.is_dept_admin);
  const labs = useQuery({ queryKey: ["labs"], queryFn: () => api<Lab[]>("/labs"), enabled: managing });

  const range = useMemo(() => {
    if (preset === "custom") return { from: iso(zoned(from, "00:00")), to: iso(new Date(zoned(to, "00:00").getTime() + 86400000)) };
    const days = Number(preset);
    const end = new Date(zoned(localDate(), "00:00").getTime() + 86400000);
    return { from: iso(new Date(end.getTime() - days * 86400000)), to: iso(end) };
  }, [preset, from, to]);
  const params = { ...range, lab_id: labId };
  const rep = useQuery({ queryKey: ["report", params], queryFn: () => api<Report>(`/reports/usage${qs(params)}`), placeholderData: (p) => p });

  return (
    <>
      <PageHeader title="Reports" subtitle={rep.data?.scope === "own" ? "Your own booking history." : "Usage of the resources you manage."}
        actions={rep.data && (
          <>
            <a href={`/api/v1/reports/usage.csv${qs(params)}`} className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-line bg-surface px-4 text-sm font-medium hover:bg-surface-2"><Download className="size-4" aria-hidden />Summary CSV</a>
            <a href={`/api/v1/reports/usage.csv${qs({ ...params, raw: true })}`} className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-line bg-surface px-4 text-sm font-medium hover:bg-surface-2"><Download className="size-4" aria-hidden />All bookings CSV</a>
          </>
        )} />

      {/* Filters: one row above the charts */}
      <div className="mb-6 flex flex-wrap items-end gap-3">
        <Field label="Period">
          <Select value={preset} onChange={(e) => setPreset(e.target.value as keyof typeof PRESETS)} className="w-40">
            {Object.entries(PRESETS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </Field>
        {preset === "custom" && (
          <>
            <Field label="From"><Input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="To"><Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>
          </>
        )}
        {managing && (
          <Field label="Lab">
            <Select value={labId} onChange={(e) => setLabId(e.target.value)} className="w-64">
              <option value="">All my labs</option>
              {labs.data?.map((l) => <option key={l.id} value={l.id}>{l.name} · {l.department_code}</option>)}
            </Select>
          </Field>
        )}
      </div>

      {rep.error && <Alert>{errorMessage(rep.error)}</Alert>}
      {!rep.data ? <Skeleton className="h-80" /> : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Booked hours" value={rep.data.totals.booked_hours.toLocaleString("en-IN")} hint={`${rep.data.totals.bookings} sessions`} />
            <Stat label="Utilization" value={rep.data.totals.utilization_pct === null ? "—" : `${rep.data.totals.utilization_pct}%`} hint="booked ÷ open hours" />
            <Stat label="Cancellations" value={rep.data.totals.cancellations} hint={`${rep.data.totals.late_cancellations} late`} />
            <Stat label="No-shows" value={rep.data.totals.no_shows} />
          </div>
          <DailyChart data={rep.data.daily} />
          {rep.data.resources.length === 0 ? <Empty icon={<BarChart3 className="size-5" />} title="No bookings in this period" /> : <ResourceTable rows={rep.data.resources} own={rep.data.scope === "own"} />}
        </div>
      )}
    </>
  );
}

function DailyChart({ data }: { data: { date: string; hours: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const W = 720, H = 220, PAD = { l: 36, r: 8, t: 12, b: 26 };
  const max = Math.max(1, ...data.map((d) => d.hours));
  const step = niceStep(max);
  const top = Math.ceil(max / step) * step;
  const innerW = W - PAD.l - PAD.r, innerH = H - PAD.t - PAD.b;
  const slot = innerW / Math.max(1, data.length);
  const barW = Math.max(2, Math.min(28, slot - 2)); // 2px surface gap between bars
  const y = (v: number) => PAD.t + innerH - (v / top) * innerH;
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step);
  const labelEvery = Math.ceil(data.length / 8);
  const total = data.reduce((s, d) => s + d.hours, 0);

  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="font-semibold">Booked hours per day</h2>
          <p className="text-xs text-muted">{total.toLocaleString("en-IN", { maximumFractionDigits: 1 })} hours across {data.length} days</p>
        </div>
        <button onClick={() => setTable((t) => !t)} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-muted hover:bg-surface-2 hover:text-ink">
          {table ? <BarChart3 className="size-3.5" aria-hidden /> : <Table2 className="size-3.5" aria-hidden />}{table ? "Chart" : "Table"}
        </button>
      </div>
      {table ? (
        <div className="max-h-72 overflow-y-auto text-sm">
          <table className="w-full"><thead className="text-left text-xs text-muted"><tr><th className="py-1.5 font-medium">Day</th><th className="py-1.5 text-right font-medium">Hours</th></tr></thead>
            <tbody>{data.map((d) => <tr key={d.date} className="border-t border-line"><td className="py-1.5">{fmtDay(`${d.date}T12:00:00Z`)}</td><td className="py-1.5 text-right tabular-nums">{d.hours}</td></tr>)}</tbody></table>
        </div>
      ) : (
        <div className="relative">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Bar chart of booked hours per day" onMouseLeave={() => setHover(null)}>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} strokeDasharray={t === 0 ? undefined : "2 4"} />
                <text x={PAD.l - 8} y={y(t)} dy="0.32em" textAnchor="end" fontSize="11" fill="var(--faint)" className="tabular-nums">{t}</text>
              </g>
            ))}
            {data.map((d, i) => {
              const cx = PAD.l + slot * i + slot / 2;
              const h = Math.max(0, y(0) - y(d.hours));
              const r = Math.min(4, barW / 2, h);
              const x0 = cx - barW / 2, x1 = cx + barW / 2, yb = y(0), yt = yb - h;
              const path = h > 0 ? `M${x0},${yb} V${yt + r} Q${x0},${yt} ${x0 + r},${yt} H${x1 - r} Q${x1},${yt} ${x1},${yt + r} V${yb} Z` : "";
              return (
                <g key={d.date}>
                  {path && <path d={path} fill="var(--chart-1)" opacity={hover === null || hover === i ? 1 : 0.55} />}
                  {i % labelEvery === 0 && <text x={cx} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--faint)">{fmtDay(`${d.date}T12:00:00Z`).split(", ").pop()}</text>}
                  {/* hit target is the full column, bigger than the mark */}
                  <rect x={PAD.l + slot * i} y={PAD.t} width={slot} height={innerH} fill="transparent" onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={0} aria-label={`${d.date}: ${d.hours} hours`} />
                </g>
              );
            })}
          </svg>
          {hover !== null && data[hover] && (
            <div className="pointer-events-none absolute top-0 rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg"
              style={{ left: `clamp(0px, calc(${((PAD.l + slot * hover + slot / 2) / W) * 100}% - 60px), calc(100% - 130px))` }}>
              <div className="text-muted">{fmtDay(`${data[hover].date}T12:00:00Z`)}</div>
              <div className="font-semibold text-ink tabular-nums">{data[hover].hours} h booked</div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function niceStep(max: number) {
  const raw = max / 4;
  const pow = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
}

function ResourceTable({ rows, own }: { rows: Row[]; own: boolean }) {
  return (
    <Card className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="border-b border-line text-left text-xs text-muted">
          <tr>
            <th className="px-4 py-2.5 font-medium">Resource</th>
            <th className="px-3 py-2.5 text-right font-medium">Hours</th>
            {!own && <th className="px-3 py-2.5 font-medium">Utilization</th>}
            <th className="px-3 py-2.5 text-right font-medium">Sessions</th>
            {!own && <th className="px-3 py-2.5 text-right font-medium">Users</th>}
            <th className="px-3 py-2.5 text-right font-medium">Cancelled</th>
            <th className="px-4 py-2.5 text-right font-medium">Late</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.resource_id} className="border-b border-line last:border-0">
              <td className="px-4 py-2.5"><div className="font-medium">{r.resource_name}</div><div className="text-xs text-muted">{r.lab_name}</div></td>
              <td className="px-3 py-2.5 text-right tabular-nums">{r.booked_hours}</td>
              {!own && (
                <td className="px-3 py-2.5">
                  {r.utilization_pct === null ? "—" : (
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-[var(--chart-1)]" style={{ width: `${Math.min(100, r.utilization_pct)}%` }} /></div>
                      <span className="text-xs tabular-nums">{r.utilization_pct}%</span>
                    </div>
                  )}
                </td>
              )}
              <td className="px-3 py-2.5 text-right tabular-nums">{r.bookings}</td>
              {!own && <td className="px-3 py-2.5 text-right tabular-nums">{r.unique_users}</td>}
              <td className="px-3 py-2.5 text-right tabular-nums">{r.cancellations}</td>
              <td className="px-4 py-2.5 text-right tabular-nums">{r.late_cancellations}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
