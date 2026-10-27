# Lab Resource Booking System: Specification

A web app for booking shared lab instruments and meeting rooms, with department/lab-based access control and an access request and approval workflow.

**Stack:** FastAPI (Python) + PostgreSQL + React (Vite). Docker Compose for local dev and deployment.

**Priority tags:** `P0` = must ship, `P1` = should ship, `P2` = nice to have.

---

## 1. Problem and goals

Shared instruments (microscopes, furnaces, GPU servers, 3D printers) and lab meeting rooms are often scheduled through WhatsApp groups or paper registers. This causes double-bookings, unclear access rules, no usage records, and no way for professors to report on utilization.

**Goals**

- G1. Make double-booking impossible, enforced at the database level.
- G2. Enforce who may book what, based on department/lab membership and per-resource policy.
- G3. Give people outside a resource's lab or department a clean way to ask for access, and give professors a clean way to decide.
- G4. Give professors and department admins usage data they can export.
- G5. Support recurring lab meetings on meeting-room resources.

**Non-goals (for this version)**

- Payments, billing or charge-back.
- Native mobile apps.
- Integration with institute SSO or HR systems.
- Automated instrument control or hardware integration.

---

## 2. Users and roles

| Role | Scope | Can do |
|---|---|---|
| Super admin | Whole system | Everything; create departments, assign department admins |
| Department admin | One department | Manage labs and resources in the department; verify members; decide access requests for any resource in the department |
| Professor (lab head / PI) | Their lab(s) | **Whole access over the lab:** add and remove lab members; create and edit the lab's resources, set rules and access policy, block maintenance; decide access requests and revoke grants for the lab's resources; see who booked and why; reports for the lab |
| Member | Lab or department | Book resources they have access to |
| Verified user (no membership) | Whole institute | Browse resources; book only `institute_open` resources; send access requests |

A user can hold several roles (for example professor of one lab and member of another). There is no separate lab-manager or resource-manager role: the professor of the owning lab holds all of those rights.

---

## 3. Access model

### 3.1 Resource access policy (set per resource)

| Policy | Who can book directly |
|---|---|
| `lab_only` | Members of the owning lab |
| `department` | Members of the owning department (any of its labs) |
| `institute_approval` | Anyone verified, but only after an approved access request |
| `institute_open` | Any verified user, instantly |

Each resource also has `accepts_requests` (boolean, default true). If true, users who cannot book directly can send an access request.

### 3.2 Permission resolution: `can_book(user, resource)`

Evaluated in this order; first match wins:

1. Resource not `active` (maintenance or retired) -> **deny**.
2. User is super admin, professor of the owning lab, or admin of the owning department -> **allow**.
3. User has an active access grant (not revoked, not expired) for this resource -> **allow**.
4. Policy check:
   - `lab_only`: allow if user is a member of the owning lab.
   - `department`: allow if user is a member of the owning department or any lab in it.
   - `institute_approval`: deny (needs a grant, see step 3).
   - `institute_open`: allow if the user's email is verified.
5. Otherwise -> **deny**. The error response includes `can_request_access: true/false` so the UI can show a "Request access" button.

This function must be a single, well-tested module. Every endpoint that reads or writes bookings goes through it.

**Example:** a CSA student tries to book a Physics instrument with policy `department`. Step 4 denies. The UI offers "Request access". The professor who heads the instrument's lab approves. A time-limited grant is created and step 3 now allows it.

### 3.3 Department verification

Users select their department at signup, but it is **unverified** until a department admin confirms it. Unverified membership grants no department-level access. This prevents someone from simply claiming to be in Physics.

---

## 4. Access request workflow (P0)

### 4.1 State machine

```
            +-----------+
 create --> |  pending  | --- cancel (by requester) ---> cancelled
            +-----------+
              |        |
        approve        reject
              |        |
              v        v
         approved    rejected
              |
        (grant expires or is revoked)
              v
          expired / revoked
```

### 4.2 Rules

- A request contains: resource, justification text (required, min 20 chars), requested duration (for example 1 month, 3 months, until a date), and optional supervisor name.
- A user cannot have more than one pending request per resource.
- A user who already has an active grant cannot create a new request.
- Deciders: professors of the owning lab, department admins of the owning department, super admins. A requester can never decide their own request.
- Approval creates an `access_grant` with an `expires_at`. The approver may shorten the requested duration. Approval may include a note.
- Rejection requires a short reason, shown to the requester.
- Grants can be revoked at any time by a decider. Existing future bookings made under a revoked grant are cancelled and their owners notified.
- Pending requests older than 30 days auto-expire (background job).
- Every state change is written to the audit log and triggers a notification to the relevant party.

