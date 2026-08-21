#!/usr/bin/env python3
import threading
import time
import datetime
import sqlalchemy
import sqlalchemy.orm
import sqlalchemy.sql.elements
from contextlib import contextmanager

# Import configuration
import config

# Logging
def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Database] {message}")

# Database Engine Configuration
engine = sqlalchemy.create_engine(
    config.DATABASE_URL, 
    pool_size=config.DATABASE_POOL_SIZE,
    max_overflow=0,
    pool_pre_ping=True,
    pool_recycle=3600
)

# Thread-local sessions
session_factory = sqlalchemy.orm.sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine
)
SessionLocal = sqlalchemy.orm.scoped_session(session_factory)

# How many `get_context_session()` blocks this thread is inside. See the note
# there: the session is thread-scoped, so nesting has to be re-entrant.
_local = threading.local()


# Initialize Database Schema
def init(wait_for_availability=True):
    """Initialize database schema"""
    if wait_for_availability:
        if not wait(timeout=60):
            _log("Database not available, cannot initialize schema")
            return False
    import models
    try:
        models.Base.metadata.create_all(bind=engine)
        _run_migrations()
        _log("Database schema initialized")
        return True
    except Exception as e:
        _log(f"Initialization error: {e}")
        return False


def _run_migrations():
    """Idempotent additive migrations for the tables this service owns.

    `create_all` builds missing tables but never adds a column to one that
    already exists, so an upgraded deployment needs these. They used to live in
    the backend, which meant one service altering another's tables - see the
    ownership split in AGENTS.md.

    Failures are raised, not swallowed: booting on a half-migrated schema turns
    an obvious startup error into a mystery query failure later.
    """
    statements = [
        # Public connection info shown on the servers page
        "ALTER TABLE servers ADD COLUMN IF NOT EXISTS hostname VARCHAR(255) NULL",
        "ALTER TABLE servers ADD COLUMN IF NOT EXISTS description TEXT NULL",
        # The primary server's timezone defines the daily-reward reset boundary
        "ALTER TABLE servers ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NULL",
        # Explicit primary flag, replacing "lowest id that happens to have a timezone"
        "ALTER TABLE servers ADD COLUMN IF NOT EXISTS is_primary BOOLEAN NOT NULL DEFAULT FALSE",
        # Idle auto-sleep timeout; 0 (the default) keeps the old behaviour of
        # staying up until somebody stops the server.
        "ALTER TABLE servers ADD COLUMN IF NOT EXISTS idle_sleep_seconds INTEGER NOT NULL DEFAULT 0",
    ]
    # Each statement gets its own transaction so one failure cannot poison the rest.
    for stmt in statements:
        label = stmt.strip().splitlines()[0].strip()
        try:
            with engine.begin() as conn:
                conn.execute(sqlalchemy.text(stmt))
        except Exception as e:
            _log(f"Migration step FAILED ({label}): {e}")
            raise

# Wait for Database Availability
def wait(timeout=30):
    """Wait for database to become available"""
    _log(f"Checking database availability...")
    start_time = datetime.datetime.now()
    while True:
        try:
            with engine.connect() as connection:
                connection.execute(sqlalchemy.text("SELECT 1"))
                _log("Database is available")
                return True
        except Exception as e:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                _log(f"Database not available after {timeout} seconds: {e}")
                return False
            #_log(f"Error {e}, retrying...")
            #_log("Waiting for database to become available...")
            time.sleep(2)

# Wait for Database Table Availability
def wait_table(model, timeout=30):
    """Wait for database table to become available"""
    _log(f"Checking database table availability...")
    
    start_time = datetime.datetime.now()
    table_name = model.__tablename__ if hasattr(model, '__tablename__') else str(model)
    safe_name = sqlalchemy.sql.quoted_name(table_name, quote=True)
    while True:
        try:
            with engine.connect() as connection:
                connection.execute(sqlalchemy.text(f"SELECT 1 FROM {safe_name} LIMIT 1"))
                _log("Database is available")
                return True
        except Exception as e:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                _log(f"Database not available after {timeout} seconds: {e}")
                return False
            _log(f"Error {e}, retrying...")
            _log("Waiting for database to become available...")
            time.sleep(2)

# Session Management
def get_session():
    """Helper for manual session management."""
    return SessionLocal()

@contextmanager
def get_context_session():
    """
    Context manager for database sessions. Re-entrant. Does not commit - the
    caller owns that.

    `SessionLocal` is thread-scoped, so a nested call on the same thread hands
    back the session the outer block is already using, not a second one.
    `remove()` at the *inner* exit therefore closed the session out from under
    the outer block: rows it had loaded became detached, and its later writes
    went nowhere - silently, because committing a detached instance raises
    nothing.

    That is what left delivered rewards stuck in 'processing'. `process()` held
    a session, called `give_reward`, which called `servers.get` - a nested
    block. The item went out over the console, and the `status = 'completed'`
    written afterwards was dropped on the floor.

    So only the outermost block cleans up; inner blocks borrow the session and
    leave it open.
    """
    depth = getattr(_local, 'depth', 0)
    if depth:
        _local.depth = depth + 1
        try:
            yield SessionLocal()
        finally:
            _local.depth = depth
        return

    session = SessionLocal()
    _local.depth = 1
    try:
        yield session
    except Exception as e:
        session.rollback()
        _log(f"Transaction error, rolled back: {str(e)}")
        raise
    finally:
        _local.depth = 0
        # returns the connection to the pool and clears thread-local state
        SessionLocal.remove()
