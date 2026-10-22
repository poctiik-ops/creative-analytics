#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
mkdir -p secrets backups
chmod 700 secrets backups
for name in db_password app_password; do
  if [ ! -e "secrets/$name" ]; then
    openssl rand -hex 32 > "secrets/$name"
  fi
done
# Empty key is valid for CSV-only mode; never overwrite an existing key.
if [ ! -e secrets/unity_api_key ]; then : > secrets/unity_api_key; fi
# Compose file-backed secrets retain host permissions. Only the container app UID
# needs read access; directory stays private to the VDS administrator.
chmod 444 secrets/db_password secrets/app_password secrets/unity_api_key
printf '%s\n' 'Secret files prepared. Admin password: read secrets/app_password locally; never commit it.'
