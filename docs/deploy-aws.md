# Deploying Relay on AWS (Amplify)

The result is a permanent `https://…amplifyapp.com` address that works with your laptop off.

```
Browser ──► AWS Amplify Hosting (React app, HTTPS)
               │  /api/* is proxied, so the browser sees one site and login cookies just work
               ▼
            AWS App Runner (FastAPI container, HTTPS) ──► Amazon RDS PostgreSQL 16 (daily backups, 7 days)
               ▲
            Amazon EventBridge, every minute: POST /api/internal/jobs/tick  (emails, reminders, expiries)
```

Amplify Hosting only hosts the frontend; it can't run the Python API or a database. That's why the backend uses App Runner and RDS, all created by one CloudFormation template (`deploy/aws/backend.yml`).

**Time:** about 45 minutes, most of it waiting for the database to be created.
**Cost:** Amplify, App Runner (one always-on instance), RDS `db.t4g.micro` and a little EventBridge. Check what your AWS free tier or credits cover before you start, and set a **billing alert** (step 1).

## 1. AWS account and tools (you)

1. Create an AWS account, or use AWS credits from your institute or AWS Educate.
2. **Billing → Budgets → Create budget**, e.g. a $10 monthly alert. This is your safety net.
3. Install the **AWS CLI v2** on your PC, then in a terminal: `aws configure` (use an IAM user's access key with admin rights, region `ap-south-1`).
4. Docker Desktop is already installed.

## 2. Create the Amplify app (you, in the AWS console)

1. **AWS Amplify → Create new app → GitHub**, authorize it, and pick **himanshisarode/Relay**, branch `main`.
2. Tick **"My app is a monorepo"** and set the root directory to **`frontend`**.
3. Amplify picks up `amplify.yml` from the repo. Accept it and deploy.
4. Copy the app address, e.g. `https://main.d1abc2def3.amplifyapp.com`. Login won't work yet because there's no backend.

## 3. Email (optional now, needed for verification and approval emails)

The simplest AWS option is **Amazon SES → SMTP settings → Create SMTP credentials**, then verify your sender address under *Verified identities*.

SES starts in a **sandbox**: it only delivers to addresses you've verified. Request production access in SES when you want to email everyone. Any other SMTP provider (e.g. Brevo) also works.

## 4. Create the backend (on your PC)

From the `relay` folder, in **Git Bash**:

```sh
bash deploy/aws/deploy-backend.sh
```

The first run creates `deploy/aws/relay.env` and stops. Open that file, set `FRONTEND_URL` to the Amplify address from step 2 (and the SMTP settings from step 3, if you have them), then run the same command again.

That run:
- generates a database password and a scheduler key (saved in `relay.env`, which is git-ignored, so **keep that file private**);
- builds and pushes the backend image;
- creates App Runner, RDS and the EventBridge schedule.

The first run takes **10–15 minutes**. At the end it prints the backend address, e.g. `https://abcd1234.ap-south-1.awsapprunner.com`. Opening `…/health` in a browser should show `{"status":"ok"}`.

With `SEED_ON_START=demo` (the default), the backend loads the demo departments, labs, resources and accounts on its first start.

## 5. Connect the frontend to the backend (you, in the Amplify console)

1. **Amplify → your app → Hosting → Rewrites and redirects → Manage → Open text editor**.
2. Paste `deploy/aws/amplify-rewrites.json`, replacing both `API_URL` with the backend address from step 4 (no trailing slash). Save.
3. **Hosting → Custom headers**: paste `deploy/aws/amplify-headers.yml`. Save.

## 6. Done: your link

Open **`https://main.<id>.amplifyapp.com/login`** in any browser and sign in as `admin@relay.test` / `relay-demo-pass`.

> Everyone you give the demo accounts to can sign in as admin. That's fine for a course demo. For real use, set `SEED_ON_START=org` in `relay.env` (or `none`) before the first deploy and create your own admin (see `docs/operations.md`).

## Updating

- **Frontend:** push to GitHub `main`. Amplify rebuilds automatically.
- **Backend:** run `bash deploy/aws/deploy-backend.sh` again. App Runner switches to the new image without downtime, and migrations run on start.

## If login doesn't stick (fallback)

Amplify passes `/api` through to App Runner, so the browser only ever talks to the Amplify address. If cookies don't survive that proxy:
1. Give both parts their own subdomains of one domain (e.g. `app.example.org` on Amplify and `api.example.org` on App Runner, via "Custom domains" in each console).
2. In Amplify → Environment variables, set `VITE_API_BASE=https://api.example.org`.
3. In App Runner, set `RELAY_CORS_ORIGINS=https://app.example.org`.

The app supports this already; no code changes needed.

## Tightening later

- **Database network:** RDS is reachable from the internet but only over TLS and with a 40-character random password. App Runner has no fixed outbound IPs, and keeping the database private would need a NAT gateway (a monthly cost) so the API can still send email. To tighten: add an App Runner VPC connector, a NAT gateway, and set the RDS security group to the connector only.
- **Secrets:** move the database password and SMTP password from stack parameters into AWS Secrets Manager.
- **Logs:** App Runner sends the API's JSON logs to CloudWatch Logs; add an alarm on errors.

## Checklist

- [ ] `https://<amplify address>/health` returns `{"status":"ok"}` (this proves the proxy works)
- [ ] Login works and survives a page reload
- [ ] App Runner logs show `POST /api/internal/jobs/tick` every minute with status 200
- [ ] Register → verification email arrives (needs SES or SMTP)
