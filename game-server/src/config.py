#!/usr/bin/env python3
# Game Server Configuration
import os

# Database Configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'mysql+pymysql://safehouse:safehouse@db/safehouse')
DATABASE_POOL_SIZE = int(os.getenv('DATABASE_POOL_SIZE', '64'))

# Cache Configuration
CACHE_HOST = os.getenv('CACHE_HOST', 'cache')
CACHE_PORT = int(os.getenv('CACHE_PORT', '6379'))
CACHE_MAX_CONNECTIONS = int(os.getenv('CACHE_MAX_CONNECTIONS', '64'))
CACHE_HEALTH_CHECK_INTERVAL = int(os.getenv('CACHE_HEALTH_CHECK_INTERVAL', '30'))

# Manager for API Configuration
MANAGER_API_PORT = int(os.getenv('MANAGER_API_PORT', '5000'))
MANAGER_API_HOST = os.getenv('MANAGER_API_HOST', '0.0.0.0')
MANAGER_API_TOKEN = os.getenv('MANAGER_API_TOKEN', '')
MANAGER_API_TOKEN = MANAGER_API_TOKEN if MANAGER_API_TOKEN else None

# Steam Configuration
STEAM_APP_ID = 380870
STEAM_APP_BETA = os.getenv('STEAM_APP_BETA', '') # 42.13.1
STEAM_APP_BETA = STEAM_APP_BETA if STEAM_APP_BETA else None
STEAM_INSTALL_DIR = os.getenv('STEAM_INSTALL_DIR', '/opt/steam-apps')

# Manager for Game Server Configuration
MANAGE_GAME_SERVERS_CHANNEL = os.getenv('MANAGE_GAME_SERVERS_CHANNEL', 'game_server_managers')

'''
# Events
EVENTS_CHANNEL = 'events_channel'

# Task Processing Configuration
PROCESS_INTERVAL = int(os.getenv('PROCESS_INTERVAL', '5'))  # seconds

# Monitoring Configuration (for manager.py)
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '30'))  # seconds
STEAMCMD_PATH = os.getenv('STEAMCMD_PATH', '/home/steam/steamcmd')
'''
