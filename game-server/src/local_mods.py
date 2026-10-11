#!/usr/bin/env python3
"""Mods uploaded through the panel instead of downloaded from the Workshop.

They live in the game's own local mods folder, ``$ZOMBOID_DATA_DIR/mods/<Folder>``,
which Project Zomboid scans alongside the Workshop content. A mod there needs no
``WorkshopItems`` entry - only its id in ``Mods`` - and that is why this is a
separate place rather than a made-up Workshop item: SteamCMD would try to update
an invented item id, and the maintenance check would ask the Workshop about it.

What the game does *not* do for a local mod is hand it to players. A client
joining a server whose ``Mods`` names a mod it does not have is refused, so an
uploaded mod suits server-side code, or a group whose players install the same
files themselves. The panel says so where the upload is offered.

Like `mods`, this is offline and dependency-free (stdlib `zipfile`), so the
part worth testing - what an archive is allowed to write, and where - is.
"""
import os
import shutil
import stat
import tempfile
import time
import zipfile

import config
import mods

# An archive with more entries than this is not a mod; it is the wrong folder.
MAX_MEMBERS = 50000
# How much of a `mod.info` is read out of an archive to learn the mod's id.
MOD_INFO_READ_LIMIT = 64 * 1024
# Staging left behind by an upload a restart interrupted is cleared after this.
STALE_STAGING_SECONDS = 3600
CHUNK = 1024 * 1024


def local_dir():
    return os.path.join(config.ZOMBOID_DATA_DIR, 'mods')


def staging_dir():
    """Where an upload is received and unpacked before it is moved into place.

    Beside the mods folder rather than inside it, so the game never scans a half
    unpacked mod, and on the same volume, so moving one in is a rename.
    """
    return os.path.join(config.ZOMBOID_DATA_DIR, '.mod-uploads')


def _mb(n):
    return f'{n // (1024 * 1024)} MB'


def valid_folder(folder):
    """Whether a name can be a folder in the local mods folder.

    The mod-name rule, since the folder name is one of the names a server's
    `Mods` line may use, and no leading dot - that is how `..` and hidden
    staging folders are kept out.
    """
    folder = str(folder or '')
    return (bool(mods.MOD_NAME_RE.match(folder)) and not folder.startswith('.')
            and folder.strip() == folder)


def folder_path(folder):
    """The directory for a local mod, or None if the name is unusable.

    Resolved and checked to sit directly in the mods folder, as `mods.item_dir`
    does and for the same reason: the name arrived over HTTP, and `remove()`
    deletes what it is given.
    """
    if not valid_folder(folder):
        return None
    root = os.path.realpath(local_dir())
    path = os.path.realpath(os.path.join(root, folder))
    if os.path.dirname(path) != root:
        return None
    return path


def describe(folder):
    """One local mod, in the same shape as an entry of `mods.item_mods()`.

    None for a folder that is not a mod (no `mod.info` the game would find).
    """
    path = folder_path(folder)
    if not path or not os.path.isdir(path):
        return None
    info_path = mods.find_mod_info(path)
    if not info_path:
        return None
    info = mods.read_mod_info(info_path)
    mod_id = info.get('id') or folder
    if not mods.MOD_NAME_RE.match(mod_id):
        mod_id = folder
    return {
        'id': mod_id,
        'name': info.get('name') or folder,
        'folder': folder,
        'description': mods._short(info.get('description')),
        'requires': mods.parse_requires(info.get('require')),
        'version': info.get('modversion') or None,
    }


def installed():
    """Every mod in the local mods folder."""
    try:
        names = sorted(os.listdir(local_dir()))
    except OSError:
        return []
    found = (describe(name) for name in names if valid_folder(name))
    return [entry for entry in found if entry]


def _size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def library(name_usage=None):
    """The local mods with their size and which servers load them.

    ``name_usage`` maps mod name -> server names, as `servers.mod_usage()`
    returns it. A server may name a mod by its id or by its folder, so both
    count.
    """
    name_usage = name_usage or {}
    entries = []
    for mod in installed():
        path = folder_path(mod['folder'])
        used = set(name_usage.get(mod['id']) or []) | set(name_usage.get(mod['folder']) or [])
        try:
            updated = int(os.path.getmtime(path))
        except OSError:
            updated = None
        entries.append(dict(mod, size=_size(path), updated_at=updated,
                            used_by=sorted(used)))
    return entries


def remove(folder):
    """Delete a local mod. Returns ``(ok, error)``.

    Refusing while a server still loads it is the caller's job, as with
    `mods.remove`.
    """
    path = folder_path(folder)
    if not path:
        return False, f"'{folder}' is not a mod folder name"
    if not os.path.isdir(path):
        return False, 'That mod is not uploaded'
    try:
        shutil.rmtree(path)
    except OSError as e:
        return False, f'Could not remove the files: {e}'
    return True, None


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------

