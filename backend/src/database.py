"""Database configuration and connection management"""
import os
import mysql.connector
from contextlib import contextmanager


class Database:
    """Database connection manager"""
    
    def __init__(self):
        self.config = {
            'host': os.getenv('DATABASE_HOST', 'db'),
            'database': os.getenv('DATABASE_NAME', 'safezone'),
            'user': os.getenv('DATABASE_USER', 'safezone'),
            'password': os.getenv('DATABASE_PASSWORD', 'safezone'),
            'autocommit': False
        }
    
    def get_connection(self):
        """Get a new database connection"""
        try:
            conn = mysql.connector.connect(**self.config)
            return conn
        except Exception as e:
            print(f"Database connection error: {e}")
            raise
    
    @contextmanager
    def get_db(self):
        """Context manager for database connections"""
        conn = self.get_connection()
        try:
            yield conn
        finally:
            conn.close()
    
    def init_db(self):
        """Initialize database tables"""
        from src.models import User, Player, Server
        
        with self.get_db() as conn:
            User.create_table(conn)
            Player.create_table(conn)
            Server.create_table(conn)
            print("Database tables initialized successfully")


# Global database instance
db = Database()
