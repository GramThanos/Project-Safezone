"""Public site content: branding, social links and the legal pages.

Unauthenticated on purpose - this is what an anonymous visitor's first page is
built from, so requiring a token would mean the site could not render until you
signed in.

Only the keys named in `settings.PUBLIC_SITE_KEYS` are served. The settings
registry also holds a shared registration password and other operational values,
and "publish the site group" would be one careless `group` away from leaking one
of them.
"""
import logging

from flask import Blueprint, jsonify

from src.utils import settings

logger = logging.getLogger(__name__)
site_bp = Blueprint('site', __name__, url_prefix='/api/site')

# Where the game itself lives. Fixed rather than editable: these are Project
# Zomboid's own pages, the same for every install of this panel.
RESOURCES = [
    {'text': 'Project Zomboid', 'url': 'https://projectzomboid.com/'},
    {'text': 'Buy on Steam', 'url': 'https://store.steampowered.com/app/108600/Project_Zomboid/'},
    {'text': 'PZ Wiki', 'url': 'https://pzwiki.net/wiki/Main_Page'},
    {'text': 'Admin commands', 'url': 'https://pzwiki.net/wiki/Admin_commands'},
    {'text': 'Workshop', 'url': 'https://steamcommunity.com/app/108600/workshop/'},
]


@site_bp.route('', methods=['GET'])
def get_site():
    """Branding, social links and the game resource links (public)."""
    try:
        values = {}
        for key, name in settings.PUBLIC_SITE_KEYS.items():
            try:
                values[name] = settings.get(key)
            except KeyError:
                values[name] = None

        social = {name: values.pop(name, '') or ''
                  for name in ('discord', 'twitter', 'youtube', 'steam')}

        return jsonify({
            **values,
            # Only the ones actually set: the footer should not show an icon
            # that goes nowhere.
            'social': {name: url for name, url in social.items() if url},
            'resources': RESOURCES,
            'legal': [{'slug': slug, 'title': title}
                      for slug, (_, title) in settings.LEGAL_PAGES.items()],
        }), 200
    except Exception as e:
        logger.error(f"Get site content error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@site_bp.route('/pages/<string:slug>', methods=['GET'])
def get_legal_page(slug):
    """One legal page's Markdown (public).

    An unwritten page is a 200 with empty content, not a 404: the page exists
    and is linked from every footer, it simply has nothing in it yet. The
    browser can say so far better than an error can.
    """
    page = settings.LEGAL_PAGES.get(slug)
    if not page:
        return jsonify({'error': 'Unknown page'}), 404

    key, title = page
    try:
        return jsonify({
            'slug': slug,
            'title': title,
            'markdown': settings.get(key) or '',
        }), 200
    except Exception as e:
        logger.error(f"Get legal page error ({slug}): {e}")
        return jsonify({'error': 'Internal server error'}), 500
