#!/bin/sh
# Nightly pg_dump at ~02:30 server time, keeping KEEP_DAYS days. Copy /backups off the box (see docs/operations.md).
set -eu
while true; do
  now=$(date +%H%M)
  if [ "$now" = "0230" ] || [ ! -f /backups/.first-run-done ]; then
    f="/backups/relay-$(date +%Y%m%d-%H%M).dump"
    pg_dump -h db -U relay -d relay -Fc -f "$f.partial" && mv "$f.partial" "$f" && echo "backup ok: $f"
    touch /backups/.first-run-done
    find /backups -name 'relay-*.dump' -mtime +"$KEEP_DAYS" -delete
    sleep 60
  fi
  sleep 30
done
