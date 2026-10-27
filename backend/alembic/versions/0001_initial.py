"""Initial schema (spec section 10, with the amendments recorded in plan.md).

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = r"""
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS citext;

-- Identity -----------------------------------------------------------------
CREATE TABLE users (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email          citext NOT NULL UNIQUE,
  name           text NOT NULL CHECK (length(trim(name)) > 0),
  password_hash  text NOT NULL,
  email_verified boolean NOT NULL DEFAULT false,
  is_superadmin  boolean NOT NULL DEFAULT false,
  is_active      boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  token_hash  text PRIMARY KEY,
  user_id     bigint NOT NULL REFERENCES users ON DELETE CASCADE,
  csrf_token  text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL,
  revoked_at  timestamptz
);
CREATE INDEX sessions_user ON sessions (user_id);

CREATE TABLE auth_tokens (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     bigint NOT NULL REFERENCES users ON DELETE CASCADE,
  purpose     text NOT NULL CHECK (purpose IN ('verify_email', 'password_reset')),
  token_hash  text NOT NULL UNIQUE,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Organization ---------------------------------------------------------------
CREATE TABLE departments (
  id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name  text NOT NULL UNIQUE,
  code  text NOT NULL UNIQUE
);

CREATE TABLE labs (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  department_id  bigint NOT NULL REFERENCES departments,
  name           text NOT NULL,
  UNIQUE (department_id, name)
);

CREATE TABLE department_members (
  user_id        bigint NOT NULL REFERENCES users ON DELETE CASCADE,
  department_id  bigint NOT NULL REFERENCES departments,
  role           text NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'dept_admin')),
  verified       boolean NOT NULL DEFAULT false,
  verified_by    bigint REFERENCES users,
  verified_at    timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, department_id)
);
CREATE INDEX department_members_queue ON department_members (department_id) WHERE NOT verified;

-- The professor of a lab has whole access over it; there is no separate manager role.
CREATE TABLE lab_members (
  user_id     bigint NOT NULL REFERENCES users ON DELETE CASCADE,
  lab_id      bigint NOT NULL REFERENCES labs,
  role        text NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'professor')),
  added_by    bigint REFERENCES users,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, lab_id)
);
CREATE INDEX lab_members_lab ON lab_members (lab_id, role);

-- Resources -------------------------------------------------------------------
CREATE TABLE resources (
  id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lab_id                   bigint NOT NULL REFERENCES labs,
  name                     text NOT NULL,
  type                     text NOT NULL CHECK (type IN ('instrument', 'meeting_room')),
  description              text NOT NULL DEFAULT '',
  location                 text NOT NULL DEFAULT '',
  access_policy            text NOT NULL
                             CHECK (access_policy IN ('lab_only', 'department', 'institute_approval', 'institute_open')),
  accepts_requests         boolean NOT NULL DEFAULT true,
  status                   text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'maintenance', 'retired')),
  slot_granularity_min     integer NOT NULL DEFAULT 30 CHECK (slot_granularity_min BETWEEN 5 AND 1440),
  min_duration_min         integer NOT NULL DEFAULT 30 CHECK (min_duration_min > 0),
  max_duration_min         integer NOT NULL DEFAULT 240,
  open_time                time NOT NULL DEFAULT '08:00',
  close_time               time NOT NULL DEFAULT '20:00',  -- equal to open_time means open 24 hours
  max_advance_days         integer NOT NULL DEFAULT 14 CHECK (max_advance_days >= 0),
  min_notice_min           integer NOT NULL DEFAULT 30 CHECK (min_notice_min >= 0),
  weekly_quota_min         integer CHECK (weekly_quota_min IS NULL OR weekly_quota_min > 0),
  cancellation_cutoff_min  integer NOT NULL DEFAULT 120 CHECK (cancellation_cutoff_min >= 0),
  requires_checkin         boolean NOT NULL DEFAULT false,
  created_at               timestamptz NOT NULL DEFAULT now(),
  UNIQUE (lab_id, name),
  CHECK (max_duration_min >= min_duration_min)
);

-- Access workflow ---------------------------------------------------------------
CREATE TABLE access_requests (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  resource_id      bigint NOT NULL REFERENCES resources,
  requester_id     bigint NOT NULL REFERENCES users,
  justification    text NOT NULL CHECK (length(justification) >= 20),
  requested_until  date NOT NULL,
  supervisor_name  text,
  status           text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')),
  decided_by       bigint REFERENCES users,
  decided_at       timestamptz,
  decision_note    text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CHECK (decided_by IS NULL OR decided_by <> requester_id)
);
CREATE UNIQUE INDEX access_requests_one_pending ON access_requests (resource_id, requester_id) WHERE status = 'pending';
CREATE INDEX access_requests_resource_status ON access_requests (resource_id, status);
CREATE INDEX access_requests_requester ON access_requests (requester_id, created_at DESC);

