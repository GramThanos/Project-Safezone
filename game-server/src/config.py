#!/usr/bin/env python3
# Game Server Configuration
import os


# Database Configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'mysql+pymysql://safehouse:safehouse@db/safehouse')

# Cache Configuration
CACHE_HOST = os.getenv('CACHE_HOST', 'cache')
CACHE_PORT = int(os.getenv('CACHE_PORT', '6379'))

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
MANAGER_GAME_SERVERS = int(os.getenv('MANAGER_GAME_SERVERS', '1'))
MANAGER_GAME_COMMANDS_CHANNEL = os.getenv('MANAGER_GAME_COMMANDS_CHANNEL', 'game_commands')

'''
# Events
EVENTS_CHANNEL = 'events_channel'

# Task Processing Configuration
PROCESS_INTERVAL = int(os.getenv('PROCESS_INTERVAL', '5'))  # seconds

# Monitoring Configuration (for manager.py)
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '30'))  # seconds
STEAMCMD_PATH = os.getenv('STEAMCMD_PATH', '/home/steam/steamcmd')
'''
