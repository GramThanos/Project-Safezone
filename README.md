# Project-Safehouse
A Project Zomboid dedicated server web manager with microservices architecture

## Overview

Project Safehouse is a modern web application for managing Project Zomboid dedicated servers. It uses a microservices architecture with separate containers for each service.

## Architecture

The application is split into 5 separate containers:

1. **SteamCMD Manager**: Monitors SteamCMD and game server status
2. **Backend API**: Flask REST API for server management
3. **Frontend**: React-based web interface
4. **Database**: MariaDB for persistent data storage
5. **Cache**: Redis for real-time status caching

## Features

- Real-time server status monitoring
- Health check endpoints
- Database and cache integration
- SteamCMD integration for game server management
- REST API for server status

## Prerequisites

- Docker
- Docker Compose

## Quick Start

1. Clone the repository:
```bash
git clone https://github.com/GramThanos/Project-Safehouse.git
cd Project-Safehouse
```

2. (Optional) Create and configure environment variables:
```bash
cp .env.example .env
# Edit .env with your preferred settings
```

3. Build and start the services:
```bash
docker-compose up -d
```

4. Access the web interface:
```
http://localhost:3000
```

5. Access the API directly:
```
http://localhost:5000
```

## Services

### SteamCMD Manager (steamcmd-manager)
- Game server monitoring daemon
- Runs SteamCMD for server management
- Based on SteamCMD image
- No supervisord needed (single process)

### Backend API (backend)
- Flask REST API
- Serves API endpoints
- Runs on port 5000
- Gunicorn WSGI server

### Frontend (frontend)
- React-based web interface
- Nginx web server
- Runs on port 3000 (mapped to 80 in container)
- Responsive design

### Database (db)
- MariaDB 11
- Stores persistent data
- Automatic health checks

### Cache (cache)
- Redis 7
- Stores real-time server status
- Automatic health checks

## API Endpoints

Backend API (port 5000):
- `GET /` - API information
- `GET /health` - System health check
- `GET /api/server/status` - Game server status

## Development

### Project Structure

```
.
├── steamcmd-manager/       # SteamCMD and monitor service
│   ├── Dockerfile
│   ├── server_monitor.py
│   └── requirements.txt
├── backend/                # Flask API backend
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
├── frontend/               # React frontend
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   ├── public/
│   └── src/
│       ├── App.js
│       ├── index.js
│       └── index.css
├── docker-compose.yml      # Multi-container orchestration
└── .env.example           # Environment variables template
```

### Running Locally

For development without Docker:

#### Backend
```bash
cd backend
pip install -r requirements.txt
export DATABASE_HOST=localhost
export REDIS_HOST=localhost
python app.py
```

#### Frontend
```bash
cd frontend
npm install
npm start
```

## Monitoring

View logs for individual services:
```bash
docker-compose logs -f steamcmd-manager  # SteamCMD and monitor
docker-compose logs -f backend           # Flask API
docker-compose logs -f frontend          # React frontend
docker-compose logs -f db                # MariaDB
docker-compose logs -f cache             # Redis
```

## Configuration

Environment variables can be set in `.env` or `docker-compose.yml`:

- `DATABASE_HOST`: MariaDB host (default: db)
- `DATABASE_NAME`: Database name (default: safehouse)
- `DATABASE_USER`: Database user (default: safehouse)
- `DATABASE_PASSWORD`: Database password (default: safehouse) - **Change in production!**
- `DATABASE_ROOT_PASSWORD`: MariaDB root password - **Change in production!**
- `REDIS_HOST`: Redis host (default: cache)
- `REDIS_PORT`: Redis port (default: 6379)
- `STEAMCMD_PATH`: SteamCMD installation path
- `CHECK_INTERVAL`: Server check interval in seconds (default: 30)
- `REACT_APP_API_URL`: Backend API URL for frontend (default: http://localhost:5000)

**Security Note**: Always change default passwords in production environments. Use `.env` file or Docker secrets for sensitive configuration.

## License

MIT License - see LICENSE file for details
