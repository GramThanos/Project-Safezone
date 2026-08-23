#!/usr/bin/env python3
# Manager with a RESTful API

from flask import Flask, jsonify, request, send_file
from functools import wraps
import os
import random
import string
import datetime
import zoneinfo

# Import configuration and modules
import config
import database
import cache
import tasks
import servers
import actions
import commands
import logs
import backups
import server_config
import sandbox_config
import mods
import workshop
import items
import reward_boxes
import server_templates
import steam
import rcon
import webhook
import mailer


app = Flask(__name__)

# Logging
def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][API Manager] {message}")

# Protect endpoints with token authentication
def require_auth(f):
    """Decorator to require authentication token"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # If no API_TOKEN is set, skip authentication
        if not config.MANAGER_API_TOKEN:
            return f(*args, **kwargs)
        
        # Get token from Authorization header
        token = request.headers.get('Authorization')
        token = token[7:] if token and token.startswith('Bearer ') else token
        
        # Validate token
        if not token or token != config.MANAGER_API_TOKEN:
            return jsonify({'error': 'Invalid authorization token'}), 403
        
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    """API root endpoint"""
    return jsonify({
        'name': 'Game Server Task Management API',
        'version': '1.0.0',
        'endpoints': {
            'list_tasks': 'GET /api/tasks',
            'get_task': 'GET /api/tasks/:id',
            'create_task': 'POST /api/tasks',
            'delete_task': 'DELETE /api/tasks/:id',
            'clear_tasks': 'DELETE /api/tasks',
            'list_actions': 'GET /api/actions',
            'preview_action': 'POST /api/actions/:id/preview',
            'installation': 'GET /api/installation',
            'list_items': 'GET /api/items',
            'list_mods': 'GET /api/mods',
            'preview_mods': 'POST /api/mods/preview',
            'list_collections': 'GET /api/mods/collections',
            'delete_collection': 'DELETE /api/mods/collections/:id',
            'delete_mod': 'DELETE /api/mods/:item_id'
        },
        'authentication': 'Required - Use Authorization header with Bearer token'
    })



# Action catalog endpoints

@app.route('/api/actions', methods=['GET'])
@require_auth
def list_actions():
    """The whitelisted console actions the panel may run.

    ``?droppable=1`` limits the list to actions that are safe to hand out as a
    player reward (no moderation or server operations).
    """
    droppable_only = request.args.get('droppable') in ('1', 'true', 'yes')
    catalog = actions.catalog(droppable_only=droppable_only)
    return jsonify({
        'data': catalog,
        'categories': [{'id': cid, 'label': label} for cid, label in actions.CATEGORIES],
        'count': len(catalog),
        'message': 'Actions retrieved successfully'
    })


@app.route('/api/actions/<string:action_id>/preview', methods=['POST'])
@require_auth
def preview_action(action_id):
    """Validate parameters and return the console command that would run.

    Nothing is dispatched. The backend uses this to validate a reward or a
    direct give before storing/queueing it, so parameter rules live in exactly
    one place, and the admin UI shows the resulting command.
    """
    data = request.get_json(silent=True) or {}
    action = actions.get(action_id)
    if not action:
        return jsonify({'error': f'Unknown action: {action_id}'}), 404

    droppable_only = bool(data.get('droppable_only'))
    username = data.get('username') or 'ExamplePlayer'
    try:
        command_text = commands.build_action_command(
            username, action_id, data.get('params'), droppable_only=droppable_only
        )
    except commands.CommandError as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({
        'data': {'action': actions.to_public(action), 'command': command_text},
        'message': 'Action validated successfully'
    })


@app.route('/api/rewards/preview', methods=['POST'])
@require_auth
def preview_reward_commands():
    """Validate a free-text reward command sequence without running anything.

    The backend calls this before storing a usable reward, so a bad sequence is
    reported to the admin at authoring time rather than failing inside a delivery
    task. Parsing and rendering rules live in `commands.py` (the command-injection
    boundary); this only exposes them. Returns the parsed steps and, for an
    example username, the exact console lines that would be sent.
    """
    data = request.get_json(silent=True) or {}
    username = data.get('username') or 'ExamplePlayer'
    try:
        steps = commands.parse_reward_commands(data.get('commands'))
        preview = [commands.render_command(s['text'], username)
                   for s in steps if s['type'] == 'command']
    except commands.CommandError as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({
        'data': {
            'steps': steps,
            'preview': preview,
            'requires_online': commands.reward_requires_online(steps),
        },
        'message': 'Reward commands validated successfully'
    })


# Task Endpoints

@app.route('/api/tasks', methods=['GET'])
@require_auth
def list_tasks():
    """List all tasks with optional filtering"""
    try:
        # Get filter parameters
        status_filter = request.args.get('status', type=str, default=None)
        limit = request.args.get('limit', type=int, default=None)
        offset = request.args.get('offset', type=int, default=0)
        
        # Get tasks from database
        task_list = tasks.get_all(status_filter, limit, offset)
        
        return jsonify({
            'data': task_list,
            'count': len(task_list),
            'message': 'Tasks retrieved successfully'
        })
    except Exception as e:
        _log(f"Error listing tasks: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks/<int:task_id>', methods=['GET'])
@require_auth
def get_task(task_id):
    """Get specific task information"""
    try:
        task = tasks.get(task_id)
        
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        
        return jsonify({
            'data': task,
            'message': 'Task retrieved successfully'
        })
    except Exception as e:
        _log(f"Error getting task: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks', methods=['POST'])
@require_auth
def create_task():
    """Create a new task"""
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400
    
    data = request.get_json()
    
    if not data:
        data = {}
    
    try:
        task = tasks.create(data)
        if not task:
            return jsonify({'error': 'Failed to create task'}), 500
        
        # Notify task processor about new task
        notification_sent = cache.broadcast_to_channel(config.MANAGE_TASKS_CHANNEL, {'action': 'new_task', 'task_id': task['id']})
        if not notification_sent:
            _log(f"Warning: Task {task['id']} created but notification failed")
        
        return jsonify({
            'data': task,
            'message': 'Task created successfully'
        }), 201
    except Exception as e:
        _log(f"Error creating task: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@require_auth
def delete_task(task_id):
    """Delete a pending or completed task"""
    try:
        success, error = tasks.delete(task_id)
        
        if success is None:
            return jsonify({'error': error}), 404
        
        if not success:
            return jsonify({'error': error}), 400
        
        return jsonify({
            'data': {'id': task_id},
            'message': f'Task deleted successfully'
        })
    except Exception as e:
        _log(f"Error deleting task: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks', methods=['DELETE'])
@require_auth
def clear_tasks():
    """Clear all pending and completed tasks"""
    try:
        deleted_count = tasks.clear()
        
        return jsonify({
            'data': {},
            'message': 'Tasks cleared successfully',
            'count': deleted_count
        })
    except Exception as e:
        _log(f"Error clearing tasks: {e}")
        return jsonify({'error': str(e)}), 500


# Server Endpoints

@app.route('/api/servers', methods=['GET'])
@require_auth
def list_servers():
    """List all servers with optional filtering"""
    try:
        # Get filter parameters
        limit = request.args.get('limit', type=int, default=None)
        offset = request.args.get('offset', type=int, default=0)
        
        # Get servers from database
        servers_list = servers.get_all(limit, offset)
        
        return jsonify({
            'data': servers_list,
            'count': len(servers_list),
            'message': 'Servers retrieved successfully'
        })
    except Exception as e:
        _log(f"Error listing servers: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<int:server_id>', methods=['GET'])
@require_auth
def get_server(server_id):
    """Get specific server information"""
    try:
        server = servers.get(server_id)
        
        if not server:
            return jsonify({'error': 'Server not found'}), 404
        
        return jsonify({
            'data': server,
            'message': 'Server retrieved successfully'
        })
    except Exception as e:
        _log(f"Error getting server: {e}")
        return jsonify({'error': str(e)}), 500

def _validate_timezone(value):
    """Validate an IANA timezone name. Returns an error string or None."""
    if value is None or value == '':
        return None
    if not isinstance(value, str) or len(value) > 64:
        return 'Timezone must be a string of at most 64 characters'
    try:
        zoneinfo.ZoneInfo(value)
    except Exception:
        return f'Unknown timezone: {value}'
    return None


# The roster is only as fresh as the manager's `players` poll (30s), so a
# timeout near or below that could sleep on somebody who joined a moment ago and
# has not been seen yet. The floor keeps a joining player several polls of
# margin. 0 stays legal - that is how "never sleep on its own" is spelled.
IDLE_SLEEP_MIN = 120
# A whole day awake with nobody on it is already a misconfiguration; the cap is
# there so a typo cannot quietly mean "never sleep" when 0 is the way to say that.
IDLE_SLEEP_MAX = 86400


def _validate_idle_sleep(value):
    """Validate the idle auto-sleep timeout. Returns an error string or None."""
    if value is None:
        return None
    # bool is a subclass of int, and True would otherwise read as 1 second.
    if isinstance(value, bool) or not isinstance(value, int):
        return 'idle_sleep_seconds must be an integer number of seconds'
    if value == 0:
        return None
    if value < IDLE_SLEEP_MIN or value > IDLE_SLEEP_MAX:
        return (f'idle_sleep_seconds must be 0 (disabled) or between '
                f'{IDLE_SLEEP_MIN} and {IDLE_SLEEP_MAX} seconds')
    return None


@app.route('/api/servers', methods=['POST'])
@require_auth
def create_server():
    """Create a new server"""
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400
    
    data = request.get_json()
    
    # Validation
    if 'name' not in data:
        return jsonify({'error': 'Missing name'}), 400
    # The name becomes part of a file path (the server's log), so it is
    # constrained here rather than sanitised at every point of use.
    if not logs.is_safe_name(data['name']):
        return jsonify({
            'error': 'Name may use letters, digits, underscore, hyphen and dot, '
                     'must start with a letter, digit or underscore, and be at '
                     'most 64 characters'
        }), 400
    if 'ports' in data and not isinstance(data['ports'], list):
        return jsonify({'error': 'Ports must be a list'}), 400
    for port in data.get('ports', []):
        if not isinstance(port, int) or port <= 0 or port > 65535:
            return jsonify({'error': f'Invalid port number: {port}'}), 400
    if 'default_state' in data and data['default_state'] not in ['stopped', 'running', 'sleeping']:
        return jsonify({'error': 'Invalid default_state'}), 400
    idle_error = _validate_idle_sleep(data.get('idle_sleep_seconds'))
    if idle_error:
        return jsonify({'error': idle_error}), 400
    if 'hostname' in data and data['hostname'] is not None:
        if not isinstance(data['hostname'], str) or len(data['hostname']) > 255:
            return jsonify({'error': 'Hostname must be a string of at most 255 characters'}), 400
    if 'description' in data and data['description'] is not None:
        if not isinstance(data['description'], str):
            return jsonify({'error': 'Description must be a string'}), 400
    tz_error = _validate_timezone(data.get('timezone'))
    if tz_error:
        return jsonify({'error': tz_error}), 400
    if 'is_primary' in data and not isinstance(data['is_primary'], bool):
        return jsonify({'error': 'is_primary must be true or false'}), 400

    data = {
        'name': data.get('name', 'zomboid_server' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))),
        'hostname': (data.get('hostname') or '').strip() or None,
        'description': (data.get('description') or '').strip() or None,
        'ports': data.get('ports', [16261, 16262]),
        'default_state': data.get('default_state', 'stopped'),
        'idle_sleep_seconds': data.get('idle_sleep_seconds') or 0,
        'timezone': (data.get('timezone') or '').strip() or None,
        'is_primary': bool(data.get('is_primary'))
    }
    
    try:
        server = servers.create(data)
        if not server:
            return jsonify({'error': 'Failed to create server'}), 500
        
        # Notify task processor about new task
        notification_sent = cache.broadcast_to_channel(config.MANAGE_GAME_SERVERS_CHANNEL, {'command': 'update-managers'})
        if not notification_sent:
            _log(f"Warning: Server {server['id']} created but notification failed")
        
        return jsonify({
            'data': server,
            'message': 'Server created successfully'
        }), 201
    except Exception as e:
        _log(f"Error creating server: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers/<int:server_id>', methods=['PUT'])
@require_auth
def update_server(server_id):
    """Update server configuration (ports, state, name)"""
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400
    
    data = request.get_json()
    to_update = {}
    
    # Validation
    if 'name' in data:
        return jsonify({'error': 'Server name can not be changed'}), 400
    if 'ports' in data:
        if not isinstance(data['ports'], list):
            return jsonify({'error': 'Ports must be a list'}), 400
        for port in data['ports']:
            if not isinstance(port, int) or port <= 0 or port > 65535:
                return jsonify({'error': f'Invalid port number: {port}'}), 400
        to_update['ports'] = data['ports']
    if 'default_state' in data:
        if data['default_state'] not in ['stopped', 'running', 'sleeping']:
            return jsonify({'error': 'Invalid default_state'}), 400
        to_update['default_state'] = data['default_state']
    if 'idle_sleep_seconds' in data:
        idle_error = _validate_idle_sleep(data['idle_sleep_seconds'])
        if idle_error:
            return jsonify({'error': idle_error}), 400
        to_update['idle_sleep_seconds'] = data['idle_sleep_seconds'] or 0
    if 'hostname' in data:
        hostname = data['hostname']
        if hostname is not None and (not isinstance(hostname, str) or len(hostname) > 255):
            return jsonify({'error': 'Hostname must be a string of at most 255 characters'}), 400
        to_update['hostname'] = (hostname or '').strip() or None
    if 'description' in data:
        description = data['description']
        if description is not None and not isinstance(description, str):
            return jsonify({'error': 'Description must be a string'}), 400
        to_update['description'] = (description or '').strip() or None
    if 'timezone' in data:
        tz_error = _validate_timezone(data['timezone'])
        if tz_error:
            return jsonify({'error': tz_error}), 400
        to_update['timezone'] = (data['timezone'] or '').strip() or None
    if 'is_primary' in data:
        if not isinstance(data['is_primary'], bool):
            return jsonify({'error': 'is_primary must be true or false'}), 400
        # servers.update demotes the others, so "primary" stays a single answer.
        to_update['is_primary'] = data['is_primary']

    data = to_update
    
    try:
        success, info = servers.update(server_id, data)
        if not success:
            # info holds the failure reason (e.g. "Server not found")
            return jsonify({'error': f"Failed to update server: {info}"}), 400

        # Notify the orchestrator so config changes (ports/state) take effect
        notification_sent = cache.broadcast_to_channel(config.MANAGE_GAME_SERVERS_CHANNEL, {'command': 'update-managers'})
        if not notification_sent:
            _log(f"Warning: Server {server_id} updated but notification failed")

        return jsonify({
            'data': info,
            'message': 'Server updated successfully'
        }), 200
    except Exception as e:
        _log(f"Error updating server: {e}")
        return jsonify({'error': str(e)}), 500

def _server_state(server_id):
    """Live state as the orchestrator sees it, or None if it has not published."""
    raw = cache.get_value(f"server:{server_id}:state")
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    return raw


@app.route('/api/servers/<int:server_id>/config/raw', methods=['GET'])
@require_auth
def get_server_config_raw(server_id):
    """Every key in a server's INI, including commented-out ones.

    Readable whatever the server is doing - looking at a config is harmless. The
    response carries the live state so the panel can show the form read-only
    rather than letting somebody type into a screen that will refuse to save.
    """
    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    payload, error = server_config.read_raw(server['name'])
    if error:
        return jsonify({'error': error}), 404

    state = _server_state(server_id)
    payload['state'] = state
    payload['editable'] = state in server_config.EDITABLE_STATES
    payload['editable_states'] = sorted(server_config.EDITABLE_STATES)
    return jsonify({'data': payload})


@app.route('/api/servers/<int:server_id>/config/raw', methods=['PUT'])
@require_auth
def update_server_config_raw(server_id):
    """Apply raw edits, only while the server is off.

    Project Zomboid rewrites this file when it shuts down, so an edit made while
    it runs is silently lost. The state is checked here, immediately before the
    write, rather than trusting the check made when the form was opened - a
    sleeping server can be woken by a player at any moment.
    """
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    state = _server_state(server_id)
    if state not in server_config.EDITABLE_STATES:
        return jsonify({
            'error': f"This server is '{state or 'in an unknown state'}'. Stop it "
                     f"before editing the config - the game rewrites this file "
                     f"when it shuts down, so changes made now would be lost."
        }), 409

    data = request.get_json() or {}
    result, error = server_config.write_raw(
        server['name'], data.get('changes'), data.get('version')
    )
    if error:
        # A stale version is a conflict, not bad input.
        code = 409 if 'Somebody else' in error else 400
        return jsonify({'error': error}), code

    return jsonify({
        'data': result,
        'message': f"Updated {len(result['changed'])} setting(s)"
                   if result['changed'] else 'Nothing to change'
    })


@app.route('/api/servers/<int:server_id>/config/template', methods=['GET'])
@require_auth
def export_server_template(server_id):
    """Build a portable template from a server's current config.

    One template carries both halves: the non-gameplay INI settings and the
    SandboxVars difficulty. Readable whatever the server is doing - exporting is
    a read. Credentials, ports and per-server identity (INI) and the sandbox
    schema VERSION are filtered out by the config modules before the template is
    built, so nothing machine-specific or secret ever leaves here.

    Either half may be missing if that file has not been written yet; the
    template simply carries whatever is available.
    """
    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    name = request.args.get('name', '')
    description = request.args.get('description', '')

    ini, ini_error = server_config.export_template(server['name'], name, description)
    sandbox, sandbox_error = sandbox_config.export_template(server['name'], name, description)

    if ini_error and sandbox_error:
        # Neither file exists yet - nothing to export.
        return jsonify({'error': ini_error}), 404

    payload = {
        'schema': 'safezone.server-template/v1',
        'name': (name or '').strip() or f"{server['name']} config",
        'description': (description or '').strip(),
        'settings': ini['settings'] if not ini_error else {},
        'sandbox': sandbox['sandbox'] if not sandbox_error else {},
    }
    return jsonify({'data': payload})


@app.route('/api/servers/<int:server_id>/config/template', methods=['POST'])
@require_auth
def import_server_template(server_id):
    """Apply a combined template to a server, only while it is off.

    The body carries ``settings`` (INI) and/or ``sandbox`` (SandboxVars); at
    least one must be present. Each half is applied to its own file through the
    module that owns it, so its blacklist and formatting rules hold. The INI is
    applied first, then the sandbox; if the sandbox write fails, the INI change
    has already landed - the response reports what each half did so the operator
    can see a partial apply rather than guessing.

    Same state rule as every other config write: Project Zomboid rewrites these
    files when it shuts down, so an edit made while it runs is silently lost, and
    the state is re-checked here immediately before the writes.
    """
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    data = request.get_json() or {}
    settings = data.get('settings')
    sandbox = data.get('sandbox')
    if not settings and not sandbox:
        return jsonify({'error': 'The template has no settings or sandbox values'}), 400

    state = _server_state(server_id)
    if state not in server_config.EDITABLE_STATES:
        return jsonify({
            'error': f"This server is '{state or 'in an unknown state'}'. Stop it "
                     f"before importing a template - the game rewrites these files "
                     f"when it shuts down, so changes made now would be lost."
        }), 409

    result = {}
    parts = []
    if settings:
        ini, error = server_config.import_template(
            server['name'], settings, data.get('version'))
        if error:
            code = 409 if 'Somebody else' in error else 400
            return jsonify({'error': f'Config: {error}'}), code
        result['settings'] = ini
        parts.append(f"{len(ini.get('changed') or [])} config setting(s)")
    if sandbox:
        sb, error = sandbox_config.import_template(
            server['name'], sandbox, data.get('sandbox_version'))
        if error:
            code = 409 if 'Somebody else' in error else 400
            # Say what already landed, so a partial apply is not a surprise.
            prefix = 'Config applied, but the world half failed. ' if result else ''
            return jsonify({'error': f'{prefix}World: {error}', 'data': result}), code
        result['sandbox'] = sb
        parts.append(f"{len(sb.get('changed') or [])} world setting(s)")

    return jsonify({'data': result, 'message': 'Applied ' + ', '.join(parts)})


@app.route('/api/servers/<int:server_id>/config/sandbox', methods=['GET'])
@require_auth
def get_server_sandbox(server_id):
    """The top-level SandboxVars for a server (gameplay difficulty settings).

    Readable whatever the server is doing - looking is harmless. The live state
    rides along so the panel can show the form read-only rather than letting
    somebody type into a screen that will refuse to save.
    """
    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    payload, error = sandbox_config.read(server['name'])
    if error:
        return jsonify({'error': error}), 404

    state = _server_state(server_id)
    payload['state'] = state
    payload['editable'] = state in server_config.EDITABLE_STATES
    payload['editable_states'] = sorted(server_config.EDITABLE_STATES)
    return jsonify({'data': payload})


@app.route('/api/servers/<int:server_id>/config/sandbox', methods=['PUT'])
@require_auth
def update_server_sandbox(server_id):
    """Apply SandboxVars edits, only while the server is off.

    Same state rule as the INI: the game rewrites its files on shutdown, so an
    edit made while it runs is silently lost, and the check is made immediately
    before the write rather than trusting the one made when the form opened.
    """
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    state = _server_state(server_id)
    if state not in server_config.EDITABLE_STATES:
        return jsonify({
            'error': f"This server is '{state or 'in an unknown state'}'. Stop it "
                     f"before editing the sandbox - the game rewrites this file "
                     f"when it shuts down, so changes made now would be lost."
        }), 409

    data = request.get_json() or {}
    result, error = sandbox_config.write(
        server['name'], data.get('changes'), data.get('version')
    )
    if error:
        code = 409 if 'Somebody else' in error else 400
        return jsonify({'error': error}), code

    return jsonify({
        'data': result,
        'message': f"Updated {len(result['changed'])} setting(s)"
                   if result['changed'] else 'Nothing to change'
    })


@app.route('/api/servers/<int:server_id>/mods', methods=['GET'])
@require_auth
def get_server_mods(server_id):
    """What mods a server is configured to use, against what is on disk."""
    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    settings, error = server_config.read(server['name'])
    if error:
        return jsonify({'error': error}), 404

    values = {s['key']: s.get('value') for s in settings}
    return jsonify({'data': mods.status(
        mods.parse_list(values.get('WorkshopItems')),
        mods.parse_list(values.get('Mods')),
    )})


@app.route('/api/servers/<int:server_id>/mods', methods=['PUT'])
@require_auth
def update_server_mods(server_id):
    """Set a server's Workshop ids and mod names together.

    Together on purpose: they are two halves of one decision, and editing them
    separately is how a server ends up with the files for a mod it is not
    loading, or loading a name it never downloaded.

    `downloaded_only` restricts the change to content already on disk - see the
    check below.
    """
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    data = request.get_json() or {}
    item_ids = [str(i).strip() for i in (data.get('workshop_ids') or []) if str(i).strip()]
    mod_names = [str(n).strip() for n in (data.get('mod_names') or []) if str(n).strip()]

    error = mods.validate(item_ids, mod_names)
    if error:
        return jsonify({'error': error}), 400

    current, read_error = server_config.read(server['name'])
    existing_items, existing_names = [], []
    if not read_error:
        values = {s['key']: s.get('value') for s in current}
        existing_items = mods.parse_list(values.get('WorkshopItems'))
        existing_names = mods.parse_list(values.get('Mods'))

    # `downloaded_only` is the caller saying "this operator may switch mods on
    # and off, but may not install". Enforced against what is on disk rather
    # than against a role, because roles are the backend's business and files
    # are ours. Only *additions* are checked: removing an entry that was already
    # broken is the repair, and refusing it would trap the server in that state.
    if data.get('downloaded_only'):
        on_disk = set(mods.installed())
        available = set()
        for item in on_disk:
            available.update(mods.mods_in_item(item))

        added_items = [i for i in item_ids if i not in existing_items and i not in on_disk]
        added_names = [n for n in mod_names if n not in existing_names and n not in available]
        if added_items or added_names:
            missing = ', '.join(added_items + added_names)
            return jsonify({'error': f'Not downloaded: {missing}. '
                                     'Only an admin can install new mods.'}), 403

    changed, error = server_config.write(server['name'], {
        'WorkshopItems': mods.join_list(item_ids),
        'Mods': mods.join_list(mod_names),
    })
    if error:
        return jsonify({'error': error}), 400

    return jsonify({
        'data': mods.status(item_ids, mod_names),
        'message': 'Mod list saved. Download them, then restart the server.'
    })


# One paste, one screenful of ids. A collection is the way to add many at once,
# and it arrives as a single line.
MAX_PASTED_ITEMS = 100


def _mod_usage():
    """Which servers reference which Workshop item, and which mod names.

    Read from each server's own INI rather than from a table, because the INI is
    what the game reads - a cached copy would be one more thing to drift.
    Returns ``(items, names)``, both mapping value -> sorted server names.
    """
    items = {}
    names = {}
    for server in servers.get_all():
        settings, error = server_config.read(server['name'])
        if error:
            # A server whose config cannot be read yet (never started) simply
            # uses nothing; it is not a reason to fail the whole listing.
            continue
        values = {s['key']: s.get('value') for s in settings}
        for item_id in mods.parse_list(values.get('WorkshopItems')):
            items.setdefault(item_id, set()).add(server['name'])
        for name in mods.parse_list(values.get('Mods')):
            names.setdefault(name, set()).add(server['name'])
    return ({k: sorted(v) for k, v in items.items()},
            {k: sorted(v) for k, v in names.items()})


@app.route('/api/installation', methods=['GET'])
@require_auth
def get_installation():
    """The state of the shared game install and its Workshop content.

    One install directory serves every server in the stack, so this is host
    state, not server state. `installed` is None when nothing has been
    downloaded yet - a first run, not an error.
    """
    state, error = steam.installed_app_state(config.STEAM_APP_ID, config.STEAM_INSTALL_DIR)
    item_usage, _name_usage = _mod_usage()
    installed_ids = mods.installed()

    return jsonify({'data': {
        'installed': state,
        'error': error,
        'app_id': str(config.STEAM_APP_ID),
        'configured_branch': config.STEAM_APP_BETA,
        'install_dir': config.STEAM_INSTALL_DIR,
        'server_script': config.SERVER_SCRIPT,
        'server_script_present': os.path.isfile(config.SERVER_SCRIPT),
        'workshop': {
            'app_id': mods.WORKSHOP_APP_ID,
            'content_dir': mods.content_dir(),
            'item_count': len(installed_ids),
            'size': mods.content_size(),
            # Configured somewhere but never downloaded: the state that makes a
            # server fail to start with nothing useful in the log.
            'missing_ids': sorted(i for i in item_usage if i not in set(installed_ids)),
        },
    }})


@app.route('/api/items', methods=['GET'])
@require_auth
def list_items():
    """The in-game item catalog, for the reward item picker.

    Reference data, not server state - it lives here because this is the
    container with egress, not because the manager owns items. `?refresh=1`
    forces a re-fetch instead of using the cached copy.
    """
    force = request.args.get('refresh') in ('1', 'true', 'yes')
    payload, error = items.get_catalog(force=force)
    if not payload:
        return jsonify({'error': error or 'The item catalog is unavailable'}), 503

    # `stale` set means the cached copy could not be refreshed: still usable,
    # just older than we would like, which is worth saying rather than hiding.
    return jsonify({'data': payload, 'stale': error})


@app.route('/api/reward-boxes', methods=['GET'])
@require_auth
def list_reward_boxes():
    """The community loot-box config index, for "Import from community".

    Reference data fetched from GitHub - it lives here because this is the
    container with egress. `?refresh=1` forces a re-fetch. Like the item
    catalog, `stale` reports a failed refresh without discarding a usable list.
    """
    force = request.args.get('refresh') in ('1', 'true', 'yes')
    payload, error = reward_boxes.get_box_list(force=force)
    if not payload:
        return jsonify({'error': error or 'The community box list is unavailable'}), 503
    return jsonify({'data': payload, 'stale': error})


@app.route('/api/reward-boxes/<string:box_id>', methods=['GET'])
@require_auth
def get_reward_box(box_id):
    """One community loot-box config, for preview before import."""
    payload, error = reward_boxes.get_box(box_id)
    if not payload:
        status = 400 if error == 'invalid box id' else 502
        return jsonify({'error': error or 'The box config is unavailable'}), status
    return jsonify({'data': payload})


@app.route('/api/server-templates', methods=['GET'])
@require_auth
def list_server_templates():
    """The community server-config template index, for "Templates".

    Reference data fetched from GitHub - it lives here because this is the
    container with egress. `?refresh=1` forces a re-fetch. Like the reward-box
    list, `stale` reports a failed refresh without discarding a usable list.
    """
    force = request.args.get('refresh') in ('1', 'true', 'yes')
    payload, error = server_templates.get_template_list(force=force)
    if not payload:
        return jsonify({'error': error or 'The community template list is unavailable'}), 503
    return jsonify({'data': payload, 'stale': error})


@app.route('/api/server-templates/<string:template_id>', methods=['GET'])
@require_auth
def get_server_template(template_id):
    """One community server-config template, for preview before import."""
    payload, error = server_templates.get_template(template_id)
    if not payload:
        status = 400 if error == 'invalid template id' else 502
        return jsonify({'error': error or 'The template is unavailable'}), status
    return jsonify({'data': payload})


@app.route('/api/mods', methods=['GET'])
@require_auth
def list_mods():
    """Every downloaded Workshop item, with what it provides and who uses it.

    Enriched with the Workshop's own title and summary where they can be
    fetched. `?metadata=0` skips that, which is the escape hatch if Steam is
    slow and somebody just wants the list.
    """
    item_usage, name_usage = _mod_usage()
    installed_ids = mods.installed()
    wanted = sorted(set(installed_ids) | set(item_usage))

    metadata, metadata_error = ({}, None)
    if request.args.get('metadata') not in ('0', 'false', 'no'):
        metadata, metadata_error = workshop.lookup(wanted)

    entries = mods.library(usage=item_usage, metadata=metadata)

    # An item a server asks for that is not on disk has no library row, so it
    # would otherwise be invisible on the page that exists to fix it.
    on_disk = {entry['id'] for entry in entries}
    missing = [{
        'id': item_id,
        'mods': [],
        'size': None,
        'updated_at': None,
        'used_by': server_names,
        'missing': True,
        'workshop': metadata.get(item_id),
    } for item_id, server_names in sorted(item_usage.items()) if item_id not in on_disk]

    return jsonify({
        'data': entries + missing,
        'mod_usage': name_usage,
        'count': len(entries) + len(missing),
        # Reported rather than swallowed: "no title shown" because Steam was
        # unreachable is a different thing from "this item has no title".
        'metadata_error': metadata_error,
    })


@app.route('/api/mods/preview', methods=['POST'])
@require_auth
def preview_mods():
    """What a list of pasted ids or Workshop URLs actually refers to.

    The point is to fail a typo in a second rather than after a SteamCMD run:
    SteamCMD reports success for an item id that does not exist, so without this
    the first sign of a wrong id is an empty directory several minutes later.
    """
    data = request.get_json(silent=True) or {}
    raw_items = data.get('items') or []
    if isinstance(raw_items, str):
        raw_items = [raw_items]
    if len(raw_items) > MAX_PASTED_ITEMS:
        return jsonify({'error': f'Too many at once (limit {MAX_PASTED_ITEMS}). '
                                 'A collection URL is one line and brings its '
                                 'whole list with it.'}), 400

    pasted, unresolved = [], []
    for raw in raw_items:
        item_id, error = mods.resolve_item_id(raw)
        if error:
            unresolved.append({'input': str(raw)[:120], 'error': error})
        elif item_id not in pasted:
            pasted.append(item_id)

    # A collection page and an item page have the same URL shape, so which one
    # was pasted can only be settled by asking Steam. Anything that comes back
    # with children is expanded in place, keeping the author's order - for a PZ
    # collection that is often the intended load order.
    expanded, collection_error = workshop.collections(pasted)

    resolved = []
    for item_id in pasted:
        for child in expanded.get(item_id, [item_id]):
            if child not in resolved:
                resolved.append(child)

    # The collections themselves are looked up too, so the panel can name what
    # it expanded rather than showing a bare id.
    metadata, metadata_error = workshop.lookup(resolved + list(expanded))
    on_disk = set(mods.installed())

    items = []
    for item_id in resolved:
        entry = dict(metadata.get(item_id) or {'id': item_id, 'found': None})
        entry['downloaded'] = item_id in on_disk
        items.append(entry)

    def _usable(item_id):
        entry = metadata.get(item_id) or {}
        return entry.get('found') is not False and not entry.get('banned')

    download_items = []
    for item_id in pasted:
        if item_id in expanded:
            download_items.append(item_id)
        elif _usable(item_id):
            download_items.append(item_id)

    return jsonify({
        'data': {
            'items': items,
            'unresolved': unresolved,
            'download_items': download_items,
            'collections': [{
                'id': collection_id,
                'count': len(children),
                'title': (metadata.get(collection_id) or {}).get('title'),
            } for collection_id, children in expanded.items()],
            'metadata_error': metadata_error or collection_error,
        }
    })


@app.route('/api/mods/collections', methods=['GET'])
@require_auth
def list_collections():
    """Collections this panel has installed from, with their author's order.

    Each is reported against what is actually downloaded, because a collection
    whose items were later deleted can no longer be applied in full and saying
    so up front beats a half-applied list.
    """
    on_disk = set(mods.installed())
    entries = []
    for row in workshop.known():
        items = row.get('items') or []
        entries.append(dict(row, downloaded=[i for i in items if i in on_disk],
                            missing=[i for i in items if i not in on_disk]))
    return jsonify({'data': entries, 'count': len(entries)})


@app.route('/api/mods/collections/<string:collection_id>', methods=['DELETE'])
@require_auth
def delete_collection(collection_id):
    """Forget a collection. The mods it brought in are untouched."""
    ok, error, found = workshop.forget_collection(collection_id)
    if not ok:
        return jsonify({'error': error}), (404 if not found else 500)
    return jsonify({'message': 'Collection forgotten'})


@app.route('/api/mods/<string:item_id>', methods=['DELETE'])
@require_auth
def delete_mod(item_id):
    """Delete a downloaded Workshop item.

    Refused while a server still lists it: removing the files under a server
    that is configured to load them turns a working server into one that fails
    at boot, and the panel is where that mistake would be made.
    """
    item_usage, name_usage = _mod_usage()
    used_by = set(item_usage.get(str(item_id)) or [])

    # Also the other half of the pair: a server whose `Mods` line still names a
    # mod this item provides is broken by the delete just as surely as one that
    # lists the id, and the two lists are allowed to disagree.
    for name in mods.mods_in_item(item_id):
        used_by.update(name_usage.get(name) or [])

    if used_by:
        return jsonify({'error': 'Still used by: ' + ', '.join(sorted(used_by))
                                 + '. Remove it from those servers first.'}), 409

    ok, error = mods.remove(item_id)
    if not ok:
        return jsonify({'error': error}), 400

    # The files are gone; the cached title should go with them, so a later
    # re-download shows fresh details rather than a day-old copy.
    workshop.forget(item_id)
    return jsonify({'message': f'Workshop item {item_id} removed'})


@app.route('/api/servers/<int:server_id>/config', methods=['GET'])
@require_auth
def get_server_config(server_id):
    """The editable settings in a server's INI."""
    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    settings, error = server_config.read(server['name'])
    if error:
        return jsonify({'error': error}), 404
    return jsonify({'data': settings})


