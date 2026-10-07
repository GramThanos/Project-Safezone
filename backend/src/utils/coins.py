"""Coins: earned by selling rewards back and by playing, spent in the shop.

**The balance is one column, changed only by relative updates.** `credit` and
`debit` are single ``UPDATE users SET coin_balance = coin_balance ± n`` statements,
so two changes at once cannot overwrite one another, and `debit` refuses in the
same statement that would take the balance below zero. Both run on the caller's
session, so the coins move in the same transaction as whatever they pay for.

**Every gain is logged** (`earn`, `models/coin_log.py`), whatever its source - a
sale, zombie kills, a staff grant, anything added later - and that log is what
the daily "yesterday you earned" summary and the staff view are built from.
Spending is not logged here: a purchase is a `shop_purchases` row and a staff
correction an audit entry.

**Buying and selling back can never make coins.** A holding sells for its
reward's `coin_value` - once, however many items it holds; a shop listing may not
be priced below that (`min_price`). The floor is enforced when a listing is saved
and when a reward's value is raised.

**Earning by playing is a set of sources** (`SOURCES`), each a counter read from
the character's save - zombie kills today, hours survived could follow. Every
source on a character remembers what it has paid for (``counted``), set to the
character's counts when it is linked so nothing from before is paid, and moved
by whole steps so the remainder carries. `settle` is the pure rule;
`settle_character` applies it to one reading of one character.

**One life at a time.** Counters only go up within a life. The character's name
in the save tells the lives apart: a new name is a new character after a death,
whose counters start from zero; a name seen before is a backup being restored,
and so is any counter that went down without a new name. Either kind of rollback
starts the counters again from where they now stand and pays nothing, so a
restored world is never paid a second time. The cost is that a new character
given the same name as the last one loses whatever it did before it was first
read - a rule that can only underpay.
"""
import logging
from collections import namedtuple
from datetime import datetime, time as clock, timedelta, timezone

from src.database import db
from src.models.character import Character
from src.models.coin_log import CoinLog
from src.models.scheduled_job import ScheduledJob
from src.models.user import User
from src.utils import daily, settings

logger = logging.getLogger(__name__)

# How much a suggested shop price is of the sell value. Only a suggestion: the
# panel fills it in and the admin decides; the floor is what is enforced.
SUGGESTED_PRICE_MULTIPLIER = 20

# Bounds on what an admin may type. Far above anything sensible, well inside a
# 32-bit column.
MAX_COIN_VALUE = 1_000_000
MAX_PRICE = 100_000_000
MAX_ADJUSTMENT = 100_000_000
MAX_DAILY_LIMIT = 1000

# How many earlier lives a character remembers, to recognise a restored backup.
KEEP_IDENTITIES = 20

# The job that checks every linked character. Named here so the pages that say
# "next check" and the job registry cannot disagree.
SETTLE_JOB = 'settle_coins'
REPORT_JOB = 'coin_report'


