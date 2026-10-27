# Operations runbook

This is for whoever owns Relay after the course (plan Q7: the pilot department's admin). It assumes one Linux VM with Docker installed and a DNS name pointing at it.

## First deploy

```sh
git clone <repo> relay && cd relay
cp .env.example .env              # fill in RELAY_DOMAIN, POSTGRES_PASSWORD, SMTP_*
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
docker compose -f docker-compose.prod.yml exec api python -m scripts.seed --no-demo   # optional: departments/labs only
```

Caddy gets a TLS certificate for `RELAY_DOMAIN` automatically, so ports 80 and 443 must be reachable. Check that it's up with `curl https://$RELAY_DOMAIN/health`. It should return `{"status":"ok"}`.

Create the first super admin by registering normally, then promote the account in the database:

```sh
docker compose -f docker-compose.prod.yml exec db psql -U relay -c "UPDATE users SET is_superadmin = true WHERE email = 'you@institute.ac.in';"
```

Everything after that happens in the app's **Admin** page: create departments, appoint department admins, and create labs with their professor.

## Updating

```sh
git pull
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

The API applies database migrations on start (`alembic upgrade head`).

## Backups

The `backup` service writes `relay-YYYYMMDD-HHMM.dump` to `BACKUP_DIR` every night at 02:30 and keeps 14 days. **Copy that folder off the machine**, for example with a nightly `rclone copy` or `rsync` cron job to institute storage. A backup that lives only on the same disk is not a backup.

### Restore (test this once a term)

```sh
docker compose -f docker-compose.prod.yml stop api worker
docker compose -f docker-compose.prod.yml exec -T db pg_restore -U relay -d relay --clean --if-exists < backups/relay-20261101-0230.dump
docker compose -f docker-compose.prod.yml start api worker
```

## Logs and health

- `docker compose -f docker-compose.prod.yml logs -f api worker` shows one JSON line per request or job.
- Email failures are retried up to six times with backoff. To see what's stuck:
  `SELECT id, user_id, type, email_attempts, last_email_error FROM notifications WHERE emailed_at IS NULL;`
- The audit log is append-only, enforced by a database trigger:
  `SELECT * FROM audit_log ORDER BY id DESC LIMIT 50;`

## Common requests

| Request | How |
|---|---|
| A new professor joins | Department admin → Admin → New lab (or add them as professor to an existing lab) |
| A student needs their lab's instruments | Their professor adds them on **My labs** |
| An instrument breaks | Professor → resource → Settings → status "Under maintenance", or block a time range |
| Someone left the institute | `UPDATE users SET is_active = false WHERE email = '…';` signs them out and blocks all booking |