def _member_parts(info):
    """An archive entry's path as a list of parts, or None if it is unsafe.

    Zip paths are meant to use `/`, but archives made on Windows sometimes use
    `\\`, and on Linux that would be a file name with a backslash in it rather
    than a folder - so both are separators here.
    """
    name = info.filename.replace('\\', '/')
    if name.startswith('/') or ':' in name.split('/')[0]:
        return None
    parts = [part for part in name.split('/') if part not in ('', '.')]
    if '..' in parts:
        return None
    return parts


def _junk(parts):
    """What macOS adds to every zip it makes; never part of a mod."""
    return bool(parts) and parts[0] == '__MACOSX'


def plan(archive):
    """Which mod folders an archive holds. Returns ``(mods, error)``.

    ``mods`` is a list of ``{'prefix', 'folder', 'id', 'name'}``, ``prefix``
    being the archive path of the mod folder as a tuple. People zip whatever
    they have open, so any of these is accepted:

    * ``MyMod/mod.info`` - one mod folder (Build 41)
    * ``MyMod/42/mod.info`` - one mod folder (Build 42)
    * ``Contents/mods/MyMod/...`` - a Workshop upload's layout, at any depth,
      holding one mod or several
    * ``mod.info`` at the top - the inside of a mod folder, named by its id

    The whole archive is refused rather than the bad entry skipped when any
    entry would land outside its folder, is a link, or takes the total past the
    size limit: an archive with one such entry was not made by packing a mod.
    The size is the one the archive declares, which is safe to trust because
    `zipfile` stops reading a member at its declared size.
    """
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        return None, f'The archive has more than {MAX_MEMBERS} entries'

    total = 0
    by_root = {}
    for info in infos:
        parts = _member_parts(info)
        if parts is None:
            return None, f"'{info.filename[:120]}' points outside the archive"
        if stat.S_ISLNK(info.external_attr >> 16):
            return None, f"'{info.filename[:120]}' is a link, which a mod has no need of"
        if _junk(parts):
            continue
        total += info.file_size
        if total > config.MOD_UPLOAD_MAX_EXTRACTED_BYTES:
            return None, ('The archive unpacks to more than '
                          f'{_mb(config.MOD_UPLOAD_MAX_EXTRACTED_BYTES)}')
        # Exactly `mod.info`: the game looks for that name on a case-sensitive
        # file system, so a `Mod.info` would be a mod it never sees.
        if info.is_dir() or not parts or parts[-1] != 'mod.info':
            continue
        root = parts[:-1]
        if root and (mods.VERSION_DIR_RE.match(root[-1]) or root[-1] == 'common'):
            root = root[:-1]
        by_root.setdefault(tuple(root), []).append((parts, info))

    if not by_root:
        return None, ('There is no mod.info in the archive. A mod is a folder '
                      'with a mod.info in it - or in its 42 folder, for Build 42.')

    # A mod.info inside a mod that already has one is part of that mod.
    roots = []
    for root in sorted(by_root, key=len):
        if not any(root[:len(kept)] == kept for kept in roots):
            roots.append(root)

    planned = []
    seen = set()
    for root in roots:
        # The info the game would read, in `mods.find_mod_info`'s order: the
        # newest version folder's, else the top of the folder, else common/'s.
        def rank(entry):
            sub = entry[0][len(root):-1]
            if sub and mods.VERSION_DIR_RE.match(sub[0]):
                return (2, mods.version_key(sub[0]))
            if not sub:
                return (1, ())
            return (0, ())
        _parts, info = max(by_root[root], key=rank)
        try:
            with archive.open(info) as handle:
                text = handle.read(MOD_INFO_READ_LIMIT).decode('utf-8', 'replace')
        except (RuntimeError, NotImplementedError, zipfile.BadZipFile, OSError) as e:
            return None, f'Could not read {info.filename[:120]}: {e}'
        values = mods.parse_mod_info(text.splitlines())

        mod_id = values.get('id')
        folder = root[-1] if root else mod_id
        if not folder:
            return None, ('mod.info is at the top of the archive and declares no '
                          'id= to name the mod by. Zip the mod folder itself.')
        if not valid_folder(folder):
            return None, (f"'{folder[:96]}' cannot be a mod folder name - letters, "
                          "digits, spaces, '.', '_' and '-' only")
        if folder in seen:
            return None, f"The archive holds two mods in folders named '{folder}'"
        seen.add(folder)
        if not mod_id or not mods.MOD_NAME_RE.match(mod_id):
            mod_id = folder
        planned.append({'prefix': root, 'folder': folder, 'id': mod_id,
                        'name': values.get('name') or folder})
    return planned, None


