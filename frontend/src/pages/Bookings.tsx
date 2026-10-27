import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Clock4, KeyRound, Repeat } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage, post, del } from "../api";
import { Alert, Badge, Button, Card, Dialog, Empty, Field, PageHeader, Skeleton, StatusBadge, Tabs, Textarea } from "../components/ui";
import { fmtDate, fmtDateTime, fmtRange, fmtTime, relative } from "../time";
import type { AccessRequest, Booking, Grant, Resource, WaitlistEntry } from "../types";
import { BookingDialog } from "./ResourcePage";

export function BookingsPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"upcoming" | "past">("upcoming");
  const list = useQuery({ queryKey: ["my-bookings"], queryFn: () => api<Booking[]>("/bookings?include_cancelled=true") });
  const wl = useQuery({ queryKey: ["waitlist"], queryFn: () => api<WaitlistEntry[]>("/waitlist") });
  const [cancelling, setCancelling] = useState<Booking | null>(null);
  const [moving, setMoving] = useState<Booking | null>(null);
  const movingRes = useQuery({ queryKey: ["resource", String(moving?.resource_id)], queryFn: () => api<Resource>(`/resources/${moving!.resource_id}`), enabled: !!moving });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["my-bookings"] }); qc.invalidateQueries({ queryKey: ["waitlist"] }); };

  const now = Date.now();
  const all = list.data ?? [];
  const upcoming = all.filter((b) => new Date(b.end).getTime() > now && (b.status === "confirmed" || b.status === "held"));
  const past = all.filter((b) => !upcoming.includes(b)).reverse();
  const shown = tab === "upcoming" ? upcoming : past;

  return (
    <>
      <PageHeader title="My bookings" subtitle="Upcoming sessions, history, and waitlist offers." actions={<Link to="/resources"><Button>New booking</Button></Link>} />
      {wl.data && wl.data.length > 0 && <WaitlistPanel entries={wl.data} onChange={refresh} />}
      <Tabs value={tab} onChange={setTab} items={[{ value: "upcoming", label: "Upcoming", count: upcoming.length }, { value: "past", label: "Past & cancelled", count: past.length }]} />
      {list.isLoading ? (
        <div className="space-y-2">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-20" />)}</div>
      ) : shown.length === 0 ? (
        <Empty icon={<CalendarDays className="size-5" />} title={tab === "upcoming" ? "No upcoming bookings" : "No history yet"} action={tab === "upcoming" && <Link to="/resources"><Button variant="secondary">Find a resource</Button></Link>}>
          {tab === "upcoming" ? "Book an instrument or room and it will show up here." : undefined}
        </Empty>
      ) : (
        <Card className="divide-y divide-line">
          {shown.map((b) => (
            <div key={b.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
              <div className="flex w-16 shrink-0 flex-col items-center rounded-lg bg-surface-2 py-1.5 text-center">
                <span className="text-[11px] font-medium text-muted uppercase">{fmtDate(b.start).split(" ")[1]}</span>
                <span className="text-lg leading-tight font-semibold">{fmtDate(b.start).split(" ")[0]}</span>
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={`/resources/${b.resource_id}`} className="font-medium hover:text-brand">{b.resource_name}</Link>
                  <StatusBadge status={b.status} />
                  {b.series_id && <Badge tone="info"><Repeat className="size-3" aria-hidden />Series</Badge>}
                </div>
                <div className="mt-0.5 text-sm text-muted">{fmtRange(b.start, b.end)} · {b.lab_name}</div>
                {b.purpose && <div className="mt-0.5 truncate text-sm">{b.purpose}</div>}
                {b.status === "cancelled" && b.cancel_reason && <div className="mt-0.5 text-xs text-muted">Cancelled: {b.cancel_reason}</div>}
              </div>
              {tab === "upcoming" && b.status === "confirmed" && (
                <div className="flex gap-2">
                  {!b.series_id && <Button size="sm" variant="secondary" onClick={() => setMoving(b)}>Reschedule</Button>}
                  <Button size="sm" variant="ghost" onClick={() => setCancelling(b)}>Cancel</Button>
                </div>
              )}
            </div>
          ))}
        </Card>
      )}
      <CancelDialog booking={cancelling} onClose={() => setCancelling(null)} onDone={refresh} />
      {moving && movingRes.data && (
        <BookingDialog r={movingRes.data} open reschedule={moving} initial={{ start: new Date(moving.start), minutes: (new Date(moving.end).getTime() - new Date(moving.start).getTime()) / 60000 }}
          onClose={() => setMoving(null)} onDone={refresh} />
      )}
    </>
  );
}

