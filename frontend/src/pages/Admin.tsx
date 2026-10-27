import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Check, UserCheck, X } from "lucide-react";
import { useState } from "react";
import { api, errorMessage, post } from "../api";
import { useAuth } from "../auth";
import { Alert, Badge, Button, Card, Empty, Field, Input, PageHeader, Select, Tabs } from "../components/ui";
import { relative } from "../time";
import type { Department, Lab } from "../types";

interface QueueItem { user_id: number; name: string; email: string; email_verified: boolean; department_id: number; department_code: string; requested_at: string }

export function AdminPage() {
  const { me } = useAuth();
  const [tab, setTab] = useState<"queue" | "org">("queue");
  return (
    <>
      <PageHeader title="Admin" subtitle={me?.is_superadmin ? "Institute-wide administration." : "Department administration."} />
      <Tabs value={tab} onChange={setTab} items={[{ value: "queue", label: "Verification queue" }, { value: "org", label: "Departments & labs" }]} />
      {tab === "queue" ? <Queue /> : <Org />}
    </>
  );
}

function Queue() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["verify-queue"], queryFn: () => api<QueueItem[]>("/departments/verification-queue") });
  const decide = useMutation({
    mutationFn: ({ item, approve }: { item: QueueItem; approve: boolean }) => post(`/departments/${item.department_id}/members/${item.user_id}/verify`, { approve }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["verify-queue"] }),
  });
  if (q.error) return <Alert>{errorMessage(q.error)}</Alert>;
  if (!q.data?.length) return <Empty icon={<UserCheck className="size-5" />} title="No one is waiting">People who pick your department at sign-up appear here until you confirm them.</Empty>;
  return (
    <Card className="divide-y divide-line">
      {q.data.map((i) => (
        <div key={`${i.user_id}-${i.department_id}`} className="flex flex-wrap items-center gap-3 p-4">
          <div className="min-w-0 flex-1">
            <div className="font-medium">{i.name}</div>
            <div className="text-sm text-muted">{i.email} · asked {relative(i.requested_at)}</div>
          </div>
          <Badge>{i.department_code}</Badge>
          {!i.email_verified && <Badge tone="warn">Email unconfirmed</Badge>}
          <div className="flex gap-2">
            <Button size="sm" onClick={() => decide.mutate({ item: i, approve: true })}><Check className="size-4" aria-hidden />Confirm</Button>
            <Button size="sm" variant="ghost" onClick={() => decide.mutate({ item: i, approve: false })}><X className="size-4" aria-hidden />Reject</Button>
          </div>
        </div>
      ))}
    </Card>
  );
}

function Org() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const depts = useQuery({ queryKey: ["departments"], queryFn: () => api<Department[]>("/departments") });
  const labs = useQuery({ queryKey: ["labs"], queryFn: () => api<Lab[]>("/labs") });
  const adminOf = new Set(me?.departments.filter((d) => d.role === "dept_admin" && d.verified).map((d) => d.id));
  const mine = (depts.data ?? []).filter((d) => me?.is_superadmin || adminOf.has(d.id));
  const [dept, setDept] = useState({ code: "", name: "" });
  const [lab, setLab] = useState({ department_id: "", name: "", professor_email: "" });
  const [adm, setAdm] = useState({ department_id: "", email: "" });
  const inv = () => ["departments", "labs", "managed-labs"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const mkDept = useMutation({ mutationFn: () => post("/departments", dept), onSuccess: () => { setDept({ code: "", name: "" }); inv(); } });
  const mkLab = useMutation({ mutationFn: () => post(`/departments/${lab.department_id}/labs`, { name: lab.name, professor_email: lab.professor_email || null }), onSuccess: () => { setLab({ ...lab, name: "", professor_email: "" }); inv(); } });
  const setAdmin = useMutation({ mutationFn: () => api(`/departments/${adm.department_id}/admins`, { method: "PUT", body: { email: adm.email } }), onSuccess: () => setAdm({ ...adm, email: "" }) });

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="space-y-4">
        {mine.map((d) => (
          <Card key={d.id} className="p-4">
            <div className="mb-2 flex items-center gap-2"><Building2 className="size-4 text-muted" aria-hidden /><span className="font-medium">{d.name}</span><Badge>{d.code}</Badge></div>
            <ul className="divide-y divide-line text-sm">
              {labs.data?.filter((l) => l.department_id === d.id).map((l) => (
                <li key={l.id} className="flex justify-between gap-3 py-2"><span>{l.name}</span><span className="truncate text-right text-muted">{l.professors || "No professor"} · {l.resource_count}</span></li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
      <div className="space-y-4">
        <Card className="space-y-3 p-4">
          <h2 className="font-semibold">New lab</h2>
          <Field label="Department"><Select value={lab.department_id} onChange={(e) => setLab({ ...lab, department_id: e.target.value })}><option value="">Choose…</option>{mine.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
          <Field label="Lab name"><Input value={lab.name} onChange={(e) => setLab({ ...lab, name: e.target.value })} /></Field>
          <Field label="Professor's email" hint="They get whole access over the lab."><Input type="email" value={lab.professor_email} onChange={(e) => setLab({ ...lab, professor_email: e.target.value })} /></Field>
          {mkLab.error && <Alert>{errorMessage(mkLab.error)}</Alert>}
          <Button className="w-full" loading={mkLab.isPending} disabled={!lab.department_id || lab.name.length < 3} onClick={() => mkLab.mutate()}>Create lab</Button>
        </Card>
        {me?.is_superadmin && (
          <>
            <Card className="space-y-3 p-4">
              <h2 className="font-semibold">New department</h2>
              <div className="grid grid-cols-[90px_1fr] gap-2">
                <Field label="Code"><Input value={dept.code} onChange={(e) => setDept({ ...dept, code: e.target.value.toUpperCase() })} /></Field>
                <Field label="Name"><Input value={dept.name} onChange={(e) => setDept({ ...dept, name: e.target.value })} /></Field>
              </div>
              {mkDept.error && <Alert>{errorMessage(mkDept.error)}</Alert>}
              <Button className="w-full" variant="secondary" loading={mkDept.isPending} onClick={() => mkDept.mutate()}>Create department</Button>
            </Card>
            <Card className="space-y-3 p-4">
              <h2 className="font-semibold">Appoint department admin</h2>
              <Field label="Department"><Select value={adm.department_id} onChange={(e) => setAdm({ ...adm, department_id: e.target.value })}><option value="">Choose…</option>{depts.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
              <Field label="Email"><Input type="email" value={adm.email} onChange={(e) => setAdm({ ...adm, email: e.target.value })} /></Field>
              {setAdmin.error && <Alert>{errorMessage(setAdmin.error)}</Alert>}
              {setAdmin.isSuccess && <Alert tone="ok">Appointed.</Alert>}
              <Button className="w-full" variant="secondary" loading={setAdmin.isPending} disabled={!adm.department_id || !adm.email} onClick={() => setAdmin.mutate()}>Appoint</Button>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
