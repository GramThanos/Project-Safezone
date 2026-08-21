#!/usr/bin/env python3
import json
import re
import time
import uuid
import datetime

# Custom modules
import config
import steam
import cache
import commands
import servers
import backups
import mods
import workshop
import server_config
import steam
import database
import models


# Logging

def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Tasks] {message}")


# Actions

# A branch name reaches a SteamCMD command line, so it is constrained to what
# Steam actually allows in one rather than trusted.
BETA_RE = re.compile(r'^[A-Za-z0-9._-]{1,64}$')


def update_server(data):
    """Install or update the game files via SteamCMD.

    `beta` may be given per-task to switch branch without a redeploy; omitted,
    the configured branch is used. Passing it explicitly as an empty string
    means "public", which is how you get back off a beta.
    """
    beta = data.get('beta', None)
    if beta is None:
        beta = config.STEAM_APP_BETA
    else:
        beta = str(beta).strip()
        if beta and not BETA_RE.match(beta):
            data['message'] = f"'{beta}' is not a valid branch name"
            return False
    beta = beta or None

    _log(f"steam.app_update('{config.STEAM_APP_ID}', beta='{beta}', install_dir='{config.STEAM_INSTALL_DIR}')")
    ok, err, output = steam.app_update(config.STEAM_APP_ID, beta=beta, install_dir=config.STEAM_INSTALL_DIR)
    if not ok:
        data['message'] = err or 'Update failed'
    else:
        # Report what landed, not just that SteamCMD exited happy: a partial
        # update leaves the manifest saying so.
        state, _error = steam.installed_app_state(config.STEAM_APP_ID, config.STEAM_INSTALL_DIR)
        if state:
            data['installed'] = state
            data['message'] = data.get('message') or (
                f"Build {state.get('buildid')} on branch {state.get('branch') or 'public'}"
            )
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
    """Deliver a reward, or run a catalog action, via a server console command.

    Expected data: server_id, username, kind ('item'|'usable'), plus one of
      - in_game_id + count            (kind 'item')
      - action_id + action_params     (kind 'usable', catalog action)
    ``scope`` is 'reward' (default, loot-safe actions only) or 'staff' (the whole
    catalog; the backend gates this on the operator's role).
    """
    server_id = data.get('server_id')
    username = data.get('username')
    kind = data.get('kind', 'item')
    action_id = data.get('action_id')
    staff = data.get('scope') == 'staff'

    server = servers.get(server_id)
    if not server:
        data['delivery_message'] = 'Server not found'
        return False

    # Player-targeted commands are no-ops for a disconnected player; server-wide
    # actions (weather, bans, save) run regardless.
    needs_online = commands.action_requires_online(action_id) if action_id else True
    if needs_online:
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
        if kind == 'usable' and action_id:
            command_text = commands.build_action_command(
                username, action_id, data.get('action_params'), droppable_only=not staff
            )
        elif kind == 'usable':
            # Free-text templates are gone: every usable is a catalog action, so
            # nothing can reach the console outside the whitelist.
            raise commands.CommandError('usable rewards require an action_id')
        else:
            command_text = commands.build_item_command(
                username, data.get('in_game_id'), data.get('count', 1)
            )
    except commands.CommandError as e:
        data['delivery_message'] = f'Invalid reward: {e}'
        return False

    # A publish succeeds even with no manager listening, so the command is sent
    # with an ack id and we wait for the manager to report that it really wrote
    # it to the game server's stdin.
    ack_id = uuid.uuid4().hex
    sent = cache.broadcast_to_channel(
        config.MANAGE_GAME_SERVERS_CHANNEL,
        {'server': server['name'], 'command': 'server-command',
         'data': command_text, 'ack_id': ack_id}
    )
    if not sent:
        data['delivery_message'] = 'Failed to dispatch command'
        return False

    ack = _await_command_ack(ack_id)
    data['command'] = command_text
    if ack is None:
        data['delivery_message'] = 'No response from the server manager'
        return False
    if not ack.get('ok'):
        data['delivery_message'] = f"Command not delivered ({ack.get('detail') or 'unknown reason'})"
        return False

    data['delivery_message'] = 'Reward delivered'
    return True


def _await_command_ack(ack_id, timeout=None, poll_interval=0.1):
    """Wait for a server manager's acknowledgement of a dispatched command.

    Returns the decoded ack (``{'ok': bool, 'detail': str|None}``), or None if
    none arrived in time - which means no manager is running for that server, or
    it died before writing the command.
    """
    timeout = config.COMMAND_ACK_TIMEOUT if timeout is None else timeout
    key = f"{config.COMMAND_ACK_PREFIX}{ack_id}"
    deadline = time.monotonic() + timeout
    while True:
        raw = cache.get_value(key)
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {'ok': False, 'detail': 'malformed acknowledgement'}
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll_interval)

