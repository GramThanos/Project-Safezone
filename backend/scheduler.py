#!/usr/bin/env python3
"""The backend's recurring-job worker.

Runs as its own process against the same image and code as the API, so it shares
the models and configuration without the game-server having to call back into
the backend - which would invert the one-way dependency the stack maintains
everywhere else.

Start it with `python -m scheduler`.

It also pumps the game-server's alert queue on every tick - see `pump_alerts` for why
that is not a job like the others.

Two workers running at once is safe: a job is claimed inside a transaction with
`SELECT ... FOR UPDATE`, so only one can hold it. A worker killed mid-job leaves
`running_since` set, and the claim is reclaimed once it goes stale rather than
blocking that job forever - the same reasoning as the game-server's `reap_stuck`.
"""
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta

from flask import Flask

from src.config import configure_app
from src.database import db
from src.models.scheduled_job import ScheduledJob
from src.utils import alerting, jobs

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][scheduler][%(levelname)s] %(message)s'
)
logger = logging.getLogger('scheduler')

# How often to look for due work. Jobs are hourly or slower, so this only needs
# to be fine enough that "run now" from the panel feels responsive.
TICK_SECONDS = int(os.getenv('SCHEDULER_TICK_SECONDS', '30'))
# A claim older than this belonged to a worker that died.
STALE_AFTER = timedelta(minutes=30)

_stop = False


def _handle_signal(signum, _frame):
    global _stop
    logger.info(f"Signal {signum} received, finishing the current job then stopping.")
    _stop = True


def create_app():
    app = Flask(__name__)
    configure_app(app)
    db.init_app(app)
    return app


def ensure_registered():
    """Make sure every known job kind has a row, without disturbing existing ones.

    New kinds appear disabled: a job that starts running the moment it is
    deployed is a surprise, and an operator should turn it on deliberately.
    """
    with db.get_db() as session:
        existing = {row.kind for row in session.query(ScheduledJob).all()}
        for kind, spec in jobs.REGISTRY.items():
            if kind in existing:
                continue
            session.add(ScheduledJob(
                kind=kind,
                interval_seconds=spec['default_interval'],
                enabled=False,
                next_run_at=datetime.utcnow(),
            ))
            logger.info(f"Registered new job kind '{kind}' (disabled)")


def claim_due_job():
    """Take ownership of one due job, or return None.

    The row is locked for the duration of the claim so two workers cannot take
    the same job. The claim itself is a separate, short transaction from the
    work: holding a row lock for the length of a job would block the panel.
    """
    now = datetime.utcnow()
    stale_before = now - STALE_AFTER
    with db.get_db() as session:
        row = (session.query(ScheduledJob)
               .filter(ScheduledJob.enabled.is_(True))
               .filter((ScheduledJob.next_run_at.is_(None)) | (ScheduledJob.next_run_at <= now))
               .filter((ScheduledJob.running_since.is_(None))
                       | (ScheduledJob.running_since < stale_before))
               .order_by(ScheduledJob.next_run_at.asc())
               .with_for_update(skip_locked=True)
               .first())
        if not row:
            return None
        if row.running_since is not None:
            logger.warning(f"Reclaiming '{row.kind}', abandoned since {row.running_since}")
        row.running_since = now
        return row.kind


def run_job(kind):
    """Run one job and record the outcome."""
    spec = jobs.REGISTRY.get(kind)
    started = time.monotonic()

    deferred = None
    if not spec:
        # The row outlived its handler - a kind was removed from the code.
        result, ok = f'no handler registered for "{kind}"', False
    else:
        try:
            with db.get_db() as session:
                result = spec['run'](session, None) or 'done'
            # A handler may return (summary, callable) to hand back work that
            # must not run inside its transaction - anything doing network I/O.
            # Holding a transaction open across a call to another service ties
            # up a connection for as long as that service is slow.
            # Shape-checked rather than assumed: a handler returning some other
            # tuple should not have its second element called.
            if isinstance(result, tuple) and len(result) == 2 and callable(result[1]):
                result, deferred = result
            ok = True
        except Exception as e:
            logger.exception(f"Job '{kind}' failed")
            result, ok = f'failed: {e}', False

    if deferred is not None:
        try:
            deferred()
        except Exception as e:
            # The database work already committed; this is follow-up that failed.
            logger.exception(f"Job '{kind}' follow-up failed")
            result = f'{result} (follow-up failed: {e})'

    elapsed = time.monotonic() - started
    with db.get_db() as session:
        row = session.query(ScheduledJob).filter_by(kind=kind).first()
        if row:
            row.last_run_at = datetime.utcnow()
            row.last_result = result
            row.running_since = None
            row.next_run_at = datetime.utcnow() + timedelta(
                seconds=max(60, row.interval_seconds or 3600)
            )
    logger.info(f"{'ran' if ok else 'FAILED'} '{kind}' in {elapsed:.1f}s: {result}")


def pump_alerts():
    """Deliver whatever the game-server has queued, to whichever channels want it.

    Not a `ScheduledJob`, deliberately. Job intervals are floored at a minute
    and new job kinds are registered switched off, and neither is right for an
    event pump: "so-and-so joined" arriving two minutes late is barely worth
    sending, and an operator who configures a channel and hears nothing has no
    reason to suspect there was a second switch elsewhere. So it runs on the
    scheduler's own tick, and the panel reads its heartbeat to say whether
    anything is draining the queue at all.
    """
    try:
        alerting.pump_seen()
        if not alerting.any_subscribers():
            # Nobody to tell. Drop the queue rather than let it wait, so adding
            # the first channel does not replay this morning into it.
            alerting.discard()
            return
        handled = alerting.drain()
        if handled:
            logger.info(f"dispatched {handled} queued alert event(s)")
    except Exception as e:
        logger.error(f"Alert pump failed: {e}")


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    app = create_app()
    with app.app_context():
        # The backend container owns migrations; this process only waits for
        # the schema to appear. It waits indefinitely rather than giving up:
        # exiting here just swaps a clear wait for a restart loop that says
        # less, and the message below points at the container that can actually
        # be fixed.
        attempt = 0
        while not _stop:
            try:
                ensure_registered()
                break
            except Exception as e:
                attempt += 1
                if attempt == 1 or attempt % 30 == 0:
                    logger.warning(
                        "Waiting for the backend to create the schema (attempt "
                        f"{attempt}). If this never clears, check the backend "
                        f"container's logs - it runs the migrations. Last error: {e}"
                    )
                time.sleep(2)
        if _stop:
            return 0

        logger.info(f"Scheduler started; {len(jobs.REGISTRY)} job kind(s) known.")
        while not _stop:
            try:
                pump_alerts()
                kind = claim_due_job()
                if kind:
                    run_job(kind)
                    continue  # there may be more due right now
            except Exception as e:
                logger.exception(f"Scheduler tick failed: {e}")
            time.sleep(TICK_SECONDS)

        logger.info("Scheduler stopped.")
        return 0


if __name__ == '__main__':
    sys.exit(main())
