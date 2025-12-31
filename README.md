# Project-Safezone
A Project Zomboid dedicated server web manager with microservices architecture

## Overview

Project Safezone is a modern web application for managing Project Zomboid dedicated servers. It features user authentication, player management, admin panel, and real-time server monitoring using a microservices architecture with separate containers for each service.

## Architecture

The application is split into 5 separate containers:

1. **Game Server Manager**: Monitors SteamCMD and game server status with task management
2. **Backend API**: Flask REST API with JWT authentication and role-based access control
3. **Frontend**: React-based web interface with modern dark theme
4. **Database**: MariaDB for persistent data storage (users, players, servers, tasks)
5. **Cache**: Redis for real-time status caching

## Features

### User Management
- **User Authentication**: JWT-based sign in/sign up system
- **User Roles**: Support for banned, player, moderator, and admin roles
- **Player Profiles**: Users can create and manage multiple game characters
- **Profile Management**: View user information and account details

### Server Management
- **Real-time Monitoring**: Live server status, active players, and game day tracking
- **Server Administration**: Create, update, and delete game servers (admin only)
- **RCON Integration**: Communicate with Project Zomboid servers via RCON
- **Task Management**: Moderators can create and monitor server tasks

### Admin Panel
- **User Management**: Admins can view all users and manage roles
- **Server Management**: Moderators/admins can manage game servers
- **Task Monitoring**: View and create tasks for the game server manager
- **Role-Based Access**: Different levels of access based on user role

### Technical Features
- Multi-file backend structure with blueprints for clean code organization
- React component-based frontend with routing and protected routes
- Context API for global state management
- RESTful API with comprehensive endpoints
- Database models for users, players, and servers
- Health check endpoints for monitoring

## Prerequisites

- Docker
- Docker Compose

## Quick Start

1. Clone the repository:
```bash
git clone https://github.com/GramThanos/Project-Safezone.git
cd Project-Safezone
```

2. (Optional) Create and configure environment variables:
```bash
cp .env.example .env
# Edit .env with your preferred settings
# IMPORTANT: Change SECRET_KEY and passwords in production!
```

3. Build and start the services:
```bash
docker compose up -d
```

Note: Use `docker compose` (v2) not `docker-compose` (v1)

4. Access the web interface:
```
http://localhost:8080
```

5. Sign in with default admin credentials:
```
Username: admin
Password: admin
```
**⚠️ IMPORTANT: Change the admin password after first login!**

6. Access the API directly:
```
http://localhost:5000
```

## First-Time Setup

After starting the services for the first time:

1. Wait for all services to start (check with `docker compose logs -f`)
2. Initialize the database (automatic on first run)
3. Access the frontend at `http://localhost:8080`
4. Sign in with the default admin account (username: `admin`, password: `admin`)
5. **IMPORTANT**: Change the default admin password
6. Create additional user accounts as needed
7. Configure game servers in the admin panel

## User Roles

The application supports four user roles:

- **banned**: User cannot access the system
- **player**: Can sign in, manage own players, view servers
- **moderator**: Player access + admin panel for servers and tasks
- **admin**: Full access including user management

## Services

### Game Server (game-server)
- Task management system with supervisord
- Runs 2 services:
  1. **Task Management API** - RESTful API on port 5001
  2. **Task Processor** - Background worker for task processing
- Based on SteamCMD image
- Token-authenticated API endpoints
- Database-backed task persistence
- Supports task states: pending, processing, completed

### Backend API (backend)
- Flask REST API with JWT authentication
- Multi-file structure with blueprints
- User, Player, and Server management
- Role-based access control
- Runs on port 5000 (internal)
- Gunicorn WSGI server

### Frontend (frontend)
- React-based web interface with React Router
- Modern dark theme with Bootstrap 5
- Component-based architecture
- Context API for state management
- Responsive design
- Runs on port 8080 (mapped to 80 in container)
- Nginx web server

### Database (db)
- MariaDB 11
- Stores persistent data (including tasks)
- Automatic health checks

### Cache (cache)
- Redis 7
- Stores real-time server status
- Automatic health checks

## API Endpoints

For detailed API documentation, see [backend/API.md](backend/API.md)

