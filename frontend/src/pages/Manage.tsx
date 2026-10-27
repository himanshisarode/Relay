import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus, Trash2, UserPlus, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, del, errorMessage, patch, post } from "../api";
import { useAuth } from "../auth";
import { Alert, Badge, Button, Card, Dialog, Empty, Field, Input, PageHeader, POLICY, PolicyBadge, Select, Skeleton, Spinner, Textarea } from "../components/ui";
import { addMinutes, fmtRange, iso, localDate, zoned } from "../time";
import type { Lab, Policy, Resource } from "../types";

function useManagedLabs() {
  const { me } = useAuth();
  return useQuery({
    queryKey: ["managed-labs", me?.id],
    queryFn: async () => {
      const all = await api<Lab[]>("/labs");
      if (me!.is_superadmin) return all;
      const prof = new Set(me!.labs.filter((l) => l.role === "professor").map((l) => l.id));
      const depts = new Set(me!.departments.filter((d) => d.role === "dept_admin" && d.verified).map((d) => d.id));
      return all.filter((l) => prof.has(l.id) || depts.has(l.department_id));
    },
    enabled: !!me,
  });
}

export function ManagePage() {
  const labs = useManagedLabs();
  const [labId, setLabId] = useState<number | null>(null);
  useEffect(() => { if (labs.data?.length && labId === null) setLabId(labs.data[0].id); }, [labs.data, labId]);
  const lab = labs.data?.find((l) => l.id === labId);

  if (labs.isLoading) return <Spinner />;
  if (!labs.data?.length) return <Empty title="You don't run a lab">Professors manage their lab's members and resources here.</Empty>;
  return (
    <>
      <PageHeader title="My labs" subtitle="As the lab's professor you decide who's in the lab and how its resources are booked."
        actions={labs.data.length > 1 && (
          <Select aria-label="Lab" value={labId ?? ""} onChange={(e) => setLabId(Number(e.target.value))} className="w-72">
            {labs.data.map((l) => <option key={l.id} value={l.id}>{l.name} · {l.department_code}</option>)}
          </Select>
        )} />
      {lab && (
        <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
          <LabResources lab={lab} />
          <LabMembers lab={lab} />
        </div>
      )}
    </>
  );
}

function LabResources({ lab }: { lab: Lab }) {
  const list = useQuery({ queryKey: ["lab-resources", lab.id], queryFn: () => api<Resource[]>(`/resources?lab_id=${lab.id}`) });
  const [adding, setAdding] = useState(false);
  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-muted">Resources in {lab.name}</h2>
        <Button size="sm" variant="secondary" onClick={() => setAdding(true)}><Plus className="size-4" aria-hidden />Add resource</Button>
      </div>
      {list.isLoading ? <Skeleton className="h-48" /> : (
        <Card className="divide-y divide-line">
          {list.data?.map((r) => (
            <Link key={r.id} to={`/manage/resources/${r.id}`} className="flex items-center gap-3 p-4 hover:bg-surface-2">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{r.name}</div>
                <div className="truncate text-xs text-muted">{r.location || "No location set"}</div>
              </div>
              {r.status !== "active" && <Badge tone="warn">{r.status}</Badge>}
              <PolicyBadge policy={r.access_policy} />
            </Link>
          ))}
          {!list.data?.length && <div className="p-6 text-center text-sm text-muted">No resources yet.</div>}
        </Card>
      )}
      <NewResourceDialog lab={lab} open={adding} onClose={() => setAdding(false)} />
    </section>
  );
}

