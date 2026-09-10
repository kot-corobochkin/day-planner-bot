#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -f /opt/day-planner/app/db/schema.sql

for migration in /opt/day-planner/app/db/migrations/*.sql; do
  [ -f "$migration" ] || continue
  psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    -f "$migration"
done