@app.route('/api/servers/<int:server_id>/config', methods=['PUT'])
@require_auth
def update_server_config(server_id):
    """Update declared settings in a server's INI.

    Only keys the catalog declares are writable, and everything else in the file
    is preserved untouched. `reload_options` picks most of them up live; a few
    (ports, mods) need a restart, which is the caller's call to make.
    """
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 400

    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    changed, error = server_config.write(server['name'], request.get_json() or {})
    if error:
        return jsonify({'error': error}), 400

    return jsonify({
        'data': {'changed': changed},
        'message': f"Updated {len(changed)} setting(s)" if changed else 'Nothing to change'
    })


@app.route('/api/servers/<int:server_id>/backups', methods=['GET'])
@require_auth
def server_backups(server_id):
    """Archives held for a server, newest first."""
    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    return jsonify({'data': backups.list_backups(server['name'])})


@app.route('/api/servers/<int:server_id>/backups/upload', methods=['POST'])
@require_auth
def upload_server_backup(server_id):
    """Accept an archive uploaded from an operator's machine.

    The name is validated and the container checked before it is accepted, so
    restore can trust whatever lands here the same way it trusts one this system
    took itself.
    """
    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'error': 'No file uploaded'}), 400

    name, error = backups.save_uploaded(server['name'], upload.filename, upload)
    if error:
        return jsonify({'error': error}), 400

    return jsonify({'data': {'name': name}, 'message': f'Uploaded {name}'})