### 4.3 Acceptance criteria

- AC-R1. A user with no access sees "Request access" and not "Book". After approval, "Book" appears without re-login.
- AC-R2. A second pending request for the same resource is rejected with a clear error.
- AC-R3. A requester cannot approve or reject their own request, even if they are also the professor of some other lab.
- AC-R4. After a grant expires, the user is blocked from new bookings. Past bookings remain visible.
- AC-R5. Revoking a grant cancels that user's future bookings on that resource and sends notifications.

---

## 5. Booking (P0)

### 5.1 Resource types

- `instrument`: usage bookings; per-user quotas apply.
- `meeting_room`: meeting bookings; recurring allowed; attendees allowed; quotas off by default.

Both are the same `resource` entity with a `type` field and different default rules.

### 5.2 Per-resource rules (configurable by the lab's professor)

| Field | Meaning | Example |
|---|---|---|
| `slot_granularity_min` | Bookings snap to this step | 30 |
| `min_duration_min` / `max_duration_min` | Allowed booking length | 30 / 240 |
| `open_time` / `close_time` | Daily bookable window | 08:00 / 20:00 |
| `max_advance_days` | How far ahead users can book | 14 |
| `min_notice_min` | Minimum lead time | 30 |
| `weekly_quota_min` | Max booked minutes per user per week (null = unlimited) | 600 |
| `cancellation_cutoff_min` | After this, cancelling counts as a late cancel | 120 |
| `requires_checkin` | Whether check-in is needed (P2) | false |

Professors of the owning lab, department admins and super admins are exempt from quota and advance limits.

### 5.3 Core behaviours

- **Create booking:** validate permission, rules, quota, then insert. The database exclusion constraint is the final authority on overlap.
- **Cancel booking:** by the owner, or by the lab's professor or an admin (reason required for the latter). Cancelled bookings free the slot.
- **Reschedule:** implemented as an atomic cancel-and-create in one transaction. If the new slot fails, the old booking is untouched.
- **Maintenance blocks:** the professor creates bookings of `kind = 'maintenance'` on the resource. They share the same overlap constraint, so users cannot book through them. If a maintenance block overlaps existing user bookings, the professor sees the list and can cancel them with notification.
- **Time handling:** store everything as UTC `timestamptz`. Display in the institute timezone (`Asia/Kolkata`, from config). Recurring series are defined in local time so they stay at the same wall-clock time.

### 5.4 Concurrency

The database enforces non-overlap:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE bookings
  ADD CONSTRAINT no_overlapping_bookings
  EXCLUDE USING gist (resource_id WITH =, during WITH &&)
  WHERE (status IN ('confirmed', 'held'));
