export type Policy = "lab_only" | "department" | "institute_approval" | "institute_open";
export type Access = "allowed" | "request_pending" | "request_possible" | "denied";

export interface Me {
  id: number;
  name: string;
  email: string;
  email_verified: boolean;
  is_superadmin: boolean;
  is_professor: boolean;
  is_dept_admin: boolean;
  labs: { id: number; name: string; role: "member" | "professor"; department_code: string }[];
  departments: { id: number; code: string; name: string; role: "member" | "dept_admin"; verified: boolean }[];
  csrf_token: string;
}

export interface Resource {
  id: number;
  name: string;
  type: "instrument" | "meeting_room";
  description: string;
  location: string;
  access_policy: Policy;
  accepts_requests: boolean;
  status: "active" | "maintenance" | "retired";
  lab_id: number;
  lab_name: string;
  department_id: number;
  department_code: string;
  department_name: string;
  slot_granularity_min: number;
  min_duration_min: number;
  max_duration_min: number;
  open_time: string;
  close_time: string;
  max_advance_days: number;
  min_notice_min: number;
  weekly_quota_min: number | null;
  cancellation_cutoff_min: number;
  requires_checkin: boolean;
  my_access: Access;
  can_manage: boolean;
  timezone: string;
}

export interface Booking {
  id: number;
  resource_id: number;
  resource_name: string;
  lab_name: string;
  kind: "usage" | "meeting" | "maintenance";
  status: "confirmed" | "held" | "cancelled" | "completed" | "no_show";
  start: string;
  end: string;
  purpose: string;
  series_id: number | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  created_at: string;
  late_cancel_after: string;
}

export interface CalendarEntry {
  id: number | null;
  start: string;
  end: string;
  kind: string;
  status: string;
  label: string;
  mine: boolean;
  user_name: string | null;
  purpose: string | null;
  series_id: number | null;
}

export interface AccessRequest {
  id: number;
  resource_id: number;
  resource_name: string;
  lab_name: string;
  department_code: string;
  requester_id: number;
  requester_name: string;
  requester_email: string | null;
  requester_departments: { code: string; name: string; verified: boolean }[];
  justification: string;
  requested_until: string;
  supervisor_name: string | null;
  status: "pending" | "approved" | "rejected" | "cancelled" | "expired";
  decision_note: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface Grant {
  id: number;
  resource_id: number;
  resource_name: string;
  lab_name: string;
  user_id: number;
  user_name: string;
  expires_at: string;
  revoked_at: string | null;
  state: "active" | "expired" | "revoked";
  created_at: string;
}

export interface Notification {
  id: number;
  type: string;
  payload: { title: string; body?: string; link?: string | null; [k: string]: unknown };
  read_at: string | null;
  created_at: string;
}

export interface Department {
  id: number;
  code: string;
  name: string;
  lab_count: number;
}

export interface Lab {
  id: number;
  name: string;
  department_id: number;
  department_code: string;
  department_name: string;
  professors: string;
  resource_count: number;
}

export interface WaitlistEntry {
  id: number;
  resource_id: number;
  resource_name: string;
  start: string;
  end: string;
  status: "waiting" | "offered";
  offer_expires_at: string | null;
}
