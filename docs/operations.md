# Operations runbook (AWS)

This is for whoever runs Relay after the course (plan Q7). Setting it up is covered in [`deploy-aws.md`](deploy-aws.md).

## Where things are

| What | Where in the AWS console |
|---|---|
| Frontend builds and deploys | **Amplify** → the app → build history |
| API and its logs | **App Runner** → `relay-api` → Logs (also in **CloudWatch Logs**) |
| Database and backups | **RDS** → the `relay` database → Maintenance & backups |
| Background job schedule | **EventBridge** → Rules → the `relay-backend-JobsSchedule…` rule |
| Everything above as one unit | **CloudFormation** → stack `relay-backend` |

## Deploying changes

- **Frontend:** push to GitHub `main`. Amplify rebuilds automatically.
- **Backend:** `bash deploy/aws/deploy-backend.sh` from the repo, in Git Bash. It builds a new image, and App Runner rolls over to it; database migrations run on start.

## First super admin (when not using demo data)

Register normally on the site, then connect to the database (host is in the stack outputs; user `relay`; password is `DB_PASSWORD` in `deploy/aws/relay.env`; TLS required) and run:

```sql
UPDATE users SET is_superadmin = true WHERE email = 'you@institute.ac.in';
```

Everything after that happens in the app's **Admin** page.

## Backups and restore

RDS takes an automatic daily backup (02:00–02:30 IST) and keeps it for **7 days**, with point-in-time recovery inside that window. Deleting the stack leaves a final snapshot.

**Restore:**
1. RDS → Automated backups (or Snapshots) → **Restore to point in time**, into a new instance.
2. Point the app at it, e.g. by temporarily editing `RELAY_DATABASE_URL` in App Runner → Configuration.

Rehearse this once a term. A local drill of the same dump-and-restore path passed: identical row counts, constraints and triggers intact.

## Health and logs

- `https://<app address>/health` → `{"status":"ok"}`. This checks Amplify, the proxy, App Runner and the database in one go.
- App Runner logs: one JSON line per request. The scheduler shows up as `POST /api/internal/jobs/tick` every minute.
- Emails that keep failing:
  `SELECT id, user_id, type, email_attempts, last_email_error FROM notifications WHERE emailed_at IS NULL;`
- When each background job last ran: `SELECT * FROM job_runs ORDER BY last_finished_at;`
- The audit log is append-only (enforced by a database trigger): `SELECT * FROM audit_log ORDER BY id DESC LIMIT 50;`

## Common requests

| Request | How |
|---|---|
| A new professor joins | Department admin → Admin → New lab (or add them as professor to an existing lab) |
| A student needs their lab's instruments | Their professor adds them on **My labs** |
| An instrument breaks | Professor → resource → Settings → status "Under maintenance", or block a time range |
| Someone left the institute | `UPDATE users SET is_active = false WHERE email = '…';` signs them out and blocks booking |
| Stop everything (and the bill) | CloudFormation → delete `relay-backend` (keeps a final DB snapshot), and delete the Amplify app |

## Local development

Unchanged: `docker compose up --build` runs everything locally, with Mailpit for email (see the README).
