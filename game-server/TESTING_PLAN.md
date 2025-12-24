# Testing Plan for Game Server Task Management System

## Overview
This document outlines the testing approach for the newly implemented task management system in the game-server container.

## What Was Implemented

### 1. Supervisord Integration
- Updated Dockerfile to install supervisor package
- Created `/game-server/supervisord.conf` configuration
- Two services managed by supervisord:
  - `api_service` - RESTful API on port 5001
  - `task_processor` - Background task processor

### 2. Task Management API Service (`api_service.py`)
- Flask-based RESTful API
- Token-based authentication using Bearer tokens
- Database initialization on startup
- Endpoints:
  - `GET /` - API information
  - `GET /api/tasks` - List all tasks with filtering
  - `GET /api/tasks/:id` - Get specific task
  - `POST /api/tasks` - Create new task
  - `DELETE /api/tasks/:id` - Delete task (pending or completed only)
  - `DELETE /api/tasks` - Clear all tasks (pending and completed only)

### 3. Task Processor Service (`task_processor.py`)
- Background worker that processes tasks from database
- Picks up pending tasks in FIFO order (oldest first)
- Updates task status through lifecycle:
  - pending → processing → completed
- Simulates work with progress updates (25%, 50%, 75%, 100%)
- Configurable processing interval (default 5 seconds)

### 4. Database Schema
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

### 5. Task Data Structure by Status

**Pending:**
```json
{
  "message": "Task is waiting to be processed"
}
```

**Processing:**
```json
{
  "message": "Processing main work",
  "started_at": "2024-01-01T12:00:05Z",
  "progress": 50,
  "original_data": { ... }
}
```

**Completed (Success):**
```json
{
  "message": "Task completed successfully",
  "completed_at": "2024-01-01T12:00:10Z",
  "started_at": "2024-01-01T12:00:05Z",
  "result": "success",
  "original_data": { ... },
  "processed_info": {
    "steps_completed": 4,
    "total_time_seconds": 5
  }
}
```

**Completed (Failed):**
```json
{
  "message": "Task failed during processing",
  "completed_at": "2024-01-01T12:00:10Z",
  "started_at": "2024-01-01T12:00:05Z",
  "result": "failed",
  "error": "Error message here",
  "original_data": { ... }
}
```

## Testing Prerequisites

### Environment Setup
1. Docker and Docker Compose v2 installed
2. Ports 5001 available on host
3. MariaDB container running and accessible
4. Valid environment variables set (especially API_TOKEN)

### Known Limitations
- SSL certificate issues in build environment prevent Docker image building
- This is an infrastructure issue, not a code issue
- Testing will need to be done in an environment with proper SSL certificates

## Manual Testing Steps

### Step 1: Verify File Structure
```bash
cd /home/runner/work/Project-Safehouse/Project-Safehouse/game-server
ls -la

# Should show:
# - Dockerfile (updated)
# - supervisord.conf (new)
# - api_service.py (new)
# - task_processor.py (new)
# - manager.py (existing)
# - requirements.txt (updated)
# - README.md (new)
# - test_api.py (new)
```

### Step 2: Verify Python Syntax
```bash
cd /home/runner/work/Project-Safehouse/Project-Safehouse/game-server
python3 -m py_compile api_service.py
python3 -m py_compile task_processor.py
python3 -m py_compile test_api.py
```

### Step 3: Verify Docker Compose Configuration
```bash
cd /home/runner/work/Project-Safehouse/Project-Safehouse
docker compose config
```

### Step 4: Build and Start Services (Requires SSL Certs)
```bash
# Build the game-server container
docker compose build game-server

# Start all services
docker compose up -d

# Check container status
docker compose ps

# View logs
docker compose logs -f game-server
```

### Step 5: Verify Supervisord is Managing Services
```bash
# Check supervisord status
docker exec game_server supervisorctl status

# Expected output:
# api_service                      RUNNING   pid X, uptime X:XX:XX
# task_processor                   RUNNING   pid X, uptime X:XX:XX
```

### Step 6: Verify Database Table Creation
```bash
# Access MariaDB
docker exec -it db mysql -u safehouse -p safehouse

# Check tasks table exists
SHOW TABLES;
DESCRIBE tasks;

# Should show the tasks table with columns:
# - id
# - status
# - data
# - created_at
# - updated_at
```