```

When an insert violates the constraint, the API catches the error and returns `409 Conflict` with a message that the slot was just taken, plus the next available slots if cheap to compute.

### 5.5 Acceptance criteria

- AC-B1. Two simultaneous requests for the same slot result in exactly one `201` and one `409`.
- AC-B2. Back-to-back bookings (one ends at 10:00, the next starts at 10:00) are allowed. The range type must be half-open, `[start, end)`.
- AC-B3. A booking outside opening hours, shorter than the minimum, or longer than the maximum is rejected with a specific error.
- AC-B4. Exceeding the weekly quota is rejected, and the error states the remaining minutes.
- AC-B5. A failed reschedule leaves the original booking intact.
- AC-B6. A user without access gets `403`, never the data or a successful write, regardless of how the request is sent.

---

## 6. Recurring lab meetings (P1)

- A **booking series** stores a recurrence rule (weekly or fortnightly, on specific weekdays), a start time, a duration, and an end date or occurrence count.
- On creation, the system **materializes** individual booking rows for the next 12 weeks. A background job extends the horizon as time passes. Materializing keeps the overlap constraint working with no special cases.
- **Conflict handling on creation:** the user chooses either "all or nothing" (abort if any occurrence conflicts) or "skip conflicts" (create the rest and list the skipped dates).
- **Editing:** cancel a single occurrence, or cancel/modify "this and all future occurrences".
- **Attendees:** the organizer can invite users. Invitees get an email with an `.ics` attachment. RSVP is optional (P2).
- Meeting bookings are ignored by quotas.

Acceptance criteria:

- AC-S1. A weekly series creates 12 occurrences at the same local time, including across daylight-saving changes in other zones (store the rule in local time).
- AC-S2. Cancelling one occurrence leaves the others untouched.
- AC-S3. "All or nothing" with one conflicting date creates zero bookings and reports the conflict.

---

## 7. Waitlist (P1)

- If a slot is taken, a user can join the waitlist for a specific time range on that resource.
- When a booking in that range is cancelled, the earliest eligible waitlist entry is **offered** the slot. They have 30 minutes to confirm (configurable). If they do not, the offer passes to the next entry.
- An offer is created in the same transaction as the cancellation, so the slot cannot be taken by someone else in between (the slot stays reserved for the offer holder).
- Eligibility is re-checked at offer time (permission, quota).

---

## 8. Reports and usage log (P1)

- **Usage log:** every booking (including cancelled and no-show) is queryable.
- **Lab report:** filter by resource, lab, user, and date range. Shows total booked hours, utilization percentage (booked hours / open hours), cancellations, late cancellations, and no-shows.
- **CSV export** of the report and of raw bookings.
- **Visibility:** professors see their labs' resources. Department admins see their department. Regular users only see their own history.

---

## 9. Notifications (P1)

| Event | Recipient |
|---|---|
| Email verification | New user |
| Booking confirmed / cancelled by someone else | Booking owner |
| Reminder (default 1 hour before) | Booking owner |
| Access request submitted | Deciders for that resource |
| Access request approved / rejected | Requester |
| Grant about to expire (7 days) | Grant holder |
| Waitlist offer | Waitlisted user |
| Meeting invite | Attendees (with `.ics`) |

Delivery: email via SMTP (configurable provider) plus an in-app notification list. A background worker sends them; failures are retried and logged.

---

## 10. Data model (PostgreSQL)

Conventions: primary keys are `bigint` identity or UUID (pick one and be consistent); all timestamps are `timestamptz`; soft-delete via status fields where history matters.

```sql
-- Identity and organization
users(
  id, email UNIQUE (citext), name, password_hash,
  email_verified bool, is_superadmin bool, is_active bool,
  created_at
)

sessions(token_hash PK, user_id -> users, csrf_token, created_at, expires_at, revoked_at NULL)
auth_tokens(id, user_id -> users, purpose,  -- 'verify_email' | 'password_reset'
            token_hash UNIQUE, expires_at, used_at NULL, created_at)

departments(id, name UNIQUE, code UNIQUE)

labs(id, department_id -> departments, name, UNIQUE(department_id, name))

department_members(
  user_id -> users, department_id -> departments,
  role  -- 'member' | 'dept_admin'
  verified bool, verified_by -> users, verified_at,
  PRIMARY KEY (user_id, department_id)
)

lab_members(
  user_id -> users, lab_id -> labs,
  role  -- 'member' | 'professor'
  PRIMARY KEY (user_id, lab_id)
)

-- Resources
resources(
  id, lab_id -> labs, name, type,       -- 'instrument' | 'meeting_room'
  description, location,
  access_policy,                        -- lab_only | department | institute_approval | institute_open
  accepts_requests bool DEFAULT true,
  status,                               -- active | maintenance | retired
  slot_granularity_min, min_duration_min, max_duration_min,
  open_time, close_time, max_advance_days, min_notice_min,
  weekly_quota_min NULL, cancellation_cutoff_min,
  created_at
)

-- (no resource_managers table: the professor of the owning lab manages every resource in it)

-- Access workflow
access_requests(
  id, resource_id, requester_id, justification, requested_until date, supervisor_name NULL,
  status,                               -- pending | approved | rejected | cancelled | expired
  decided_by NULL, decided_at NULL, decision_note NULL,
  created_at
)
-- partial unique index: one pending request per (resource_id, requester_id)

access_grants(
  id, resource_id, user_id, request_id NULL -> access_requests,
  granted_by, expires_at, revoked_at NULL, revoked_by NULL, created_at
)

-- Bookings
booking_series(
  id, resource_id, owner_id, rrule_text, tz, local_start_time, duration_min,
  starts_on, ends_on NULL, materialized_until, status, created_at
)

bookings(
  id, resource_id, user_id, series_id NULL -> booking_series,
  grant_id NULL -> access_grants,       -- set when the booking was allowed by a grant
  waitlist_entry_id NULL,               -- set for a 'held' waitlist offer
  kind,                                 -- usage | meeting | maintenance
  during tstzrange NOT NULL,
  status,                               -- confirmed | held | cancelled | completed | no_show
  purpose text,
  checked_in_at NULL, cancelled_at NULL, cancelled_by NULL, cancel_reason NULL,
  created_at
  -- EXCLUDE constraint from section 5.4
)

