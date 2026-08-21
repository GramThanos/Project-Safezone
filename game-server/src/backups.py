#!/usr/bin/env python3
"""World backups: archive a server's save directory, and put it back.

The manager already owns the server's process lifecycle, which is what makes a
*clean* backup possible: it can tell the running server to flush to disk and
wait for that to land before reading the files.

Layout assumption
-----------------
Project Zomboid keeps dedicated-server saves under
``$ZOMBOID_DATA_DIR/Saves/Multiplayer/<server name>``. Both parts are
configurable (`ZOMBOID_DATA_DIR`, `BACKUP_DIR`) because that path is the one
thing here most likely to differ between installs - if backups come back empty,
check it before anything else.

Backups live in their own directory, which should be its own volume. A backup
sharing a volume with the thing it protects is not a backup.

Safety
------
Restoring extracts an archive, and a tar can name paths outside its root. Every
member is checked before extraction rather than trusting the archive, and the
live save is moved aside rather than deleted, so a restore that turns out to be
the wrong one is still recoverable.
"""
import datetime
import os
import re
import shutil
import tarfile

import config

# A backup file name is derived from a timestamp, so it needs no sanitising -
# but a *requested* one arrives from the API and does.
ARCHIVE_RE = re.compile(r'^[0-9]{8}-[0-9]{6}(-[A-Za-z0-9_-]{1,32})?\.tar\.gz$')


def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Backups] {message}")


def save_dir(server_name):
    """Where a server's world lives, or None if the name is unusable."""
    import logs  # shared name validation - a name that cannot be a log path
    if not logs.is_safe_name(server_name):
        return None
    return os.path.join(config.ZOMBOID_DATA_DIR, 'Saves', 'Multiplayer', server_name)


def backup_dir(server_name):
    """Where a server's archives live, or None if the name is unusable."""
    import logs
    if not logs.is_safe_name(server_name):
        return None
    return os.path.join(config.BACKUP_DIR, server_name)


def list_backups(server_name):
    """Archives for a server, newest first."""
    directory = backup_dir(server_name)
    if not directory or not os.path.isdir(directory):
        return []

    out = []
    for name in os.listdir(directory):
        if not ARCHIVE_RE.match(name):
            continue
        path = os.path.join(directory, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        out.append({
            'name': name,
            'bytes': stat.st_size,
            'created_at': datetime.datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        })
    out.sort(key=lambda b: b['name'], reverse=True)
    return out


def create(server_name, note=None):
    """Archive a server's save directory. Returns ``(archive_name, error)``.

    The caller is responsible for quiescing the server first - see
    `tasks.backup_world`, which flushes and waits before calling this.
    """
    source = save_dir(server_name)
    target_dir = backup_dir(server_name)
    if not source or not target_dir:
        return None, 'That server name cannot be used for backups'
    if not os.path.isdir(source):
        return None, f'No save directory at {source} - has this server ever run?'

    suffix = ''
    if note:
        cleaned = re.sub(r'[^A-Za-z0-9_-]', '', str(note))[:32]
        if cleaned:
            suffix = f'-{cleaned}'

    stamp = datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    name = f'{stamp}{suffix}.tar.gz'

    try:
        os.makedirs(target_dir, exist_ok=True)
        # Write to a partial name first: a half-written archive that looks like
        # a real one is worse than no archive, because it will be trusted.
        partial = os.path.join(target_dir, name + '.partial')
        with tarfile.open(partial, 'w:gz') as archive:
            archive.add(source, arcname='.')
        os.replace(partial, os.path.join(target_dir, name))
    except Exception as e:
        _log(f"Backup of '{server_name}' failed: {e}")
        return None, f'Backup failed: {e}'

    return name, None


def prune(server_name, keep):
    """Delete all but the newest `keep` archives. Returns how many went."""
    try:
        keep = int(keep)
    except (TypeError, ValueError):
        return 0
    if keep <= 0:
        return 0

    directory = backup_dir(server_name)
    if not directory:
        return 0

    removed = 0
    for entry in list_backups(server_name)[keep:]:
        try:
            os.remove(os.path.join(directory, entry['name']))
            removed += 1
        except OSError as e:
            _log(f"Could not remove {entry['name']}: {e}")
    return removed


def _is_safe_member(member, root):
    """Whether a tar member stays inside `root` once extracted."""
    if member.issym() or member.islnk():
        # A link can point anywhere once followed; a world save has no need of one.
        return False
    destination = os.path.realpath(os.path.join(root, member.name))
    return destination == root or destination.startswith(root + os.sep)


def restore(server_name, archive_name):
    """Replace a server's save directory from an archive.

    Returns ``(kept_aside_path, error)``. The caller must ensure the server is
    stopped: restoring under a running server would have it writing into a
    directory being replaced beneath it.
    """
    directory = backup_dir(server_name)
    destination = save_dir(server_name)
    if not directory or not destination:
        return None, 'That server name cannot be used for backups'
    if not ARCHIVE_RE.match(str(archive_name or '')):
        return None, 'That is not a valid backup name'

    path = os.path.join(directory, archive_name)
    if not os.path.isfile(path):
        return None, 'No such backup'

    root = os.path.realpath(destination)
    staging = destination + '.restoring'
    kept_aside = None

    try:
        if os.path.exists(staging):
            shutil.rmtree(staging)
        os.makedirs(staging, exist_ok=True)
        staging_root = os.path.realpath(staging)

        with tarfile.open(path, 'r:gz') as archive:
            members = archive.getmembers()
            for member in members:
                if not _is_safe_member(member, staging_root):
                    return None, f'Refusing to restore: archive contains an unsafe path ({member.name})'
            archive.extractall(staging)

        # Keep the old world rather than deleting it: a restore of the wrong
        # archive is a mistake somebody should be able to walk back.
        if os.path.isdir(destination):
            kept_aside = f'{destination}.replaced-{datetime.datetime.utcnow():%Y%m%d-%H%M%S}'
            os.replace(destination, kept_aside)

        os.replace(staging, destination)
        _ = root  # the realpath check above is what mattered
    except Exception as e:
        _log(f"Restore of '{server_name}' failed: {e}")
        return None, f'Restore failed: {e}'
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)

    return kept_aside, None