### Backend API (port 5000 - internal):
- `GET /` - API information
- `GET /health` - System health check
- `POST /api/auth/signin` - User sign in
- `POST /api/auth/signup` - User registration
- `GET /api/auth/me` - Get current user (requires auth)
- `GET /api/players` - Get user's players (requires auth)
- `POST /api/players` - Create player (requires auth)
- `PUT /api/players/:id` - Update player (requires auth)
- `DELETE /api/players/:id` - Delete player (requires auth)
- `GET /api/servers` - Get all servers (public)
- `GET /api/servers/status` - Get server status (public)
- `GET /api/admin/users` - Get all users (admin only)
- `PUT /api/admin/users/:id` - Update user role (admin only)
- `GET /api/admin/servers` - Get servers (moderator/admin)
- `POST /api/admin/servers` - Create server (admin only)
- `GET /api/admin/tasks` - Get tasks (moderator/admin)
- `POST /api/admin/tasks` - Create task (moderator/admin)

### Game Server Task API (port 5001):
All endpoints require Authorization header with Bearer token.

- `GET /api/tasks` - List all tasks (supports filtering by status, limit, offset)
- `GET /api/tasks/:id` - Get specific task information
- `POST /api/tasks` - Create new task
- `DELETE /api/tasks/:id` - Delete a pending or completed task
- `DELETE /api/tasks` - Clear all pending and completed tasks

See [game-server/README.md](game-server/README.md) for detailed API documentation and examples.

## Development

### Project Structure

```
.
├── game-server/            # Game server manager with task API
│   ├── Dockerfile
│   ├── manager.py
│   └── src/
│       ├── manager_api.py
│       ├── manager_tasks.py
│       ├── models.py
│       └── ...
├── backend/                # Flask API backend
│   ├── Dockerfile
│   ├── app.py
│   ├── init_db.py
│   ├── requirements.txt
│   ├── API.md
│   └── src/
│       ├── database.py
│       ├── models/
│       │   ├── user.py
│       │   ├── player.py
│       │   └── server.py
│       ├── routes/
│       │   ├── auth.py
│       │   ├── players.py
│       │   ├── servers.py
│       │   └── admin.py
│       └── middleware/
│           └── auth.py
├── frontend/               # React frontend
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   ├── README.md
│   ├── public/
│   │   ├── index.html
│   │   └── assets/
│   └── src/
│       ├── App.js
│       ├── index.js
│       ├── components/
│       │   ├── Navbar.js
│       │   ├── Footer.js
│       │   └── ProtectedRoute.js
│       ├── pages/
│       │   ├── Home.js
│       │   ├── SignIn.js
│       │   ├── Servers.js
│       │   ├── Players.js
│       │   ├── Profile.js
│       │   └── Admin.js
│       ├── context/
│       │   └── AuthContext.js
│       └── services/
│           └── api.js
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
export SECRET_KEY=dev-secret-key

# Initialize database
python -m init_db

# Run the app
python app.py
```

#### Frontend
```bash
cd frontend
npm install
npm start
```

The frontend will be available at `http://localhost:3000` and will proxy API requests to the backend at `http://localhost:5000`.

## Monitoring

View logs for individual services:
```bash
docker compose logs -f game-server         # Game server with task management
docker compose logs -f backend             # Flask API
docker compose logs -f frontend            # React frontend
docker compose logs -f db                  # MariaDB
docker compose logs -f cache               # Redis
```

View specific supervisord service logs in game-server:
```bash
# API service logs
docker exec game_server tail -f /var/log/supervisor/api_service.out.log

# Task processor logs
docker exec game_server tail -f /var/log/supervisor/task_processor.out.log
```

## Configuration

Environment variables can be set in `.env` or `docker-compose.yml`:

- `DATABASE_HOST`: MariaDB host (default: db)
- `DATABASE_NAME`: Database name (default: safezone)
- `DATABASE_USER`: Database user (default: safezone)
- `DATABASE_PASSWORD`: Database password (default: safezone) - **Change in production!**
- `DATABASE_ROOT_PASSWORD`: MariaDB root password - **Change in production!**
- `REDIS_HOST`: Redis host (default: cache)
- `REDIS_PORT`: Redis port (default: 6379)
- `STEAMCMD_PATH`: SteamCMD installation path
- `CHECK_INTERVAL`: Server check interval in seconds (default: 30)
- `API_TOKEN`: Game server task API authentication token - **Change in production!**
- `PROCESS_INTERVAL`: Task processing check interval in seconds (default: 5)
- `REACT_APP_API_URL`: Backend API URL for frontend (default: http://localhost:5000)
- `SECRET_KEY`: JWT secret key for token generation - **Change in production!**
- `TOKEN_EXPIRY_HOURS`: JWT token expiration time in hours (default: 24)

**Security Note**: Always change default passwords and secret keys in production environments. Use `.env` file or Docker secrets for sensitive configuration.

## License

MIT License - see LICENSE file for details
