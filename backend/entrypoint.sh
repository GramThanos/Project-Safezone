#!/bin/sh
# Bring the schema up to date before starting the web server. init_db is
# idempotent, so it is safe to run on every boot.
#
# Only "the database is not up yet" is retried. Anything else - a missing
# dependency, a broken migration - is reported immediately, because retrying it
# thirty times only delays the real error by a minute and then hides it behind a
# message about the database that is not true.
set -e

RETRYABLE=75          # init_db exits with this while the database is starting
ATTEMPTS=30

echo "[entrypoint] Bringing the database schema up to date..."

i=1
while [ "$i" -le "$ATTEMPTS" ]; do
    set +e
    python -m init_db
    code=$?
    set -e

    if [ "$code" -eq 0 ]; then
        echo "[entrypoint] Schema ready."
        break
    fi

    if [ "$code" -ne "$RETRYABLE" ]; then
        echo "[entrypoint] ERROR: initialization failed (exit $code)."
        echo "[entrypoint] This is NOT a 'database still starting' problem - the"
        echo "[entrypoint] cause is in the output above."
        exit "$code"
    fi

    if [ "$i" -eq "$ATTEMPTS" ]; then
        echo "[entrypoint] ERROR: database still unreachable after $ATTEMPTS attempts."
        exit 1
    fi

    echo "[entrypoint] Database not up yet (attempt $i/$ATTEMPTS), retrying in 2s..."
    i=$((i + 1))
    sleep 2
done

echo "[entrypoint] Starting application: $*"
exec "$@"