def send_console(server, command_text):
    """Write one console command to a running server, waiting for the ack.

    Returns (ok, detail). Same mechanism as reward delivery: a publish succeeds
    with nobody listening, so the ack is what proves it was written. Public
    because the admin console endpoint needs exactly this - a dispatch that can
    say whether it landed, rather than one that always claims success.
    """
    ack_id = uuid.uuid4().hex
    sent = cache.broadcast_to_channel(
        config.MANAGE_GAME_SERVERS_CHANNEL,
        {'server': server['name'], 'command': 'server-command',
         'data': command_text, 'ack_id': ack_id}
    )
    if not sent:
        return False, 'failed to dispatch'
    ack = _await_command_ack(ack_id)
    if ack is None:
        return False, 'no response from the server manager'
    if not ack.get('ok'):
        return False, ack.get('detail') or 'not delivered'
    return True, None


def backup_world(data):
    """Archive a server's world.

    If the server is running it is told to `save` first and given a moment to
    flush, so the archive is a consistent world rather than one caught mid-write.
    A server that is not running needs no such care - the files are already at
    rest, and a failed save must not stop the backup.
    """
    server_id = data.get('server_id')
    server = servers.get(server_id)
    if not server:
        data['result'] = 'error'
        data['message'] = 'Server not found'
        return False

    state = cache.get_value(f"server:{server_id}:state")
    if state == 'running':
        ok, detail = send_console(server, 'save')
        if ok:
            time.sleep(config.BACKUP_QUIESCE_SECONDS)
            data['quiesced'] = True
        else:
            # Worth recording, not worth aborting: a slightly older world is a
            # great deal better than no backup at all.
            data['quiesced'] = False
            data['quiesce_detail'] = detail

    name, error = backups.create(server['name'], data.get('note'))
    if error:
        data['result'] = 'error'
        data['message'] = error
        return False

    removed = backups.prune(server['name'], data.get('keep', config.BACKUP_KEEP))
    data['result'] = 'success'
    data['backup'] = name
    data['message'] = f"Backed up as {name}" + (f"; pruned {removed} old archive(s)" if removed else '')
    return True


def restore_world(data):
    """Replace a server's world from an archive.

    Refused while the server is running: restoring underneath a live server
    would have it writing into a directory being swapped out beneath it.
    """
    server_id = data.get('server_id')
    server = servers.get(server_id)
    if not server:
        data['result'] = 'error'
        data['message'] = 'Server not found'
        return False

    state = cache.get_value(f"server:{server_id}:state")
    if state == 'running':
        data['result'] = 'error'
        data['message'] = 'Stop the server before restoring a backup'
        return False

    kept_aside, error = backups.restore(server['name'], data.get('backup'))
    if error:
        data['result'] = 'error'
        data['message'] = error
        return False

    data['result'] = 'success'
    data['message'] = 'World restored'
    if kept_aside:
        # Say where the old world went: somebody restoring the wrong archive
        # needs to know it is recoverable.
        data['previous_world'] = kept_aside
    return True


def update_mods(data):
    """Download the Workshop items a server is configured to use.

    Reads the ids from the server's own INI rather than taking them from the
    task, so what gets downloaded is always what the server will actually try to
    load. Passing them separately is how the two drift apart.
    """
    server_id = data.get('server_id')
    server = servers.get(server_id)
    if not server:
        data['result'] = 'error'
        data['message'] = 'Server not found'
        return False

    settings, error = server_config.read(server['name'])
    if error:
        data['result'] = 'error'
        data['message'] = error
        return False

    values = {s['key']: s.get('value') for s in settings}
    item_ids = mods.parse_list(values.get('WorkshopItems'))
    mod_names = mods.parse_list(values.get('Mods'))

    ok, error, output = steam.workshop_download(item_ids, config.STEAM_INSTALL_DIR)
    data['output'] = output
    if not ok:
        data['result'] = 'error'
        data['message'] = error
        return False

    mods.forget_sizes()

    # Report the mismatch that silently breaks a server: ids downloaded fine,
    # mod names wrong, nobody can connect and the logs are unhelpful.
    state = mods.status(item_ids, mod_names)
    data['mods'] = state
    data['result'] = 'success'

    notes = [f"{len(item_ids)} Workshop item(s) up to date"]
    if state['missing_ids']:
        notes.append(f"still missing: {', '.join(state['missing_ids'])}")
    if state['unknown_mod_names']:
        notes.append(f"mod name(s) no downloaded item provides: "
                     f"{', '.join(state['unknown_mod_names'])}")
    data['message'] = '; '.join(notes)
    return True


