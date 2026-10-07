#!/usr/bin/env python3
"""The decisions behind maintenance, with nothing attached to them.

Maintenance is: notice that the game or a mod has an update, decide when it can
go out, warn whoever is playing, take every server down, update, and bring them
back. The *doing* is in `manager_maintenance.py` and `maintenance_store.py`;
this module is only the part that is worth testing on its own - cron matching,
the policy and its validation, which mods are out of date, when a planned run
may start, and which countdown warning is due.

No database, no Redis, no SteamCMD: every function here takes plain values and
returns plain values, so the rules can be exercised without a running stack.

Why every server goes down for any update: one install directory serves every
server, and the Workshop library sits inside it. A mod update rewrites files a
running server may have loaded, and a game update replaces the binaries all of
them run. A per-server rollout would only be correct for a mod that exactly one
server uses, and getting that wrong costs a corrupted session - so the run takes
the whole stack down, once, for everything that is due.
"""
import datetime
import math

import actions

# ---------------------------------------------------------------------------
# Cron
# ---------------------------------------------------------------------------
#
# Standard five fields - minute, hour, day of month, month, day of week - with
# `*`, lists, ranges and steps. Day of week is 0-7 with both 0 and 7 meaning
# Sunday. When both day fields are restricted a time matches if *either* does,
# which is what every cron since Vixie's has done and what people expect.
#
# Written here rather than taken from a library because it is forty lines, the
# game-server deliberately carries few dependencies, and a schedule that
# silently means something other than what was typed is the failure that
# matters - so it is tested rather than trusted.

CRON_FIELDS = (
    ('minute', 0, 59),
    ('hour', 0, 23),
    ('day of month', 1, 31),
    ('month', 1, 12),
    ('day of week', 0, 7),
)

CRON_MACROS = {
    '@hourly': '0 * * * *',
    '@daily': '0 0 * * *',
    '@midnight': '0 0 * * *',
    '@weekly': '0 0 * * 0',
    '@monthly': '0 0 1 * *',
}

# How far ahead `next_cron` looks before deciding an expression never fires
# (`0 0 30 2 *` - the 30th of February).
CRON_HORIZON_DAYS = 366 * 5


class CronSpec:
    """A parsed cron expression."""

    __slots__ = ('expression', 'minutes', 'hours', 'days', 'months', 'weekdays',
                 'days_restricted', 'weekdays_restricted')

    def __init__(self, expression, minutes, hours, days, months, weekdays,
                 days_restricted, weekdays_restricted):
        self.expression = expression
        self.minutes = minutes
        self.hours = hours
        self.days = days
        self.months = months
        self.weekdays = weekdays
        self.days_restricted = days_restricted
        self.weekdays_restricted = weekdays_restricted


def _parse_cron_field(text, name, low, high):
    values = set()
    for part in text.split(','):
        part = part.strip()
        if not part:
            raise ValueError(f'{name}: empty list entry')
        step = 1
        if '/' in part:
            part, step_text = part.split('/', 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise ValueError(f"{name}: '{step_text}' is not a valid step")
            step = int(step_text)
        if part == '*':
            start, end = low, high
        elif '-' in part:
            start_text, end_text = part.split('-', 1)
            if not (start_text.isdigit() and end_text.isdigit()):
                raise ValueError(f"{name}: '{part}' is not a valid range")
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"{name}: range '{part}' runs backwards")
        elif part.isdigit():
            start = int(part)
            # `5/15` means "from 5, every 15" - the same as `5-max/15`.
            end = high if step > 1 else start
        else:
            raise ValueError(f"{name}: '{part}' is not a number")
        if start < low or end > high:
            raise ValueError(f'{name}: values must be between {low} and {high}')
        values.update(range(start, end + 1, step))
    return frozenset(values)


def parse_cron(expression):
    """Parse a cron expression. Raises ValueError with a readable reason."""
    text = ' '.join(str(expression or '').split())
    if not text:
        raise ValueError('the schedule is empty')
    text = CRON_MACROS.get(text.lower(), text)
    parts = text.split(' ')
    if len(parts) != 5:
        raise ValueError('a schedule has five fields: minute hour day month weekday')

    parsed = [_parse_cron_field(part, name, low, high)
              for part, (name, low, high) in zip(parts, CRON_FIELDS)]
    minutes, hours, days, months, weekdays = parsed
    # 7 is Sunday's second spelling; store one.
    weekdays = frozenset(0 if d == 7 else d for d in weekdays)
    return CronSpec(text, minutes, hours, days, months, weekdays,
                    days_restricted=parts[2] != '*',
                    weekdays_restricted=parts[4] != '*')