booking_attendees(booking_id, user_id, rsvp NULL, PRIMARY KEY (booking_id, user_id))

waitlist_entries(
  id, resource_id, user_id, desired_during tstzrange,
  status,                               -- waiting | offered | fulfilled | expired | cancelled
  offer_expires_at NULL, created_at
)

-- Cross-cutting
notifications(id, user_id, type, payload jsonb, read_at NULL, emailed_at NULL,
              email_attempts, last_email_error NULL, created_at)

audit_log(id, actor_id, action, entity_type, entity_id, details jsonb, created_at)
```

Indexes to include: `bookings(resource_id, during)` (GiST, covered by the exclusion constraint), `bookings(user_id, created_at)`, `access_requests(resource_id, status)`, `notifications(user_id, read_at)`.

---

## 11. API design (FastAPI)

REST + JSON, versioned under `/api/v1`. Pydantic models for all request and response bodies; OpenAPI docs auto-generated.

### Auth
- `POST /auth/register`
- `POST /auth/verify-email`
- `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- `POST /auth/password-reset/request`, `POST /auth/password-reset/confirm`

### Organization
- `GET /departments`, `GET /departments/{id}/labs`
- `POST /departments/{id}/members/{user_id}/verify` (dept admin)
- Admin CRUD for departments, labs, memberships

### Resources
- `GET /resources` (filter by department, lab, type, "I can book")
- `GET /resources/{id}` (includes `my_access`: `allowed` | `request_possible` | `denied`)
- `POST /resources`, `PATCH /resources/{id}` (professor of the lab, dept admin)
- `POST /resources/{id}/maintenance` (professor of the lab)

### Availability and bookings
- `GET /resources/{id}/availability?from=&to=`
- `POST /bookings`
- `GET /bookings?mine=true&from=&to=`
- `POST /bookings/{id}/cancel`
- `POST /bookings/{id}/reschedule`
- `POST /bookings/{id}/check-in` (P2)
- `POST /booking-series`, `POST /booking-series/{id}/cancel?scope=this|future`

### Access workflow
- `POST /resources/{id}/access-requests`
- `GET /access-requests?mine=true` and `GET /access-requests?to_decide=true`
- `POST /access-requests/{id}/approve` (body: duration, note)
- `POST /access-requests/{id}/reject` (body: reason)
- `POST /access-requests/{id}/cancel`
- `POST /access-grants/{id}/revoke`

### Waitlist and notifications
- `POST /waitlist`, `POST /waitlist/{id}/accept`, `DELETE /waitlist/{id}`
- `GET /notifications`, `POST /notifications/{id}/read`

### Reports
- `GET /reports/usage?resource_id=&lab_id=&from=&to=`
- `GET /reports/usage.csv?...`

### Error format

```json
{ "error": { "code": "slot_conflict", "message": "That slot was just booked.", "details": {} } }
```

Common codes: `unauthenticated` (401), `forbidden` (403, with `can_request_access`), `slot_conflict` (409), `quota_exceeded` (422), `rule_violation` (422), `not_found` (404).

---

## 12. Frontend (React + Vite)

Pages:

1. **Login / Register / Verify email**
2. **Resource directory:** search and filter; each card shows the policy and whether *you* can book it.
3. **Resource page:** week calendar of bookings, rules summary, "Book" or "Request access" button depending on `my_access`.
4. **Booking dialog:** pick start and duration, purpose field, live validation message.
5. **My bookings:** upcoming and past, cancel and reschedule.
6. **My access:** my grants (with expiry) and my requests (with status).
7. **Professor inbox:** requests to decide, with justification, requester's department, and approve/reject controls.
8. **Lab and resource settings** (professors): lab members, rules, policy, maintenance blocks.
9. **Reports** (professors, department admins): filters, summary cards, chart, CSV export.
10. **Admin:** departments, labs, memberships, department verification queue.

UI requirements: clear empty and error states; mobile-responsive; times always shown with timezone; the calendar library may be an off-the-shelf component (for example FullCalendar).

---

## 13. Background jobs

Run in a separate worker process (APScheduler or a simple loop) so the web process stays responsive:

- Send queued emails and retry failures.
- Send booking reminders.
- Expire stale access requests and ended grants; notify before expiry.
- Extend recurring series horizons.
- Expire waitlist offers and promote the next entry.
- Mark past confirmed bookings as `completed` (or `no_show` when check-in is required and missing, P2).

