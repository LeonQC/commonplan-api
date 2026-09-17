#!/bin/sh
set -eu

case "$AUTH_POSTGRES_DB" in
  ""|*[!a-zA-Z0-9_]*)
    echo "AUTH_POSTGRES_DB must contain only letters, numbers, and underscores" >&2
    exit 2
    ;;
esac

database_exists="$(
  psql \
    --host=db \
    --username="$POSTGRES_USER" \
    --dbname=postgres \
    --tuples-only \
    --no-align \
    --command="SELECT 1 FROM pg_database WHERE datname = '$AUTH_POSTGRES_DB'"
)"

if [ "$database_exists" != "1" ]; then
  createdb \
    --host=db \
    --username="$POSTGRES_USER" \
    --owner="$POSTGRES_USER" \
    "$AUTH_POSTGRES_DB"
fi