def _cron_weekday(moment):
    # Python counts Monday as 0; cron counts Sunday as 0.
    return (moment.weekday() + 1) % 7


def _day_matches(spec, moment):
    day_ok = moment.day in spec.days
    weekday_ok = _cron_weekday(moment) in spec.weekdays
    if spec.days_restricted and spec.weekdays_restricted:
        return day_ok or weekday_ok
    if spec.days_restricted:
        return day_ok
    if spec.weekdays_restricted:
        return weekday_ok
    return True


def cron_matches(spec, moment):
    """Whether ``moment`` (to the minute) is a time the schedule fires."""
    return (moment.minute in spec.minutes and moment.hour in spec.hours
            and moment.month in spec.months and _day_matches(spec, moment))


def next_cron(spec, after):
    """The first firing strictly after ``after``, or None if it never fires.

    Works in whatever wall clock ``after`` carries: give it a datetime in the
    primary server's timezone and "05:00" means five in the morning there.
    Skips whole months, days and hours that cannot match, so a yearly schedule
    costs a few hundred steps rather than half a million.
    """
    moment = after.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
    limit = after + datetime.timedelta(days=CRON_HORIZON_DAYS)
    while moment <= limit:
        if moment.month not in spec.months:
            year = moment.year + (1 if moment.month == 12 else 0)
            month = 1 if moment.month == 12 else moment.month + 1
            moment = moment.replace(year=year, month=month, day=1, hour=0, minute=0)
            continue
        if not _day_matches(spec, moment):
            moment = (moment + datetime.timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if moment.hour not in spec.hours:
            moment = (moment + datetime.timedelta(hours=1)).replace(minute=0)
            continue
        if moment.minute not in spec.minutes:
            moment += datetime.timedelta(minutes=1)
            continue
        return moment
    return None


def cron_error(expression):
    """Why an expression is unusable, or None. An empty one means "off"."""
    if not str(expression or '').strip():
        return None
    try:
        spec = parse_cron(expression)
    except ValueError as e:
        return str(e)
    if next_cron(spec, datetime.datetime(2000, 1, 1)) is None:
        return 'this schedule never fires'
    return None


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------
#
# One policy for the whole install, because there is one install. Stored as a
# single JSON document; anything missing falls back to the default below, so a
# key added in a later version needs no migration.

DEFAULT_COUNTDOWN = [900, 600, 300, 30, 15, 5]
MAX_COUNTDOWN_STEPS = 12
MAX_COUNTDOWN_SECONDS = 2 * 3600
MAX_WAIT_HOURS = 24 * 30
MAX_EXCLUDED_MODS = 500

DEFAULT_POLICY = {
    # Automatic checks and automatic planning. Off out of the box: an upgrade
    # should not start restarting somebody's servers on its own. Checking by
    # hand and planning a run from the panel work either way.
    'enabled': False,
    'game_check_cron': '0 */6 * * *',
    'mods_check_cron': '*/30 * * * *',
    # Check again when a server stops, sleeps or fails - the moment an update
    # costs nobody anything.
    'check_on_state_change': True,
    # Which kinds of update wait for a person to approve them. Mods default to
    # approval because a mod update is somebody else's code arriving
    # unannounced; the game is Valve-distributed and stays a known quantity.
    'game_requires_approval': False,
    'mods_requires_approval': True,
    # Deploy the moment every server is empty or asleep - nobody to warn.
    'apply_when_empty': True,
    # When a forced deploy (with the countdown) is allowed to start. Empty means
    # never on a schedule, leaving "when empty" and the maximum wait.
    'window_cron': '0 5 * * *',
    # Force it with a countdown after this long, wherever the clock is. 0 means
    # wait for an empty server or the window indefinitely.
    'max_wait_hours': 24,
    'countdown': list(DEFAULT_COUNTDOWN),
    'message': 'The server will restart for an update in {time}.',
    'cancel_message': 'The scheduled restart has been cancelled.',
    # Workshop item ids never updated automatically. See the panel's warning:
    # players' Steam clients always fetch the latest version of a mod, so
    # holding one back can stop them joining.
    'excluded_mods': [],
}

BOOL_KEYS = ('enabled', 'check_on_state_change', 'game_requires_approval',
             'mods_requires_approval', 'apply_when_empty')
CRON_KEYS = ('game_check_cron', 'mods_check_cron', 'window_cron')


def policy_with_defaults(stored):
    """A complete policy from whatever was stored, unknown keys dropped."""
    stored = stored if isinstance(stored, dict) else {}
    policy = {}
    for key, default in DEFAULT_POLICY.items():
        value = stored.get(key, default)
        policy[key] = list(value) if isinstance(value, list) else value
    return policy


def _parse_countdown(value):
    if isinstance(value, str):
        value = [part for part in value.replace(' ', '').split(',') if part]
    if not isinstance(value, (list, tuple)):
        raise ValueError('a list of seconds is expected')
    steps = set()
    for raw in value:
        try:
            seconds = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"'{raw}' is not a whole number of seconds")
        if seconds < 1 or seconds > MAX_COUNTDOWN_SECONDS:
            raise ValueError(f'each warning must be between 1 second and '
                             f'{MAX_COUNTDOWN_SECONDS // 3600} hours before the restart')
        steps.add(seconds)
    if len(steps) > MAX_COUNTDOWN_STEPS:
        raise ValueError(f'at most {MAX_COUNTDOWN_STEPS} warnings')
    return sorted(steps, reverse=True)


