#!/usr/bin/env python3
import datetime
import sqlalchemy
import sqlalchemy.orm
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


# Initialize Database Schema
def init():
    """Initialize database schema"""
    # Import inside the function to avoid circular import issues
    from . import models 
    try:
        models.Base.metadata.create_all(bind=engine)
        return True
    except Exception as e:
        _log(f"Initialization error: {e}")
        return False


# Session Management
def get_session():
    """Helper for manual session management."""
    return SessionLocal()

@contextmanager
def get_context_session():
    """
    Context manager for database sessions.
    Handles rollback on error and ensures thread-local cleanup via .remove()
    """
    session = SessionLocal()
    try:
        yield session
    except Exception as e:
        session.rollback()
        _log(f"Transaction error, rolled back: {str(e)}")
        raise
    finally:
        # returns the connection to the pool and clears thread-local state
        SessionLocal.remove()
