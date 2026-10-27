# Deploying Relay to a student-credit VM (plan Q7, option B)

The result is a permanent `https://` address that works with your laptop off. It runs the same `docker-compose.prod.yml` that was tested locally: Caddy with automatic HTTPS, the API, the worker, Postgres and nightly backups.

**Time:** about 30 minutes. **Cost:** covered by student credits; check the current offer when you sign up.

## 1. Get the credits (you)

1. Sign up for the **GitHub Student Developer Pack** at https://education.github.com/pack with your institute email.
2. From the pack, claim the **DigitalOcean** offer. *Azure for Students* also works; the steps are the same apart from the cloud console.
3. The pack can also give you a **free domain** (for example a `.me` or `.tech` name). Optional, because step 3 has a free fallback.

## 2. Create the server (you)

In DigitalOcean → **Create → Droplet**:

| Setting | Choose |
|---|---|
| Image | **Ubuntu 24.04 LTS** |
| Size | Basic, **2 GB RAM** (1 GB is too tight to build the frontend) |
| Region | The one closest to your users (e.g. Bangalore) |
| Authentication | **SSH key** (safer than a password) |
| Backups | Optional; Relay already does nightly database dumps |

Note the droplet's **public IP address**, e.g. `139.59.10.20`.

## 3. Pick the address

- **No domain needed:** use `139-59-10-20.sslip.io` (your IP with dashes). It already points at your server, and Caddy gets a real HTTPS certificate for it. The setup script suggests this name automatically.
- **Your own domain:** add a DNS **A record** pointing to the droplet's IP *before* running the script, then enter the domain when asked.

## 4. Get an email sender (you)

Mailpit only works locally. To deliver verification and approval emails, create a free **Brevo** account (or use another SMTP provider), verify a sender address, and copy the SMTP settings: host `smtp-relay.brevo.com`, port `587`, login, SMTP key.

## 5. Run the setup script (on the server)

```sh
ssh root@139.59.10.20
curl -fsSL https://raw.githubusercontent.com/himanshisarode/Relay/main/deploy/setup-server.sh -o setup.sh
sudo bash setup.sh
```

The script:
- installs Docker;
- adds swap;
- opens only ports 22, 80 and 443;
- clones the repo to `/opt/relay`;
- asks for the domain and SMTP details, and generates a random database password into `.env` (readable only by root);
- starts everything.

## 6. Demo data and first login

```sh
cd /opt/relay
docker compose -f docker-compose.prod.yml exec api python -m scripts.seed
```

Open `https://<your address>/login` and sign in as `admin@relay.test` / `relay-demo-pass`.

> **The demo password is public** (it's in the README), so anyone can sign in as admin. That's fine for a course demo. For real use, skip the demo seed (`python -m scripts.seed --no-demo`), register your own account and make it super admin as described in `docs/operations.md`.

## Updating after a new push to GitHub

```sh
cd /opt/relay && git pull && docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

## Checklist

- [ ] `https://<address>/health` returns `{"status":"ok"}`
- [ ] Login works, and register → verification email arrives
- [ ] `/opt/relay-backups` gets a new `.dump` file each night; copy it off the server (see `docs/operations.md`)
