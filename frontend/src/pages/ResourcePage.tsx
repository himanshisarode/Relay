import FullCalendar from "@fullcalendar/react";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import luxonPlugin from "@fullcalendar/luxon3";
import type { EventInput, EventSourceFuncArg } from "@fullcalendar/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarPlus, Clock, KeyRound, MapPin, Repeat, Settings2, Wrench } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, errorMessage, post } from "../api";
import { AccessBadge, Alert, Badge, Button, Card, Dialog, Field, Input, POLICY, PolicyBadge, Select, Spinner, Textarea } from "../components/ui";
import { addMinutes, fmtDate, fmtRange, fmtTime, humanMinutes, iso, localDate, localHHMM, TZ, tzLabel, zoned } from "../time";
import type { Booking, CalendarEntry, Resource } from "../types";

export function ResourcePage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const r = useQuery({ queryKey: ["resource", id], queryFn: () => api<Resource>(`/resources/${id}`) });
  const cal = useRef<FullCalendar>(null);
  const [booking, setBooking] = useState<{ start: Date | null; minutes?: number } | null>(null);
  const [requesting, setRequesting] = useState(false);

  if (r.isLoading) return <Spinner />;
  if (r.error || !r.data) return <Alert>{errorMessage(r.error)}</Alert>;
  const res = r.data;
  const refresh = () => {
    cal.current?.getApi().refetchEvents();
    qc.invalidateQueries({ queryKey: ["resource", id] });
    qc.invalidateQueries({ queryKey: ["quota", res.id] });
  };
  const canBook = res.my_access === "allowed" && res.status === "active";
  const allDay = res.open_time === res.close_time;

  const loadEvents = async (info: EventSourceFuncArg): Promise<EventInput[]> => {
    const items = await api<CalendarEntry[]>(`/resources/${res.id}/availability?from=${encodeURIComponent(info.startStr)}&to=${encodeURIComponent(info.endStr)}`);
    return items.map((e) => ({
      id: String(e.id ?? `${e.start}`),
      start: e.start,
      end: e.end,
      title: e.label + (e.user_name && !e.mine && e.purpose ? ` — ${e.purpose}` : ""),
      classNames: [e.kind === "maintenance" ? "ev-maint" : e.status === "held" ? "ev-held" : e.mine ? "ev-mine" : "ev-other"],
    }));
  };

  return (
    <>
      <Link to="/resources" className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-ink"><ArrowLeft className="size-4" aria-hidden />All resources</Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {res.status !== "active" ? <Badge tone="warn"><Wrench className="size-3" aria-hidden />{res.status}</Badge> : <AccessBadge access={res.my_access} />}
            <PolicyBadge policy={res.access_policy} />
            <Badge>{res.type === "meeting_room" ? "Meeting room" : "Instrument"}</Badge>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">{res.name}</h1>
          <p className="mt-1 text-sm text-muted">{res.lab_name} · {res.department_name}</p>
          {res.location && <p className="mt-1 flex items-center gap-1.5 text-sm text-muted"><MapPin className="size-3.5" aria-hidden />{res.location}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          {res.can_manage && <Link to={`/manage/resources/${res.id}`}><Button variant="secondary"><Settings2 className="size-4" aria-hidden />Settings</Button></Link>}
          {canBook ? (
            <Button onClick={() => setBooking({ start: null })}><CalendarPlus className="size-4" aria-hidden />Book</Button>
          ) : res.my_access === "request_possible" && res.status === "active" ? (
            <Button onClick={() => setRequesting(true)}><KeyRound className="size-4" aria-hidden />Request access</Button>
          ) : res.my_access === "request_pending" ? (
            <Link to="/access"><Button variant="secondary">Request pending — view</Button></Link>
          ) : null}
        </div>
      </div>

      {!canBook && res.my_access !== "allowed" && (
        <div className="mb-4">
          <Alert tone="info" title={res.my_access === "request_pending" ? "Your request is with the lab's professor." : "You can't book this yet."}>
            {POLICY[res.access_policy].hint} can book directly.
            {res.my_access === "request_possible" && " Send a request and the lab's professor will decide."}
          </Alert>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        <Card className="overflow-hidden p-2 sm:p-3">
          <FullCalendar
            ref={cal}
            plugins={[timeGridPlugin, interactionPlugin, luxonPlugin]}
            timeZone={TZ}
            initialView={window.innerWidth < 640 ? "timeGridDay" : "timeGridWeek"}
            headerToolbar={{ left: "prev,next today", center: "title", right: "timeGridWeek,timeGridDay" }}
            buttonText={{ today: "Today", week: "Week", day: "Day" }}
            firstDay={1}
            height="auto"
            allDaySlot={false}
            nowIndicator
            slotDuration={{ minutes: Math.min(60, Math.max(15, res.slot_granularity_min)) }}
            snapDuration={{ minutes: res.slot_granularity_min }}
            slotMinTime={allDay ? "00:00" : res.open_time.slice(0, 5)}
            slotMaxTime={allDay ? "24:00" : res.close_time <= res.open_time ? "24:00" : res.close_time.slice(0, 5)}
            scrollTime={allDay ? "08:00" : undefined}
            slotLabelFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
            eventTimeFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
            dayHeaderFormat={{ weekday: "short", day: "numeric" }}
            selectable={canBook}
            selectMirror
            selectOverlap={false}
            select={(s) => { setBooking({ start: s.start, minutes: Math.round((s.end.getTime() - s.start.getTime()) / 60000) }); s.view.calendar.unselect(); }}
            events={loadEvents}
          />
          <div className="flex flex-wrap gap-4 px-2 pt-3 text-xs text-muted">
            <Legend className="bg-brand" label="Your bookings" />
            <Legend className="bg-surface-2 border border-faint" label="Booked" />
            <Legend className="bg-warn-soft border border-warn" label="Maintenance" />
            <span className="ml-auto">{canBook ? "Drag on the calendar to pick a time · " : ""}{tzLabel()}</span>
          </div>
        </Card>
        <aside className="space-y-4">
          <RulesCard r={res} />
          {res.description && <Card className="p-4 text-sm text-muted">{res.description}</Card>}
        </aside>
      </div>

      <BookingDialog r={res} open={!!booking} initial={booking} onClose={() => setBooking(null)} onDone={refresh} />
      <RequestAccessDialog r={res} open={requesting} onClose={() => setRequesting(false)} onDone={refresh} />
    </>
  );
}

function Legend({ className, label }: { className: string; label: string }) {
  return <span className="inline-flex items-center gap-1.5"><span className={`size-3 rounded-sm ${className}`} aria-hidden />{label}</span>;
}

function RulesCard({ r }: { r: Resource }) {
  const quota = useQuery({ queryKey: ["quota", r.id], queryFn: () => api<{ weekly_quota_min: number | null; used_min: number; remaining_min: number | null }>(`/resources/${r.id}/my-quota`), enabled: r.my_access === "allowed" });
  const hours = r.open_time === r.close_time ? "Open 24 hours" : `${r.open_time.slice(0, 5)}–${r.close_time.slice(0, 5)}`;
  const rows: [string, string][] = [
    ["Hours", hours],
    ["Length", `${humanMinutes(r.min_duration_min)} – ${humanMinutes(r.max_duration_min)}`],
    ["Slots", `${r.slot_granularity_min}-minute steps`],
    ["Book ahead", `up to ${r.max_advance_days} days`],
    ["Notice", r.min_notice_min ? `${humanMinutes(r.min_notice_min)} minimum` : "none"],
    ["Weekly limit", r.weekly_quota_min && r.type !== "meeting_room" ? humanMinutes(r.weekly_quota_min) : "none"],
    ["Late cancel", `within ${humanMinutes(r.cancellation_cutoff_min)} of start`],
  ];
  const q = quota.data;
  return (
    <Card className="p-4">
      <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold"><Clock className="size-4 text-muted" aria-hidden />Booking rules</h2>
      <dl className="space-y-2 text-sm">
        {rows.map(([k, v]) => <div key={k} className="flex justify-between gap-3"><dt className="text-muted">{k}</dt><dd className="text-right font-medium">{v}</dd></div>)}
      </dl>
      {q && q.weekly_quota_min !== null && (
        <div className="mt-4 border-t border-line pt-3">
          <div className="mb-1.5 flex justify-between text-xs"><span className="text-muted">Used this week</span><span className="font-medium tabular-nums">{humanMinutes(q.used_min)} of {humanMinutes(q.weekly_quota_min)}</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-2" role="meter" aria-valuenow={q.used_min} aria-valuemax={q.weekly_quota_min} aria-label="Weekly quota used">
            <div className="h-full rounded-full bg-brand" style={{ width: `${Math.min(100, (100 * q.used_min) / q.weekly_quota_min)}%` }} />
          </div>
        </div>
      )}
    </Card>
  );
}

// ---- booking dialog (create, reschedule, recurring) ---------------------------------------------------------

function timeOptions(r: Resource): string[] {
  const out: string[] = [];
  const [oh, om] = r.open_time.split(":").map(Number);
  const [ch, cm] = r.close_time.split(":").map(Number);
  const open = oh * 60 + om;
  let close = ch * 60 + cm;
  if (close <= open) close += 24 * 60;
  for (let m = open; m + r.min_duration_min <= close; m += r.slot_granularity_min) {
    const mm = m % (24 * 60);
    out.push(`${String(Math.floor(mm / 60)).padStart(2, "0")}:${String(mm % 60).padStart(2, "0")}`);
  }
  return out;
}

function durationOptions(r: Resource): number[] {
  const out: number[] = [];
  const first = Math.ceil(r.min_duration_min / r.slot_granularity_min) * r.slot_granularity_min;
  for (let m = first; m <= r.max_duration_min; m += r.slot_granularity_min) out.push(m);
  return out;
}

function clientCheck(r: Resource, start: Date, end: Date, privileged: boolean): string | null {
  const now = Date.now();
  if (start.getTime() < now) return "That time is in the past.";
  if (!privileged && start.getTime() < now + r.min_notice_min * 60000) return `Book at least ${humanMinutes(r.min_notice_min)} ahead.`;
  if (!privileged && start.getTime() > now + r.max_advance_days * 86400000) return `You can book at most ${r.max_advance_days} days ahead.`;
  if (r.open_time !== r.close_time && r.close_time > r.open_time) {
    const close = zoned(localDate(start), r.close_time.slice(0, 5));
    if (end > close) return `This runs past closing time (${r.close_time.slice(0, 5)}).`;
  }
  return null;
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function BookingDialog({ r, open, initial, onClose, onDone, reschedule }: {
  r: Resource; open: boolean; initial: { start: Date | null; minutes?: number } | null; onClose: () => void; onDone: () => void; reschedule?: Booking;
}) {
  const times = useMemo(() => timeOptions(r), [r]);
  const durations = useMemo(() => durationOptions(r), [r]);
  const start0 = initial?.start ?? null;
  const [date, setDate] = useState(start0 ? localDate(start0) : localDate(new Date(Date.now() + 86400000)));
  const [time, setTime] = useState(start0 ? localHHMM(start0) : times.find((t) => t >= "10:00") ?? times[0]);
  const [minutes, setMinutes] = useState(initial?.minutes && durations.includes(initial.minutes) ? initial.minutes : durations.find((d) => d >= 60) ?? durations[0]);
  const [purpose, setPurpose] = useState(reschedule?.purpose ?? "");
  const [repeat, setRepeat] = useState(false);
  const [series, setSeries] = useState({ weekdays: [] as number[], interval: 1, count: 12, mode: "skip_conflicts", attendees: "" });
  const [done, setDone] = useState<string | null>(null);

  const start = zoned(date, time);
  const end = addMinutes(start, minutes);
  const warn = clientCheck(r, start, end, r.can_manage);

  const m = useMutation({
    mutationFn: async () => {
      if (repeat) {
        const wd = series.weekdays.length ? series.weekdays : [(new Date(`${date}T12:00:00Z`).getUTCDay() + 6) % 7];
        const res = await post<{ created: Booking[]; skipped: { start: string }[] }>("/booking-series", {
          resource_id: r.id, title: purpose || "Lab meeting", weekdays: wd, interval: series.interval, local_start_time: time,
          duration_min: minutes, starts_on: date, count: series.count, mode: series.mode,
          attendee_emails: series.attendees.split(/[\s,;]+/).filter(Boolean),
        });
        return `${res.created.length} meetings booked${res.skipped.length ? `; skipped ${res.skipped.map((s) => fmtDate(s.start)).join(", ")}` : ""}.`;
      }
      if (reschedule) {
        await post(`/bookings/${reschedule.id}/reschedule`, { start: iso(start), end: iso(end) });
        return "Moved.";
      }
      await post("/bookings", { resource_id: r.id, start: iso(start), end: iso(end), purpose });
      return "Booked.";
    },
    onSuccess: (msg) => { setDone(msg); onDone(); },
  });
  const waitlist = useMutation({ mutationFn: () => post("/waitlist", { resource_id: r.id, start: iso(start), end: iso(end) }), onSuccess: () => setDone("You're on the waitlist. We'll notify you if it frees up.") });
  // Reset the form whenever the dialog is opened with a new selection.
  const key = `${open}-${initial?.start?.getTime()}-${initial?.minutes}`;
  useEffect(() => {
    if (!open) return;
    if (start0) { setDate(localDate(start0)); setTime(localHHMM(start0)); }
    if (initial?.minutes && durations.includes(initial.minutes)) setMinutes(initial.minutes);
    setDone(null);
    m.reset();
    waitlist.reset();
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const err = m.error as ApiError | null;
  const suggestions: { start: string; end: string }[] = err?.code === "slot_conflict" ? err.details.next_available ?? [] : [];

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={reschedule ? `Move booking · ${r.name}` : `Book ${r.name}`}
      footer={done ? <Button onClick={onClose}>Done</Button> : (
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={() => m.mutate()} loading={m.isPending} disabled={!!warn && !repeat}>
            {repeat ? "Book series" : reschedule ? "Move booking" : "Confirm booking"}
          </Button>
        </>
      )}
    >
      {done ? (
        <Alert tone="ok" title={done}>{!repeat && fmtRange(iso(start), iso(end))}</Alert>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Field label="Date"><Input type="date" value={date} min={localDate()} onChange={(e) => setDate(e.target.value)} /></Field>
            <Field label="Start"><Select value={time} onChange={(e) => setTime(e.target.value)}>{times.map((t) => <option key={t}>{t}</option>)}</Select></Field>
            <Field label="Length"><Select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>{durations.map((d) => <option key={d} value={d}>{humanMinutes(d)}</option>)}</Select></Field>
          </div>
          <div className="flex items-center justify-between rounded-lg bg-surface-2 px-3 py-2 text-sm">
            <span className="font-medium">{fmtRange(iso(start), iso(end))}</span>
          </div>
          {!repeat && warn && <Alert tone="warn">{warn}</Alert>}
          {!reschedule && (
            <Field label={repeat ? "Meeting title" : "Purpose"} hint={repeat ? undefined : "Only you and the lab's professor can see this."}>
              <Textarea className="min-h-16" maxLength={500} value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder={repeat ? "Weekly group meeting" : "e.g. Sample characterisation"} />
            </Field>
          )}
          {r.type === "meeting_room" && !reschedule && (
            <div className="rounded-lg border border-line p-3">
              <label className="flex cursor-pointer items-center gap-2 text-sm font-medium">
                <input type="checkbox" className="accent-[var(--brand)]" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} />
                <Repeat className="size-4 text-muted" aria-hidden /> Repeat this meeting
              </label>
              {repeat && (
                <div className="mt-3 space-y-3">
                  <div className="flex flex-wrap gap-1.5">
                    {WEEKDAYS.map((d, i) => {
                      const on = series.weekdays.includes(i);
                      return (
                        <button key={d} type="button" onClick={() => setSeries({ ...series, weekdays: on ? series.weekdays.filter((x) => x !== i) : [...series.weekdays, i] })}
                          className={`h-8 w-11 rounded-md border text-xs font-medium ${on ? "border-brand bg-brand text-brand-ink" : "border-line text-muted hover:bg-surface-2"}`}>
                          {d}
                        </button>
                      );
                    })}
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Every"><Select value={series.interval} onChange={(e) => setSeries({ ...series, interval: Number(e.target.value) })}><option value={1}>Week</option><option value={2}>Two weeks</option></Select></Field>
                    <Field label="Occurrences"><Input type="number" min={1} max={200} value={series.count} onChange={(e) => setSeries({ ...series, count: Number(e.target.value) })} /></Field>
                  </div>
                  <Field label="If a date is taken">
                    <Select value={series.mode} onChange={(e) => setSeries({ ...series, mode: e.target.value })}>
                      <option value="skip_conflicts">Skip that date, book the rest</option>
                      <option value="all_or_nothing">Book nothing (all or nothing)</option>
                    </Select>
                  </Field>
                  <Field label="Invite people" hint="Emails separated by commas. They get a calendar invite.">
                    <Input value={series.attendees} onChange={(e) => setSeries({ ...series, attendees: e.target.value })} placeholder="name@relay.test, …" />
                  </Field>
                </div>
              )}
            </div>
          )}
          {m.error && (
            <Alert title={errorMessage(m.error)}>
              {err?.code === "series_conflicts" && Array.isArray(err.details.skipped) && <>Clashes: {err.details.skipped.map((s: any) => fmtDate(s.start)).join(", ")}</>}
              {suggestions.length > 0 && (
                <div className="mt-2">
                  <div className="mb-1.5 text-xs">Next free slots:</div>
                  <div className="flex flex-wrap gap-1.5">
                    {suggestions.map((s) => (
                      <button key={s.start} className="rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-ink hover:border-brand"
                        onClick={() => { setDate(localDate(new Date(s.start))); setTime(localHHMM(new Date(s.start))); m.reset(); }}>
                        {fmtDate(s.start)} {fmtTime(s.start)}
                      </button>
                    ))}
                  </div>
                  {!reschedule && <Button size="sm" variant="secondary" className="mt-3" loading={waitlist.isPending} onClick={() => waitlist.mutate()}>Join the waitlist for this time</Button>}
                  {waitlist.error && <div className="mt-2 text-xs">{errorMessage(waitlist.error)}</div>}
                </div>
              )}
            </Alert>
          )}
        </div>
      )}
    </Dialog>
  );
}

function RequestAccessDialog({ r, open, onClose, onDone }: { r: Resource; open: boolean; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ justification: "", requested_until: localDate(new Date(Date.now() + 90 * 86400000)), supervisor_name: "" });
  const m = useMutation({ mutationFn: () => post(`/resources/${r.id}/access-requests`, f), onSuccess: onDone });
  const short = f.justification.trim().length < 20;
  return (
    <Dialog open={open} onClose={onClose} title={`Request access · ${r.name}`}
      footer={m.isSuccess ? <Button onClick={onClose}>Done</Button> : <><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={() => m.mutate()} loading={m.isPending} disabled={short}>Send request</Button></>}>
      {m.isSuccess ? (
        <Alert tone="ok" title="Request sent.">The professor of {r.lab_name} has been notified. You'll get an email when they decide.</Alert>
      ) : (
        <div className="space-y-4">
          {m.error && <Alert>{errorMessage(m.error)}</Alert>}
          <Field label="Why do you need it?" hint={`${Math.max(0, 20 - f.justification.trim().length) || "✓"} ${short ? "more characters needed" : ""}`}>
            <Textarea value={f.justification} maxLength={2000} onChange={(e) => setF({ ...f, justification: e.target.value })} placeholder="What you'll measure, for which project, and roughly how often." />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Access until"><Input type="date" min={localDate(new Date(Date.now() + 86400000))} value={f.requested_until} onChange={(e) => setF({ ...f, requested_until: e.target.value })} /></Field>
            <Field label="Supervisor (optional)"><Input value={f.supervisor_name} onChange={(e) => setF({ ...f, supervisor_name: e.target.value })} /></Field>
          </div>
        </div>
      )}
    </Dialog>
  );
}
