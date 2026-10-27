import { useQuery } from "@tanstack/react-query";
import { DoorOpen, MapPin, Microscope, Search, SearchX, Wrench } from "lucide-react";
import { useDeferredValue, useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, qs } from "../api";
import { AccessBadge, Badge, Card, Empty, Input, PageHeader, PolicyBadge, Select, Skeleton } from "../components/ui";
import type { Department, Resource } from "../types";

export function ResourcesPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const dept = params.get("department_id") ?? "";
  const type = params.get("type") ?? "";
  const bookable = params.get("bookable") === "1";
  const deferredQ = useDeferredValue(q);
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v); else p.delete(k);
    setParams(p, { replace: true });
  };

  const depts = useQuery({ queryKey: ["departments"], queryFn: () => api<Department[]>("/departments") });
  const list = useQuery({
    queryKey: ["resources", deferredQ, dept, type, bookable],
    queryFn: () => api<Resource[]>(`/resources${qs({ q: deferredQ, department_id: dept, type, bookable })}`),
    placeholderData: (prev) => prev,
  });

  const grouped = useMemo(() => {
    const g = new Map<string, Resource[]>();
    for (const r of list.data ?? []) {
      const key = `${r.department_name}`;
      g.set(key, [...(g.get(key) ?? []), r]);
    }
    return [...g.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [list.data]);

  return (
    <>
      <PageHeader title="Resources" subtitle={list.data ? `${list.data.length} instruments and rooms` : "Instruments and meeting rooms across the institute"} />
      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
        <div className="relative sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" aria-hidden />
          <Input aria-label="Search" placeholder="Search name, lab, room…" className="pl-9" value={q} onChange={(e) => set("q", e.target.value)} />
        </div>
        <Select aria-label="Department" className="sm:w-64" value={dept} onChange={(e) => set("department_id", e.target.value)}>
          <option value="">All departments</option>
          {depts.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </Select>
        <Select aria-label="Type" className="sm:w-40" value={type} onChange={(e) => set("type", e.target.value)}>
          <option value="">All types</option>
          <option value="instrument">Instruments</option>
          <option value="meeting_room">Meeting rooms</option>
        </Select>
        <label className="flex h-10 cursor-pointer items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm select-none">
          <input type="checkbox" className="accent-[var(--brand)]" checked={bookable} onChange={(e) => set("bookable", e.target.checked ? "1" : "")} />
          I can book
        </label>
      </div>

      {list.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{Array.from({ length: 9 }, (_, i) => <Skeleton key={i} className="h-36" />)}</div>
      ) : list.data?.length === 0 ? (
        <Empty icon={<SearchX className="size-5" />} title="Nothing matches these filters">Try clearing the search or the “I can book” filter.</Empty>
      ) : (
        <div className="space-y-8">
          {grouped.map(([deptName, items]) => (
            <section key={deptName}>
              <h2 className="mb-3 text-sm font-semibold text-muted">{deptName}</h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((r) => <ResourceCard key={r.id} r={r} />)}
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}

function ResourceCard({ r }: { r: Resource }) {
  const Icon = r.type === "meeting_room" ? DoorOpen : Microscope;
  return (
    <Link to={`/resources/${r.id}`} className="group">
      <Card className="flex h-full flex-col p-4 transition-shadow group-hover:shadow-md group-hover:border-brand/40">
        <div className="flex items-start gap-3">
          <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand"><Icon className="size-4.5" aria-hidden /></div>
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium group-hover:text-brand">{r.name}</div>
            <div className="truncate text-xs text-muted">{r.lab_name}</div>
          </div>
        </div>
        {r.location && <div className="mt-3 flex items-center gap-1.5 truncate text-xs text-muted"><MapPin className="size-3.5 shrink-0" aria-hidden />{r.location}</div>}
        <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-4">
          {r.status !== "active" ? <Badge tone="warn"><Wrench className="size-3" aria-hidden />{r.status}</Badge> : <AccessBadge access={r.my_access} />}
          <PolicyBadge policy={r.access_policy} />
          {r.can_manage && <Badge tone="brand">You manage</Badge>}
        </div>
      </Card>
    </Link>
  );
}
