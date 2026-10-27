import { useMutation, useQuery } from "@tanstack/react-query";
import { CalendarCheck2, ShieldCheck, Users } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api, errorMessage, post } from "../api";
import { useAuth } from "../auth";
import { Logo } from "../components/Layout";
import { Alert, Button, Field, Input, Select, Spinner } from "../components/ui";
import type { Department } from "../types";

function Shell({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_1.1fr]">
      <div className="flex flex-col px-6 py-8 sm:px-12">
        <Logo />
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-10">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1.5 text-sm text-muted">{subtitle}</p>}
          <div className="mt-7">{children}</div>
        </div>
      </div>
      <div className="relative hidden overflow-hidden bg-brand lg:block">
        <div className="absolute inset-0 opacity-[0.12]" style={{ backgroundImage: "radial-gradient(circle at 1px 1px, white 1px, transparent 0)", backgroundSize: "22px 22px" }} />
        <div className="relative flex h-full flex-col justify-center px-14 text-brand-ink">
          <p className="max-w-md text-3xl leading-tight font-semibold tracking-tight">Book shared instruments and rooms without the WhatsApp chaos.</p>
          <ul className="mt-10 space-y-5 text-[15px] opacity-95">
            {[
              [CalendarCheck2, "Double-booking is impossible", "The database itself refuses overlapping slots."],
              [ShieldCheck, "Clear access rules", "Each professor decides who can use their lab's instruments."],
              [Users, "Ask for access in one click", "Outside your lab? Send a request; the professor approves it."],
            ].map(([Icon, t, d]) => {
              const I = Icon as typeof Users;
              return (
                <li key={t as string} className="flex gap-3">
                  <I className="mt-0.5 size-5 shrink-0" aria-hidden />
                  <div><div className="font-medium">{t as string}</div><div className="text-sm opacity-80">{d as string}</div></div>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </div>
  );
}

export function LoginPage() {
  const { me, login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const m = useMutation({ mutationFn: () => login(email, password), onSuccess: () => nav((loc.state as any)?.from ?? "/resources", { replace: true }) });
  if (me) return <Navigate to="/resources" replace />;
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(); };
  return (
    <Shell title="Sign in" subtitle={<>New here? <Link to="/register" className="font-medium text-brand">Create an account</Link></>}>
      <form onSubmit={submit} className="space-y-4">
        {m.error && <Alert>{errorMessage(m.error)}</Alert>}
        <Field label="Email"><Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password"><Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <div className="flex justify-end text-sm"><Link to="/forgot-password" className="text-muted hover:text-ink">Forgot password?</Link></div>
        <Button type="submit" className="w-full" loading={m.isPending}>Sign in</Button>
      </form>
      {import.meta.env.DEV && (
        <div className="mt-8 rounded-lg border border-dashed border-line p-3 text-xs text-muted">
          <div className="mb-1 font-medium text-ink">Demo accounts (password <code>relay-demo-pass</code>)</div>
          <button className="block hover:text-brand" onClick={() => setEmail("admin@relay.test")}>admin@relay.test — super admin</button>
          <button className="block hover:text-brand" onClick={() => setEmail("guest@relay.test")}>guest@relay.test — outsider with one grant</button>
          <span className="block">Professors, HODs and students: see <code>backend/seed/institute.yaml</code></span>
        </div>
      )}
    </Shell>
  );
}

export function RegisterPage() {
  const depts = useQuery({ queryKey: ["departments"], queryFn: () => api<Department[]>("/departments") });
  const [f, setF] = useState({ name: "", email: "", password: "", department_id: "" });
  const [done, setDone] = useState<{ token: string | null } | null>(null);
  const m = useMutation({
    mutationFn: () => post<{ dev_token: string | null }>("/auth/register", { ...f, department_id: f.department_id ? Number(f.department_id) : null }),
    onSuccess: (r) => setDone({ token: r.dev_token }),
  });
  if (done)
    return (
      <Shell title="Check your inbox" subtitle={<>We sent a confirmation link to <b>{f.email}</b>.</>}>
        <Alert tone="info">Your department membership stays unconfirmed until the department admin verifies it. Until then you can book open resources and send access requests.</Alert>
        {done.token && <p className="mt-4 text-sm">Dev mode: <Link className="font-medium text-brand" to={`/verify-email?token=${done.token}`}>verify now</Link></p>}
        <Link to="/login" className="mt-6 inline-block text-sm font-medium text-brand">Back to sign in</Link>
      </Shell>
    );
  return (
    <Shell title="Create your account" subtitle={<>Already registered? <Link to="/login" className="font-medium text-brand">Sign in</Link></>}>
      <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-4">
        {m.error && <Alert>{errorMessage(m.error)}</Alert>}
        <Field label="Full name"><Input required minLength={2} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Institute email"><Input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Password" hint="At least 10 characters.">
          <Input type="password" required minLength={10} autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        </Field>
        <Field label="Department" hint="A department admin confirms this before it gives you department access.">
          <Select value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value })}>
            <option value="">I'm not in a department / visiting</option>
            {depts.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
        </Field>
        <Button type="submit" className="w-full" loading={m.isPending}>Create account</Button>
      </form>
    </Shell>
  );
}

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const { refresh } = useAuth();
  const token = params.get("token") ?? "";
  const m = useMutation({ mutationFn: () => post("/auth/verify-email", { token }), onSuccess: () => refresh() });
  useEffect(() => { if (token) m.mutate(); }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Shell title="Email confirmation">
      {m.isPending && <Spinner label="Confirming" />}
      {m.isSuccess && <><Alert tone="ok" title="Your email is confirmed." /><Link to="/resources" className="mt-6 inline-block text-sm font-medium text-brand">Go to resources →</Link></>}
      {m.error && <Alert>{errorMessage(m.error)}</Alert>}
      {!token && <Alert>This link is missing its token.</Alert>}
    </Shell>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const m = useMutation({ mutationFn: () => post<{ dev_token: string | null }>("/auth/password-reset/request", { email }) });
  return (
    <Shell title="Reset your password" subtitle="We'll email you a link that works for one hour.">
      {m.isSuccess ? (
        <>
          <Alert tone="ok">If an account exists for {email}, a reset link is on its way.</Alert>
          {m.data?.dev_token && <p className="mt-4 text-sm">Dev mode: <Link className="font-medium text-brand" to={`/reset-password?token=${m.data.dev_token}`}>reset now</Link></p>}
        </>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-4">
          {m.error && <Alert>{errorMessage(m.error)}</Alert>}
          <Field label="Email"><Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Button type="submit" className="w-full" loading={m.isPending}>Send reset link</Button>
        </form>
      )}
      <Link to="/login" className="mt-6 inline-block text-sm text-muted hover:text-ink">Back to sign in</Link>
    </Shell>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const [password, setPassword] = useState("");
  const m = useMutation({ mutationFn: () => post("/auth/password-reset/confirm", { token: params.get("token"), password }) });
  return (
    <Shell title="Choose a new password">
      {m.isSuccess ? (
        <><Alert tone="ok" title="Password changed. Other sessions were signed out." /><Link to="/login" className="mt-6 inline-block text-sm font-medium text-brand">Sign in</Link></>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }} className="space-y-4">
          {m.error && <Alert>{errorMessage(m.error)}</Alert>}
          <Field label="New password" hint="At least 10 characters."><Input type="password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <Button type="submit" className="w-full" loading={m.isPending}>Save password</Button>
        </form>
      )}
    </Shell>
  );
}