def _message_error(template, steps):
    """Why a broadcast template cannot go out, or None.

    Rendered against every warning it will be used for and run through the same
    builder the console uses, so a template that passes here cannot be refused
    mid-countdown - which is the worst moment to find out.
    """
    if not str(template or '').strip():
        return 'a message is required'
    for seconds in steps or [60]:
        try:
            broadcast_command(render_message(template, seconds))
        except actions.CommandError:
            return ('the message may not contain quotes, backslashes or line '
                    'breaks, and must stay under 200 characters')
    return None


def validate_policy(raw, current=None):
    """Merge ``raw`` over ``current`` and validate. Returns ``(policy, errors)``.

    ``errors`` maps a key to what is wrong with it and is empty on success. Only
    known keys are read, so a client cannot store anything else.
    """
    policy = policy_with_defaults(current)
    raw = raw if isinstance(raw, dict) else {}
    errors = {}

    for key in BOOL_KEYS:
        if key in raw:
            policy[key] = bool(raw[key])

    for key in CRON_KEYS:
        if key in raw:
            value = ' '.join(str(raw[key] or '').split())
            error = cron_error(value)
            if error:
                errors[key] = error
            else:
                policy[key] = value

    if 'max_wait_hours' in raw:
        try:
            hours = int(raw['max_wait_hours'] or 0)
            if hours < 0 or hours > MAX_WAIT_HOURS:
                raise ValueError
            policy['max_wait_hours'] = hours
        except (TypeError, ValueError):
            errors['max_wait_hours'] = f'between 0 and {MAX_WAIT_HOURS} hours'

    if 'countdown' in raw:
        try:
            policy['countdown'] = _parse_countdown(raw['countdown'])
        except ValueError as e:
            errors['countdown'] = str(e)

    for key in ('message', 'cancel_message'):
        if key in raw:
            policy[key] = str(raw[key] or '').strip()
    for key in ('message', 'cancel_message'):
        error = _message_error(policy[key], policy['countdown'] if key == 'message' else [60])
        if error:
            errors[key] = error

    if 'excluded_mods' in raw:
        value = raw['excluded_mods']
        if isinstance(value, str):
            value = value.replace(',', ' ').split()
        if not isinstance(value, (list, tuple)):
            errors['excluded_mods'] = 'a list of Workshop item ids is expected'
        else:
            ids = []
            for item in value:
                item = str(item).strip()
                if not item.isdigit() or len(item) > 20:
                    errors['excluded_mods'] = f"'{item}' is not a Workshop item id"
                    break
                if item not in ids:
                    ids.append(item)
            else:
                if len(ids) > MAX_EXCLUDED_MODS:
                    errors['excluded_mods'] = f'at most {MAX_EXCLUDED_MODS} items'
                else:
                    policy['excluded_mods'] = ids

    return policy, errors


# ---------------------------------------------------------------------------
# What is out of date
# ---------------------------------------------------------------------------

