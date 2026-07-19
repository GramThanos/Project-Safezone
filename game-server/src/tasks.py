#!/usr/bin/env python3
import json
import datetime

# Custom modules
import config
import steam
import cache
import commands
import servers
import database
import models


# Logging

def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Tasks] {message}")


# Actions

def update_server(data):
    _log(f"steam.app_update('{config.STEAM_APP_ID}', beta='{config.STEAM_APP_BETA}', install_dir='{config.STEAM_INSTALL_DIR}')")
    ok, err, output = steam.app_update(config.STEAM_APP_ID, beta=(config.STEAM_APP_BETA if config.STEAM_APP_BETA else None), install_dir=config.STEAM_INSTALL_DIR)
    if not ok:
        data['message'] = err or 'Update failed'
    data['data'] = output if output else '-'
    return ok

# Similar info can be get from
# https://api.steamcmd.net/v1/info/380870
def get_app_info(data):
    _log(f"steam.app_info('{config.STEAM_APP_ID}')")
    info, err = steam.app_info(config.STEAM_APP_ID)
    if not info:
        data['message'] = err or 'Failed to fetch app info'
        return False

    # Store a compact summary (the full VDF can be large).
    common = info.get('common', {}) if isinstance(info, dict) else {}
    branches = {}
    try:
        #public = info.get('depots', {}).get('branches', {}).get('public', {}) or {}
        branches = info.get('depots', {}).get('branches', {}) or {}
    except AttributeError:
        branches = {}
    data['data'] = {
        'name': common.get('name'),
        'branches': branches
        #'public_buildid': branches.get('public', {}).get('buildid'),
        #'public_timeupdated': branches.get('public', {}).get('timeupdated'),
    }
    data['message'] = f"App: {common.get('name')}"
    return True

def give_reward(data):
    """Deliver an item or usable to an online player via a server console command.

    Expected data: server_id, username, kind ('item'|'usable'),
    in_game_id+count (items) or command_template (usables).
    """
    server_id = data.get('server_id')
    username = data.get('username')
    kind = data.get('kind', 'item')

    server = servers.get(server_id)
    if not server:
        data['delivery_message'] = 'Server not found'
        return False

    # The player must be online to receive the command.
    raw = cache.get_value(f"server:{server_id}:online_players")
    try:
        online = set(json.loads(raw)) if raw else set()
    except (json.JSONDecodeError, TypeError):
        online = set()
    if username not in online:
        data['delivery_message'] = 'Player is not online'
        return False

    # Build the command safely (raises CommandError on bad input).
    try:
        if kind == 'usable':
            command_text = commands.build_usable_command(username, data.get('command_template'))
        else:
            command_text = commands.build_item_command(
                username, data.get('in_game_id'), data.get('count', 1)
            )
    except commands.CommandError as e:
        data['delivery_message'] = f'Invalid reward: {e}'
        return False

    sent = cache.broadcast_to_channel(
        config.MANAGE_GAME_SERVERS_CHANNEL,
        {'server': server['name'], 'command': 'server-command', 'data': command_text}
    )
    if not sent:
        data['delivery_message'] = 'Failed to dispatch command'
        return False

    data['delivery_message'] = 'Reward delivered'
    data['command'] = command_text
    return True

ACTIONS = {
    'update_server': update_server,
    'get_app_info': get_app_info,
    'give_reward': give_reward,
}


# Tasks

def get_all(status_filter=None, limit=None, offset=0):
    """List all tasks with optional filtering using context session"""
    with database.get_context_session() as session:
        query = session.query(models.Task)
        
        if status_filter and isinstance(status_filter, str):
            query = query.filter(models.Task.status == status_filter)
        
        query = query.order_by(models.Task.created_at.desc())
        
        if limit:
            query = query.limit(limit).offset(offset)
        
        tasks = query.all()
        return [task.to_dict() for task in tasks]

def get_pending(limit=None, offset=0):
    return get_all(status_filter='pending', limit=limit, offset=offset)

def update(task_id, status, data=None):
    """Update task status and data with safe JSON parsing"""
    with database.get_context_session() as session:
        task = session.query(models.Task).filter(models.Task.id == task_id).first()
        if not task:
            return False
            
        task.status = status
        if data is not None:
            try:
                # Ensure we handle potential JSON string errors
                task.data = data if isinstance(data, dict) else json.loads(data)
            except (json.JSONDecodeError, TypeError) as e:
                _log(f"Invalid data format for task {task_id}: {e}")
                return False
                
        session.commit()
        return True

def create(data=None):
    """Create a new task"""
    data = data or {}
    with database.get_context_session() as session:
        # Mirror the action into its column so listings are readable.
        task = models.Task(status='pending', action=data.get('action', 'none'), data=data)
        session.add(task)
        session.commit()
        session.refresh(task)
        return task.to_dict()

def get(task_id):
    """Get specific task by ID"""
    with database.get_context_session() as session:
        task = session.query(models.Task).filter(models.Task.id == task_id).first()
        return task.to_dict() if task else None

def delete(task_id):
    """Delete a task (only if not processing)"""
    with database.get_context_session() as session:
        task = session.query(models.Task).filter(models.Task.id == task_id).first()

        if not task:
            return False, "Task not found"
        if task.status == 'processing':
            return False, "Cannot delete task that is currently processing"

        session.delete(task)
        session.commit()
        return True, None

def clear():
    """Delete all pending and completed tasks (leaves processing tasks intact).

    Returns the number of tasks removed.
    """
    with database.get_context_session() as session:
        deleted_count = session.query(models.Task).filter(
            models.Task.status != 'processing'
        ).delete(synchronize_session=False)
        session.commit()
        return deleted_count
