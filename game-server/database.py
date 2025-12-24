"""
Database module using SQLAlchemy
Handles all database connections and operations
"""
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, JSON, TIMESTAMP, Index
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.sql import func
from config import DATABASE_HOST, DATABASE_NAME, DATABASE_USER, DATABASE_PASSWORD

# Create SQLAlchemy engine
DATABASE_URL = f"mysql+pymysql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}/{DATABASE_NAME}"
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)

# Create base class for declarative models
class Base(DeclarativeBase):
    pass

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Task(Base):
    """Task model"""
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(50), nullable=False, default='pending')
    data = Column(JSON, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp()
    )
    
    __table_args__ = (
        Index('idx_status', 'status'),
        Index('idx_created_at', 'created_at'),
    )
    
    def to_dict(self):
        """Convert task to dictionary"""
        # Parse data field - handle both dict and JSON string
        data = self.data
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                # If JSON parsing fails, return as-is wrapped in a dict
                data = {'raw_data': data}
        
        return {
            'id': self.id,
            'status': self.status,
            'data': data,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


def get_db_session():
    """Get database session"""
    return SessionLocal()


def init_database():
    """Initialize database schema"""
    try:
        Base.metadata.create_all(bind=engine)
        print("Database initialized successfully")
        return True
    except Exception as e:
        print(f"Database initialization error: {e}")
        return False


def close_db_session(session):
    """Close database session"""
    try:
        session.close()
    except Exception as e:
        print(f"Error closing database session: {e}")