def game_update(installed, branches):
    """Compare the installed build with what Steam offers on the same branch.

    ``installed`` is `steam.installed_app_state()`; ``branches`` is the
    ``depots.branches`` block of `steam.app_info()`. The branch compared is the
    one *installed*, not the configured one: an admin who switched branch from
    the panel meant it, and maintenance should keep them there rather than
    quietly switching them back.

    Returns a dict with ``update_available``; a target for a run when it is.
    """
    if not installed or not installed.get('buildid'):
        return {'update_available': False, 'reason': 'the game is not installed'}

    branch = installed.get('branch') or 'public'
    entry = (branches or {}).get(branch)
    if not isinstance(entry, dict) or not entry.get('buildid'):
        return {'update_available': False, 'branch': branch,
                'installed_build': str(installed.get('buildid')),
                'reason': f"Steam lists no build for branch '{branch}'"}

    available = str(entry.get('buildid'))
    current = str(installed.get('buildid'))
    try:
        available_at = int(entry.get('timeupdated') or 0) or None
    except (TypeError, ValueError):
        available_at = None
    # A partial or interrupted update leaves the manifest flagged as such while
    # still naming the new build id; that install needs updating too.
    damaged = installed.get('state_flags') not in (None, 4)
    return {
        'update_available': available != current or damaged,
        'branch': branch,
        'installed_build': current,
        'available_build': available,
        'available_at': available_at,
        'damaged': damaged,
    }


def outdated_mods(used, installed, remote, excluded=()):
    """Which Workshop items in use have a newer version on the Workshop.

    ``used`` maps item id -> server names using it; ``installed`` maps id ->
    {'timeupdated'} from Steam's workshop manifest; ``remote`` maps id -> the
    `workshop.lookup` entry. Returns ``(outdated, held_back)``, each a list of
    targets, oldest-installed first.

    An item that is not on disk at all is not an update - it is a missing mod,
    which the installation page already reports. An item the Workshop no longer
    serves (removed, made private) is not an update either: there is nothing to
    download, and SteamCMD would delete nothing and report success.
    """
    excluded = {str(i) for i in excluded or ()}
    outdated, held_back = [], []
    for item_id in sorted(used or {}):
        local = (installed or {}).get(item_id)
        meta = (remote or {}).get(item_id)
        if not local or not meta or not meta.get('found') or meta.get('banned'):
            continue
        installed_at = local.get('timeupdated') or 0
        updated_at = meta.get('updated') or 0
        if not updated_at or updated_at <= installed_at:
            continue
        target = {
            'id': item_id,
            'title': meta.get('title'),
            'installed_at': installed_at or None,
            'updated_at': updated_at,
            'size': meta.get('size'),
            'servers': list(used.get(item_id) or []),
        }
        (held_back if item_id in excluded else outdated).append(target)
    key = lambda t: (t['installed_at'] or 0, t['id'])
    return sorted(outdated, key=key), sorted(held_back, key=key)


# ---------------------------------------------------------------------------
# Targets: what one run will do
# ---------------------------------------------------------------------------

def empty_targets():
    return {'game': None, 'mods': []}


def has_targets(targets):
    return bool(targets and (targets.get('game') or targets.get('mods')))


def merge_targets(existing, new):
    """Fold newly found updates into a run that has not started yet.

    A newer game build replaces the older target, and a mod found again with a
    later timestamp replaces its entry - one restart then covers both, rather
    than a run that updates to a build that is already stale.
    """
    existing = existing or empty_targets()
    new = new or empty_targets()
    game = new.get('game') or existing.get('game')
    mods = {m['id']: m for m in existing.get('mods') or []}
    for mod in new.get('mods') or []:
        current = mods.get(mod['id'])
        if not current or (mod.get('updated_at') or 0) >= (current.get('updated_at') or 0):
            mods[mod['id']] = mod
    return {'game': game, 'mods': [mods[k] for k in sorted(mods)]}


def covered_by(previous, wanted):
    """Whether ``wanted`` asks for nothing ``previous`` did not already.

    Used after a cancel: the same updates are not planned again on their own
    until the next maintenance window, but a genuinely newer build or mod
    version is new information and is planned as usual.
    """
    previous = previous or empty_targets()
    game = wanted.get('game')
    if game:
        old = previous.get('game')
        if not old or str(old.get('available_build')) != str(game.get('available_build')):
            return False
    old_mods = {m['id']: m for m in previous.get('mods') or []}
    for mod in wanted.get('mods') or []:
        old = old_mods.get(mod['id'])
        if not old or (mod.get('updated_at') or 0) > (old.get('updated_at') or 0):
            return False
    return True


