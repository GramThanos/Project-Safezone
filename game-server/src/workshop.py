#!/usr/bin/env python3
"""Steam Workshop item metadata - titles, summaries and whether an id is real.

Three things are worth separating, because they answer different questions and
cost different amounts:

* ``mod.info`` on disk gives the **mod** name and description. Free, offline,
  and only available after the item is downloaded. See :mod:`mods`.
* This module gives the **Workshop item** title and description, for *any* id,
  before anything is downloaded. One HTTP call, no API key.
* Browsing or searching the Workshop for items you do not already have an id
  for needs `IPublishedFileService/QueryFiles`, which does need a Steam Web API
  key. Not done here.

The item title and the mod name are not the same thing and routinely differ - an
item called "Brita's Armor Pack" can contain a mod named ``Brita_Armor_Base`` -
so both are shown rather than one being treated as the other.

`GetPublishedFileDetails` is keyless and long-standing, but it is not part of
Steam's documented partner API, so everything here degrades to "no metadata"
rather than failing: a panel that cannot reach Steam must still list what is on
disk and still let an admin download by id.

Uses `urllib` rather than `requests` deliberately - the game-server image pins a
deliberately small dependency set, and this needs one POST.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import datetime

import config
import cache


def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Workshop] {message}")

# Steam rejects very large batches; this is well inside anything it minds and
# keeps one slow request from holding up a page load.
BATCH_SIZE = 50

# `result` codes on an individual entry. 1 is EResultOK; 9 is EResultFileNotFound,
# which is what a mistyped id comes back as and is the check worth having.
RESULT_OK = 1
RESULT_NOT_FOUND = 9

_BBCODE_RE = re.compile(r'\[/?[a-zA-Z][^\]]{0,64}\]')
_WHITESPACE_RE = re.compile(r'\s+')
# Tags are replaced with a space so `word[b]word[/b]` does not become one word,
# which leaves a gap before any punctuation that followed a closing tag.
_SPACED_PUNCTUATION_RE = re.compile(r'\s+([.,;:!?)\]])')

CACHE_PREFIX = 'workshop:item:'


def summarize(description, limit=280):
    """A Workshop description turned into one short line of plain text.

    Descriptions are BBCode and can run to several screens; a table needs a
    sentence. Tags are stripped rather than rendered because this text is placed
    into a page, and the markup is somebody else's to control.
    """
    text = _BBCODE_RE.sub(' ', str(description or ''))
    text = _WHITESPACE_RE.sub(' ', text)
    text = _SPACED_PUNCTUATION_RE.sub(r'\1', text).strip()
    if len(text) <= limit:
        return text
    # Trim on a word boundary so the ellipsis does not land mid-word.
    cut = text[:limit].rsplit(' ', 1)[0]
    return (cut or text[:limit]).rstrip(' .,;:') + '…'


def parse_details(payload):
    """Turn a GetPublishedFileDetails response into ``{id: entry}``.

    Pure, so the shape this depends on is testable without touching the network.
    An entry always carries ``found``: an id Steam does not know is a real,
    useful answer, not an error, and it is the one that stops a pointless
    several-minute SteamCMD run.
    """
    entries = {}
    response = (payload or {}).get('response') or {}
    for detail in response.get('publishedfiledetails') or []:
        if not isinstance(detail, dict):
            continue
        item_id = str(detail.get('publishedfileid') or '').strip()
        if not item_id:
            continue

        result = detail.get('result')
        found = result == RESULT_OK
        banned = bool(detail.get('banned'))

        def _int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        entries[item_id] = {
            'id': item_id,
            'found': found,
            'banned': banned,
            'ban_reason': detail.get('ban_reason') or None,
            'title': (detail.get('title') or None) if found else None,
            'summary': summarize(detail.get('description')) if found else None,
            'preview_url': (detail.get('preview_url') or None) if found else None,
            'size': _int(detail.get('file_size')),
            'created': _int(detail.get('time_created')),
            'updated': _int(detail.get('time_updated')),
            'subscriptions': _int(detail.get('lifetime_subscriptions')),
            'tags': [t.get('tag') for t in (detail.get('tags') or [])
                     if isinstance(t, dict) and t.get('tag')],
            # Steam's own word for "this id does not exist", kept so a caller can
            # tell a typo from a network problem.
            'result': result,
        }
    return entries


def _post(url, fields):
    """One form-encoded POST to Steam. Returns ``(payload, error)``.

    Every failure is turned into a message rather than an exception: nothing
    here is important enough to break a page over, and the callers all have a
    reasonable answer for "no metadata".
    """
    body = urllib.parse.urlencode(fields).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=config.WORKSHOP_API_TIMEOUT) as response:
            return json.loads(response.read().decode('utf-8', errors='replace')), None
    except urllib.error.HTTPError as e:
        return None, f'Steam returned HTTP {e.code}'
    except urllib.error.URLError as e:
        return None, f'Could not reach Steam: {e.reason}'
    except (TimeoutError, OSError) as e:
        return None, f'Could not reach Steam: {e}'
    except json.JSONDecodeError:
        return None, 'Steam returned something that was not JSON'


def _fetch(item_ids):
    """One call to Steam for a batch of item ids. Returns ``(entries, error)``."""
    fields = [('itemcount', str(len(item_ids)))]
    fields.extend((f'publishedfileids[{i}]', str(item))
                  for i, item in enumerate(item_ids))

    payload, error = _post(config.WORKSHOP_API_URL, fields)
    if error:
        return {}, error
    return parse_details(payload), None


def parse_collections(payload):
    """Turn a GetCollectionDetails response into ``{collection id: [item ids]}``.

    Children come back with a `sortorder`, which is the order the collection's
    author put them in. That is worth preserving: for a Project Zomboid
    collection it is frequently the intended *load* order, and throwing it away
    would hand somebody a correct set of mods in an order that does not work.

    Only ``filetype`` 0 - a plain Workshop item - is returned. A collection can
    contain other collections, and following those automatically would let one
    paste pull in hundreds of mods nobody looked at.
    """
    collections = {}
    response = (payload or {}).get('response') or {}
    for detail in response.get('collectiondetails') or []:
        if not isinstance(detail, dict):
            continue
        collection_id = str(detail.get('publishedfileid') or '').strip()
        if not collection_id:
            continue
        # A non-collection id answers with result 9 here, which is exactly how
        # an item id is told apart from a collection id without asking anyone.
        if detail.get('result') != RESULT_OK:
            continue

        children = [c for c in (detail.get('children') or []) if isinstance(c, dict)]

        def _order(child):
            try:
                return int(child.get('sortorder'))
            except (TypeError, ValueError):
                return 0

        items = []
        for child in sorted(children, key=_order):
            if int(child.get('filetype') or 0) != 0:
                continue
            child_id = str(child.get('publishedfileid') or '').strip()
            if child_id and child_id not in items:
                items.append(child_id)
        collections[collection_id] = items
    return collections


def collections(collection_ids):
    """Expand Workshop collection ids into the items they contain.

    Returns ``({collection id: [item ids]}, error)``, containing only the ids
    that really are collections - an ordinary item id is simply absent, which is
    how a caller tells the two apart.

    This is the keyless way to get a *list* of mods out of the Workshop. Search
    proper (`IPublishedFileService/QueryFiles`) needs a Steam Web API key;
    a collection is somebody else's curated list and needs nothing.
    """
    wanted = []
    for raw in collection_ids or []:
        item_id = str(raw).strip()
        if item_id and item_id not in wanted:
            wanted.append(item_id)
    if not wanted or not config.WORKSHOP_METADATA:
        return {}, None

    found = {}
    error = None
    for start in range(0, len(wanted), BATCH_SIZE):
        batch = wanted[start:start + BATCH_SIZE]
        fields = [('collectioncount', str(len(batch)))]
        fields.extend((f'publishedfileids[{i}]', item)
                      for i, item in enumerate(batch))

        payload, batch_error = _post(config.WORKSHOP_COLLECTION_API_URL, fields)
        if batch_error:
            error = batch_error
            break
        found.update(parse_collections(payload))

    return found, error


def lookup(item_ids, use_cache=True):
    """Metadata for Workshop item ids. Returns ``(entries, error)``.

    ``entries`` maps id -> entry for everything that could be resolved, and is
    partial rather than empty when only some ids came back. ``error`` is set
    when Steam could not be reached at all, so a caller can say "no metadata"
    instead of "this mod does not exist" - those mean very different things to
    somebody about to delete a mod.
    """
    wanted = []
    for raw in item_ids or []:
        item_id = str(raw).strip()
        if item_id and item_id not in wanted:
            wanted.append(item_id)
    if not wanted:
        return {}, None
    if not config.WORKSHOP_METADATA:
        return {}, None

    entries = {}
    missing = wanted
    if use_cache:
        missing = []
        for item_id in wanted:
            raw = cache.get_value(f'{CACHE_PREFIX}{item_id}')
            if raw:
                try:
                    entries[item_id] = json.loads(raw)
                    continue
                except (json.JSONDecodeError, TypeError):
                    pass
            missing.append(item_id)

    error = None
    for start in range(0, len(missing), BATCH_SIZE):
        batch = missing[start:start + BATCH_SIZE]
        fetched, batch_error = _fetch(batch)
        if batch_error:
            # Keep whatever earlier batches produced; a partial answer beats none.
            error = batch_error
            break
        entries.update(fetched)
        if use_cache:
            for item_id, entry in fetched.items():
                # A "not found" is cached briefly, not for a day: the usual cause
                # is a typo being corrected within the minute, and the second
                # cause is a mod that was private and has just been published.
                ttl = (config.WORKSHOP_CACHE_TTL if entry.get('found')
                       else config.WORKSHOP_MISS_CACHE_TTL)
                cache.set_value(f'{CACHE_PREFIX}{item_id}', json.dumps(entry), ttl=ttl)

    return entries, error


def forget(item_id):
    """Drop a cached entry, so a re-check asks Steam again."""
    r = cache.get_instance()
    if not r:
        return False
    try:
        r.delete(f'{CACHE_PREFIX}{item_id}')
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Remembering collections
#
# Steam can always be asked again, so what is stored is not the data but the
# *decision*: this panel installed from this collection, and here is the order
# its author put things in. That is what makes "enable all of this, in order" a
# button rather than forty clicks, and it has to keep working when Steam is
# unreachable - which is exactly when somebody is fixing a server.
# ---------------------------------------------------------------------------

def remember(collection_id, title, item_ids):
    """Record a collection and its order. Upserts; returns True on success."""
    import database
    import models

    collection_id = str(collection_id).strip()
    if not collection_id:
        return False
    try:
        with database.get_context_session() as session:
            row = (session.query(models.WorkshopCollection)
                   .filter(models.WorkshopCollection.id == collection_id).first())
            if row:
                row.title = title or row.title
                row.items = list(item_ids)
            else:
                session.add(models.WorkshopCollection(
                    id=collection_id, title=title, items=list(item_ids)))
            session.commit()
            return True
    except Exception as e:
        # A collection that could not be recorded is a lost convenience, not a
        # failed download. The install it accompanied must not fail over this -
        # but it is said out loud, because the symptom otherwise is a button
        # that never appears.
        _log(f"Could not record collection {collection_id}: {e}")
        return False


def known():
    """Every remembered collection, newest first."""
    import database
    import models

    try:
        with database.get_context_session() as session:
            rows = (session.query(models.WorkshopCollection)
                    .order_by(models.WorkshopCollection.updated_at.desc())
                    .all())
            return [row.to_dict() for row in rows]
    except Exception as e:
        _log(f"Could not read collections: {e}")
        return []


def forget_collection(collection_id):
    """Drop a remembered collection.

    Returns ``(ok, error, existed)``. ``existed`` separates "there is no such
    collection" from "the database would not do it" - a 404 and a 500, and
    reporting the second as the first sends somebody looking in the wrong place.
    """
    import database
    import models

    try:
        with database.get_context_session() as session:
            row = (session.query(models.WorkshopCollection)
                   .filter(models.WorkshopCollection.id == str(collection_id)).first())
            if not row:
                return False, 'That collection is not recorded', False
            session.delete(row)
            session.commit()
            return True, None, True
    except Exception as e:
        _log(f"Could not forget collection {collection_id}: {e}")
        return False, f'Could not remove it: {e}', True
