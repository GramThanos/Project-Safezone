#!/usr/bin/env python3
"""Steam Workshop mods for a server.

Project Zomboid needs two lists that are easy to confuse and easy to get wrong:

* ``WorkshopItems`` - numeric Workshop **item** ids. What SteamCMD downloads.
* ``Mods`` - the mod **names** declared inside those items. What the game loads.

They are not the same thing and one Workshop item can contain several mods,
which is why a server can have every file on disk and still not load a mod: the
ids downloaded fine and the name is missing or misspelled. Both lists are edited
together here so that failure mode is at least visible.

**Assumption to verify on a real install.** Downloaded content is expected under
``$STEAM_INSTALL_DIR/steamapps/workshop/content/<app id>/<item id>``, which is
SteamCMD's documented layout. `installed()` reports what is actually on disk so
a mismatch between "configured" and "downloaded" can be seen rather than guessed.
"""
import os
import re
import shutil

import config

# The Workshop app id for content is Project Zomboid's own app id.
WORKSHOP_APP_ID = '108600'

# `\Z`, not `$`. In Python `$` also matches just before a trailing newline, so
# an id or a name ending in one passes a check whose entire purpose is to keep
# newlines out of a file the game parses line by line. Callers happen to strip
# their input today; that is not a guarantee worth resting this on.
ITEM_ID_RE = re.compile(r'^[0-9]{1,20}\Z')
# Mod names are folder names inside a Workshop item.
MOD_NAME_RE = re.compile(r'^[A-Za-z0-9_.\- ]{1,96}\Z')


def parse_list(raw):
    """Split a `a;b;c` INI list into clean parts."""
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(';') if part.strip()]


def join_list(parts):
    return ';'.join(parts)


def validate(workshop_ids, mod_names):
    """Returns an error string, or None.

    Validated because both lists are written into a file the game parses, and a
    stray separator or newline there turns one entry into two.
    """
    for item in workshop_ids:
        if not ITEM_ID_RE.match(item):
            return f"'{item}' is not a Workshop item id (they are numeric)"
    for name in mod_names:
        if not MOD_NAME_RE.match(name):
            return f"'{name}' is not a valid mod name"
    if len(set(workshop_ids)) != len(workshop_ids):
        return 'the same Workshop id is listed more than once'
    if len(set(mod_names)) != len(mod_names):
        return 'the same mod name is listed more than once'
    return None


def content_dir():
    return os.path.join(config.STEAM_INSTALL_DIR, 'steamapps', 'workshop',
                        'content', WORKSHOP_APP_ID)


def installed():
    """Workshop item ids present on disk."""
    root = content_dir()
    if not os.path.isdir(root):
        return []
    return sorted(name for name in os.listdir(root) if ITEM_ID_RE.match(name))


def _short(text, limit=200):
    """One short line of plain text, or None.

    `mod.info` descriptions are free-form and occasionally enormous; a table
    needs a sentence. Kept here rather than shared with the Workshop lookup so
    this module stays offline and dependency-free.
    """
    collapsed = ' '.join(str(text or '').split())
    if not collapsed:
        return None
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[:limit].rsplit(' ', 1)[0] or collapsed[:limit]
    return cut.rstrip(' .,;:') + '…'


def read_mod_info(path):
    """Parse a `mod.info` file into a dict.

    The format is flat `key=value` with `#` comments, same shape as the server
    INI. Only the first occurrence of a key wins, and values keep their spaces
    because mod titles contain them.
    """
    values = {}
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                key = key.strip().lower()
                if key and key not in values:
                    values[key] = value.strip()
    except OSError:
        return {}
    return values


def parse_requires(raw):
    """Split a `require=A,B` line into mod ids.

    Comma-separated here, unlike the server INI's semicolons - two formats for
    the same idea, which is exactly the sort of thing that gets written once and
    then guessed at forever.
    """
    if not raw:
        return []
    parts = []
    for part in str(raw).replace(';', ',').split(','):
        part = part.strip()
        if part and part not in parts:
            parts.append(part)
    return parts


