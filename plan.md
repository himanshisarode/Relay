# Lab Resource Booking System (Relay): Build Plan

Companion to `spec.md`. The spec says **what** to build; this file says **how and in what order**, records the decisions that close the spec's open questions, and tracks status.

**Status legend:** `[ ]` not started · `[~]` built, waiting on verification · `[x]` done and verified · `[?]` blocked on a decision from outside the team

> **Current state (2026-10-27):** M1–M6 are implemented and verified: **359 backend tests pass against real PostgreSQL 16 in Docker** (0 skipped), plus frontend type-check, unit tests and production build. The full Docker stack runs (API, worker, frontend, Postgres, Mailpit), and email delivery was checked end to end. Still open: a manual browser walk-through (M7) and the pilot decisions.

---

## 0. Decisions

### 0.1 Role model: the professor owns the lab (decided 2026-10-27)

There is **no lab-manager or resource-manager role**. The **professor** (lab head / PI) has whole access over their lab:

- adds and removes lab members;
- creates and edits the lab's resources, rules and access policy, and blocks maintenance;
- decides access requests and revokes grants for the lab's resources;
- sees who booked and why, and gets the lab's reports;
- is exempt from quota and advance-booking limits on their lab's resources.

Department admins (HOD) can do the same for every lab in their department, appoint professors and verify department members. Super admins can do everything. `lab_members.role` is `member | professor`, and the `resource_managers` table was dropped. `spec.md` was updated to match.

### 0.2 Open questions (spec §18)

