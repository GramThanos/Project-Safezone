"""Database configuration and connection management with SQLAlchemy"""
import logging
import os
import threading
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Create declarative base for models
Base = declarative_base()


class Database:
    """Database connection manager using SQLAlchemy"""
    
    def __init__(self):
        # These will be initialized in init_app() when Flask app is available
        self.engine = None
        self.session_factory = None
        self.Session = None
        # How many `get_db()` blocks this thread is currently inside. See the
        # note there: the session is thread-scoped, so nesting is re-entrant.
        self._depth = threading.local()
    
    def init_app(self, app):
        """Initialize database with Flask app configuration"""
        # Build database URL from Flask config
        self.database_url = app.config['SQLALCHEMY_DATABASE_URI']
        
        # Create engine with connection pooling
        self.engine = create_engine(
            self.database_url,
            pool_pre_ping=app.config['SQLALCHEMY_POOL_PRE_PING'],
            pool_recycle=app.config['SQLALCHEMY_POOL_RECYCLE'],
            echo=app.config['SQLALCHEMY_ECHO']
        )
        
        # Create session factory
        self.session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(self.session_factory)
    
    def get_session(self):
        """Get a new database session"""
        return self.Session()
    
    @contextmanager
    def get_db(self):
        """Context manager for database sessions. Re-entrant.

        `Session` is thread-scoped, so a nested `get_db()` on the same thread
        hands back the session the outer block is already using - not a second
        one. Committing and closing it at the *inner* exit therefore ended the
        outer transaction halfway through: it published a partial write, dropped
        any `FOR UPDATE` lock, and left every row the outer block had already
        loaded detached and expired, so the next attribute read raised
        `DetachedInstanceError`.

        That is not a hypothetical. The cached reader `utils/settings.py` opens
        a session of its own on a cache miss, and is called from inside routes
        that hold one. The failure therefore appeared only on the first request
        after a cache entry expired, which is exactly the shape of a bug that
        "happens sometimes": settings-dependent routes returned a 500, and daily
        grants and box opens could half-write.

        So only the outermost block owns the transaction. Inner blocks join it
        and leave commit and close to the caller that opened it.
        """
        depth = getattr(self._depth, 'value', 0)
        if depth:
            self._depth.value = depth + 1
            try:
                yield self.get_session()
            finally:
                self._depth.value = depth
            return

        session = self.get_session()
        self._depth.value = 1
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            self._depth.value = 0
            session.close()
    
    def init_db(self):
        """Bring the backend's own tables up to date with Alembic.

        Only the backend's tables: `servers`, `tasks` and `server_player_counts`
        belong to the game-server, which migrates them in its own `database.init()`.
        Alembic is told to ignore them (see alembic/env.py), so it never proposes
        dropping a table it simply does not know about.

        Run on every boot from the container entrypoint. Failures are raised - a
        half-migrated schema must stop the service, not become a mystery query
        error later.
        """
        from alembic import command
        from alembic.config import Config as AlembicConfig

        self._check_not_pre_alembic()

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = AlembicConfig(os.path.join(root, 'alembic.ini'))
        cfg.set_main_option('script_location', os.path.join(root, 'alembic'))
        cfg.set_main_option('sqlalchemy.url', self.database_url)

        command.upgrade(cfg, 'head')
        logger.info("Database schema is up to date")

    def _check_not_pre_alembic(self):
        """Refuse to migrate a database that predates Alembic.

        Such a database has the tables - built by the old `create_all()` path -
        but no `alembic_version` row, so Alembic believes nothing has been
        applied and tries to create tables that already exist. The resulting
        "table already exists" error says nothing about the actual situation.

        Not stamped automatically: the old path only ever added tables and a
        hand-listed set of columns, so the schema is *close* to head but not
        reliably equal to it. Silently stamping would leave columns missing and
        turn a loud startup error into a mystery query failure weeks later,
        which is the thing this whole migration setup exists to prevent.
        """
        from sqlalchemy import inspect

        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())

        if 'alembic_version' in tables or 'users' not in tables:
            return      # already adopted, or genuinely empty

        raise RuntimeError(
            "This database was created before Alembic was adopted: it has the "
            "application's tables but no 'alembic_version' row, so Alembic would "
            "try to create tables that already exist.\n"
            "\n"
            "  Test data only (the usual case):\n"
            "    docker compose down -v && docker compose up -d --build\n"
            "    This drops the database volume and rebuilds the schema cleanly.\n"
            "\n"
            "  Data worth keeping:\n"
            "    Stamp the revision the schema actually matches, then upgrade:\n"
            "      docker compose run --rm backend alembic stamp <revision>\n"
            "    Compare the schema against alembic/versions/ to pick it, and "
            "add any columns the old path never applied."
        )

    def drop_all(self):
        """Drop all tables (for testing)"""
        Base.metadata.drop_all(self.engine)
        logger.warning("All database tables dropped")


# Global database instance
db = Database()