def automatic_targets(game_check, mods_check, policy):
    """The part of the latest checks policy lets through without a person."""
    targets = empty_targets()
    game = (game_check or {}).get('result') or {}
    if game.get('update_available') and not policy.get('game_requires_approval'):
        targets['game'] = game
    if not policy.get('mods_requires_approval'):
        targets['mods'] = list(((mods_check or {}).get('result') or {}).get('outdated') or [])
    return targets


def select_targets(game_check, mods_check, include_game, mod_ids):
    """The targets a person picked in the panel, from the latest checks.

    Only what the checks actually reported can be chosen - a client cannot ask
    for an arbitrary Workshop id to be downloaded through this path. Held-back
    (excluded) items may be picked: excluding stops the *automatic* update, and
    an admin ticking one by hand is the override.
    """
    targets = empty_targets()
    game = (game_check or {}).get('result') or {}
    if include_game and game.get('update_available'):
        targets['game'] = game
    result = (mods_check or {}).get('result') or {}
    available = {m['id']: m for m in (result.get('outdated') or []) + (result.get('held_back') or [])}
    wanted = [str(i) for i in mod_ids or []]
    targets['mods'] = [available[i] for i in sorted(set(wanted)) if i in available]
    return targets


def describe_targets(targets):
    """One line for logs, alerts and the panel."""
    parts = []
    game = (targets or {}).get('game')
    if game:
        parts.append(f"game build {game.get('installed_build')} -> {game.get('available_build')}")
    mods = (targets or {}).get('mods') or []
    if mods:
        parts.append(f"{len(mods)} mod{'s' if len(mods) != 1 else ''}")
    return ' and '.join(parts) or 'nothing'


# ---------------------------------------------------------------------------
# When a planned run may start
# ---------------------------------------------------------------------------

def decide_scheduled(force_at, deadline, players_online, window_fired, policy, now):
    """What a planned run does next. Returns ``(action, reason)``.

    ``action`` is ``wait``, ``countdown`` (warn the players, then stop) or
    ``stop`` (nobody to warn - go straight to taking the servers down).
    """
    def go(reason):
        return ('stop' if players_online == 0 else 'countdown'), reason

    if force_at is not None and now >= force_at:
        return go('requested by staff')
    if players_online == 0 and policy.get('apply_when_empty'):
        return 'stop', 'every server is empty'
    if window_fired:
        return go('the maintenance window opened')
    if deadline is not None and now >= deadline:
        return go('it has waited as long as the policy allows')
    return 'wait', None


# ---------------------------------------------------------------------------
# The countdown
# ---------------------------------------------------------------------------

def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def format_duration(seconds):
    """`900` -> "15 minutes", `90` -> "1 minute 30 seconds"."""
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(_plural(hours, 'hour'))
    if minutes:
        parts.append(_plural(minutes, 'minute'))
    if secs or not parts:
        parts.append(_plural(secs, 'second'))
    return ' '.join(parts)


def render_message(template, seconds):
    return str(template or '').replace('{time}', format_duration(seconds)).strip()


def broadcast_command(text):
    """The console command for a server-wide message, via the action catalog."""
    return actions.build('broadcast', None, {'message': text})


def countdown_length(policy):
    steps = policy.get('countdown') or []
    return max(steps) if steps else 0


def due_announcement(steps, remaining, sent):
    """The warning to broadcast now, if any. Returns ``(seconds_to_say, sent)``.

    A warning is due once the time left drops to its step. If several came due
    at once - the worker was busy or restarted - only the latest is said, and
    the earlier ones are marked done: three warnings in one second is noise,
    and "15 minutes" said with five left is wrong. When the step is said late,
    the actual time left is said instead of the step's.
    """
    sent = list(sent or [])
    crossed = [s for s in steps or [] if remaining <= s and s not in sent]
    if not crossed:
        return None, sent
    step = min(crossed)
    say = step if step - remaining < 3 else max(1, math.ceil(remaining))
    return say, sorted(set(sent) | set(crossed), reverse=True)
