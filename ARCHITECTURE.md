# Project Safehouse Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Docker Compose                          │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │              Main Application Container                   │ │
│  │           (Based on SteamCMD Image)                       │ │
│  │                                                           │ │
│  │  ┌─────────────────────────────────────────────────────┐ │ │
│  │  │              Supervisord                            │ │ │
│  │  │         (Process Manager)                           │ │ │
│  │  │                                                     │ │ │
│  │  │  ┌──────────────────┐   ┌──────────────────────┐  │ │ │
│  │  │  │  Flask Web App   │   │  Server Monitor      │  │ │ │
│  │  │  │                  │   │                      │  │ │ │
│  │  │  │  - Dashboard     │   │  - Process Check     │  │ │ │
│  │  │  │  - Health API    │   │  - SteamCMD Check    │  │ │ │
│  │  │  │  - Status API    │   │  - Status Updates    │  │ │ │
│  │  │  │  Port: 5000      │   │  Interval: 30s       │  │ │ │
│  │  │  └────────┬─────────┘   └──────────┬───────────┘  │ │ │
│  │  │           │                        │              │ │ │
│  │  └───────────┼────────────────────────┼──────────────┘ │ │
│  │              │                        │                │ │
│  └──────────────┼────────────────────────┼────────────────┘ │
│                 │                        │                  │
│                 ├────────────────────────┼──────────────┐   │
│                 │                        │              │   │
│  ┌──────────────▼──────────┐  ┌──────────▼─────────┐  │   │
│  │  PostgreSQL Database    │  │  Redis Cache       │  │   │
│  │                         │  │                    │  │   │
│  │  - Version: 16          │  │  - Version: 7      │  │   │
│  │  - Persistent Storage   │  │  - Status Cache    │  │   │
│  │  - Health Checks        │  │  - Real-time Data  │  │   │
│  └─────────────────────────┘  └────────────────────┘  │   │
│                                                        │   │
└────────────────────────────────────────────────────────┴───┘
                                                         │
                                                         │
                                                  ┌──────▼─────┐
                                                  │   Volumes  │
                                                  │            │
                                                  │ - postgres │
                                                  │ - steamcmd │
                                                  │ - gamedata │
                                                  └────────────┘
```

## Component Details

### Flask Web Application (app.py)
- **Purpose**: Web interface for server management
- **Port**: 5000
- **Features**:
  - Beautiful responsive dashboard
  - Real-time status display
  - Health monitoring endpoints
  - REST API for server status
- **Connections**:
  - PostgreSQL for persistent data
  - Redis for caching and real-time updates

### Server Monitor Service (server_monitor.py)
- **Purpose**: Continuous monitoring of game server
- **Check Interval**: 30 seconds (configurable)
- **Features**:
  - Process monitoring (checks if ProjectZomboid is running)
  - SteamCMD installation verification
  - Status updates to Redis cache
  - Timestamp tracking
- **Statuses**:
  - `not_installed`: SteamCMD not found
  - `running`: Game server process active
  - `stopped`: SteamCMD installed but server not running

### Supervisord
- **Purpose**: Multi-process management
- **Configuration**: `/etc/supervisor/conf.d/supervisord.conf`
- **Features**:
  - Auto-start both services
  - Auto-restart on failure
  - Log management
  - Runs as non-root user (steam)

### PostgreSQL Database
- **Image**: postgres:16-alpine
- **Purpose**: Persistent data storage
- **Features**:
  - Volume-backed persistence
  - Health checks
  - Automatic initialization

### Redis Cache
- **Image**: redis:7-alpine
- **Purpose**: Fast in-memory cache
- **Features**:
  - Real-time status storage
  - Health checks
  - Pub/sub capabilities (future use)

## Network Architecture

All services communicate through a private Docker bridge network (`safehouse_network`):

- **app → db**: PostgreSQL connection on port 5432
- **app → cache**: Redis connection on port 6379
- **host → app**: HTTP access on port 5000

## Data Flow

1. **Monitoring Loop**:
   ```
   Server Monitor → Check Process → Update Redis → Flask reads cache
   ```

2. **Web Request**:
   ```
   Browser → Flask → Query Redis/PostgreSQL → Return JSON → Render UI
   ```

3. **Health Check**:
   ```
   /health endpoint → Check DB → Check Redis → Return status JSON
   ```

## Security Features

- ✅ No hardcoded passwords (environment variables)
- ✅ XSS prevention with HTML escaping
- ✅ Non-root user execution (steam user)
- ✅ Specific exception handling
- ✅ Debug mode disabled in production
- ✅ CodeQL security scan passed

## Deployment

Simple one-command deployment:
```bash
docker-compose up -d
```

Services start automatically with proper dependencies and health checks.
