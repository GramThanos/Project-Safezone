"""
Configuration module for Game Server
Centralizes all configuration settings
"""
import os


# Database Configuration
# IMPORTANT: Change default credentials in production!
DATABASE_HOST = os.getenv('DATABASE_HOST', 'db')
DATABASE_NAME = os.getenv('DATABASE_NAME', 'safehouse')
DATABASE_USER = os.getenv('DATABASE_USER', 'safehouse')
DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD', 'safehouse')

# Redis Configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'cache')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_CHANNEL = 'task_notifications'

# Task Processing Configuration
PROCESS_INTERVAL = int(os.getenv('PROCESS_INTERVAL', '5'))  # seconds

# API Configuration
# SECURITY WARNING: Change API_TOKEN in production!
# Set via environment variable: API_TOKEN=your-secure-token
API_TOKEN = os.getenv('API_TOKEN', 'safehouse-api-token-change-me')

# Monitoring Configuration (for manager.py)
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '30'))  # seconds
STEAMCMD_PATH = os.getenv('STEAMCMD_PATH', '/home/steam/steamcmd')


def warn_default_token():
    """Warn if using default API token"""
    if API_TOKEN == 'safehouse-api-token-change-me':
        print("=" * 60)
        print("WARNING: Using default API token!")
        print("Change API_TOKEN environment variable in production!")
        print("=" * 60)