All jobs must be idempotent so a retry or duplicate run does no harm.

---

## 14. Security and privacy

- Password hashing with argon2 (or bcrypt); rate-limit login and password reset.
- Email verification required before booking.
- Session via HTTP-only secure cookies (add CSRF protection) or short-lived JWT plus refresh; pick one.
- Authorization is enforced **server-side** in every endpoint. The UI hiding a button is a convenience, not security.
- Do not expose other users' emails or booking purposes to people without a reason. Default visibility on a resource calendar: show "Booked" plus the lab name; the lab's professor (and admins) see who and why.
- Secrets (database URL, SMTP credentials, signing keys) only via environment variables; nothing in the repo.
- Validate all input; use parameterized queries via the ORM.
- Keep the audit log append-only.
- Store only the personal data needed (name, email, department).

---

## 15. Architecture and deployment

```
Browser (React)  -->  FastAPI app  -->  PostgreSQL
                          |
                          +--> Worker (jobs, email)  -->  SMTP provider
```

- **Backend:** FastAPI, SQLAlchemy 2.x, Alembic migrations, Pydantic v2.
- **Database:** PostgreSQL with `btree_gist` and `citext` extensions.
- **Packaging:** Docker Compose with services `api`, `worker`, `db`, `frontend` (static build served by a reverse proxy).
- **Config:** a single settings module reading environment variables (database URL, SMTP, timezone, base URL).
- **Deployment target:** any host that can run containers plus managed Postgres. Needs HTTPS and daily database backups.
- **Observability:** structured logs, a `/health` endpoint, and error tracking if available.

---

## 16. Testing strategy

| Area | Tests |
|---|---|
| Permission resolution | Table-driven test over (role x policy x grant state) with the expected result for every combination |
| Concurrency | Fire N simultaneous booking requests for one slot; assert exactly one success |
| Booking rules | Boundaries: min/max duration, opening hours, back-to-back, quota edges |
| Access workflow | Full state machine, self-approval blocked, one pending request per resource, expiry and revocation effects |
| Recurring series | Occurrence generation, all-or-nothing, cancel-one vs cancel-future |
| Waitlist | Offer on cancel, offer expiry passes to next, eligibility re-check |
| API | Auth required on every endpoint; response codes and error shapes |
| Migrations | Fresh database builds from migrations; seed script works |

Include a seed script (reading `backend/seed/institute.yaml`) that creates sample departments, labs, resources, users in each role, and some bookings, so the app is demoable immediately.

---

## 17. Milestones

Each milestone ends with working, tested, deployed functionality.

- **M1: Foundation.** Project skeleton, Docker Compose, schema and migrations, auth (register, verify, login), roles and memberships, seed data.
- **M2: Resources and bookings.** Resource CRUD, rules, availability endpoint, booking create/cancel/reschedule with the exclusion constraint, concurrency tests, calendar UI.
- **M3: Access control and requests.** `can_book` module, policies, full access request workflow, grants, professor inbox, permission test matrix.
- **M4: Quotas, notifications, jobs.** Weekly quotas, email and in-app notifications, reminders, expiry jobs, audit log.
- **M5: Meetings.** Meeting room type, recurring series, attendees, `.ics` invites.
- **M6: Waitlist and reports.** Waitlist with offers, usage report, CSV export.
- **M7: Hardening and deployment.** Security review, rate limiting, backups, production deploy, documentation, demo script.
- **Stretch (P2):** check-in and no-show handling, calendar subscription feed, analytics dashboard, no-show prediction model, natural-language booking via an LLM call (the LLM only extracts fields into JSON, and all validation and permission checks still run in the backend).

---

## 18. Open questions

> **Status:** each question below has a working decision in `plan.md` §0. Q4 (pilot lab), Q7 (host/owner) and the pilot department admin for Q2 still need confirmation from outside the team before M7.

1. How will users sign in? (Institute-domain Google sign-in is simplest if the deployment allows it. Otherwise email and password with email verification.)
2. Who verifies department membership in practice? (Department admins by default. Confirm this works for the pilot group.)
3. Should the calendar show who booked a slot to everyone, or only to professors?
4. Which single lab or instrument will be the pilot, and who is its professor?
5. Is there existing booking data (spreadsheets, WhatsApp logs) to import?
6. Do instruments need check-in or sign-off after use (for example logging samples or issues)?
7. Where will this be hosted, and who owns it after the course ends?