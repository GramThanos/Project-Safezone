"""Centralized configuration for the Flask application"""
import os


class Config:
    """Application configuration with default values"""
    
    # Database Configuration
    DATABASE_HOST = os.getenv('DATABASE_HOST', 'db')
    DATABASE_NAME = os.getenv('DATABASE_NAME', 'safezone')
    DATABASE_USER = os.getenv('DATABASE_USER', 'safezone')
    DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD', 'safezone')
    
    # Build database URL for SQLAlchemy
    SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}/{DATABASE_NAME}"
    
    # JWT Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    TOKEN_EXPIRY_HOURS = int(os.getenv('TOKEN_EXPIRY_HOURS', '24'))
    TOKEN_ISSUER = os.getenv('TOKEN_ISSUER', 'safezone-api')
    TOKEN_AUDIENCE = os.getenv('TOKEN_AUDIENCE', 'safezone-frontend')
    
    # Redis Configuration
    REDIS_HOST = os.getenv('REDIS_HOST', 'cache')
    REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}"
    
    # CORS Configuration
    ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'http://localhost:3000').split(',')
    
    # Security Configuration
    HTTPS_ENABLED = os.getenv('HTTPS_ENABLED', 'false').lower() == 'true'
    
    # Game Server Configuration
    GAME_SERVER_API_URL = os.getenv('GAME_SERVER_API_URL', 'http://game-server:5001')
    API_TOKEN = os.getenv('API_TOKEN', '')
    
    # Flask Configuration
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    # Rate Limiting Configuration
    RATELIMIT_STORAGE_URI = REDIS_URL
    RATELIMIT_DEFAULT_LIMITS = ["200 per day", "50 per hour"]
    
    # SQLAlchemy Connection Pool Configuration
    SQLALCHEMY_POOL_PRE_PING = True  # Verify connections before using
    SQLALCHEMY_POOL_RECYCLE = 3600   # Recycle connections after 1 hour
    SQLALCHEMY_ECHO = False          # Set to True for SQL logging during development


def configure_app(app):
    """Apply configuration to Flask app instance"""
    app.config.from_object(Config)
    return app