CREATE TABLE access_grants (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  resource_id       bigint NOT NULL REFERENCES resources,
  user_id           bigint NOT NULL REFERENCES users,
  request_id        bigint REFERENCES access_requests,
  granted_by        bigint NOT NULL REFERENCES users,
  expires_at        timestamptz NOT NULL,
  revoked_at        timestamptz,
  revoked_by        bigint REFERENCES users,
  expiry_warned_at  timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX access_grants_lookup ON access_grants (user_id, resource_id) WHERE revoked_at IS NULL;

-- Bookings ------------------------------------------------------------------------
CREATE TABLE booking_series (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  resource_id         bigint NOT NULL REFERENCES resources,
  owner_id            bigint NOT NULL REFERENCES users,
  title               text NOT NULL DEFAULT '',
  rrule_text          text NOT NULL,
  tz                  text NOT NULL,
  local_start_time    time NOT NULL,
  duration_min        integer NOT NULL CHECK (duration_min > 0),
  starts_on           date NOT NULL,
  ends_on             date,
  max_occurrences     integer,
  materialized_until  date NOT NULL,
  status              text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended', 'cancelled')),
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE waitlist_entries (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  resource_id       bigint NOT NULL REFERENCES resources,
  user_id           bigint NOT NULL REFERENCES users,
  desired_during    tstzrange NOT NULL CHECK (NOT isempty(desired_during)),
  status            text NOT NULL DEFAULT 'waiting'
                      CHECK (status IN ('waiting', 'offered', 'fulfilled', 'expired', 'cancelled')),
  offer_expires_at  timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX waitlist_lookup ON waitlist_entries USING gist (resource_id, desired_during) WHERE status = 'waiting';

CREATE TABLE bookings (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  resource_id        bigint NOT NULL REFERENCES resources,
  user_id            bigint NOT NULL REFERENCES users,
  series_id          bigint REFERENCES booking_series,
  grant_id           bigint REFERENCES access_grants,
  waitlist_entry_id  bigint REFERENCES waitlist_entries,
  kind               text NOT NULL DEFAULT 'usage' CHECK (kind IN ('usage', 'meeting', 'maintenance')),
  during             tstzrange NOT NULL,
  status             text NOT NULL DEFAULT 'confirmed'
                       CHECK (status IN ('confirmed', 'held', 'cancelled', 'completed', 'no_show')),
  purpose            text NOT NULL DEFAULT '',
  checked_in_at      timestamptz,
  cancelled_at       timestamptz,
  cancelled_by       bigint REFERENCES users,
  cancel_reason      text,
  reminded_at        timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  -- Half-open [start, end) so back-to-back bookings never overlap (AC-B2).
  CHECK (NOT isempty(during) AND lower_inc(during) AND NOT upper_inc(during)
         AND NOT lower_inf(during) AND NOT upper_inf(during)),
  -- The final authority on double-booking (spec 5.4). 'held' covers waitlist offers.
  CONSTRAINT no_overlapping_bookings
    EXCLUDE USING gist (resource_id WITH =, during WITH &&) WHERE (status IN ('confirmed', 'held'))
);
CREATE INDEX bookings_user_created ON bookings (user_id, created_at);
CREATE INDEX bookings_resource_during_all ON bookings USING gist (resource_id, during);
CREATE INDEX bookings_series ON bookings (series_id) WHERE series_id IS NOT NULL;
CREATE INDEX bookings_grant ON bookings (grant_id) WHERE grant_id IS NOT NULL;

CREATE TABLE booking_attendees (
  booking_id  bigint NOT NULL REFERENCES bookings ON DELETE CASCADE,
  user_id     bigint NOT NULL REFERENCES users,
  rsvp        text CHECK (rsvp IN ('yes', 'no', 'maybe')),
  PRIMARY KEY (booking_id, user_id)
);

-- Cross-cutting -----------------------------------------------------------------------
CREATE TABLE notifications (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id           bigint NOT NULL REFERENCES users ON DELETE CASCADE,
  type              text NOT NULL,
  payload           jsonb NOT NULL DEFAULT '{}',
  read_at           timestamptz,
  emailed_at        timestamptz,
  email_attempts    integer NOT NULL DEFAULT 0,
  last_email_error  text,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notifications_user_read ON notifications (user_id, read_at);
CREATE INDEX notifications_outbox ON notifications (created_at) WHERE emailed_at IS NULL;

CREATE TABLE audit_log (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id     bigint REFERENCES users,
  action       text NOT NULL,
  entity_type  text NOT NULL,
  entity_id    bigint,
  details      jsonb NOT NULL DEFAULT '{}',
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_entity ON audit_log (entity_type, entity_id);

-- Append-only audit log, enforced in the database rather than by convention.
CREATE FUNCTION audit_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only';
END $$;
CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
"""

DOWNGRADE = """
DROP TABLE IF EXISTS audit_log, notifications, booking_attendees, bookings, waitlist_entries, booking_series,
  access_grants, access_requests, resources, lab_members, department_members, labs, departments,
  auth_tokens, sessions, users CASCADE;
DROP FUNCTION IF EXISTS audit_log_append_only();
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