function LabMembers({ lab }: { lab: Lab }) {
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["lab-members", lab.id], queryFn: () => api<{ user_id: number; name: string; email: string; role: string }[]>(`/labs/${lab.id}/members`) });
  const [email, setEmail] = useState("");
  const add = useMutation({ mutationFn: () => post(`/labs/${lab.id}/members`, { email, role: "member" }), onSuccess: () => { setEmail(""); qc.invalidateQueries({ queryKey: ["lab-members", lab.id] }); } });
  const remove = useMutation({ mutationFn: (uid: number) => del(`/labs/${lab.id}/members/${uid}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["lab-members", lab.id] }) });
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold text-muted">Lab members</h2>
      <Card className="p-4">
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <Input type="email" required placeholder="student@relay.test" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Member email" />
          <Button type="submit" loading={add.isPending} aria-label="Add member"><UserPlus className="size-4" aria-hidden /></Button>
        </form>
        <p className="mt-1.5 text-xs text-muted">Adding someone also confirms their department membership.</p>
        {(add.error || remove.error) && <div className="mt-3"><Alert>{errorMessage(add.error ?? remove.error)}</Alert></div>}
        <ul className="mt-4 divide-y divide-line">
          {members.data?.map((m) => (
            <li key={m.user_id} className="flex items-center gap-2 py-2.5">
              <div className="grid size-8 shrink-0 place-items-center rounded-full bg-brand-soft text-xs font-semibold text-brand">{m.name.replace("Prof. ", "").split(" ").map((p) => p[0]).slice(0, 2).join("")}</div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{m.name}</div>
                <div className="truncate text-xs text-muted">{m.email}</div>
              </div>
              {m.role === "professor" ? <Badge tone="brand">Professor</Badge> : (
                <button className="rounded-md p-1.5 text-faint hover:bg-bad-soft hover:text-bad" aria-label={`Remove ${m.name}`} onClick={() => remove.mutate(m.user_id)}><Trash2 className="size-4" /></button>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}

const POLICIES = Object.keys(POLICY) as Policy[];

function NewResourceDialog({ lab, open, onClose }: { lab: Lab; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: "", type: "instrument", access_policy: "department", location: "", description: "" });
  const m = useMutation({
    mutationFn: () => post<Resource>("/resources", { ...f, lab_id: lab.id }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["lab-resources", lab.id] }); onClose(); },
  });
  return (
    <Dialog open={open} onClose={onClose} title={`New resource in ${lab.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={m.isPending} onClick={() => m.mutate()} disabled={f.name.trim().length < 2}>Create</Button></>}>
      <div className="space-y-4">
        {m.error && <Alert>{errorMessage(m.error)}</Alert>}
        <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type"><Select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}><option value="instrument">Instrument</option><option value="meeting_room">Meeting room</option></Select></Field>
          <Field label="Who can book"><Select value={f.access_policy} onChange={(e) => setF({ ...f, access_policy: e.target.value })}>{POLICIES.map((p) => <option key={p} value={p}>{POLICY[p].label}</option>)}</Select></Field>
        </div>
        <Field label="Location"><Input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
        <p className="text-xs text-muted">Booking rules start from sensible defaults; adjust them in the resource's settings.</p>
      </div>
    </Dialog>
  );
}

// ---- resource settings --------------------------------------------------------------------------------------

type Form = Record<string, string | number | boolean | null>;

export function ResourceSettingsPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const r = useQuery({ queryKey: ["resource", id], queryFn: () => api<Resource>(`/resources/${id}`) });
  const [f, setF] = useState<Form | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (r.data) setF({ ...r.data, open_time: r.data.open_time.slice(0, 5), close_time: r.data.close_time.slice(0, 5) }); }, [r.data]);
  const save = useMutation({
    mutationFn: () => {
      const body: Form = {};
      for (const k of ["name", "description", "location", "access_policy", "accepts_requests", "status", "slot_granularity_min", "min_duration_min", "max_duration_min",
        "open_time", "close_time", "max_advance_days", "min_notice_min", "cancellation_cutoff_min"]) body[k] = f![k];
      if (f!.weekly_quota_min === null || f!.weekly_quota_min === "") body.clear_weekly_quota = true; else body.weekly_quota_min = Number(f!.weekly_quota_min);
      return patch<Resource>(`/resources/${id}`, body);
    },
    onSuccess: (d) => { qc.setQueryData(["resource", id], d); setSaved(true); setTimeout(() => setSaved(false), 2500); },
  });
  if (r.isLoading || !f) return <Spinner />;
  if (!r.data!.can_manage) return <Alert>Only the lab's professor can change these settings.</Alert>;
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const num = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value === "" ? "" : Number(e.target.value) });

  return (
    <>
      <Link to={`/resources/${id}`} className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-ink"><ArrowLeft className="size-4" aria-hidden />Back to calendar</Link>
      <PageHeader title={`Settings · ${r.data!.name}`} subtitle={r.data!.lab_name} />
      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Card className="space-y-4 p-5">
            <h2 className="font-semibold">Details</h2>
            <Field label="Name"><Input value={String(f.name)} onChange={set("name")} /></Field>
            <Field label="Location"><Input value={String(f.location)} onChange={set("location")} /></Field>
            <Field label="Description"><Textarea value={String(f.description)} onChange={set("description")} /></Field>
            <Field label="Status" hint="Maintenance and retired resources can't be booked.">
              <Select value={String(f.status)} onChange={set("status")}><option value="active">Active</option><option value="maintenance">Under maintenance</option><option value="retired">Retired</option></Select>
            </Field>
          </Card>
          <Card className="space-y-4 p-5">
            <h2 className="font-semibold">Who can book</h2>
            <div className="grid gap-2 sm:grid-cols-2">
              {POLICIES.map((p) => (
                <label key={p} className={`cursor-pointer rounded-lg border p-3 ${f.access_policy === p ? "border-brand bg-brand-soft" : "border-line hover:bg-surface-2"}`}>
                  <input type="radio" className="sr-only" checked={f.access_policy === p} onChange={() => setF({ ...f, access_policy: p })} />
                  <div className="text-sm font-medium">{POLICY[p].label}</div>
                  <div className="text-xs text-muted">{POLICY[p].hint}</div>
                </label>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="accent-[var(--brand)]" checked={!!f.accepts_requests} onChange={(e) => setF({ ...f, accepts_requests: e.target.checked })} />
              Others can send me access requests
            </label>
          </Card>
          <Card className="space-y-4 p-5">
            <h2 className="font-semibold">Booking rules</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Field label="Opens"><Input type="time" value={String(f.open_time)} onChange={set("open_time")} /></Field>
              <Field label="Closes" hint="Same as opening = 24 h"><Input type="time" value={String(f.close_time)} onChange={set("close_time")} /></Field>
              <Field label="Slot step (min)"><Input type="number" min={5} value={String(f.slot_granularity_min)} onChange={num("slot_granularity_min")} /></Field>
              <Field label="Shortest (min)"><Input type="number" min={5} value={String(f.min_duration_min)} onChange={num("min_duration_min")} /></Field>
              <Field label="Longest (min)"><Input type="number" min={5} value={String(f.max_duration_min)} onChange={num("max_duration_min")} /></Field>
              <Field label="Book ahead (days)"><Input type="number" min={0} value={String(f.max_advance_days)} onChange={num("max_advance_days")} /></Field>
              <Field label="Notice (min)"><Input type="number" min={0} value={String(f.min_notice_min)} onChange={num("min_notice_min")} /></Field>
              <Field label="Weekly limit (min)" hint="Empty = no limit"><Input type="number" min={1} value={f.weekly_quota_min === null ? "" : String(f.weekly_quota_min)} onChange={num("weekly_quota_min")} /></Field>
              <Field label="Late cancel (min)"><Input type="number" min={0} value={String(f.cancellation_cutoff_min)} onChange={num("cancellation_cutoff_min")} /></Field>
            </div>
          </Card>
          {save.error && <Alert>{errorMessage(save.error)}</Alert>}
          <div className="flex items-center gap-3">
            <Button type="submit" loading={save.isPending}>Save changes</Button>
            {saved && <span className="text-sm text-ok">Saved</span>}
          </div>
        </form>
        <aside><MaintenanceCard r={r.data!} /></aside>
      </div>
    </>
  );
}

function MaintenanceCard({ r }: { r: Resource }) {
  const [date, setDate] = useState(localDate(new Date(Date.now() + 86400000)));
  const [time, setTime] = useState("09:00");
  const [hours, setHours] = useState(4);
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState<any[] | null>(null);
  const start = zoned(date, time);
  const end = addMinutes(start, hours * 60);
  const m = useMutation({
    mutationFn: (cancel_conflicts: boolean) => post<{ cancelled_booking_ids: number[] }>(`/resources/${r.id}/maintenance`, { start: iso(start), end: iso(end), reason, cancel_conflicts }),
    onSuccess: () => setConfirm(null),
    onError: (e) => { if (e instanceof ApiError && e.code === "maintenance_conflicts") setConfirm(e.details.bookings); },
  });
  return (
    <Card className="space-y-4 p-5">
      <h2 className="flex items-center gap-1.5 font-semibold"><Wrench className="size-4 text-warn" aria-hidden />Block for maintenance</h2>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Date"><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="From"><Input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
      </div>
      <Field label="Hours"><Input type="number" min={1} max={168} value={hours} onChange={(e) => setHours(Number(e.target.value))} /></Field>
      <Field label="Reason"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Filament replacement" /></Field>
      <p className="text-xs text-muted">{fmtRange(iso(start), iso(end))}</p>
      {m.isSuccess && <Alert tone="ok" title="Blocked.">{m.data.cancelled_booking_ids.length ? `${m.data.cancelled_booking_ids.length} booking(s) cancelled and notified.` : "No bookings were affected."}</Alert>}
      {m.error && !confirm && <Alert>{errorMessage(m.error)}</Alert>}
      <Button className="w-full" variant="secondary" loading={m.isPending && !confirm} disabled={reason.trim().length < 3} onClick={() => m.mutate(false)}>Block time</Button>
      <Dialog open={!!confirm} onClose={() => setConfirm(null)} title="These bookings overlap"
        footer={<><Button variant="secondary" onClick={() => setConfirm(null)}>Keep them</Button><Button variant="danger" loading={m.isPending} onClick={() => m.mutate(true)}>Cancel {confirm?.length} and block</Button></>}>
        <p className="mb-3 text-sm text-muted">Their owners will be notified with your reason.</p>
        <ul className="space-y-1.5 text-sm">{confirm?.map((b) => <li key={b.id} className="rounded-md bg-surface-2 px-3 py-2"><b>{b.user_name}</b> · {fmtRange(b.start, b.end)}</li>)}</ul>
      </Dialog>
    </Card>
  );
}
