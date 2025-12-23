# Project Safehouse 🏚️

A Project Zomboid dedicated server web manager with a modern web interface.

## Tech Stack

- **Backend**: Flask (Python) with MariaDB database
- **Frontend**: React (JavaScript)
- **Containerization**: Docker & Docker Compose

## Architecture

- **Database Container**: MariaDB for data persistence
- **Backend Container**: Flask REST API for server management
- **Frontend Container**: React web application for user interface

## Prerequisites

- Docker
- Docker Compose

## Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/GramThanos/Project-Safehouse.git
   cd Project-Safehouse
   ```

2. Copy the environment file:
   ```bash
   cp .env.example .env
   ```

3. Update the `.env` file with your desired configuration (optional).

4. Start the application:
   ```bash
   docker-compose up -d
   ```

5. Access the application:
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:5000
   - Database: localhost:3306

## Development

### Backend

The Flask backend is located in the `backend/` directory:
- Main application: `app.py`
- Database models and API routes included
- Connected to MariaDB database

### Frontend

The React frontend is located in the `frontend/` directory:
- Built with Create React App
- Communicates with backend API
- Modern UI for server management

## Environment Variables

Key environment variables (see `.env.example`):

- `DB_ROOT_PASSWORD`: MariaDB root password
- `DB_NAME`: Database name
- `DB_USER`: Database user
- `DB_PASSWORD`: Database password
- `FLASK_ENV`: Flask environment (development/production)
- `SECRET_KEY`: Flask secret key

## API Endpoints

- `GET /`: API information
- `GET /api/health`: Health check and database status
- `GET /api/servers`: List all servers

## License

See LICENSE file for details.
