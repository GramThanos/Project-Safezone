#!/usr/bin/env python3
"""Database initialization: run migrations, then seed.

Run from the backend directory with `python -m init_db`. Idempotent, and the
container entrypoint runs it on every boot.

Exit codes matter here. The entrypoint retries this while the database container
is still starting, so a transient connection failure has to be distinguishable
from a real one - otherwise a missing dependency or a broken migration gets
retried thirty times and is then reported as "database not ready", which sends
somebody looking in entirely the wrong place.

    0   done
    75  database not reachable yet (EX_TEMPFAIL) - worth retrying
    1   anything else - retrying will not help
"""
import sys
import traceback

from flask import Flask

from src.config import configure_app
from src.database import db
from src.models.user import User

# Matches sysexits.h EX_TEMPFAIL; entrypoint.sh keys off this exact value.
EXIT_RETRYABLE = 75


# MySQL client error codes that mean "the server is not reachable". Anything
# else - including plenty of OperationalErrors - is a real problem: 1050 is
# "table already exists", 1045 is "access denied", and retrying either is just
# a slower way to fail.
CONNECTION_ERRNOS = {
    2002,   # can't connect through socket
    2003,   # can't connect to server
    2005,   # unknown server host
    2006,   # server has gone away
    2013,   # lost connection during query
}


def is_connection_error(error):
    """Whether this is "the database is not accepting connections yet".

    Keyed on the driver's error code rather than the exception class, because
    PyMySQL raises OperationalError for server-side errors too.
    """
    from sqlalchemy.exc import InterfaceError

    # DBAPI-level failures are always connection failures.
    if isinstance(error, InterfaceError):
        return True

    args = getattr(getattr(error, 'orig', None), 'args', ())
    if args and isinstance(args[0], int):
        return args[0] in CONNECTION_ERRNOS

    # No code available (DNS failure before the driver gets involved, say).
    text = str(error).lower()
    return any(hint in text for hint in (
        "can't connect", 'connection refused', 'gone away',
        'name or service not known', 'getaddrinfo failed',
    ))


def create_app():
    """Minimal app, just for configuration and the database binding."""
    app = Flask(__name__)
    configure_app(app)
    db.init_app(app)
    return app


def init_database():
    """Bring the schema up to date. Raises on anything worth stopping for."""
    print("Applying database migrations...")
    db.init_db()
    print("OK  Schema is up to date")


def seed_boxes_and_events():
    """On a fresh database, create the starter boxes and the two system events.

    A fresh deployment needs a working economy: a daily event that can grant a
    box, and a weekly bonus event for the streak job. Boxes start with empty
    loot pools - an admin fills them - so the daily grant is live the moment a
    reward is added to a box.

    Gated on the daily system event already existing rather than looking boxes
    up by name each boot: once seeded, an operator may rename or remove any of
    these, and re-running must not resurrect them.
    """
    from src.models.box import Box
    from src.models.event import Event
    from src.models.event_box import EventBox

    print("\nChecking loot boxes and events...")
    with db.get_db() as session:
        if session.query(Event).filter_by(type=Event.TYPE_DAILY, system=True).first():
            print("OK  Boxes and events already present")
            return

        # (name, draws, daily pick weight or None if bonus-only)
        starter_boxes = [
            ('Small', 1, 0.6),
            ('Medium', 2, 0.3),
            ('Big', 3, 0.1),
            ('Weekly Bonus', 4, None),
        ]
        boxes = {}
        for name, draws, _ in starter_boxes:
            box = Box(name=name, draws=draws)
            session.add(box)
            boxes[name] = box

        daily = Event(type=Event.TYPE_DAILY, name='Daily box', system=True,
                      enabled=True, cadence=Event.CADENCE_DAILY,
                      description='One box every day, picked by weight from the boxes below.')
        weekly = Event(type=Event.TYPE_WEEKLY_BONUS, name='Weekly bonus', system=True,
                       enabled=True, cadence=Event.CADENCE_WEEKLY,
                       description='A bonus box for players who collected enough daily '
                                   'boxes during the week.')
        session.add(daily)
        session.add(weekly)
        session.flush()   # assign ids before wiring the line-ups

        for name, _, weight in starter_boxes:
            if weight is not None:
                session.add(EventBox(event_id=daily.id, box_id=boxes[name].id, weight=weight))
        session.add(EventBox(event_id=weekly.id, box_id=boxes['Weekly Bonus'].id, weight=1.0))

    print("OK  Seeded starter boxes and the daily and weekly bonus events")


def create_admin_user():
    """Create the default admin account if there is none."""
    print("\nChecking for admin user...")
    with db.get_db() as session:
        if session.query(User).filter_by(username='admin').first():
            print("OK  Admin user already exists")
            return

        admin = User(
            username='admin',
            email='admin@safezone.local',
            role=User.ROLE_ADMIN
        )
        admin.set_password('admin')
        # The documented default is a liability on a public deployment, so the
        # account can do nothing but read itself and set a new password until
        # that happens. This turns a README warning into a property of the
        # system.
        admin.must_change_password = True
        admin.token_version = 0
        session.add(admin)
        session.flush()

        print("OK  Admin user created")
        print("  Username: admin")
        print("  Password: admin")
        print("  !! You must change this password at first sign-in;")
        print("     the account cannot do anything else until you do.")


def main():
    print("=" * 60)
    print("Project Safezone - Database Initialization")
    print("=" * 60)

    app = create_app()
    try:
        with app.app_context():
            init_database()
            create_admin_user()
            seed_boxes_and_events()
    except Exception as e:
        if is_connection_error(e):
            print(f"ERROR Database not reachable yet: {e}")
            return EXIT_RETRYABLE

        # Not a startup race. Show the whole thing: this is the message somebody
        # actually needs, and burying it behind a retry loop wastes their time.
        print("ERROR Initialization failed, and retrying will not help:\n")
        # Same stream as the surrounding messages: split across stdout and
        # stderr, container logs can show the traceback detached from the line
        # that explains it.
        traceback.print_exc(file=sys.stdout)
        print("\nCommon causes:")
        print("  - the image was not rebuilt, so `alembic` is not installed")
        print("  - a migration is broken (see the traceback above)")
        return 1

    print("\n" + "=" * 60)
    print("Database initialization complete!")
    print("=" * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
