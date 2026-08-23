"""The registry of runtime-editable settings, and how to read and write them.

A setting has an environment variable as its default and an optional database row
as a live override. Reads are cached briefly, because these are consulted on hot
paths (every signup, for instance) and change rarely.

Only keys declared in ``REGISTRY`` are readable or writable, so the admin endpoint
cannot be used to set arbitrary rows.
"""
import logging
import time

from flask import current_app

from src.database import db
from src.models.app_setting import AppSetting

logger = logging.getLogger(__name__)


# key -> declaration.
#   config:   the Flask config key holding the environment default
#   default:  a literal default, for settings with no environment variable
#             behind them - the mail settings, whose fallback lives in the
#             game-server's environment rather than this one's
#   type:     'bool' | 'int' | 'str' | 'text' | 'markdown'
#   secret:   never returned to the browser; only whether it is set
#   group:    which section of the panel it belongs to
#   validate: callable(value) -> error string, or None if it is acceptable.
#             A setting that can break every request if mistyped is checked
#             before it is stored, not after somebody notices
REGISTRY = {
    'registration_enabled': {
        'config': 'REGISTRATION_ENABLED',
        'type': 'bool',
        'label': 'Registration open',
        'help': 'When off, nobody can create an account. Existing accounts are unaffected.',
    },
    'registration_password': {
        'config': 'REGISTRATION_PASSWORD',
        'type': 'str',
        'secret': True,
        'label': 'Registration password',
        'help': 'If set, new accounts must supply this shared password. Blank means no password.',
    },
    'invites_enabled': {
        'config': 'INVITES_ENABLED',
        'type': 'bool',
        'label': 'Invitations accepted',
        'help': 'Allow signing up with an invitation link even when registration is closed.',
    },
    'player_invites_enabled': {
        'config': 'PLAYER_INVITES_ENABLED',
        'type': 'bool',
        'label': 'Players may invite',
        'help': 'Let ordinary players issue invitations, not just staff.',
    },
    'player_invite_quota': {
        'config': 'PLAYER_INVITE_QUOTA',
        'type': 'int',
        'label': 'Invitations per player',
        'help': 'How many unused invitations one player may have outstanding.',
    },
    'streak_bonus_enabled': {
        'config': 'STREAK_BONUS_ENABLED',
        'type': 'bool',
        'label': 'Weekly streak bonus',
        'help': 'Grant a bonus box to accounts that collected enough daily boxes last week.',
    },
    'streak_threshold': {
        'config': 'STREAK_THRESHOLD',
        'type': 'int',
        'label': 'Daily boxes needed for the bonus',
        'help': 'Out of seven. The default is five.',
    },
    'captcha_enabled': {
        'config': 'CAPTCHA_ENABLED',
        'type': 'bool',
        'label': 'CAPTCHA on signup',
        'help': 'Ask new accounts to read a distorted code. Stops drive-by bots, not a determined attacker.',
    },
    'box_expiry_days': {
        'config': 'BOX_EXPIRY_DAYS',
        'type': 'int',
        'label': 'Unopened boxes expire after (days)',
        'help': 'Gives a lapsed player a reason to come back rather than a hundred boxes. 0 never expires.',
    },
    'inventory_expiry_days': {
        'config': 'INVENTORY_EXPIRY_DAYS',
        'type': 'int',
        'label': 'Unsent rewards expire after (days)',
        'help': 'Applies only to rewards still waiting to be sent in game. 0 never expires.',
    },
    'alerts_enabled': {
        'config': 'ALERTS_ENABLED',
        'type': 'bool',
        'label': 'Operational alerts',
        'help': 'Notify staff when a server cannot stay up, the game-server is unreachable, or deliveries start failing.',
    },
    'alert_cooldown_minutes': {
        'config': 'ALERT_COOLDOWN_MINUTES',
        'type': 'int',
        'label': 'Alert cooldown (minutes)',
        'help': 'How long the same alert stays quiet once raised. Too short and staff learn to ignore alerts.',
    },
    'dormant_link_days': {
        'config': 'DORMANT_LINK_DAYS',
        'type': 'int',
        'label': 'Warn about unused characters after (days)',
        'help': 'Tells the owner their link looks abandoned so they can act. Never unlinks on its own. 0 disables.',
    },
    'audit_retention_days': {
        'config': 'AUDIT_RETENTION_DAYS',
        'type': 'int',
        'label': 'Audit retention (days)',
        'help': 'How long audit entries are kept. 0 keeps them forever.',
    },

    # --- Mail ---------------------------------------------------------------
    # No `config` key: the environment default for these lives in the
    # *game-server* container, which is the one that can reach a mail server.
    # Leave the host blank and that environment is used unchanged; fill it in
    # and these win, so an operator can point the site at a different mailbox
    # during an incident without a redeploy.
    'smtp_host': {
        'type': 'str',
        'group': 'mail',
        'label': 'SMTP host',
        'help': 'Blank uses whatever SMTP_HOST the game-server container was started '
                'with. Setting it here overrides that for every message.',
    },
    'smtp_port': {
        'type': 'int',
        'default': 587,
        'group': 'mail',
        'label': 'SMTP port',
        'help': '587 for STARTTLS, which is what most providers want.',
    },
    'smtp_user': {
        'type': 'str',
        'group': 'mail',
        'label': 'SMTP username',
        'help': 'Blank means no authentication.',
    },
    'smtp_password': {
        'type': 'str',
        'secret': True,
        'group': 'mail',
        'label': 'SMTP password',
        'help': 'An app-specific password from a consumer provider drops straight in. '
                'Never shown again once saved.',
    },
    'smtp_tls': {
        'type': 'bool',
        'default': True,
        'group': 'mail',
        'label': 'Use STARTTLS',
        'help': 'Leave on unless the mail server genuinely does not support it.',
    },
    'smtp_from': {
        'type': 'str',
        'group': 'mail',
        'label': 'From address',
        'help': 'Blank falls back to the username. Some providers reject a From '
                'that is not the authenticated account.',
    },

    # --- Sessions ------------------------------------------------------------
    'token_expiry_hours': {
        'config': 'TOKEN_EXPIRY_HOURS',
        'type': 'int',
        'group': 'limits',
        'label': 'Session length (hours)',
        'help': 'How long a sign-in lasts. Shortening it does not end sessions '
                'already issued; "sign out everywhere" does.',
    },

    'site_url': {
        'config': 'SITE_URL',
        'type': 'str',
        'label': 'Public site address',
        'help': 'Where players reach this deployment. Used for the links inside '
                'email and invitations, so a wrong value produces links that go '
                'nowhere.',
    },

    # --- Site content -------------------------------------------------------
    # `group: 'site'` keeps these off the operational Settings screen: they are
    # edited on their own pages, by somebody thinking about wording rather than
    # about retention windows. `text` is multi-line, and `markdown` is text that
    # is rendered as a document.
    'site_brand_name': {
        'config': 'SITE_BRAND_NAME',
        'type': 'str',
        'group': 'site',
        'label': 'Brand name',
        'help': 'Shown in the navbar, the footer and the browser tab.',
    },
    'site_hero_title': {
        'config': 'SITE_HERO_TITLE',
        'type': 'str',
        'group': 'site',
        'label': 'Home page headline',
        'help': 'The large line across the banner on the home page.',
    },
    'site_hero_subtitle': {
        'config': 'SITE_HERO_SUBTITLE',
        'type': 'text',
        'group': 'site',
        'label': 'Home page subtitle',
        'help': 'The paragraph under the headline. A couple of sentences reads best.',
    },
    'site_social_discord': {
        'config': 'SITE_SOCIAL_DISCORD',
        'type': 'str',
        'group': 'site',
        'label': 'Discord link',
        'help': 'Full URL. Leave blank to hide the icon.',
    },
    'site_social_twitter': {
        'config': 'SITE_SOCIAL_TWITTER',
        'type': 'str',
        'group': 'site',
        'label': 'X / Twitter link',
        'help': 'Full URL. Leave blank to hide the icon.',
    },
    'site_social_youtube': {
        'config': 'SITE_SOCIAL_YOUTUBE',
        'type': 'str',
        'group': 'site',
        'label': 'YouTube link',
        'help': 'Full URL. Leave blank to hide the icon.',
    },
    'site_social_steam': {
        'config': 'SITE_SOCIAL_STEAM',
        'type': 'str',
        'group': 'site',
        'label': 'Steam group link',
        'help': 'Full URL. Leave blank to hide the icon.',
    },
    'site_legal_terms': {
        'config': 'SITE_LEGAL_TERMS',
        'type': 'markdown',
        'group': 'site',
        'label': 'Terms',
        'help': 'Markdown. Blank means the page says it has not been written yet.',
    },
    'site_legal_privacy': {
        'config': 'SITE_LEGAL_PRIVACY',
        'type': 'markdown',
        'group': 'site',
        'label': 'Privacy',
        'help': 'Markdown. On a public server with accounts, this is the one worth writing.',
    },
    'site_legal_cookies': {
        'config': 'SITE_LEGAL_COOKIES',
        'type': 'markdown',
        'group': 'site',
        'label': 'Cookies',
        'help': 'Markdown. Blank means the page says it has not been written yet.',
    },
    'site_rules': {
        'config': 'SITE_RULES',
        'type': 'markdown',
        'group': 'site',
        'label': 'Server rules',
        'help': 'Markdown. Linked from the footer and the servers page. Rules '
                'nobody can read are rules nobody agreed to.',
    },
}