function CancelDialog({ booking, onClose, onDone }: { booking: Booking | null; onClose: () => void; onDone: () => void }) {
  const [scope, setScope] = useState<"this" | "future">("this");
  const m = useMutation({
    mutationFn: () =>
      booking!.series_id
        ? post(`/booking-series/${booking!.series_id}/cancel?scope=${scope}&booking_id=${booking!.id}`)
        : post(`/bookings/${booking!.id}/cancel`, {}),
    onSuccess: () => { onDone(); onClose(); },
  });
  if (!booking) return null;
  const late = Date.now() > new Date(booking.late_cancel_after).getTime();
  return (
    <Dialog open onClose={onClose} title="Cancel booking"
      footer={<><Button variant="secondary" onClick={onClose}>Keep it</Button><Button variant="danger" loading={m.isPending} onClick={() => m.mutate()}>Cancel booking</Button></>}>
      <div className="space-y-3 text-sm">
        <p><b>{booking.resource_name}</b><br />{fmtRange(booking.start, booking.end)}</p>
        {late && <Alert tone="warn">This is within the late-cancellation window, so it will be recorded as a late cancel.</Alert>}
        {booking.series_id && (
          <div className="space-y-1.5">
            <label className="flex items-center gap-2"><input type="radio" className="accent-[var(--brand)]" checked={scope === "this"} onChange={() => setScope("this")} />Only this meeting</label>
            <label className="flex items-center gap-2"><input type="radio" className="accent-[var(--brand)]" checked={scope === "future"} onChange={() => setScope("future")} />This and all future meetings</label>
          </div>
        )}
        {m.error && <Alert>{errorMessage(m.error)}</Alert>}
      </div>
    </Dialog>
  );
}

