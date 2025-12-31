# Backend API Documentation

## Overview

The Project Safezone backend is a Flask-based REST API with JWT authentication, user management, player profiles, and server monitoring capabilities.

## Architecture

The backend is organized into multiple modules for clean code structure:

```
backend/
├── app.py                 # Main Flask application
├── init_db.py            # Database initialization script
├── requirements.txt      # Python dependencies
└── src/
    ├── database.py       # Database connection management
    ├── models/           # Data models
    │   ├── user.py       # User model
    │   ├── player.py     # Player (character) model
    │   └── server.py     # Server model
    ├── routes/           # API route blueprints
    │   ├── auth.py       # Authentication routes
    │   ├── players.py    # Player management routes
    │   ├── servers.py    # Server status routes
    │   └── admin.py      # Admin panel routes
    └── middleware/       # Middleware
        └── auth.py       # JWT authentication middleware
```

## Features

- **User Authentication**: JWT-based authentication with sign in/sign up
- **User Roles**: Support for banned, player, moderator, and admin roles
- **Player Management**: Users can create and manage multiple game characters
- **Server Monitoring**: Real-time server status and statistics
- **Admin Panel**: Role-based access for managing users, servers, and tasks

## API Endpoints

### Authentication (`/api/auth`)

- `POST /api/auth/signin` - User sign in
  ```json
  {
    "username": "user",
    "password": "password"
  }
  ```
  
- `POST /api/auth/signup` - User registration
  ```json
  {
    "username": "user",
    "email": "user@example.com",
    "password": "password"
  }
  ```

- `GET /api/auth/me` - Get current user info (requires authentication)

### Players (`/api/players`)

All player endpoints require authentication.

- `GET /api/players` - Get all players for current user
- `GET /api/players/:id` - Get specific player
- `POST /api/players` - Create new player
  ```json
  {
    "name": "Character Name",
    "description": "Character description",
    "avatar": "https://example.com/avatar.png"
  }
  ```
- `PUT /api/players/:id` - Update player
- `DELETE /api/players/:id` - Delete player

### Servers (`/api/servers`)

Public endpoints for server information.

- `GET /api/servers` - Get all servers
- `GET /api/servers/:id` - Get specific server
- `GET /api/servers/status` - Get all servers with real-time status

### Admin Panel (`/api/admin`)

Endpoints require moderator or admin role.

#### Users (Admin only)
- `GET /api/admin/users` - Get all users
- `PUT /api/admin/users/:id` - Update user role
  ```json
  {
    "role": "player|moderator|admin|banned"
  }
  ```

#### Servers (Moderator/Admin)
- `GET /api/admin/servers` - Get all servers
- `POST /api/admin/servers` - Create server (admin only)
- `PUT /api/admin/servers/:id` - Update server (admin only)
- `DELETE /api/admin/servers/:id` - Delete server (admin only)

#### Tasks (Moderator/Admin)
- `GET /api/admin/tasks` - Get all tasks from game server
- `POST /api/admin/tasks` - Create new task

## Setup

### Environment Variables

```bash
DATABASE_HOST=db                    # Database host
DATABASE_NAME=safezone              # Database name
DATABASE_USER=safezone              # Database user
DATABASE_PASSWORD=safezone          # Database password
REDIS_HOST=cache                    # Redis host
REDIS_PORT=6379                     # Redis port
SECRET_KEY=your-secret-key          # JWT secret key
TOKEN_EXPIRY_HOURS=24              # Token expiration time
GAME_SERVER_API_URL=http://game-server:5001  # Game server API URL
API_TOKEN=your-api-token            # Game server API token
```

### Database Initialization

Run the initialization script to create tables and default admin user:

```bash
cd backend
python -m init_db
```

Default admin credentials:
- Username: `admin`
- Password: `admin`

**⚠️ IMPORTANT: Change the admin password in production!**

### Running Locally

```bash
# Install dependencies
cd backend
pip install -r requirements.txt

# Set environment variables
export DATABASE_HOST=localhost
export REDIS_HOST=localhost

# Initialize database
python -m init_db

# Run the application
python app.py
```

## Authentication

The API uses JWT (JSON Web Tokens) for authentication. Include the token in the Authorization header:

```
Authorization: Bearer <token>
```

## User Roles

- **banned**: Cannot access the system
- **player**: Can manage their own players
- **moderator**: Can access admin panel, manage servers and tasks
- **admin**: Full access including user management

## Database Models

### User
- id (int, primary key)
- username (string, unique)
- email (string, unique)
- password_hash (string)
- role (string: banned/player/moderator/admin)
- created_at (timestamp)

### Player
- id (int, primary key)
- user_id (int, foreign key)
- name (string)
- description (text)
- avatar (string)
- stats (json)
- created_at (timestamp)
- updated_at (timestamp)

### Server
- id (int, primary key)
- name (string, unique)
- host (string)
- port (int)
- rcon_port (int)
- rcon_password (string)
- status (string)
- active_players (int)
- max_players (int)
- game_day (int)
- created_at (timestamp)
- updated_at (timestamp)

## Security

- Passwords are hashed using Werkzeug's security functions
- JWT tokens expire after 24 hours (configurable)
- Role-based access control for sensitive endpoints
- CORS enabled for frontend communication