### Step 7: Test API Endpoints

#### Test Authentication
```bash
# Should fail without token
curl http://localhost:5001/api/tasks
# Expected: 401 Unauthorized

# Should succeed with token
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks
# Expected: 200 OK with task list
```

#### Test Create Task
```bash
curl -X POST \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  -H "Content-Type: application/json" \
  -d '{"message": "Test task"}' \
  http://localhost:5001/api/tasks
  
# Expected: 201 Created with task ID
```

#### Test Get Task
```bash
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/1
  
# Expected: 200 OK with task details
```

#### Test Filter Tasks
```bash
# Filter by status
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  "http://localhost:5001/api/tasks?status=pending"

curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  "http://localhost:5001/api/tasks?status=completed"
  
# Expected: 200 OK with filtered results
```

#### Test Delete Task
```bash
curl -X DELETE \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/1
  
# Expected: 200 OK (if not processing)
```

### Step 8: Test Task Processing Flow

1. Create a new task
2. Check status immediately (should be "pending")
3. Wait 2 seconds and check again (should be "processing")
4. Wait another 5 seconds and check again (should be "completed")
5. Verify data attribute changes through each status

### Step 9: Run Automated Test Suite
```bash
cd /home/runner/work/Project-Safehouse/Project-Safehouse/game-server
python3 test_api.py

# This will run all API tests automatically
```

### Step 10: Test Persistence
```bash
# Create tasks
curl -X POST \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  -H "Content-Type: application/json" \
  -d '{"message": "Persistence test"}' \
  http://localhost:5001/api/tasks

# Restart container
docker compose restart game-server

# Wait for container to start
sleep 10

# Verify tasks still exist
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks
  
# Expected: Tasks should still be in database
```

## Validation Checklist

- [ ] All Python files have valid syntax
- [ ] Docker Compose configuration is valid
- [ ] Docker image builds successfully
- [ ] Supervisord starts both services
- [ ] Database table is created on startup
- [ ] API authentication works correctly
- [ ] API endpoints respond correctly:
  - [ ] GET /api/tasks
  - [ ] GET /api/tasks/:id
  - [ ] POST /api/tasks
  - [ ] DELETE /api/tasks/:id
  - [ ] DELETE /api/tasks
- [ ] Task processor picks up pending tasks
- [ ] Task status transitions work (pending → processing → completed)
- [ ] Task data updates correctly for each status
- [ ] Multiple tasks are processed in order
- [ ] Cannot delete processing tasks
- [ ] Tasks persist after container restart
- [ ] Filtering by status works
- [ ] Pagination works (limit and offset)

## Security Validation

- [ ] API requires authentication token
- [ ] Invalid tokens are rejected
- [ ] Missing tokens are rejected
- [ ] API_TOKEN environment variable works
- [ ] Default token should be changed in production (documented)

## Performance Considerations

- [ ] Task processor doesn't block other tasks
- [ ] API responds quickly even with many tasks
- [ ] Database indexes are used for queries
- [ ] No memory leaks in long-running services

## Error Handling Validation

- [ ] Database connection failures are handled gracefully
- [ ] Invalid JSON in requests returns 400
- [ ] Non-existent task IDs return 404
- [ ] Processing errors mark tasks as completed with failed status
- [ ] All exceptions are caught and logged

## Success Criteria

All of the following must be true:
1. Both services start and run under supervisord
2. All API endpoints work with authentication
3. Tasks are processed automatically in order
4. Task status and data update correctly
5. Tasks persist in database
6. All error cases are handled properly
7. Documentation is complete and accurate

## Known Issues

### SSL Certificate Build Failure
**Issue:** Docker build fails due to SSL certificate verification errors when downloading Python packages from PyPI.

**Impact:** Cannot build Docker image in current environment.

**Resolution:** Build in environment with proper SSL certificates configured, or use pre-built base images with packages already installed.

**Not a Code Issue:** This is an infrastructure/environment issue, not a problem with the implementation.

## Conclusion

The implementation is complete and ready for testing in an environment with proper SSL certificates. All code has been verified for syntax correctness, and the architecture follows best practices for task queue systems with RESTful APIs.
