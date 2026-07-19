"""Database configuration and connection management with SQLAlchemy"""
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base
from contextlib import contextmanager
from flask import current_app

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
        """Context manager for database sessions"""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def init_db(self):
        """Initialize database tables owned by the backend (users, players, claim_requests)"""
        # Import models to register them with Base
        from src.models import (User, Player, ClaimRequest, Reward,
                                 BoxLootPool, UserBox, InventoryItem, AuditLog)

        # Create all tables
        Base.metadata.create_all(self.engine)
        # Apply additive migrations for columns create_all won't add to existing tables
        self._run_migrations()
        logger.info("Database tables initialized successfully")

    def _run_migrations(self):
        """Idempotent additive migrations (no Alembic yet).

        MariaDB's `ADD COLUMN IF NOT EXISTS` makes these safe to run repeatedly on
        both fresh and existing databases.
        """
        from sqlalchemy import text
        statements = [
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS server_id INT",
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS in_game_username VARCHAR(32)",
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS verified BOOLEAN NOT NULL DEFAULT FALSE",
        ]
        with self.engine.begin() as conn:
            for stmt in statements:
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    logger.warning(f"Migration step skipped ({stmt}): {e}")
    
    def drop_all(self):
        """Drop all tables (for testing)"""
        Base.metadata.drop_all(self.engine)
        logger.warning("All database tables dropped")


# Global database instance
db = Database()
