# Project-Safehouse
A Project Zomboid dedicated server web manager

## Overview

Project Safehouse is a Flask-based web application for managing Project Zomboid dedicated servers. It runs inside a SteamCMD Docker container with multiple services managed by supervisord.

## Architecture

- **Flask Web Application**: Web interface for server management and monitoring
- **Server Monitor Service**: Python daemon that monitors SteamCMD game server deployment
- **PostgreSQL Database**: Persistent data storage
- **Redis Cache**: Caching layer for real-time server status
- **Supervisord**: Process manager running multiple daemons in parallel

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
http://localhost:5000
```

## Services

### Main Application (app)
- Flask web application
- Server monitoring daemon
- Runs on port 5000
- Based on SteamCMD image

### Database (db)
- PostgreSQL 16
- Stores persistent data
- Automatic health checks

### Cache (cache)
- Redis 7
- Stores real-time server status
- Automatic health checks

## API Endpoints

- `GET /` - Main dashboard
- `GET /health` - System health check
- `GET /api/server/status` - Game server status

## Development

### Project Structure

```
.
├── app.py                  # Flask web application
├── server_monitor.py       # Game server monitoring service
├── templates/
│   └── index.html         # Dashboard template
├── requirements.txt        # Python dependencies
├── Dockerfile             # Container image definition
├── docker-compose.yml     # Multi-container setup
├── supervisord.conf       # Process manager configuration
└── .env.example           # Environment variables template
```

### Running Locally

For development without Docker:

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variables:
```bash
export DATABASE_HOST=localhost
export REDIS_HOST=localhost
```

3. Run the Flask app:
```bash
python app.py
```

## Monitoring

Supervisord manages two main processes:
- **flask_app**: Web application server
- **server_monitor**: Game server monitoring daemon

View logs:
```bash
docker-compose logs -f app
```

## Configuration

Environment variables can be set in `.env` or `docker-compose.yml`:

- `DATABASE_HOST`: PostgreSQL host (default: db)
- `DATABASE_NAME`: Database name (default: safehouse)
- `DATABASE_USER`: Database user (default: safehouse)
- `DATABASE_PASSWORD`: Database password (default: safehouse) - **Change in production!**
- `REDIS_HOST`: Redis host (default: cache)
- `REDIS_PORT`: Redis port (default: 6379)
- `STEAMCMD_PATH`: SteamCMD installation path
- `CHECK_INTERVAL`: Server check interval in seconds (default: 30)
- `FLASK_DEBUG`: Enable Flask debug mode (default: false) - **Keep false in production!**

**Security Note**: Always change default passwords in production environments. Use `.env` file or Docker secrets for sensitive configuration.

## License

MIT License - see LICENSE file for details
