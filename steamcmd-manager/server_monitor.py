"""
Game Server Monitor Service
Monitors the SteamCMD game server deployment and status
"""
import os
import time
import subprocess
import redis
from datetime import datetime

# Configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'cache')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '30'))  # seconds
STEAMCMD_PATH = os.getenv('STEAMCMD_PATH', '/home/steam/steamcmd')


def get_redis_connection():
    """Get Redis connection"""
    try:
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True
        )
        return r
    except Exception as e:
        print(f"Redis connection error: {e}")
        return None


def check_game_server_process():
    """Check if game server process is running"""
    try:
        # Check for Project Zomboid server process
        result = subprocess.run(
            ['pgrep', '-f', 'ProjectZomboid'],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Error checking game server process: {e}")
        return False


def check_steamcmd_installation():
    """Check if SteamCMD is properly installed"""
    try:
        return os.path.exists(STEAMCMD_PATH) and os.path.isdir(STEAMCMD_PATH)
    except Exception as e:
        print(f"Error checking SteamCMD installation: {e}")
        return False


def monitor_game_server():
    """Main monitoring loop"""
    print("Starting Game Server Monitor Service...")
    
    r = get_redis_connection()
    if not r:
        print("Failed to connect to Redis. Exiting.")
        return
    
    while True:
        try:
            # Check SteamCMD installation
            steamcmd_installed = check_steamcmd_installation()
            
            # Check if game server is running
            server_running = check_game_server_process()
            
            # Determine overall status
            if not steamcmd_installed:
                status = 'not_installed'
            elif server_running:
                status = 'running'
            else:
                status = 'stopped'
            
            # Update Redis cache
            timestamp = datetime.now().isoformat()
            r.set('game_server_status', status)
            r.set('game_server_last_update', timestamp)
            r.set('steamcmd_installed', str(steamcmd_installed))
            
            print(f"[{timestamp}] Status: {status}, SteamCMD: {steamcmd_installed}, Running: {server_running}")
            
        except Exception as e:
            print(f"Error in monitoring loop: {e}")
        
        # Wait before next check
        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    monitor_game_server()
