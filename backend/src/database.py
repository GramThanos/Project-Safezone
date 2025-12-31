"""Database configuration and connection management with SQLAlchemy"""
import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Create declarative base for models
Base = declarative_base()


class Database:
    """Database connection manager using SQLAlchemy"""
    
    def __init__(self):
        # Build database URL
        host = os.getenv('DATABASE_HOST', 'db')
        database = os.getenv('DATABASE_NAME', 'safezone')
        user = os.getenv('DATABASE_USER', 'safezone')
        password = os.getenv('DATABASE_PASSWORD', 'safezone')
        
        self.database_url = f"mysql+pymysql://{user}:{password}@{host}/{database}"
        
        # Create engine with connection pooling
        self.engine = create_engine(
            self.database_url,
            pool_pre_ping=True,  # Verify connections before using
            pool_recycle=3600,   # Recycle connections after 1 hour
            echo=False           # Set to True for SQL logging during development
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
        """Initialize database tables"""
        # Import models to register them with Base
        from src.models import User, Player, Server
        
        # Create all tables
        Base.metadata.create_all(self.engine)
        logger.info("Database tables initialized successfully")
    
    def drop_all(self):
        """Drop all tables (for testing)"""
        Base.metadata.drop_all(self.engine)
        logger.warning("All database tables dropped")


# Global database instance
db = Database()