def _extract(archive, planned, dest):
    """Write each planned mod to ``dest/<folder>``. Entries outside them are left."""
    for info in archive.infolist():
        parts = _member_parts(info)
        if not parts or _junk(parts):
            continue
        for mod in planned:
            depth = len(mod['prefix'])
            if tuple(parts[:depth]) == mod['prefix'] and len(parts) > depth:
                break
        else:
            continue

        base = os.path.realpath(os.path.join(dest, mod['folder']))
        target = os.path.join(base, *parts[depth:])
        # Already refused by plan(); checked again because this is the line
        # that writes.
        if not os.path.realpath(target).startswith(base + os.sep):
            raise ValueError(f"'{info.filename[:120]}' points outside its folder")
        if info.is_dir():
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with archive.open(info) as source, open(target, 'wb') as out:
            shutil.copyfileobj(source, out, CHUNK)


def _clear_stale():
    """Remove staging an interrupted upload left behind."""
    root = staging_dir()
    try:
        names = os.listdir(root)
    except OSError:
        return
    cutoff = time.time() - STALE_STAGING_SECONDS
    for name in names:
        path = os.path.join(root, name)
        try:
            if os.path.getmtime(path) >= cutoff:
                continue
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        except OSError:
            continue


def _receive(stream, path):
    """Copy an upload to disk, stopping at the size limit. Returns an error or None."""
    written = 0
    with open(path, 'wb') as out:
        while True:
            chunk = stream.read(CHUNK)
            if not chunk:
                return None
            written += len(chunk)
            if written > config.MOD_UPLOAD_MAX_BYTES:
                return f'The file is larger than {_mb(config.MOD_UPLOAD_MAX_BYTES)}'
            out.write(chunk)


def upload(stream, filename, replace=False, reserved=()):
    """Install the mods in an uploaded .zip. Returns ``(installed, error, conflicts)``.

    ``installed`` lists the mods as `describe()` reports them. ``conflicts``
    names folders that are already uploaded, when ``replace`` is false - the
    caller asks before overwriting somebody's mod with another copy.

    ``reserved`` is every name a downloaded Workshop mod answers to. A local
    mod sharing one would leave the game choosing between two mods by one name,
    so that is refused rather than replaced.

    Everything is unpacked to staging first and each mod moved in by a rename,
    so the game never sees a half-written mod, and a mod being replaced is put
    back if its replacement cannot be moved in.
    """
    if not str(filename or '').lower().endswith('.zip'):
        return None, 'Upload the mod as a .zip archive', []

    os.makedirs(staging_dir(), exist_ok=True)
    os.makedirs(local_dir(), exist_ok=True)
    _clear_stale()
    work = tempfile.mkdtemp(dir=staging_dir())
    try:
        archive_path = os.path.join(work, 'upload.zip')
        error = _receive(stream, archive_path)
        if error:
            return None, error, []
        try:
            archive = zipfile.ZipFile(archive_path)
        except (zipfile.BadZipFile, OSError):
            return None, 'That file is not a valid .zip archive', []

        with archive:
            planned, error = plan(archive)
            if error:
                return None, error, []

            names = {m['id'] for m in planned} | {m['folder'] for m in planned}
            clashes = sorted(names & set(reserved))
            if clashes:
                return None, ('A downloaded Workshop mod already goes by '
                              + ', '.join(clashes) + '. Remove one of the two.'), []

            folders = {m['folder'] for m in planned}
            for other in installed():
                if other['folder'] in folders:
                    continue
                taken = {other['id'], other['folder']} & names
                if taken:
                    return None, (f"The uploaded mod in '{other['folder']}' already "
                                  f"goes by {', '.join(sorted(taken))}"), []

            existing = sorted(f for f in folders if os.path.lexists(os.path.join(local_dir(), f)))
            if existing and not replace:
                return None, 'Already uploaded: ' + ', '.join(existing), existing

            try:
                _extract(archive, planned, os.path.join(work, 'new'))
            except (OSError, ValueError, RuntimeError, NotImplementedError,
                    zipfile.BadZipFile) as e:
                return None, f'Could not unpack the archive: {e}', []

        done = []
        for mod in planned:
            target = folder_path(mod['folder'])
            if not target:
                return done, f"Could not place '{mod['folder']}'", []
            aside = None
            try:
                if os.path.lexists(target):
                    aside = os.path.join(work, 'old', mod['folder'])
                    os.makedirs(os.path.dirname(aside), exist_ok=True)
                    os.rename(target, aside)
                try:
                    os.rename(os.path.join(work, 'new', mod['folder']), target)
                except OSError:
                    if aside:
                        os.rename(aside, target)
                    raise
            except OSError as e:
                return done, f"Could not move '{mod['folder']}' into place: {e}", []
            entry = describe(mod['folder'])
            if entry:
                done.append(entry)
        return done, None, []
    finally:
        shutil.rmtree(work, ignore_errors=True)