def _whole(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


# Ways a character earns coins by playing. ``read`` takes the character's status
# block - the same keys in a full report and in a snapshot summary - and returns
# a whole-number counter that only grows within one life. ``rate`` names the
# settings: coins paid per step, and the size of a step.
SOURCES = {
    'kills': {
        'label': 'zombie kills',
        'unit': 'kills',
        'read': lambda status: _whole(status.get('zombie_kills')),
        'rate': ('coins_per_kill_step', 'kills_per_coin_step'),
    },
}

# Sources that are not a character's: shown in the log and the summary.
OTHER_SOURCES = {
    CoinLog.SOURCE_SALE: 'selling rewards',
    CoinLog.SOURCE_ADMIN: 'staff',
}

Reading = namedtuple('Reading', 'identity saved_at values')


def enabled():
    """Whether the coin system is switched on. A settings failure reads as off."""
    try:
        return bool(settings.get('coins_enabled'))
    except Exception as e:
        logger.error(f"Could not read coins_enabled, treating coins as off: {e}")
        return False


def rate(source):
    """``(coins, per)`` for a source, or None when it pays nothing."""
    if not enabled():
        return None
    coins_key, per_key = SOURCES[source]['rate']
    try:
        coins = settings.get(coins_key) or 0
        per = settings.get(per_key) or 0
    except Exception as e:
        logger.error(f"Could not read the {source} rate: {e}")
        return None
    if coins < 1 or per < 1:
        return None
    return coins, per


def rates():
    """Every source that is paying right now, for the pages that explain it."""
    out = []
    for key, source in SOURCES.items():
        found = rate(key)
        if found:
            out.append({'key': key, 'label': source['label'], 'unit': source['unit'],
                        'coins': found[0], 'per': found[1]})
    return out


def label(source):
    """What a log source is called in a sentence."""
    if source in SOURCES:
        return SOURCES[source]['label']
    return OTHER_SOURCES.get(source, source)


# ---------------------------------------------------------------------------
# The balance
# ---------------------------------------------------------------------------

def balance(session, user_id):
    value = session.query(User.coin_balance).filter(User.id == user_id).scalar()
    return value or 0


def credit(session, user_id, amount):
    """Add ``amount`` coins without logging - use `earn` for a gain. Returns whether it did."""
    if amount <= 0:
        return amount == 0
    updated = (session.query(User)
               .filter(User.id == user_id)
               .update({User.coin_balance: User.coin_balance + amount},
                       synchronize_session=False))
    return updated == 1


def debit(session, user_id, amount):
    """Take ``amount`` coins if the account has them. Returns whether it did."""
    if amount <= 0:
        return amount == 0
    updated = (session.query(User)
               .filter(User.id == user_id, User.coin_balance >= amount)
               .update({User.coin_balance: User.coin_balance - amount},
                       synchronize_session=False))
    return updated == 1


def earn(session, user_id, amount, source, quantity=None, character_id=None, detail=None):
    """Credit a gain and log where it came from, in the caller's transaction."""
    if amount <= 0 or not credit(session, user_id, amount):
        return False
    session.add(CoinLog(user_id=user_id, amount=amount, source=source, quantity=quantity,
                        character_id=character_id, detail=(detail or '')[:255] or None))
    return True


# ---------------------------------------------------------------------------
# Prices and limits
# ---------------------------------------------------------------------------

def units(kind, count):
    """How many items a listing delivers: a usable runs once."""
    if kind == 'usable':
        return 1
    return count or 1


def min_price(reward):
    """The lowest price a listing of ``reward`` may have: what it sells back for.

    Never below one coin: a free listing would be an unlimited giveaway.
    """
    return max(1, reward.coin_value or 0)


def suggested_price(reward):
    """The panel's starting point for a new listing."""
    return max(1, SUGGESTED_PRICE_MULTIPLIER * (reward.coin_value or 0))


def whole_number(value):
    """``value`` as an int if it is one (not a bool, not a float), else None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def day_bounds(day=None):
    """``(start, end)`` of a day in the primary server's timezone, as naive UTC.

    The same day the daily crate uses, so "a day" means one thing on this site.
    """
    zone = daily.primary_timezone()
    day = day or datetime.now(zone).date()
    start = datetime.combine(day, clock.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), clock.min, tzinfo=zone)
    return (start.astimezone(timezone.utc).replace(tzinfo=None),
            end.astimezone(timezone.utc).replace(tzinfo=None))


# ---------------------------------------------------------------------------
# Earning by playing
# ---------------------------------------------------------------------------

def life(current, previous, identity):
    """Whether a reading is the ``same`` life, a ``new`` one, or a ``restored`` old one."""
    if not identity or not current or identity == current:
        return 'same'
    if identity in (previous or []):
        return 'restored'
    return 'new'


def settle(counted, value, rate, life='same'):
    """The pure rule for one source. Returns ``(coins, counted)``.

    ``counted`` is what has been paid for (None before the first reading),
    ``value`` the new reading, ``rate`` ``(coins, per)`` or None to pay nothing -
    the counter still moves, so switching coins on later pays nothing for the
    time they were off.
    """
    if value is None or value < 0:
        return 0, counted
    # A first reading, a restored backup, or a counter that went down within
    # the same life: start from here and pay nothing.
    if counted is None or life == 'restored' or (life == 'same' and value < counted):
        return 0, value
    base = 0 if life == 'new' else counted
    if rate is None:
        return 0, value
    coins, per = rate
    steps = (value - base) // per
    return steps * coins, base + steps * per


def parse_saved_at(value):
    """The game-server's ISO save time as naive UTC, the way the database stores times."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _reading(identity, status, saved_at):
    saved_at = parse_saved_at(saved_at)
    if saved_at is None or not isinstance(status, dict):
        return None
    values = {key: source['read'](status) for key, source in SOURCES.items()}
    if all(v is None for v in values.values()):
        return None
    return Reading(identity if isinstance(identity, str) and identity else None, saved_at, values)


def reading_from_entry(entry, allow_stale=True):
    """A `Reading` out of what `character_info.fetch` returned, or None."""
    if not isinstance(entry, dict) or (entry.get('stale') and not allow_stale):
        return None
    report = entry.get('report') or {}
    return _reading((report.get('character') or {}).get('name'),
                    report.get('status'), entry.get('saved_at'))


def reading_from_summary(summary, saved_at):
    """A `Reading` out of one character of a snapshot, or None."""
    if not isinstance(summary, dict):
        return None
    return _reading(summary.get('name'), summary, saved_at)


def baseline(character, reading):
    """Start a newly linked character from the counts it already has.

    Without a reading - not saved yet, or only an old copy to hand - the first
    settlement sets the baseline instead. Either way nothing from before the
    link is paid.
    """
    if reading is None:
        return
    character.coin_progress = {key: {'counted': value, 'seen': value}
                               for key, value in reading.values.items() if value is not None}
    character.coin_identity = reading.identity
    character.coin_identities = []
    character.coin_saved_at = reading.saved_at
    character.coin_checked_at = datetime.utcnow()


def settle_character(session, character_id, reading, now=None):
    """Pay a linked character's owner for what it has done since the last reading.

    Locks the character row, so two settlements of the same save cannot both
    pay; a reading no newer than the last one only records that it was checked.
    Returns the coins paid.
    """
    if reading is None:
        return 0
    character = (session.query(Character)
                 .filter_by(id=character_id)
                 .with_for_update()
                 .first())
    if not character or not character.is_deliverable():
        return 0
    character.coin_checked_at = now or datetime.utcnow()
    if character.coin_saved_at is not None and reading.saved_at <= character.coin_saved_at:
        return 0

    which = life(character.coin_identity, character.coin_identities, reading.identity)
    owner = session.query(User.role).filter(User.id == character.user_id).scalar()
    paying = bool(owner) and owner != User.ROLE_BANNED

    progress = dict(character.coin_progress or {})
    total = 0
    for key, value in reading.values.items():
        if value is None:
            continue
        current = rate(key) if paying else None
        state = progress.get(key) or {}
        paid, counted = settle(state.get('counted'), value, current, which)
        progress[key] = {'counted': counted, 'seen': value}
        if paid:
            quantity = paid // current[0] * current[1]
            earn(session, character.user_id, paid, key, quantity=quantity,
                 character_id=character.id,
                 detail=f"{quantity} {SOURCES[key]['unit']} as {character.in_game_username}")
            total += paid

    if total:
        character.coin_earned = (character.coin_earned or 0) + total

    if which != 'same':
        history = [i for i in (character.coin_identities or []) if i != reading.identity]
        if character.coin_identity:
            history.append(character.coin_identity)
        character.coin_identities = history[-KEEP_IDENTITIES:]
    if reading.identity:
        character.coin_identity = reading.identity
    character.coin_progress = progress
    character.coin_saved_at = reading.saved_at
    return total


def settle_quietly(character_id, reading):
    """`settle_character` in its own transaction, for a page that only happens to have the data.

    Must never break the page it rides on, so a failure is logged and dropped;
    the next reading settles what this one could not.
    """
    if reading is None:
        return 0
    try:
        with db.get_db() as session:
            return settle_character(session, character_id, reading)
    except Exception as e:
        logger.error(f"Could not settle coins for character {character_id}: {e}")
        return 0


# ---------------------------------------------------------------------------
# What players and staff are shown
# ---------------------------------------------------------------------------

def describe_gains(parts):
    """"30 for 300 zombie kills, 4 for selling 2 rewards" from ``(source, amount, quantity)``."""
    out = []
    for source, amount, quantity in sorted(parts, key=lambda part: -part[1]):
        if source in SOURCES and quantity:
            out.append(f"{amount} for {quantity} {SOURCES[source]['label']}")
        elif source == CoinLog.SOURCE_SALE and quantity:
            out.append(f"{amount} for selling {quantity} reward{'' if quantity == 1 else 's'}")
        else:
            out.append(f"{amount} from {label(source)}")
    return ', '.join(out)


def report_enabled(session):
    """Whether players get the daily "yesterday you earned" message."""
    job = session.query(ScheduledJob).filter_by(kind=REPORT_JOB).first()
    return bool(job and job.enabled)


def next_sweep(session):
    """When the daily check next runs, or None when it is switched off."""
    job = session.query(ScheduledJob).filter_by(kind=SETTLE_JOB).first()
    if not job or not job.enabled:
        return None
    return job.next_run_at


def character_status(character, paying):
    """One linked character's coin progress, for a page.

    ``paying`` is `rates()` keyed by source. ``to_next`` is how much more of a
    source the next payment needs, when the source is paying and has a reading.
    """
    progress = character.coin_progress or {}
    sources = []
    for key, source in SOURCES.items():
        state = progress.get(key) or {}
        counted, seen = state.get('counted'), state.get('seen')
        current = paying.get(key)
        to_next = None
        if current and counted is not None and seen is not None:
            to_next = max(current['per'] - (seen - counted), 0)
        sources.append({'key': key, 'label': source['label'], 'unit': source['unit'],
                        'counted': counted, 'seen': seen, 'to_next': to_next})
    return {
        'id': character.id,
        'in_game_username': character.in_game_username,
        'server_id': character.server_id,
        'life': character.coin_identity,
        'checked_at': character.coin_checked_at.isoformat() if character.coin_checked_at else None,
        'saved_at': character.coin_saved_at.isoformat() if character.coin_saved_at else None,
        'earned': character.coin_earned or 0,
        'sources': sources,
    }