# The site keys the public pages are allowed to read, and the name each is
# published under. Explicit rather than "everything in group site", so adding a
# setting can never accidentally publish it.
PUBLIC_SITE_KEYS = {
    'site_brand_name': 'brand_name',
    'site_hero_title': 'hero_title',
    'site_hero_subtitle': 'hero_subtitle',
    'site_social_discord': 'discord',
    'site_social_twitter': 'twitter',
    'site_social_youtube': 'youtube',
    'site_social_steam': 'steam',
}

# Legal pages, by the slug their URL uses.
LEGAL_PAGES = {
    'rules': ('site_rules', 'Server Rules'),
    'terms': ('site_legal_terms', 'Terms of Service'),
    'privacy': ('site_legal_privacy', 'Privacy Policy'),
    'cookies': ('site_legal_cookies', 'Cookie Policy'),
}

# Overrides change rarely and are read on hot paths, so they are cached rather
# than fetched per request. Short enough that a panel change feels immediate.
_CACHE_TTL_SECONDS = 15
# How long a *failed* read is remembered - see `_overrides`. Much shorter
# than a successful one: this is about not hammering a database that is
# down, not about caching an answer.
_FAILURE_TTL_SECONDS = 2
_cache = {'values': None, 'at': 0.0}


def _coerce(raw, kind):
    """Turn stored text into the declared type."""
    if raw is None:
        return None
    if kind == 'bool':
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')
    if kind == 'int':
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return str(raw)


