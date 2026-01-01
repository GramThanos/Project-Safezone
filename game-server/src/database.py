#!/usr/bin/env python3
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


# Initialize Database Schema
def init(wait_for_availability=True):
    """Initialize database schema"""
    if wait_for_availability:
        if not wait(timeout=60):
            _log("Database not available, cannot initialize schema")
            return False
    import models
    while True:
        try:
            models.Base.metadata.create_all(bind=engine)
            _log(f"Database schema initialized")
            return True
        except Exception as e:
            _log(f"Initialization error: {e}")
            return False

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