@app.route('/api/servers/<int:server_id>/backups/<string:archive_name>/download', methods=['GET'])
@require_auth
def download_server_backup(server_id, archive_name):
    """Stream one archive back to the caller."""
    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    path, error = backups.archive_path(server['name'], archive_name)
    if error:
        return jsonify({'error': error}), 404
    return send_file(path, as_attachment=True, download_name=archive_name,
                     mimetype='application/gzip')


@app.route('/api/servers/<int:server_id>/backups/<string:archive_name>', methods=['DELETE'])
@require_auth
def delete_server_backup(server_id, archive_name):
    """Remove one archive."""
    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    ok, error = backups.delete(server['name'], archive_name)
    if not ok:
        return jsonify({'error': error}), 404
    return jsonify({'message': f'Deleted {archive_name}'})


@app.route('/api/servers/<int:server_id>/logs', methods=['GET'])
@require_auth
def server_logs(server_id):
    """Tail a server's log.

    The manager already keeps this file open to build the online roster; this
    just exposes it, so diagnosing a server no longer requires shell access.
    """
    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    lines, error = logs.tail(server['name'], request.args.get('lines', logs.DEFAULT_LINES))
    if error:
        return jsonify({'error': error}), 404

    return jsonify({
        'data': {'server_id': server_id, 'lines': lines, 'count': len(lines)}
    })


