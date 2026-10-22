#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
mkdir -p backups
backup="backups/analytics-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db pg_dump -U analytics -d analytics -Fc > "$backup"
# Remove incomplete dumps if validation fails.
if ! docker compose exec -T db pg_restore --list < "$backup" >/dev/null; then
  rm -f "$backup"
  exit 1
fi
printf 'Backup saved: %s\n' "$backup"
