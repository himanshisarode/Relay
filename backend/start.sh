#!/bin/sh
# Container entrypoint: migrate, optionally seed, then serve. Used by AWS App Runner and docker compose alike.
set -e
alembic upgrade head
case "$RELAY_SEED_ON_START" in
  demo) python -m scripts.seed ;;
  org)  python -m scripts.seed --no-demo ;;
esac
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
