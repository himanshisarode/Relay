#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 22.04/24.04 server for Relay (plan Q7, option B).
# Clone the repo to /opt/relay first (see docs/deploy-vm.md; the repo is private), then run as root:
#   sudo bash /opt/relay/deploy/setup-server.sh
# It installs Docker, opens ports 22/80/443, writes .env and starts the stack.
set -euo pipefail

DIR=/opt/relay

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }

echo "== 1/5 Docker"
if ! command -v docker >/dev/null; then
  apt-get update -y
  apt-get install -y ca-certificates curl git ufw
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

echo "== 2/5 Swap (small servers need it to build the frontend)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== 3/5 Firewall: SSH, HTTP, HTTPS only"
ufw allow 22/tcp >/dev/null && ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

echo "== 4/5 Code"
[ -d "$DIR/.git" ] || { echo "Clone the repo to $DIR first (docs/deploy-vm.md, step 5)."; exit 1; }
cd "$DIR"

echo "== 5/5 Settings"
if [ ! -f .env ]; then
  IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
  DEFAULT_DOMAIN="$(echo "$IP" | tr . -).sslip.io"
  read -rp "Domain for the site [$DEFAULT_DOMAIN]: " DOMAIN; DOMAIN=${DOMAIN:-$DEFAULT_DOMAIN}
  read -rp "SMTP host (e.g. smtp-relay.brevo.com): " SMTP_HOST
  read -rp "SMTP port [587]: " SMTP_PORT; SMTP_PORT=${SMTP_PORT:-587}
  read -rp "SMTP username: " SMTP_USER
  read -rsp "SMTP password / key: " SMTP_PASSWORD; echo
  read -rp "From address (e.g. Relay <you@yourdomain>): " SMTP_FROM
  umask 077
  cat > .env <<EOF
RELAY_DOMAIN=$DOMAIN
POSTGRES_PASSWORD=$(openssl rand -hex 24)
SMTP_HOST=$SMTP_HOST
SMTP_PORT=$SMTP_PORT
SMTP_USER=$SMTP_USER
SMTP_PASSWORD=$SMTP_PASSWORD
SMTP_FROM=$SMTP_FROM
SMTP_STARTTLS=true
BACKUP_DIR=/opt/relay-backups
BACKUP_KEEP_DAYS=14
EOF
  mkdir -p /opt/relay-backups
fi

docker compose -f docker-compose.prod.yml --env-file .env up -d --build
DOMAIN=$(grep ^RELAY_DOMAIN= .env | cut -d= -f2)
echo
echo "Relay is starting at https://$DOMAIN  (the HTTPS certificate can take a minute on first start)."
echo "Load demo data:   cd $DIR && docker compose -f docker-compose.prod.yml exec api python -m scripts.seed"
