# Quick Reference Guide

## API Endpoints

### Authentication
All endpoints except `/` require the `Authorization` header:
```
Authorization: Bearer your-api-token-here
```

### Endpoints

#### Get API Info
```bash
curl http://localhost:5001/
```

#### List All Tasks
```bash
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks
```

#### List Pending Tasks
```bash
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  "http://localhost:5001/api/tasks?status=pending"
```

#### List Tasks with Pagination
```bash
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  "http://localhost:5001/api/tasks?limit=10&offset=0"
```

#### Get Specific Task
```bash
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/1
```

#### Create Task
```bash
curl -X POST \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  -H "Content-Type: application/json" \
  -d '{"message": "My task description"}' \
  http://localhost:5001/api/tasks
```

#### Delete Task
```bash
curl -X DELETE \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/1
```

#### Clear All Tasks
```bash
curl -X DELETE \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks
```

## Docker Commands

### Build Container
```bash
docker compose build game-server
```

### Start Container
```bash
docker compose up -d game-server
```

### Stop Container
```bash
docker compose stop game-server
```

### View Logs
```bash
# All logs
docker compose logs -f game-server

# API service logs
docker exec game_server tail -f /var/log/supervisor/api_service.out.log

# Task processor logs
docker exec game_server tail -f /var/log/supervisor/task_processor.out.log
```

### Check Service Status
```bash
docker exec game_server supervisorctl status
```

### Restart Services
```bash
# Restart all services
docker exec game_server supervisorctl restart all

# Restart API only
docker exec game_server supervisorctl restart api_service

# Restart processor only
docker exec game_server supervisorctl restart task_processor
```

## Environment Variables

Set in `.env` file:
```bash
# Required
API_TOKEN=your-secure-token-here

# Database
DATABASE_HOST=db
DATABASE_NAME=safehouse
DATABASE_USER=safehouse
DATABASE_PASSWORD=your-secure-password

# Redis
REDIS_HOST=cache
REDIS_PORT=6379

# Task Processing
PROCESS_INTERVAL=5
```

## Testing

### Run Automated Tests
```bash
cd game-server
python3 test_api.py
```

### Manual Test Flow
```bash
# 1. Create a task
TASK_ID=$(curl -s -X POST \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  -H "Content-Type: application/json" \
  -d '{"message": "Test task"}' \
  http://localhost:5001/api/tasks | jq -r '.id')

echo "Created task: $TASK_ID"

# 2. Check status (pending)
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/$TASK_ID | jq

# 3. Wait 2 seconds
sleep 2

# 4. Check status (should be processing)
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/$TASK_ID | jq

# 5. Wait 5 more seconds
sleep 5

# 6. Check status (should be completed)
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks/$TASK_ID | jq
```

## Database Access

### Connect to MariaDB
```bash
docker exec -it db mysql -u safehouse -p safehouse
```

### Check Tasks Table
```sql
-- Show all tasks
SELECT id, status, created_at, updated_at FROM tasks;

-- Count by status
SELECT status, COUNT(*) as count FROM tasks GROUP BY status;

-- Show recent tasks
SELECT * FROM tasks ORDER BY created_at DESC LIMIT 10;

-- Show pending tasks
SELECT * FROM tasks WHERE status = 'pending';
```

## Troubleshooting

### API Not Responding
```bash
# Check if container is running
docker ps | grep game_server

# Check supervisord status
docker exec game_server supervisorctl status

# Check API logs
docker exec game_server tail -n 50 /var/log/supervisor/api_service.err.log

# Restart API service
docker exec game_server supervisorctl restart api_service
```

### Tasks Not Processing
```bash
# Check processor logs
docker exec game_server tail -n 50 /var/log/supervisor/task_processor.out.log

# Check for errors
docker exec game_server tail -n 50 /var/log/supervisor/task_processor.err.log

# Check Redis connection
docker exec cache redis-cli ping

# Restart processor
docker exec game_server supervisorctl restart task_processor
```

### Database Issues
```bash
# Check database connection
docker exec db mysqladmin -u safehouse -p safehouse status

# Check if tasks table exists
docker exec -it db mysql -u safehouse -p safehouse -e "SHOW TABLES;"

# Check table structure
docker exec -it db mysql -u safehouse -p safehouse -e "DESCRIBE tasks;"
```

## Common Scenarios

### Scenario 1: Create and Monitor Multiple Tasks
```bash
# Create 5 tasks
for i in {1..5}; do
  curl -X POST \
    -H "Authorization: Bearer safehouse-api-token-change-me" \
    -H "Content-Type: application/json" \
    -d "{\"message\": \"Task $i\"}" \
    http://localhost:5001/api/tasks
done

# Monitor processing
watch -n 1 'curl -s -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks | jq ".tasks[] | {id, status}"'
```

### Scenario 2: Clear Completed Tasks
```bash
# List completed tasks
curl -H "Authorization: Bearer safehouse-api-token-change-me" \
  "http://localhost:5001/api/tasks?status=completed"

# Delete all completed tasks
curl -X DELETE \
  -H "Authorization: Bearer safehouse-api-token-change-me" \
  http://localhost:5001/api/tasks
```

### Scenario 3: Check System Health
```bash
# Check all services
docker compose ps

# Check supervisord
docker exec game_server supervisorctl status

# Check API
curl http://localhost:5001/

# Check Redis
docker exec cache redis-cli ping

# Check database
docker exec db mysqladmin -u safehouse -p safehouse ping
```

## Performance Tips

### For High Volume Task Processing
1. Increase `PROCESS_INTERVAL` to reduce database load
2. Ensure Redis is properly configured
3. Monitor database connection pool
4. Consider horizontal scaling of processors

### For Better Response Times
1. Keep Redis connection stable
2. Ensure database has proper indexes
3. Monitor API service memory usage
4. Use pagination for large task lists

## Security Reminders

⚠️ **Always change these in production:**
- `API_TOKEN` environment variable
- `DATABASE_PASSWORD` environment variable
- `DATABASE_ROOT_PASSWORD` environment variable

✅ **Best practices:**
- Use strong, random tokens
- Enable SSL/TLS for external access
- Implement rate limiting if exposed publicly
- Regular security audits
- Keep dependencies updated

## Support & Documentation

For detailed information, see:
- `game-server/README.md` - Complete API documentation
- `game-server/TESTING_PLAN.md` - Testing procedures
- `IMPLEMENTATION_COMPLETE.md` - Implementation details
- `FINAL_SUMMARY.md` - Comprehensive summary
- `ARCHITECTURE.md` - System architecture