def download_workshop(data):
    """Download Workshop items by id, independent of any server's config.

    `update_mods` deliberately takes its ids from a server's INI, so it can only
    fetch what a server is *already* configured to load. Installing something
    new is the other direction - download first, then decide which servers get
    it - and that is what this is for.
    """
    raw_ids = data.get('workshop_ids') or []
    item_ids = []
    for raw in raw_ids:
        item_id, error = mods.resolve_item_id(raw)
        if error:
            data['result'] = 'error'
            data['message'] = error
            return False
        if item_id not in item_ids:
            item_ids.append(item_id)

    if not item_ids:
        data['result'] = 'error'
        data['message'] = 'No Workshop items given'
        return False

    # A collection id downloads nothing on its own, so expand it into its items
    # first. The panel already does this when it previews, but the task is
    # reachable directly and should behave the same either way.
    expanded, _error = workshop.collections(item_ids)
    if expanded:
        data['collections'] = {k: len(v) for k, v in expanded.items()}
        resolved = []
        for item_id in item_ids:
            for child in expanded.get(item_id, [item_id]):
                if child not in resolved:
                    resolved.append(child)
        item_ids = resolved

        if not item_ids:
            # Every id given was a collection, and none of them contain
            # anything. Reporting success for a run that downloaded nothing is
            # how a mystery starts.
            data['result'] = 'error'
            data['message'] = ('Nothing to download: '
                               + ', '.join(expanded) + ' contain no items')
            return False

    error = mods.validate(item_ids, [])
    if error:
        data['result'] = 'error'
        data['message'] = error
        return False

    # Ask Steam what these ids are before spending minutes on SteamCMD. A
    # metadata failure is not a reason to refuse - the download is the real
    # work and it does not need Steam's web API to succeed - but a definite
    # "no such item" is, because SteamCMD would report success and download
    # nothing.
    metadata, metadata_error = workshop.lookup(item_ids + list(expanded))
    if metadata_error:
        data['metadata_error'] = metadata_error
    else:
        unknown = [i for i in item_ids
                   if i in metadata and metadata[i].get('found') is False]
        banned = [i for i in item_ids if (metadata.get(i) or {}).get('banned')]
        if unknown or banned:
            data['result'] = 'error'
            reasons = []
            if unknown:
                reasons.append(f"no such Workshop item: {', '.join(unknown)}")
            if banned:
                reasons.append(f"removed from the Workshop: {', '.join(banned)}")
            data['message'] = '; '.join(reasons)
            return False
        data['titles'] = {i: (metadata.get(i) or {}).get('title')
                          for i in item_ids if metadata.get(i)}

    ok, error, output = steam.workshop_download(item_ids, config.STEAM_INSTALL_DIR)
    data['output'] = output
    if not ok:
        data['result'] = 'error'
        data['message'] = error
        return False

    # SteamCMD reports success for an item id that does not exist, so what is
    # on disk afterwards is the only honest answer about what was installed.
    # Sizes measured before this run describe files that have just changed.
    mods.forget_sizes()
    on_disk = set(mods.installed())
    downloaded = [i for i in item_ids if i in on_disk]
    failed = [i for i in item_ids if i not in on_disk]
    data['downloaded'] = downloaded
    data['failed'] = failed
    data['mods'] = {i: mods.item_mods(i) for i in downloaded}

    if failed:
        data['result'] = 'error'
        data['message'] = (f"{len(downloaded)} item(s) downloaded; nothing arrived for: "
                           f"{', '.join(failed)}")
        return False

    # Remember the collections only now, once their contents are really on
    # disk. The order is the thing worth keeping: it is what lets the panel
    # offer "enable all of this, in the author's order" instead of leaving
    # somebody to arrange forty mods by hand.
    for collection_id, children in expanded.items():
        workshop.remember(collection_id,
                          (metadata.get(collection_id) or {}).get('title'),
                          children)

    provided = sum(len(v) for v in data['mods'].values())
    data['result'] = 'success'
    data['message'] = f"{len(downloaded)} Workshop item(s) downloaded, providing {provided} mod(s)"
    return True


ACTIONS = {
    'update_server': update_server,
    'get_app_info': get_app_info,
    'give_reward': give_reward,
    # Same handler, honest name: staff-initiated catalog actions (bans, kicks)
    # are not rewards, and the task list is read by people.
    'run_action': give_reward,
    'backup_world': backup_world,
    'restore_world': restore_world,
    'update_mods': update_mods,
    'download_workshop': download_workshop,
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

def reap_stuck(timeout=None):
    """Fail tasks left in 'processing' longer than ``timeout`` seconds.

    A task is marked 'processing' before its action runs, so a service restart
    mid-task strands it there forever: the pending sweep skips it, `clear()`
    refuses to delete it, and anything waiting on its result (a reward delivery)
    never resolves. Returns the number of tasks failed.
    """
    timeout = config.TASK_PROCESSING_TIMEOUT if timeout is None else timeout
    cutoff = datetime.datetime.now() - datetime.timedelta(seconds=timeout)
    reaped = 0
    with database.get_context_session() as session:
        stuck = (session.query(models.Task)
                 .filter(models.Task.status == 'processing',
                         models.Task.updated_at < cutoff)
                 .all())
        for task in stuck:
            data = task.data if isinstance(task.data, dict) else {}
            data['result'] = 'failure'
            data['message'] = 'Task abandoned (manager restarted while processing)'
            data['ended_at'] = datetime.datetime.now().isoformat()
            task.data = data
            task.status = 'completed'
            reaped += 1
        if reaped:
            session.commit()
    return reaped


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
