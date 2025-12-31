#!/usr/bin/env python3
"""
Database initialization script
Creates tables and optionally seeds with an admin user
Run this from the backend directory: python -m init_db
"""
import sys
from flask import Flask
from src.config import configure_app
from src.database import db
from src.models.user import User

def create_app():
    """Create Flask app for database initialization"""
    app = Flask(__name__)
    configure_app(app)
    db.init_app(app)
    return app

def init_database():
    """Initialize database tables"""
    print("Initializing database...")
    try:
        db.init_db()
        print("✓ Database tables created successfully")
    except Exception as e:
        print(f"✗ Error creating tables: {e}")
        return False
    
    return True

def create_admin_user():
    """Create a default admin user if none exists"""
    print("\nChecking for admin user...")
    try:
        with db.get_db() as session:
            # Check if admin user already exists
            admin = session.query(User).filter_by(username='admin').first()
            if admin:
                print("✓ Admin user already exists")
                return True
            
            # Create admin user
            admin = User(
                username='admin',
                email='admin@safezone.local',
                role=User.ROLE_ADMIN
            )
            admin.set_password('admin')  # CHANGE THIS IN PRODUCTION!
            session.add(admin)
            session.flush()  # Flush to get user ID
            
            print("✓ Admin user created successfully")
            print("  Username: admin")
            print("  Password: admin")
            print("  ⚠️  IMPORTANT: Change the admin password in production!")
            return True
    except Exception as e:
        print(f"✗ Error creating admin user: {e}")
        return False

if __name__ == '__main__':
    print("=" * 60)
    print("Project Safezone - Database Initialization")
    print("=" * 60)
    
    # Create Flask app with configuration
    app = create_app()
    
    # Run database operations within app context
    with app.app_context():
        # Initialize database
        if not init_database():
            sys.exit(1)
        
        # Create admin user
        if not create_admin_user():
            sys.exit(1)
    
    print("\n" + "=" * 60)
    print("Database initialization complete!")
    print("=" * 60)