def check_requirements(mod_names, provided):
    """Problems with a load order. Returns a list of ``{mod, requires, problem}``.

    Two failures are worth catching, and they are the reason load order is a
    setting rather than a detail:

    * ``missing`` - a mod needs something that is not in the list at all.
    * ``order`` - it is in the list, but after the mod that needs it. Project
      Zomboid loads `Mods` top to bottom, so this loads a dependency too late.

    ``provided`` maps **every name a mod answers to** - its declared id and its
    folder name both - to the mod entry, as `status()` builds it. Both are
    accepted in a server's `Mods` line and a `require=` may name either, so the
    two sides are reduced to a canonical id before being compared. Without that
    a server configured by folder name gets told its dependencies are missing
    when they are sitting right there.

    Anything a downloaded item does not provide is skipped rather than reported
    here: an unknown name is already reported by `status()` as
    `unknown_mod_names`, and saying it twice in different words helps nobody.
    """
    def canonical(name):
        entry = provided.get(name)
        return entry['id'] if entry else name

    position = {}
    for index, name in enumerate(mod_names):
        # First occurrence wins, so a duplicated entry cannot make a dependency
        # that loads early look like one that loads late.
        position.setdefault(canonical(name), index)

    problems = []
    for index, name in enumerate(mod_names):
        entry = provided.get(name)
        if not entry:
            continue
        for required in entry.get('requires') or []:
            key = canonical(required)
            if key not in position:
                problems.append({'mod': name, 'requires': required,
                                 'problem': 'missing'})
            elif position[key] > index:
                problems.append({'mod': name, 'requires': required,
                                 'problem': 'order'})
    return problems


def item_mods(item_id):
    """The mods a downloaded Workshop item provides, with their real names.

    Each entry is ``{'id', 'name', 'folder', 'description', 'requires'}``. ``id``
    is what belongs in the server's `Mods` line - taken from `mod.info` where it
    declares one, because
    the folder name and the declared id are allowed to differ and only the
    declared id is what the game matches on. ``name`` is the human title, which
    exists so nobody has to recognise a mod by an id like `BritaWeaponPack`.
    """
    if not ITEM_ID_RE.match(str(item_id)):
        return []
    root = os.path.join(content_dir(), str(item_id))
    if not os.path.isdir(root):
        return []

    found = {}
    # Layouts vary: <item>/mods/<Mod>/mod.info and <item>/<Mod>/mod.info both
    # occur in the wild, so look one level down as well as at the top.
    for base in (root, os.path.join(root, 'mods')):
        if not os.path.isdir(base):
            continue
        try:
            entries = sorted(os.listdir(base))
        except OSError:
            continue
        for folder in entries:
            info_path = os.path.join(base, folder, 'mod.info')
            if not os.path.isfile(info_path):
                continue
            info = read_mod_info(info_path)
            mod_id = info.get('id') or folder
            if not MOD_NAME_RE.match(mod_id):
                # A mod declaring an id we could not write into the INI safely
                # is reported under its folder name instead of being dropped.
                mod_id = folder
            found.setdefault(mod_id, {
                'id': mod_id,
                'name': info.get('name') or folder,
                'folder': folder,
                'description': _short(info.get('description')),
                # What this mod needs loaded before it. `require=` is a
                # comma-separated list of mod ids.
                'requires': parse_requires(info.get('require')),
            })
    return [found[key] for key in sorted(found)]


def mods_in_item(item_id):
    """Every name a downloaded item answers to, for mismatch checking.

    Both the declared id and the folder name are returned on purpose: a server
    configured with either one loads the mod, so warning about the other would
    be a false alarm. Use `item_mods()` when the caller wants one canonical
    entry per mod to display or offer.
    """
    names = set()
    for mod in item_mods(item_id):
        names.add(mod['id'])
        names.add(mod['folder'])
    return sorted(names)


def status(workshop_ids, mod_names):
    """Compare what is configured against what is on disk.

    The point of this is the mismatch: a server whose ids downloaded but whose
    mod names are wrong looks completely healthy until nobody can connect.
    """
    on_disk = set(installed())
    configured = set(str(i) for i in workshop_ids)

    available = set()
    # Keyed by every name the mod answers to, matching what `available` accepts:
    # a server may configure a mod by its declared id or by its folder name, and
    # the dependency check has to recognise both or it invents problems.
    provided = {}
    for item in configured & on_disk:
        available.update(mods_in_item(item))
        for mod in item_mods(item):
            provided.setdefault(mod['id'], mod)
            provided.setdefault(mod['folder'], mod)

    return {
        'workshop_ids': sorted(configured),
        'mod_names': list(mod_names),
        'installed_ids': sorted(on_disk),
        'missing_ids': sorted(configured - on_disk),
        'available_mod_names': sorted(available),
        # Names the server is told to load that no downloaded item provides.
        # This is the one that silently breaks a server.
        'unknown_mod_names': sorted(n for n in mod_names if available and n not in available),
        # Dependencies declared by the mods themselves, checked against the
        # order they are actually loaded in.
        'requirement_problems': check_requirements(list(mod_names), provided),
    }


