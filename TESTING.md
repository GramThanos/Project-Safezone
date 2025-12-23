# Testing Guide for Reorganized Container Architecture

## Overview
This document provides testing instructions for the reorganized microservices architecture.

## Structure Changes
The application has been reorganized from a monolithic container to 5 separate containers:

1. **steamcmd-manager**: SteamCMD and server monitoring (single process, no supervisord)
2. **backend**: Flask REST API backend
3. **frontend**: React web application served by Nginx
4. **db**: MariaDB database (replaced PostgreSQL)
5. **cache**: Redis cache

## Pre-requisites
- Docker and Docker Compose v2
- Network access to PyPI (for building images)
- Ports 3000 and 5000 available on host

## Building the Containers

Due to potential SSL certificate issues in build environments, builds may fail. This is an infrastructure issue, not a code issue.

If you have a working Docker environment with proper SSL certificates:

```bash
# Build all containers
docker compose build

# Or build individually
docker compose build steamcmd-manager
docker compose build backend
docker compose build frontend
```

## Starting the Services

```bash
# Start all services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f
```

## Testing Endpoints

### Backend API (Port 5000)
```bash
# API root
curl http://localhost:5000/

# Health check
curl http://localhost:5000/health

# Server status
curl http://localhost:5000/api/server/status
```

Expected responses:
- `/`: JSON with API information and endpoints
- `/health`: JSON with status of database, cache, and application
- `/api/server/status`: JSON with game server status from Redis

### Frontend (Port 3000)
Open browser to: http://localhost:3000

Expected behavior:
- Dashboard displays with gradient purple background
- Two cards: "System Status" and "Game Server"
- Status indicators with color coding
- Auto-refresh every 10 seconds

## Validation Checklist

- [x] Python syntax validation for backend/app.py
- [x] Python syntax validation for steamcmd-manager/server_monitor.py
- [x] docker-compose.yml syntax validation
- [x] React application structure created
- [x] Dockerfile for each service created
- [x] Documentation updated (README.md, ARCHITECTURE.md)
- [ ] Docker images build successfully (requires network access)
- [ ] Services start without errors
- [ ] Backend API endpoints respond correctly
- [ ] Frontend displays correctly in browser
- [ ] MariaDB connection works
- [ ] Redis connection works
- [ ] SteamCMD manager updates Redis

## Known Issues

### Build Environment SSL Certificates
The current build environment has SSL certificate verification issues when connecting to PyPI. This prevents pip from downloading packages during the Docker build process. This is not a code issue and will work in environments with proper SSL certificates configured.

### Workarounds for Testing
1. Build in an environment with proper SSL certificates
2. Use pre-built images
3. Add `--build-arg PIP_TRUSTED_HOST=pypi.org` to Docker build commands

## Manual Testing Steps

### 1. Verify File Organization
```bash
ls -la steamcmd-manager/
ls -la backend/
ls -la frontend/
```

### 2. Check Docker Compose Configuration
```bash
docker compose config
```

### 3. Test Backend Imports
```bash
cd backend
python3 -c "import mysql.connector; import redis; import flask; import flask_cors; print('All imports successful')"
```

### 4. Test Frontend Package Structure
```bash
cd frontend
cat package.json  # Verify React dependencies
```

## Architecture Validation

The new architecture properly separates concerns:

1. **SteamCMD Manager**:
   - Runs as single Python process (no supervisord)
   - Only needs Redis client library
   - Uses SteamCMD base image

2. **Backend API**:
   - Pure Python Flask application
   - MariaDB connector instead of PostgreSQL
   - CORS enabled for frontend communication
   - Runs on Gunicorn

3. **Frontend**:
   - React 18 application
   - Multi-stage Docker build (Node build → Nginx serve)
   - Communicates with backend via API calls
   - Served on port 3000

4. **Database**:
   - MariaDB 11 (MySQL-compatible)
   - Persistent volume for data
   - Health checks configured

5. **Cache**:
   - Redis 7
   - In-memory cache for real-time status
   - Health checks configured

## Security Considerations

- ✅ No hardcoded credentials
- ✅ Environment variable configuration
- ✅ Non-root user in SteamCMD container
- ✅ CORS properly configured
- ✅ Separate frontend/backend security isolation
- ✅ Nginx for efficient static file serving

## Migration Notes

### Database Migration
The application now uses MariaDB instead of PostgreSQL. Any existing data in PostgreSQL will need to be migrated:
1. Export data from PostgreSQL
2. Convert to MariaDB-compatible format
3. Import into MariaDB container

### API Changes
The backend now serves only API endpoints. The root endpoint (/) returns API information instead of serving the HTML dashboard. The dashboard is now served by the frontend container on port 3000.

## Success Criteria

✅ All Python files have valid syntax
✅ Docker Compose configuration is valid
✅ Directory structure properly organized
✅ Dockerfiles created for each service
✅ Documentation updated to reflect new architecture
✅ Frontend React application structure complete
✅ Backend API properly configured with CORS
✅ MariaDB configuration replaces PostgreSQL
⏳ Docker images build successfully (blocked by SSL issue)
⏳ Integration testing (requires running containers)