| # | Question | Decision | Status |
|---|---|---|---|
| Q1 | How do users sign in? | **Email + password with email verification.** Login is isolated in `services/accounts.py` + `auth/` so institute Google (OIDC) sign-in can be added later. | Decided |
| Q2 | Who verifies department membership? | **Department admins**, via the Admin → Verification queue; super admins as fallback. A professor adding someone to their lab also verifies that person's department membership, since the professor is vouching for them. | Decided; **needs confirmation** that the pilot department has a named admin |
| Q3 | Who sees who booked? | **Only the lab's professor and admins.** Others see "Booked · <booker's lab>". Owners see their own details. | Decided, implemented |
| Q4 | Pilot lab and its professor? | Seeded from `instruments_list` → `backend/seed/institute.yaml`: **14 departments, 30 labs, 104 resources, a professor per lab, a HOD per department, 3 students per lab** (all fictional). The real pilot lab is set up in the Admin UI; no code depends on which lab it is. | **Needs confirmation** by M7 |
| Q5 | Import existing booking data? | No import in v1. A CSV import script is a P2 task, only if the pilot has a spreadsheet. | Decided |
| Q6 | Check-in / sign-off after use? | Not in v1. `requires_checkin` is in the schema (default false). Check-in, no-show and post-use sign-off are P2. | Decided |
| Q7 | Hosting and ownership? | **AWS (decided 2026-10-27, replacing the student-VM choice made earlier that day).** Frontend on **Amplify Hosting** from GitHub `main` (monorepo root `frontend/`, `amplify.yml`), proxying `/api/*` to the backend so cookies stay same-origin. Backend container on **App Runner**; **RDS PostgreSQL 16** (`db.t4g.micro`, TLS forced, 7-day automated backups); **EventBridge** calls `POST /api/internal/jobs/tick` every minute instead of a worker process (App Runner throttles CPU between requests, so an in-process scheduler wouldn't run reliably). All backend resources in `deploy/aws/backend.yml` (cfn-lint clean), deployed with `deploy/aws/deploy-backend.sh`; steps in `docs/deploy-aws.md`. Trade-off: RDS is internet-reachable (TLS + 40-char random password) to avoid a paid NAT gateway; tightening steps documented. | Host decided; **waiting on you** for the AWS account and the console steps. Owner after the course still to confirm |

### 0.3 Technical decisions

| Topic | Decision |
|---|---|
| Primary keys | `bigint GENERATED ALWAYS AS IDENTITY` everywhere |
| Sessions | Server-side `sessions` table; random token in an HTTP-only `Secure` `SameSite=Lax` cookie, stored hashed; CSRF double-submit (`relay_csrf` cookie + `X-CSRF-Token` header) on every non-GET |
| Passwords | argon2id; login takes the same time for unknown emails; reset revokes all sessions |
| Rate limiting | In-process sliding window on login, register, resend, reset (single API container; swap for Redis if scaled out) |
| DB access | Sync SQLAlchemy 2 + psycopg 3; FastAPI runs handlers in its thread pool |
| Schema | One hand-written Alembic migration in raw SQL (constraints are the point, so they're explicit); ORM models mirror it |
| Overlap | `EXCLUDE USING gist (resource_id WITH =, during WITH &&) WHERE status IN ('confirmed','held')`; `during` must be a finite half-open `[)` range (CHECK) |
| Quota race | `pg_advisory_xact_lock(user, resource)` around the quota check and insert |
| Quota week | Monday 00:00 in the institute timezone; a booking over Sunday midnight counts in both weeks |
| Opening hours | `open_time == close_time` means 24 h; `close < open` means an overnight window |
| Exemptions | Privileged users (professor of the lab, dept admin, super admin) skip quota, min-notice and max-advance; they still obey hours, durations and granularity |
| Booking under a grant | Must end before the grant expires (`beyond_grant`) |
| Grant end | End of the chosen local day; the approver may shorten but not extend |
| Hiding records | Someone else's booking, request or grant returns **404**, not 403, so existence isn't leaked |
| Audit log | Append-only, enforced by a trigger that rejects UPDATE/DELETE |
| Notifications | Rows are the email outbox; the worker sends with exponential backoff (max 6 tries). Token links are never shown in-app. |
| Worker | Same job functions, two triggers: locally an APScheduler worker process; on AWS, EventBridge → `POST /api/internal/jobs/tick` (shared-secret header, constant-time compare, 404 when no key is set). Each job holds a Postgres advisory lock, is idempotent and records its finish in `job_runs`; the endpoint runs only jobs past their interval. Email batches are capped at 25 per run to keep each call short |
| Series | `dateutil.rrule` evaluated in the series' stored `tz`; occurrences validated with the horizon replacing `max_advance_days`; series are for meeting rooms only |
| Waitlist | An offer is a real booking with status `held`, created in the cancellation's transaction; accept → `confirmed`; expiry → next eligible entry |
| Reports | Utilization = booked ÷ (open hours − maintenance); late cancel = owner cancelled inside the cutoff |
| Frontend | React 18 + Vite + TypeScript, Tailwind v4 with design tokens and dark mode, TanStack Query, React Router, FullCalendar week view pinned to IST via the Luxon plugin, Inter font, lucide icons |
| Chart | Hand-built SVG (one series, validated colour `#0d9488` light / `#2a9d8f` dark), hover tooltip, table toggle |
| Dev email | Mailpit in Compose; `RELAY_DEV_EXPOSE_TOKENS=true` returns verify/reset tokens in dev only |
| Tests | pytest against real Postgres (no SQLite, since exclusion constraints and ranges are Postgres-only). DB tests skip unless `RELAY_TEST_DATABASE_URL` is set. Vitest for frontend helpers. |

### 0.4 Spec amendments (now folded into `spec.md`)

1. Booking status `held` for waitlist offers, covered by the exclusion constraint.
2. `access_requests.requested_until` (date) and `supervisor_name`. Rejection reason goes in `decision_note`.
3. "One active grant per user and resource" is enforced in the service: requesting while holding a grant returns `already_granted`.
4. Professor/admin exemption replaces the "flag on the role".
5. `booking_series.tz`, `materialized_until`, `status`.
6. `sessions` and `auth_tokens` tables.
7. `bookings.grant_id` (to cancel exactly the bookings made under a revoked grant) and `waitlist_entry_id`.
8. Maintenance blocks are bookings of kind `maintenance`, excluded from quotas, and subtracted from open hours in utilization.

---

## 1. Repository layout

```
relay/
  spec.md  plan.md  README.md  instruments_list
  docker-compose.yml (local dev)  amplify.yml (Amplify build)  .github/workflows/ci.yml
  backend/
    requirements.txt  pyproject.toml  Dockerfile  alembic.ini  alembic/versions/0001_initial.py
    seed/institute.yaml  scripts/seed.py
    app/
      main.py  settings.py  db.py  errors.py  models.py  schemas.py
      auth/       security.py (argon2, tokens, rate limiter)  deps.py (session, CSRF)
      services/   permissions.py  rules.py  bookings.py  access.py  waitlist.py  series.py
                  reports.py  accounts.py  org.py  resources.py  events.py  mailer.py
      api/v1/     auth  org  bookings  access  inbox (waitlist, notifications)  meetings (series, reports)
      worker/     jobs.py  main.py
    tests/        test_permissions  test_rules  test_series (pure)  + *_db.py (Postgres)
  frontend/
    src/{api,auth,time,types}.ts(x)  src/components  src/pages   (built by Amplify)
  deploy/  aws/{backend.yml, deploy-backend.sh, relay.env.example, amplify-rewrites.json, amplify-headers.yml}  initdb/ (local)
  docs/    deploy-aws.md  operations.md  demo-script.md
```

Rule: routers stay thin. Every service that touches bookings calls `permissions.require_book` / `require_manage` first.

---

## 2. Milestones

### M1: Foundation
- [x] Repo layout, settings from env, no secrets in the repo (`deploy/aws/relay.env` is git-ignored)
- [x] Alembic migration: extensions, all tables, exclusion constraint, partial unique index, append-only audit trigger
- [x] Auth: register, verify email, login/logout, `/auth/me`, password reset, sessions + CSRF, rate limits
- [x] Departments, labs, memberships, verification queue
- [x] Error format (`{error: {code, message, details}}`), `/health`, JSON request logs
- [x] Seed from `instruments_list` (idempotent; tested to run twice)
- [x] Frontend: login, register, verify email, forgot/reset password
- [x] Docker Compose (db, api, worker, frontend, mailpit) and CI workflow *(CI runs once `relay/` is its own repo)*
- **Tests:** [x] route table: every protected route returns 401 without a session · [x] auth flows · [x] migrations from scratch · [x] seed twice

### M2: Resources and bookings
- [x] Resource CRUD by the professor, rules, status
- [x] `rules.py`: granularity, min/max duration, opening hours (incl. 24 h and overnight), notice, advance; week split
- [x] Availability with privacy (Q3); next-free-slot suggestions on 409
- [x] Create / cancel / reschedule (atomic); maintenance blocks with conflict confirmation
- [x] Frontend: directory with filters, resource page with IST week calendar, booking dialog with live validation, My bookings
- **Tests:** [x] rule boundaries · [x] AC-B1 (12 threads, one slot) · [x] AC-B2 · [x] AC-B3 · [x] AC-B5 · [x] AC-B6

### M3: Access control and requests
- [x] `permissions.py`: `decide()` exactly per spec 3.2, with the professor model
- [x] `my_access` (`allowed | request_pending | request_possible | denied`), "I can book" filter
- [x] Request / cancel / approve (shorten, note) / reject (reason) / revoke (cancels future bookings under the grant)
- [x] Frontend: request dialog, My access, professor Inbox, Admin verification queue
- **Tests:** [x] matrix: 11 roles × 4 policies × grant × resource status × email-verified (232 cases) · [x] AC-R1–R5

### M4: Quotas, notifications, jobs
- [x] Weekly quota with remaining minutes in the error (AC-B4)
- [x] Notifications for every spec §9 event; in-app bell; HTML + text email
- [x] Worker: emails with retry, reminders, request expiry, grant-expiry warnings, completing past bookings, session cleanup
- [x] Audit log on every state change, append-only in the DB
- **Tests:** [x] quota edges · [x] each job is idempotent · [x] outbox retry/backoff

### M5: Meetings
- [x] Series (weekly/fortnightly, chosen weekdays, count or end date), 12-week materialization, `all_or_nothing` vs `skip_conflicts`
- [x] Cancel this / this-and-future; horizon extension job
- [x] Attendees + `.ics` invite email
- [x] Frontend: "Repeat this meeting" in the booking dialog, series-aware cancel
- **Tests:** [x] AC-S1 (Europe/London across the Oct 2026 DST change) · [x] AC-S2 · [x] AC-S3 · [x] meetings ignore quota

### M6: Waitlist and reports
- [x] Waitlist join → `held` offer on cancel → accept, or expire and pass to next; eligibility re-checked
- [x] Usage report (hours, utilization, cancellations, late cancels, no-shows, daily series) with visibility rules; CSV summary + raw
- [x] Frontend: waitlist panel, Reports page with filters, stat tiles, chart, table, CSV links
- **Tests:** [x] offer/accept/expiry/ineligible · [x] report numbers on a hand-computed fixture · [x] visibility

### M7: Hardening and deployment
- [x] ~~Production compose with Caddy and nightly `pg_dump`~~ replaced by AWS on 2026-10-27; the VM files were removed. The local production run had verified HTTPS, a `Secure` cookie, HSTS and no dev tokens, and those settings carry over (Amplify headers, `RELAY_COOKIE_SECURE=true`)
- [x] Hosting decided (Q7: AWS Amplify + App Runner + RDS + EventBridge); `deploy/aws/*`, `amplify.yml`, `docs/deploy-aws.md`
- [x] Job endpoint for EventBridge (`/api/internal/jobs/tick`, migration `0002_job_runs`) with tests; seed-on-start option; optional CORS fallback (`RELAY_CORS_ORIGINS` / `VITE_API_BASE`)
- [x] `backend.yml` passes cfn-lint (ap-south-1, us-east-1); SPA rewrite rule checked against app and asset paths
- [ ] **You:** AWS account + budget alert, AWS CLI, Amplify app from GitHub, run `deploy-backend.sh`, paste the rewrites (docs/deploy-aws.md)
- [ ] Smoke-test on AWS: `/health` through Amplify, login survives a reload (proxy cookies), job ticks every minute in App Runner logs, registration email
- [x] **Run the full suite against Postgres** (`docker compose exec api pytest -q`): 359 passed (incl. the job endpoint). The first run found three bugs, all fixed:
  - `alembic` couldn't import `app` in the container → `prepend_sys_path = .` in `alembic.ini`
  - Pydantic's `EmailStr` rejects reserved domains such as `.test`, so **no seeded account could sign in** → plain format check (`schemas.Email`)
  - `FOR UPDATE` on joined-eager queries is refused by Postgres → lock only the main table (`of=`)
  - plus: the route-table auth test had silently collected 0 routes (FastAPI now nests routers) → discover routes from OpenAPI, add a guard
- [ ] Click through `docs/demo-script.md` in a browser; check both themes and phone width
- [ ] Security pass against spec §14 on the running stack
- [x] Restore drill: a `pg_dump -Fc` restored into an empty database gave identical row counts (138 users, 104 resources, 273 bookings), with the overlap constraint and audit trigger intact
- [?] Pilot lab and professor (Q4), owner after the course (Q7), pilot department admin (Q2)

### Stretch (P2)
- [ ] Check-in and no-show handling (`requires_checkin`)
- [ ] Post-use sign-off and issue reporting (Q6)
- [ ] CSV booking import (Q5)
- [ ] Google OIDC sign-in (Q1)
- [ ] Per-user calendar subscription feed; RSVP for attendees
- [ ] Analytics dashboard, no-show prediction, natural-language booking (LLM only extracts fields; all checks stay in the backend)

---

## 3. Risks

| Risk | Mitigation |
|---|---|
| Permission bugs leak access | One `decide()` function, a 232-case matrix test, route-table auth test, 404 for others' records |
| DB tests not yet run on this machine | Marked `[x]`; first thing to do once Docker is installed |
| Timezone/DST errors | Store rule + tz; AC-S1 tested in a DST zone; frontend converts with the zone's real offset |
| Waitlist hold racing a normal booking | The hold is a real row under the same exclusion constraint |
| Duplicate workers | Advisory lock per job and idempotent jobs |
| In-process rate limiter resets on restart | Acceptable for one container; documented swap to Redis |