def _overrides():
    """Every stored override, cached."""
    now = time.monotonic()
    if _cache['values'] is not None and now - _cache['at'] < _CACHE_TTL_SECONDS:
        return _cache['values']

    values = {}
    try:
        with db.get_db() as session:
            for row in session.query(AppSetting).all():
                values[row.key] = row.value
    except Exception as e:
        # A settings read must never take the site down; fall back to defaults.
        #
        # The failure is cached briefly too. Without that, a page reading a
        # dozen settings makes a dozen connection attempts to a database that
        # is already known to be down, each waiting out its own timeout - so an
        # outage turns every request into a slow one on top of a degraded one.
        # Short enough that recovery is noticed within seconds.
        logger.error(f"Could not read app settings, using environment defaults: {e}")
        fallback = _cache['values'] or {}
        _cache['values'] = fallback
        _cache['at'] = now - _CACHE_TTL_SECONDS + _FAILURE_TTL_SECONDS
        return fallback

    _cache['values'] = values
    _cache['at'] = now
    return values


def reset_cache():
    """Forget cached overrides (after a write, and in tests)."""
    _cache['values'] = None
    _cache['at'] = 0.0


def get(key):
    """The effective value: stored override if present, else the env default."""
    spec = REGISTRY.get(key)
    if not spec:
        raise KeyError(f"Unknown setting '{key}'")

    raw = _overrides().get(key)
    if raw is not None:
        value = _coerce(raw, spec['type'])
        if value is not None:
            return value

    if spec.get('config'):
        return _coerce(current_app.config.get(spec['config']), spec['type'])
    return spec.get('default')


def set_value(session, key, value, actor_user_id=None):
    """Store an override. Caller owns the session and the commit."""
    spec = REGISTRY.get(key)
    if not spec:
        raise KeyError(f"Unknown setting '{key}'")

    validator = spec.get('validate')
    if validator:
        problem = validator(value)
        if problem:
            raise ValueError(f"'{key}': {problem}")

    if spec['type'] == 'bool':
        stored = 'true' if _coerce(value, 'bool') else 'false'
    elif spec['type'] == 'int':
        number = _coerce(value, 'int')
        if number is None:
            raise ValueError(f"'{key}' must be a whole number")
        stored = str(number)
    else:
        stored = '' if value is None else str(value)

    row = session.get(AppSetting, key)
    if row:
        row.value = stored
        row.updated_by = actor_user_id
    else:
        session.add(AppSetting(key=key, value=stored, updated_by=actor_user_id))

    reset_cache()
    return stored


def describe():
    """Every setting with its effective value, for the admin panel.

    Secrets report only whether they are set - the panel never needs the value
    back, and echoing it would put it in a browser and in logs.
    """
    out = []
    for key, spec in REGISTRY.items():
        entry = {
            'key': key,
            'type': spec['type'],
            'group': spec.get('group', 'operations'),
            'label': spec['label'],
            'help': spec.get('help'),
            'secret': bool(spec.get('secret')),
        }
        value = get(key)
        if entry['secret']:
            entry['is_set'] = bool(value)
        else:
            entry['value'] = value
        out.append(entry)
    return out