@app.route('/api/servers/<int:server_id>/history', methods=['GET'])
@require_auth
def server_history(server_id):
    """Online-player history for a server, bucketed for charting."""
    try:
        if not servers.get(server_id):
            return jsonify({'error': 'Server not found'}), 404

        hours = request.args.get('hours', type=int, default=24)
        bucket = request.args.get('bucket_minutes', type=int, default=15)
        history = servers.get_player_history(server_id, hours=hours, bucket_minutes=bucket)

        return jsonify({
            'data': history,
            'count': len(history),
            'message': 'Server history retrieved successfully'
        })
    except Exception as e:
        _log(f"Error getting server history: {e}")
        return jsonify({'error': str(e)}), 500

SERVER_CONTROL_COMMANDS = {
    'start': 'server-start',
    'stop': 'server-stop',
    'sleep': 'server-sleep',
}

@app.route('/api/servers/<int:server_id>/<string:action>', methods=['POST'])
@require_auth
def control_server(server_id, action):
    """Send a lifecycle command to a running server manager.

    Actions: start, stop, sleep, command. The command is broadcast on the game
    server management channel; the matching GameManager reacts to it.
    """
    server = servers.get(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404

    if action == 'command':
        data = request.get_json(silent=True) or {}
        command_text = (data.get('command') or '').strip()
        if not command_text:
            return jsonify({'error': 'A command string is required'}), 400

        # The console takes bare commands - `servermsg "hi"`, not `/servermsg
        # "hi"`. The slash is the in-game chat form; written to the console it
        # is not a command at all, and the server ignores it silently, which
        # looks exactly like the panel losing the command. Every builder in
        # `actions.py` emits the bare form, so a hand-typed one is normalised to
        # match rather than being quietly dropped.
        if command_text.startswith('/'):
            command_text = command_text[1:].lstrip()
            if not command_text:
                return jsonify({'error': 'A command string is required'}), 400

        # RCON when it is configured, because it gives back what the console
        # printed - `players` and `showoptions` are pointless without that. The
        # stdin path stays as the fallback: its acknowledgement is what makes
        # reward delivery trustworthy, and RCON being down must not stop a
        # command working.
        if rcon.available(server):
            output, error = rcon.execute(
                config.RCON_HOST, server.get('rcon_port'),
                server.get('rcon_password'), command_text
            )
            if error is None:
                return jsonify({
                    'data': {'id': server_id, 'action': action, 'output': output,
                             'via': 'rcon', 'command': command_text},
                    'message': 'Command executed'
                }), 200
            _log(f"RCON unavailable for '{server['name']}' ({error}); using stdin")

        # Acked, like reward delivery: a bare publish succeeds with nobody
        # listening, so reporting "sent" off the back of one told the operator
        # the command had run when nothing had received it.
        ok, detail = tasks.send_console(server, command_text)
        if not ok:
            return jsonify({'error': f'Command not delivered: {detail}'}), 502
        return jsonify({
            'data': {'id': server_id, 'action': action, 'output': None,
                     'via': 'stdin', 'command': command_text},
            'message': 'Command written to the server console'
        }), 200
    elif action in SERVER_CONTROL_COMMANDS:
        message = {'server': server['name'], 'command': SERVER_CONTROL_COMMANDS[action]}
    else:
        return jsonify({'error': f'Invalid action: {action}'}), 400

    sent = cache.broadcast_to_channel(config.MANAGE_GAME_SERVERS_CHANNEL, message)
    if not sent:
        return jsonify({'error': 'Failed to dispatch command to server manager'}), 503

    return jsonify({
        'data': {'id': server_id, 'action': action},
        'message': f"Command '{action}' dispatched to server '{server['name']}'"
    }), 202

@app.route('/api/servers/<int:server_id>', methods=['DELETE'])
@require_auth
def delete_server(server_id):
    """Remove a server from the database"""
    try:
        success, error = servers.delete(server_id)
        
        if not success:
            return jsonify({'error': error}), 500
        
        # Notify task processor about new task
        notification_sent = cache.broadcast_to_channel(config.MANAGE_GAME_SERVERS_CHANNEL, {'command': 'update-managers'})
        if not notification_sent:
            _log(f"Warning: Server {server_id} deleted but notification failed")
        
        return jsonify({
            'data': {'id': server_id},
            'message': f'Server deleted successfully'
        })
    except Exception as e:
        _log(f"Error deleting server: {e}")
        return jsonify({'error': str(e)}), 500



# Webhook relay

@app.route('/api/webhook', methods=['POST'])
@require_auth
def relay_webhook():
    """Post one already-composed message to a Discord webhook.

    The backend has no egress at all, so this is how an alert leaves the stack.
    It relays; it does not compose - what to say and who to say it to is the
    backend's business, and duplicating that here would mean two answers to
    "which channel wants this".

    The URL is checked against Discord's own hosts before anything is sent (see
    `webhook.py`). Only the status code comes back: enough to tell a deleted
    webhook from a rate limit, and nothing that could be used to read an
    internal endpoint through this.
    """
    data = request.get_json(silent=True) or {}
    url = data.get('url')
    payload = data.get('payload')

    if not url or not isinstance(payload, dict):
        return jsonify({'error': 'url and payload are required'}), 400
    if not webhook.is_webhook_url(url):
        return jsonify({'error': 'Not a Discord webhook URL'}), 400

    ok, status, error = webhook.post(url, payload)
    if not ok:
        _log(f"Webhook relay failed ({status}): {error}")
    return jsonify({'ok': ok, 'status': status, 'error': error})


# Mail relay

@app.route('/api/mail', methods=['GET'])
@require_auth
def mail_status():
    """Whether a mail server is configured at all.

    The backend asks so it can decide what to tell somebody - "check your
    email" is the wrong thing to say on a deployment with no SMTP host.
    """
    return jsonify({'data': {'configured': mailer.is_configured()}})


@app.route('/api/mail', methods=['POST'])
@require_auth
def relay_mail():
    """Send one composed message.

    The backend writes the subject and body - wording, links and templates are
    its business - and this puts it on the wire, because the backend has no
    egress. See `mailer.py`.
    """
    data = request.get_json(silent=True) or {}
    to_address = data.get('to')
    subject = data.get('subject')
    body = data.get('body')
    # Optional: the SMTP server to use, when an admin configured mail in the
    # panel instead of this container's environment. Absent means "use mine".
    overrides = data.get('smtp')
    if overrides is not None and not isinstance(overrides, dict):
        return jsonify({'error': 'smtp must be an object'}), 400

    if not to_address or not subject:
        return jsonify({'error': 'to and subject are required'}), 400
    if not mailer.is_address(to_address):
        return jsonify({'error': 'Not an email address'}), 400

    ok, error = mailer.send(to_address, subject, body, overrides=overrides)
    configured = mailer.is_configured(overrides)
    if not ok and configured:
        _log(f"Mail relay failed: {error}")
    return jsonify({'ok': ok, 'configured': configured, 'error': error})


if __name__ == '__main__':
    # Initialize database on startup
    _log("Initializing database...")
    database.init()
    _log("Checking cache availability...")
    cache.wait()
    
    # Start Flask app
    _log("Starting Task Management API Service...")
    app.run(host=config.MANAGER_API_HOST, port=config.MANAGER_API_PORT, debug=False)
