#!/usr/bin/env python3
"""
Test script for Game Server Task Management API
This script tests all API endpoints
"""

import sys
import json
import time
import urllib.request
import urllib.error

# Configuration
API_URL = "http://localhost:5001"
API_TOKEN = "safehouse-api-token-change-me"

def make_request(method, path, data=None):
    """Make HTTP request to API"""
    url = f"{API_URL}{path}"
    headers = {
        'Authorization': f'Bearer {API_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    request_data = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=request_data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode()) if e.code != 500 else {'error': str(e)}
    except Exception as e:
        return 0, {'error': str(e)}

def test_auth():
    """Test authentication"""
    print("\n=== Testing Authentication ===")
    
    # Test without token
    print("Testing without token...")
    url = f"{API_URL}/api/tasks"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as response:
            print("❌ FAILED: Should have been rejected without token")
            return False
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("✓ Correctly rejected without token (401)")
        else:
            print(f"❌ FAILED: Expected 401, got {e.code}")
            return False
    
    # Test with valid token
    print("Testing with valid token...")
    status, response = make_request('GET', '/api/tasks')
    if status == 200:
        print("✓ Accepted with valid token (200)")
        return True
    else:
        print(f"❌ FAILED: Expected 200, got {status}")
        return False

def test_create_task():
    """Test creating a task"""
    print("\n=== Testing Task Creation ===")
    
    status, response = make_request('POST', '/api/tasks', {
        'message': 'Test task created by test script'
    })
    
    if status == 201:
        print(f"✓ Task created successfully (ID: {response['id']})")
        return response['id']
    else:
        print(f"❌ FAILED: Expected 201, got {status}")
        print(f"Response: {response}")
        return None

def test_list_tasks():
    """Test listing tasks"""
    print("\n=== Testing List Tasks ===")
    
    status, response = make_request('GET', '/api/tasks')
    
    if status == 200:
        count = response.get('count', 0)
        print(f"✓ Retrieved {count} tasks")
        return True
    else:
        print(f"❌ FAILED: Expected 200, got {status}")
        return False

def test_get_task(task_id):
    """Test getting a specific task"""
    print(f"\n=== Testing Get Task {task_id} ===")
    
    status, response = make_request('GET', f'/api/tasks/{task_id}')
    
    if status == 200:
        print(f"✓ Retrieved task {task_id}")
        print(f"  Status: {response['status']}")
        print(f"  Data: {json.dumps(response['data'], indent=2)}")
        return response
    else:
        print(f"❌ FAILED: Expected 200, got {status}")
        return None

def test_filter_tasks():
    """Test filtering tasks"""
    print("\n=== Testing Task Filtering ===")
    
    for status_filter in ['pending', 'processing', 'completed']:
        status, response = make_request('GET', f'/api/tasks?status={status_filter}')
        if status == 200:
            count = response.get('count', 0)
            print(f"✓ Filtered {status_filter} tasks: {count} results")
        else:
            print(f"❌ FAILED: Could not filter by {status_filter}")
            return False
    
    return True

def test_delete_task(task_id):
    """Test deleting a task"""
    print(f"\n=== Testing Delete Task {task_id} ===")
    
    # First, check if task is processing
    status, task = make_request('GET', f'/api/tasks/{task_id}')
    if status == 200 and task['status'] == 'processing':
        print(f"Task {task_id} is processing, waiting for completion...")
        # Wait for task to complete
        for _ in range(10):
            time.sleep(2)
            status, task = make_request('GET', f'/api/tasks/{task_id}')
            if task['status'] != 'processing':
                break
    
    status, response = make_request('DELETE', f'/api/tasks/{task_id}')
    
    if status == 200:
        print(f"✓ Task {task_id} deleted successfully")
        return True
    else:
        print(f"❌ FAILED: Expected 200, got {status}")
        print(f"Response: {response}")
        return False

def test_clear_tasks():
    """Test clearing all tasks"""
    print("\n=== Testing Clear All Tasks ===")
    
    status, response = make_request('DELETE', '/api/tasks')
    
    if status == 200:
        print(f"✓ Cleared {response.get('deleted_count', 0)} tasks")
        return True
    else:
        print(f"❌ FAILED: Expected 200, got {status}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Game Server Task Management API Test Suite")
    print("=" * 60)
    
    # Test API is accessible
    print("\nChecking API availability...")
    try:
        status, response = make_request('GET', '/')
        if status == 200:
            print(f"✓ API is accessible at {API_URL}")
            print(f"  Name: {response.get('name')}")
            print(f"  Version: {response.get('version')}")
        else:
            print(f"❌ API is not accessible (status: {status})")
            print(f"Please make sure the game-server container is running:")
            print(f"  docker compose up -d game-server")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Cannot connect to API: {e}")
        print(f"Please make sure the game-server container is running:")
        print(f"  docker compose up -d game-server")
        sys.exit(1)
    
    # Run tests
    results = []
    
    results.append(("Authentication", test_auth()))
    results.append(("List Tasks", test_list_tasks()))
    
    task_id = test_create_task()
    results.append(("Create Task", task_id is not None))
    
    if task_id:
        # Wait a moment for task to be processed
        print("\nWaiting for task to be processed...")
        for i in range(3):
            time.sleep(2)
            task = test_get_task(task_id)
            if task and task['status'] == 'completed':
                break
        
        results.append(("Get Task", task is not None))
        results.append(("Filter Tasks", test_filter_tasks()))
        results.append(("Delete Task", test_delete_task(task_id)))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        sys.exit(1)

if __name__ == '__main__':
    main()
