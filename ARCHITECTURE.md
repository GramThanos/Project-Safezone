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

### React Frontend (frontend/)
- **Purpose**: Web user interface
- **Port**: 3000 (host) → 80 (container)
- **Server**: Nginx
- **Features**:
  - Beautiful responsive dashboard
  - Real-time status display
  - Automatic refresh every 10 seconds
  - API integration with backend
  - Modern React 18 architecture
- **Build**: Multi-stage Docker build (Node.js build → Nginx serve)

### Flask Backend API (backend/)
- **Purpose**: REST API backend
- **Port**: 5000
- **Server**: Gunicorn
- **Features**:
  - RESTful API endpoints
  - Health monitoring
  - CORS enabled for frontend
  - Database integration
  - Redis caching
- **Connections**:
  - MariaDB for persistent data
  - Redis for caching and real-time updates

### Game Server (game-server/)
- **Purpose**: Game server management with task processing system
- **Base Image**: cm2network/steamcmd:latest
- **Process Manager**: Supervisord (manages 2 services)
- **Services**:
  1. **Task Management API** (port 5001):
     - RESTful API for task management
     - Token-based authentication
     - CRUD operations for tasks
     - Task filtering and pagination
  2. **Task Processor**:
     - Background worker processing tasks
     - Automatic status updates
     - Progress tracking
- **Features**:
  - Task queue with database persistence
  - Three task states: pending, processing, completed
  - JSON data storage for each task
  - Real-time progress updates
  - Protected API endpoints
  - Configurable processing interval
- **Database**: Uses MariaDB for task persistence
- **API Endpoints**:
  - `GET /api/tasks` - List all tasks (with filtering)
  - `GET /api/tasks/:id` - Get specific task
  - `POST /api/tasks` - Create new task
  - `DELETE /api/tasks/:id` - Delete task
  - `DELETE /api/tasks` - Clear all tasks

### MariaDB Database
- **Image**: mariadb:11
- **Purpose**: Persistent data storage
- **Features**:
  - Volume-backed persistence
  - Health checks
  - Automatic initialization
  - MySQL-compatible

### Redis Cache
- **Image**: redis:7-alpine
- **Purpose**: Fast in-memory cache
- **Features**:
  - Real-time status storage
  - Health checks
  - Pub/sub capabilities

## Network Architecture

All services communicate through a private Docker bridge network (`safehouse_network`):

- **frontend → backend**: HTTP requests to API on port 5000
- **backend → db**: MariaDB connection on port 3306
- **backend → cache**: Redis connection on port 6379
- **steamcmd-manager → cache**: Redis connection on port 6379
- **host → frontend**: HTTP access on port 3000
- **host → backend**: HTTP access on port 5000 (direct API access)

## Data Flow

1. **Monitoring Loop**:
   ```
   SteamCMD Manager → Check Process → Update Redis → Backend reads cache → Frontend displays
   ```

2. **Web Request**:
   ```
   Browser → Frontend (React) → Backend API → Query Redis/MariaDB → Return JSON → Frontend renders
   ```

3. **Health Check**:
   ```
   Frontend → /health endpoint → Backend checks DB & Redis → Return status JSON → Display in UI
   ```

## Security Features

- ✅ No hardcoded passwords (environment variables)
- ✅ XSS prevention with React's built-in escaping
- ✅ Non-root user execution (steam user in steamcmd-manager)
- ✅ Specific exception handling
- ✅ CORS properly configured
- ✅ Separate frontend and backend for security isolation
- ✅ Nginx for secure static file serving

## Deployment

Simple one-command deployment:
```bash
docker compose up -d
```

## Container Isolation Benefits

- **SteamCMD Manager**: Isolated environment for game server operations
- **Backend**: Focused API service, easier to scale
- **Frontend**: Static files served efficiently by Nginx
- **Database**: Standard MariaDB container with persistent storage
- **Cache**: Lightweight Redis container for fast caching

Services start automatically with proper dependencies and health checks.