function WaitlistPanel({ entries, onChange }: { entries: WaitlistEntry[]; onChange: () => void }) {
  const accept = useMutation({ mutationFn: (id: number) => post(`/waitlist/${id}/accept`), onSuccess: onChange });
  const leave = useMutation({ mutationFn: (id: number) => del(`/waitlist/${id}`), onSuccess: onChange });
  return (
    <Card className="mb-6 p-4">
      <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold"><Clock4 className="size-4 text-muted" aria-hidden />Waitlist</h2>
      {(accept.error || leave.error) && <div className="mb-2"><Alert>{errorMessage(accept.error ?? leave.error)}</Alert></div>}
      <div className="space-y-2">
        {entries.map((e) => (
          <div key={e.id} className={`flex flex-wrap items-center gap-3 rounded-lg p-3 ${e.status === "offered" ? "bg-info-soft" : "bg-surface-2"}`}>
            <div className="min-w-0 flex-1 text-sm">
              <div className="font-medium">{e.resource_name}</div>
              <div className="text-muted">{fmtRange(e.start, e.end)}</div>
              {e.status === "offered" && e.offer_expires_at && <div className="mt-0.5 text-xs font-medium text-info">The slot is free for you — confirm by {fmtTime(e.offer_expires_at)}</div>}
            </div>
            {e.status === "offered" && <Button size="sm" loading={accept.isPending} onClick={() => accept.mutate(e.id)}>Confirm booking</Button>}
            <Button size="sm" variant="ghost" onClick={() => leave.mutate(e.id)}>Leave</Button>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ---- My access ------------------------------------------------------------------------------------------------

export function AccessPage() {
  const qc = useQueryClient();
  const grants = useQuery({ queryKey: ["my-grants"], queryFn: () => api<Grant[]>("/access-grants?mine=true") });
  const reqs = useQuery({ queryKey: ["my-requests"], queryFn: () => api<AccessRequest[]>("/access-requests?mine=true") });
  const cancel = useMutation({ mutationFn: (id: number) => post(`/access-requests/${id}/cancel`), onSuccess: () => qc.invalidateQueries({ queryKey: ["my-requests"] }) });
  const active = (grants.data ?? []).filter((g) => g.state === "active");
  return (
    <>
      <PageHeader title="My access" subtitle="Grants you hold on other labs' resources, and the requests you've sent." />
      <section className="mb-8">
        <h2 className="mb-3 text-sm font-semibold text-muted">Active grants</h2>
        {grants.isLoading ? <Skeleton className="h-24" /> : active.length === 0 ? (
          <Empty icon={<KeyRound className="size-5" />} title="No grants yet">Your own lab's and department's resources don't need one. For anything else, open the resource and press “Request access”.</Empty>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {active.map((g) => {
              const days = Math.ceil((new Date(g.expires_at).getTime() - Date.now()) / 86400000);
              return (
                <Card key={g.id} className="p-4">
                  <Link to={`/resources/${g.resource_id}`} className="font-medium hover:text-brand">{g.resource_name}</Link>
                  <div className="text-sm text-muted">{g.lab_name}</div>
                  <div className="mt-3 flex items-center gap-2 text-sm">
                    <Badge tone={days <= 7 ? "warn" : "ok"}>{days <= 0 ? "Ends today" : `${days} days left`}</Badge>
                    <span className="text-muted">until {fmtDate(g.expires_at)}</span>
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </section>
      <section>
        <h2 className="mb-3 text-sm font-semibold text-muted">Requests</h2>
        {reqs.data?.length ? (
          <Card className="divide-y divide-line">
            {reqs.data.map((r) => (
              <div key={r.id} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2"><Link to={`/resources/${r.resource_id}`} className="font-medium hover:text-brand">{r.resource_name}</Link><StatusBadge status={r.status} /></div>
                  <div className="text-sm text-muted">{r.lab_name} · sent {relative(r.created_at)} · until {fmtDate(r.requested_until)}</div>
                  {r.decision_note && <div className="mt-1.5 rounded-md bg-surface-2 px-2.5 py-1.5 text-sm">{r.status === "rejected" ? "Reason: " : "Note: "}{r.decision_note}</div>}
                </div>
                {r.status === "pending" && <Button size="sm" variant="ghost" onClick={() => cancel.mutate(r.id)}>Withdraw</Button>}
              </div>
            ))}
          </Card>
        ) : (
          <p className="text-sm text-muted">You haven't sent any requests.</p>
        )}
      </section>
    </>
  );
}

// ---- Professor inbox ---------------------------------------------------------------------------------------------

export function InboxPage() {
  const qc = useQueryClient();
  const reqs = useQuery({ queryKey: ["inbox"], queryFn: () => api<AccessRequest[]>("/access-requests?to_decide=true") });
  const grants = useQuery({ queryKey: ["managed-grants"], queryFn: () => api<Grant[]>("/access-grants?mine=false") });
  const [deciding, setDeciding] = useState<{ req: AccessRequest; action: "approve" | "reject" } | null>(null);
  const [revoking, setRevoking] = useState<Grant | null>(null);
  const [tab, setTab] = useState<"requests" | "grants">("requests");
  const refresh = () => ["inbox", "inbox-count", "managed-grants"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  return (
    <>
      <PageHeader title="Inbox" subtitle="Access requests for your labs' resources, and the grants you've given." />
      <Tabs value={tab} onChange={setTab} items={[{ value: "requests", label: "To decide", count: reqs.data?.length }, { value: "grants", label: "Active grants", count: grants.data?.length }]} />
      {tab === "requests" ? (
        reqs.isLoading ? <Skeleton className="h-40" /> : !reqs.data?.length ? (
          <Empty title="Nothing to decide" icon={<KeyRound className="size-5" />}>New access requests for your labs will appear here.</Empty>
        ) : (
          <div className="space-y-3">
            {reqs.data.map((r) => (
              <Card key={r.id} className="p-4 sm:p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-medium">{r.requester_name} <span className="font-normal text-muted">wants</span> {r.resource_name}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-sm text-muted">
                      {r.requester_email}
                      {r.requester_departments.map((d) => <Badge key={d.code} tone={d.verified ? "neutral" : "warn"}>{d.code}{d.verified ? "" : " · unverified"}</Badge>)}
                      {!r.requester_departments.length && <Badge>No department</Badge>}
                    </div>
                  </div>
                  <div className="text-right text-xs text-muted">sent {relative(r.created_at)}<br />until {fmtDate(r.requested_until)}</div>
                </div>
                <p className="mt-3 rounded-lg bg-surface-2 p-3 text-sm whitespace-pre-line">{r.justification}</p>
                {r.supervisor_name && <p className="mt-2 text-xs text-muted">Supervisor: {r.supervisor_name}</p>}
                <div className="mt-4 flex gap-2">
                  <Button size="sm" onClick={() => setDeciding({ req: r, action: "approve" })}>Approve…</Button>
                  <Button size="sm" variant="secondary" onClick={() => setDeciding({ req: r, action: "reject" })}>Reject…</Button>
                </div>
              </Card>
            ))}
          </div>
        )
      ) : !grants.data?.length ? (
        <Empty title="No active grants">Approved requests become grants that you can revoke here.</Empty>
      ) : (
        <Card className="divide-y divide-line">
          {grants.data.map((g) => (
            <div key={g.id} className="flex flex-wrap items-center gap-3 p-4">
              <div className="min-w-0 flex-1">
                <div className="font-medium">{g.user_name}</div>
                <div className="text-sm text-muted">{g.resource_name} · until {fmtDateTime(g.expires_at)}</div>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setRevoking(g)}>Revoke…</Button>
            </div>
          ))}
        </Card>
      )}
      {deciding && <DecideDialog {...deciding} onClose={() => setDeciding(null)} onDone={refresh} />}
      {revoking && <RevokeDialog grant={revoking} onClose={() => setRevoking(null)} onDone={refresh} />}
    </>
  );
}

function DecideDialog({ req, action, onClose, onDone }: { req: AccessRequest; action: "approve" | "reject"; onClose: () => void; onDone: () => void }) {
  const [until, setUntil] = useState(req.requested_until);
  const [text, setText] = useState("");
  const m = useMutation({
    mutationFn: () => action === "approve" ? post(`/access-requests/${req.id}/approve`, { until, note: text || null }) : post(`/access-requests/${req.id}/reject`, { reason: text }),
    onSuccess: () => { onDone(); onClose(); },
  });
  return (
    <Dialog open onClose={onClose} title={`${action === "approve" ? "Approve" : "Reject"} · ${req.requester_name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant={action === "reject" ? "danger" : "primary"} loading={m.isPending} disabled={action === "reject" && text.trim().length < 5} onClick={() => m.mutate()}>{action === "approve" ? "Approve" : "Reject"}</Button></>}>
      <div className="space-y-4">
        {m.error && <Alert>{errorMessage(m.error)}</Alert>}
        {action === "approve" && <Field label="Access until" hint="You can shorten what they asked for, not extend it."><input type="date" className="h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm" max={req.requested_until} value={until} onChange={(e) => setUntil(e.target.value)} /></Field>}
        <Field label={action === "approve" ? "Note (optional)" : "Reason (shown to the requester)"}>
          <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={action === "approve" ? "e.g. Please book afternoons only." : "e.g. The instrument is reserved for thesis work this term."} />
        </Field>
      </div>
    </Dialog>
  );
}

function RevokeDialog({ grant, onClose, onDone }: { grant: Grant; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const m = useMutation({ mutationFn: () => post<{ cancelled_booking_ids: number[] }>(`/access-grants/${grant.id}/revoke`, { reason: reason || null }), onSuccess: onDone });
  return (
    <Dialog open onClose={onClose} title={`Revoke ${grant.user_name}'s access`}
      footer={m.isSuccess ? <Button onClick={onClose}>Done</Button> : <><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="danger" loading={m.isPending} onClick={() => m.mutate()}>Revoke</Button></>}>
      {m.isSuccess ? <Alert tone="ok" title="Access revoked.">{m.data.cancelled_booking_ids.length} upcoming booking(s) were cancelled and the user was notified.</Alert> : (
        <div className="space-y-3">
          <p className="text-sm text-muted">Their upcoming bookings on <b className="text-ink">{grant.resource_name}</b> will be cancelled and they'll be notified.</p>
          {m.error && <Alert>{errorMessage(m.error)}</Alert>}
          <Field label="Reason (optional)"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        </div>
      )}
    </Dialog>
  );
}
