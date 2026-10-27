import clsx from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Bell, CalendarDays, FlaskConical, Inbox, KeyRound, LogOut, Menu, Settings2, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { api, post } from "../api";
import { canManageAnything, useAuth } from "../auth";
import { relative, tzLabel } from "../time";
import type { Notification } from "../types";
import { Alert, Button } from "./ui";

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
      <span className="grid size-8 place-items-center rounded-lg bg-brand text-brand-ink">
        <FlaskConical className="size-4.5" aria-hidden />
      </span>
      <span className="text-[17px]">Relay</span>
    </Link>
  );
}

export function Layout() {
  const { me, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const managing = canManageAnything(me);
  const inbox = useQuery({
    queryKey: ["inbox-count"],
    queryFn: () => api<unknown[]>("/access-requests?to_decide=true"),
    enabled: managing,
    refetchInterval: 60_000,
  });

  const links = [
    { to: "/resources", label: "Resources", icon: FlaskConical, show: true },
    { to: "/bookings", label: "My bookings", icon: CalendarDays, show: true },
    { to: "/access", label: "My access", icon: KeyRound, show: true },
    { to: "/inbox", label: "Inbox", icon: Inbox, show: managing, badge: inbox.data?.length },
    { to: "/manage", label: "My labs", icon: Settings2, show: !!me && (me.is_professor || me.is_dept_admin || me.is_superadmin) },
    { to: "/reports", label: "Reports", icon: BarChart3, show: true },
    { to: "/admin", label: "Admin", icon: ShieldCheck, show: !!me && (me.is_dept_admin || me.is_superadmin) },
  ].filter((l) => l.show);

  const navList = (
    <nav className="flex flex-col gap-0.5">
      {links.map((l) => (
        <NavLink
          key={l.to}
          to={l.to}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            clsx(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              isActive ? "bg-brand-soft text-brand" : "text-muted hover:bg-surface-2 hover:text-ink",
            )
          }
        >
          <l.icon className="size-4" aria-hidden />
          <span className="flex-1">{l.label}</span>
          {!!l.badge && <span className="rounded-full bg-brand px-1.5 text-[11px] font-semibold text-brand-ink">{l.badge}</span>}
        </NavLink>
      ))}
    </nav>
  );

  const userBox = me && (
    <div className="border-t border-line pt-3">
      <div className="truncate px-1 text-sm font-medium">{me.name}</div>
      <div className="truncate px-1 text-xs text-muted">{roleLine(me)}</div>
      <Button variant="ghost" size="sm" className="mt-2 w-full justify-start" onClick={async () => { await logout(); nav("/login"); }}>
        <LogOut className="size-4" aria-hidden /> Sign out
      </Button>
    </div>
  );

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[240px_1fr]">
      <aside className="hidden h-dvh flex-col gap-6 border-r border-line bg-surface px-3 py-5 lg:sticky lg:top-0 lg:flex">
        <div className="px-2"><Logo /></div>
        <div className="flex-1">{navList}</div>
        <div className="px-2 text-[11px] text-faint">Times shown in {tzLabel()}</div>
        {userBox}
      </aside>

      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-line bg-surface/90 px-4 backdrop-blur lg:hidden">
        <button onClick={() => setOpen(true)} className="rounded-md p-1.5 text-muted hover:bg-surface-2" aria-label="Open menu">
          <Menu className="size-5" />
        </button>
        <Logo />
        <NotificationBell />
      </header>
      {open && (
        <div className="fixed inset-0 z-30 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-72 flex-col gap-6 bg-surface px-3 py-5">
            <div className="flex items-center justify-between px-2">
              <Logo />
              <button onClick={() => setOpen(false)} className="rounded-md p-1 text-muted" aria-label="Close menu"><X className="size-5" /></button>
            </div>
            <div className="flex-1">{navList}</div>
            {userBox}
          </div>
        </div>
      )}

      <main className="min-w-0">
        <div className="hidden h-14 items-center justify-end border-b border-line bg-surface/60 px-8 lg:flex">
          <NotificationBell />
        </div>
        <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {me && !me.email_verified && <VerifyBanner />}
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function roleLine(me: NonNullable<ReturnType<typeof useAuth>["me"]>) {
  if (me.is_superadmin) return "Super admin";
  const prof = me.labs.filter((l) => l.role === "professor").map((l) => l.name);
  if (prof.length) return `Professor · ${prof.join(", ")}`;
  if (me.is_dept_admin) return `Department admin · ${me.departments.filter((d) => d.role === "dept_admin").map((d) => d.code).join(", ")}`;
  if (me.labs.length) return me.labs.map((l) => l.name).join(", ");
  const d = me.departments[0];
  return d ? `${d.code}${d.verified ? "" : " (awaiting verification)"}` : "Verified user";
}

function VerifyBanner() {
  const [sent, setSent] = useState<string | null>(null);
  const m = useMutation({ mutationFn: () => post<{ dev_token: string | null }>("/auth/resend-mine"), onSuccess: (r) => setSent(r.dev_token) });
  return (
    <div className="mb-6">
      <Alert tone="warn" title="Confirm your email to start booking">
        We sent you a link.{" "}
        <button className="font-medium underline" onClick={() => m.mutate()} disabled={m.isPending}>Send it again</button>
        {sent !== null && <> · Sent.{sent && <> (Dev: <Link className="underline" to={`/verify-email?token=${sent}`}>verify now</Link>)</>}</>}
      </Alert>
    </div>
  );
}

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<{ unread: number; items: Notification[] }>("/notifications?limit=30"),
    refetchInterval: 45_000,
  });
  const readAll = useMutation({ mutationFn: () => post("/notifications/read-all"), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  const readOne = useMutation({ mutationFn: (id: number) => post(`/notifications/${id}/read`), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  const unread = q.data?.unread ?? 0;
  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} className="relative rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-ink" aria-label={`Notifications, ${unread} unread`}>
        <Bell className="size-5" />
        {unread > 0 && <span className="absolute top-1 right-1 grid min-w-4 place-items-center rounded-full bg-bad px-1 text-[10px] font-semibold text-white">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-40 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-line bg-surface shadow-2xl">
            <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
              <span className="text-sm font-semibold">Notifications</span>
              {unread > 0 && <button className="text-xs font-medium text-brand" onClick={() => readAll.mutate()}>Mark all read</button>}
            </div>
            <div className="max-h-96 overflow-y-auto">
              {q.data?.items.length ? (
                q.data.items.map((n) => (
                  <button
                    key={n.id}
                    onClick={() => {
                      if (!n.read_at) readOne.mutate(n.id);
                      const link = n.payload.link;
                      if (link && link.startsWith("/")) { setOpen(false); nav(link); }
                    }}
                    className={clsx("block w-full border-b border-line px-4 py-3 text-left last:border-0 hover:bg-surface-2", !n.read_at && "bg-brand-soft/40")}
                  >
                    <div className="flex gap-2">
                      {!n.read_at && <span className="mt-1.5 size-2 shrink-0 rounded-full bg-brand" aria-label="unread" />}
                      <div className="min-w-0">
                        <div className="text-sm font-medium">{n.payload.title}</div>
                        {n.payload.body && <div className="mt-0.5 line-clamp-2 text-xs text-muted">{n.payload.body}</div>}
                        <div className="mt-1 text-[11px] text-faint">{relative(n.created_at)}</div>
                      </div>
                    </div>
                  </button>
                ))
              ) : (
                <div className="px-4 py-10 text-center text-sm text-muted">You're all caught up.</div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
