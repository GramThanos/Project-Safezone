# Game Server Task Management System

This directory contains the task management system for the game server, which uses supervisord to run two services:

1. **API Service** - RESTful API for task management
2. **Task Processor** - Background service that processes tasks from the queue

## Architecture

The system uses supervisord to manage two Python services:
- `api_service.py` - Flask REST API running on port 5001
- `task_processor.py` - Background worker that processes tasks

## Task States

Tasks can be in one of three states:
- **pending** - Task is waiting to be processed
- **processing** - Task is currently being processed
- **completed** - Task has finished processing (success or failure)

## Task Data Structure

Each task has:
- `id` - Unique identifier
- `status` - Current status (pending, processing, completed)
- `data` - JSON object with task-specific information
- `created_at` - Timestamp when task was created
- `updated_at` - Timestamp when task was last updated

### Data Attribute Content by Status

- **pending**: Contains a wait message
- **processing**: Shows processing progress, started time, and current step
- **completed**: Contains result (success/failed), completion time, and any output/error

## API Endpoints

All API endpoints require authentication via Bearer token in the Authorization header.

### Authentication

Include the API token in the Authorization header:
```
Authorization: Bearer your-api-token-here
```

Or just the token:
```
Authorization: your-api-token-here
```

### Endpoints

#### List All Tasks
```
GET /api/tasks
```

Optional query parameters:
- `status` - Filter by status (pending, processing, completed)
- `limit` - Maximum number of results
- `offset` - Offset for pagination

Example:
```bash
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks?status=pending&limit=10
```

#### Get Specific Task
```
GET /api/tasks/:id
```

Example:
```bash
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/1
```

#### Create New Task
```
POST /api/tasks
Content-Type: application/json
```

Body (optional):
```json
{
  "message": "Custom task description",
  "any_other_field": "value"
}
```

Example:
```bash
curl -X POST \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  -H "Content-Type: application/json" \
  -d '{"message": "My custom task"}' \
  http://localhost:5001/api/tasks
```

#### Delete Task
```
DELETE /api/tasks/:id
```

Note: Cannot delete tasks that are currently processing.

Example:
```bash
curl -X DELETE \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/1
```

#### Clear All Tasks
```
DELETE /api/tasks
```

Deletes all pending and completed tasks (not processing tasks).

Example:
```bash
curl -X DELETE \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks
```

## Configuration

Environment variables:

### API Service
- `DATABASE_HOST` - MariaDB host (default: db)
- `DATABASE_NAME` - Database name (default: safehouse)
- `DATABASE_USER` - Database user (default: safehouse)
- `DATABASE_PASSWORD` - Database password (default: safehouse)
- `API_TOKEN` - Authentication token (default: safehouse-api-token-change-me)

### Task Processor
- `DATABASE_HOST` - MariaDB host (default: db)
- `DATABASE_NAME` - Database name (default: safehouse)
- `DATABASE_USER` - Database user (default: safehouse)
- `DATABASE_PASSWORD` - Database password (default: safehouse)
- `PROCESS_INTERVAL` - Seconds between checks for pending tasks (default: 5)

## Database Schema

```sql
CREATE TABLE tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    data JSON NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
);
```

## Running

The services are automatically started by supervisord when the container starts:

```bash
docker compose up -d game-server
```

View logs:
```bash
# All supervisord logs
docker compose logs -f game-server

# API service logs
docker exec game_server tail -f /var/log/supervisor/api_service.out.log

# Task processor logs
docker exec game_server tail -f /var/log/supervisor/task_processor.out.log
```

## Security

**Important:** Change the default API_TOKEN in production!

Set in `.env` file:
```
API_TOKEN=your-secure-random-token-here
```

## Task Processing Flow

1. Client creates a new task via POST /api/tasks
2. Task is stored in database with status='pending'
3. Task processor picks up the task (oldest first)
4. Task status changes to 'processing'
5. Processor updates task data with progress information
6. On completion, status changes to 'completed' with result data

## Example Task Lifecycle

### 1. Create Task
```bash
curl -X POST \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  -H "Content-Type: application/json" \
  -d '{"message": "Process game data"}' \
  http://localhost:5001/api/tasks
```

Response:
```json
{
  "id": 1,
  "status": "pending",
  "data": {
    "message": "Process game data"
  },
  "message": "Task created successfully"
}
```

### 2. Check Task Status (Pending)
```bash
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/1
```

Response:
```json
{
  "id": 1,
  "status": "pending",
  "data": {
    "message": "Process game data"
  },
  "created_at": "2024-01-01T12:00:00",
  "updated_at": "2024-01-01T12:00:00"
}
```

### 3. Check Task Status (Processing)
```bash
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/1
```

Response:
```json
{
  "id": 1,
  "status": "processing",
  "data": {
    "message": "Processing main work",
    "started_at": "2024-01-01T12:00:05",
    "progress": 50,
    "original_data": {
      "message": "Process game data"
    }
  },
  "created_at": "2024-01-01T12:00:00",
  "updated_at": "2024-01-01T12:00:08"
}
```

### 4. Check Task Status (Completed)
```bash
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/1
```

Response:
```json
{
  "id": 1,
  "status": "completed",
  "data": {
    "message": "Task completed successfully",
    "completed_at": "2024-01-01T12:00:10",
    "started_at": "2024-01-01T12:00:05",
    "result": "success",
    "original_data": {
      "message": "Process game data"
    },
    "processed_info": {
      "steps_completed": 4,
      "total_time_seconds": 5
    }
  },
  "created_at": "2024-01-01T12:00:00",
  "updated_at": "2024-01-01T12:00:10"
}
```