# Accepts what an admin actually has in their clipboard: the Workshop page URL.
_URL_ID_RE = re.compile(r'[?&]id=([0-9]{1,20})\b')


def resolve_item_id(text):
    """Turn what somebody pasted into a Workshop item id.

    Returns ``(item_id, error)``. Both the bare id and the full
    `steamcommunity.com/sharedfiles/filedetails/?id=...` URL are accepted,
    because the id alone is not what a browser puts on the clipboard.
    """
    raw = str(text or '').strip()
    if not raw:
        return None, 'No Workshop item given'
    if ITEM_ID_RE.match(raw):
        return raw, None
    match = _URL_ID_RE.search(raw)
    if match:
        return match.group(1), None
    return None, f"Could not find a Workshop item id in '{raw[:80]}'"


def item_dir(item_id):
    """The on-disk directory for a Workshop item, or None if the id is unusable.

    The path is resolved and checked to be inside the content directory before
    it is returned. Every caller here builds a filesystem path from a value that
    arrived over HTTP, so containment is verified once, here, rather than
    trusted to the id pattern alone.
    """
    if not ITEM_ID_RE.match(str(item_id)):
        return None
    root = os.path.realpath(content_dir())
    path = os.path.realpath(os.path.join(root, str(item_id)))
    if path != root and not path.startswith(root + os.sep):
        return None
    return path


# Sizes are memoised, keyed on the item directory's mtime. Measuring one means
# walking every file it contains, a large mod pack is tens of thousands of them,
# and the panel asks for the whole library on every poll - so without this a
# page left open re-walks the entire Workshop tree every five seconds, competing
# for the disk with the SteamCMD download it is watching.
_SIZE_CACHE = {}


def forget_sizes(item_id=None):
    """Drop memoised sizes, for one item or all of them.

    Called after this service changes the files itself. The mtime key catches a
    directory whose entries changed, but a download that only rewrites existing
    files inside can leave the top-level mtime alone.
    """
    if item_id is None:
        _SIZE_CACHE.clear()
    else:
        _SIZE_CACHE.pop(str(item_id), None)


def item_size(item_id):
    """Bytes on disk for one Workshop item, or None if it is not downloaded."""
    path = item_dir(item_id)
    if not path or not os.path.isdir(path):
        return None

    try:
        stamp = os.path.getmtime(path)
    except OSError:
        stamp = None

    cached = _SIZE_CACHE.get(str(item_id))
    if cached and stamp is not None and cached[0] == stamp:
        return cached[1]

    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    if stamp is not None:
        _SIZE_CACHE[str(item_id)] = (stamp, total)
    return total


def content_size():
    """Bytes used by all downloaded Workshop content.

    Summed from the per-item sizes rather than walked separately, so the whole
    tree is measured once and the memo above serves both this and the library.
    """
    total = 0
    for item_id in installed():
        total += item_size(item_id) or 0
    return total


def library(usage=None, metadata=None):
    """Everything downloaded, independent of any one server.

    One install directory is shared by every server in the stack, so the set of
    downloaded items is a property of the host and not of a server - which is
    why this exists separately from `status()`.

    ``usage`` optionally maps item id -> list of server names that reference it,
    so the panel can say what a mod is for and refuse to delete one still in use.

    ``metadata`` optionally maps item id -> the Workshop item's own details. It
    is passed in rather than fetched here so this module stays offline: a host
    with no outbound HTTP still gets a full library listing, just without titles.
    """
    usage = usage or {}
    metadata = metadata or {}
    entries = []
    for item_id in installed():
        path = item_dir(item_id)
        updated = None
        if path and os.path.isdir(path):
            try:
                updated = int(os.path.getmtime(path))
            except OSError:
                updated = None
        entries.append({
            'id': item_id,
            'mods': item_mods(item_id),
            'size': item_size(item_id),
            'updated_at': updated,
            'used_by': sorted(usage.get(item_id, [])),
            'workshop': metadata.get(item_id),
        })
    return entries


def remove(item_id):
    """Delete a downloaded Workshop item. Returns ``(ok, error)``.

    Deleting files a server is configured to load would leave it starting
    against a mod list it cannot satisfy, so refusing that is the caller's job -
    this only refuses what it can see for itself: an id it cannot resolve to a
    path inside the content directory.
    """
    path = item_dir(item_id)
    if not path:
        return False, f"'{item_id}' is not a Workshop item id"
    if not os.path.isdir(path):
        return False, 'That Workshop item is not downloaded'
    try:
        shutil.rmtree(path)
    except OSError as e:
        return False, f'Could not remove the files: {e}'
    forget_sizes(item_id)
    return True, None
