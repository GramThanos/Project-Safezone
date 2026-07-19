#!/bin/sh
# Initialize the database (create tables + seed admin user) before starting the
# web server. init_db is idempotent, so it is safe to run on every boot.
# Retries because the database container may not be ready yet.
set -e

echo "[entrypoint] Waiting for database and initializing schema..."
for i in $(seq 1 30); do
    if python -m init_db; then
        echo "[entrypoint] Database initialization complete."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[entrypoint] ERROR: Database not ready after 30 attempts. Exiting."
        exit 1
    fi
    echo "[entrypoint] Attempt $i failed, retrying in 2s..."
    sleep 2
done

echo "[entrypoint] Starting application: $*"
exec "$@"
