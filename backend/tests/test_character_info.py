"""Tests for a linked character's game data: who sees what, and the cache.

The properties worth pinning:

  * **An allowlist, not a blocklist.** The Steam ID, admin flags, chat tag and
    mod data never reach a browser, in either view.
  * **The infection is staff-only.** The owner's view carries no infection
    flag, no ``zombie infection`` condition, no infection stats - and no wound
    that only existed because of the infection, since an empty wound would say
    the same thing. Staff see all of it.
  * **The cache.** A fresh copy is served without asking the game-server; a
    due one is refreshed; a game-server that cannot answer gets the last copy
    marked stale; a 404 is authoritative and replaces the copy.
  * **Only the owner, and staff.** Another player's character is refused, an
    unlinked one has nothing to show, and the staff route is moderator-only.
"""
import os
import sys
import unittest
from contextlib import contextmanager
from unittest import mock

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.database import Base  # noqa: E402
from src.middleware import auth  # noqa: E402
from src.models.character import Character  # noqa: E402
from src.models.user import User  # noqa: E402
from src.routes.admin import admin_bp  # noqa: E402
from src.routes.characters import characters_bp  # noqa: E402
from src.utils import character_info  # noqa: E402


def sample_report():
    """The shape `zomboid_db_api`'s ``toDict()`` returns, cut down."""
    return {
        'owner': {'username': 'thanos', 'steam_id': '76561190000000000', 'world': 'Alpha'},
        'character': {'name': 'Da Sheep', 'gender': 'male', 'profession': 'base:doctor',
                      'traits': ['base:nightowl'], 'display_name': 'thanos'},
        'status': {'status': 'alive', 'hours_survived': 162.04, 'time_alive': '6 days 18 hours',
                   'days_survived': 6.75, 'zombie_kills': 86, 'survivor_kills': 0,
                   'zombie_infected': True, 'asleep': False, 'on_fire': False, 'in_vehicle': False},
        'location': {'x': 8128.5, 'y': 11744.6, 'z': 1.0, 'location': '8128,11744,1',
                     'facing': 'SE', 'vehicle': None},
        'health': {
            'injuries': [
                {'part': 'Hand_L', 'health': 62.5, 'conditions': ['bitten', 'zombie infection', 'bandaged']},
                # Only there because of the infection: the owner must not see it at all.
                {'part': 'Neck', 'health': 100.0, 'conditions': ['zombie infection']},
            ],
            'zombie_infected': True,
            'body_parts': [{'name': 'Hand_L', 'infected': True}, {'name': 'Neck', 'infected': True},
                           {'name': 'Head', 'infected': False}],
            'body': {'infection_level': 12.5},
        },
        'condition': {
            'stats': {'hunger': {'value': 0.15, 'percent': 15.0},
                      'temperature': {'value': 37.1},
                      'zombie_infection': {'value': 12.0, 'percent': 12.0},
                      'zombie_fever': {'value': 3.0, 'percent': 3.0}},
            'nutrition': {'weight': 77.7, 'calories': -2200.0},
        },
        'skills': {'perks': {'Doctor': {'level': 6, 'xp': 5799.9}, 'Cooking': {'level': 0, 'xp': 0.0}},
                   'xp_multipliers': {}},
        'equipment': {'worn': []},
        'inventory': {'item_count': 31, 'items': []},
        'other': {'admin_flags': {'god_mode': True}, 'chat': {'tag_prefix': 'ADMIN'}},
        'mod_data': {'secret': 1},
        'decoding': {'complete': True, 'errors': []},
    }


def flatten(value):
    """Every key and string anywhere in a JSON value, for "is X anywhere" checks."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from flatten(v)
    elif isinstance(value, list):
        for v in value:
            yield from flatten(v)
    elif isinstance(value, str):
        yield value


class TestViews(unittest.TestCase):
    def test_private_fields_never_leave_in_either_view(self):
        for view in (character_info.owner_view, character_info.staff_view):
            words = set(flatten(view(sample_report())))
            for private in ('steam_id', '76561190000000000', 'admin_flags', 'god_mode',
                            'tag_prefix', 'ADMIN', 'mod_data', 'secret'):
                self.assertNotIn(private, words, msg=(view.__name__, private))

    def test_owner_sees_no_infection(self):
        view = character_info.owner_view(sample_report())
        words = set(flatten(view))
        self.assertNotIn('infection', view)
        self.assertNotIn('zombie infection', words)
        self.assertNotIn('zombie_infection', words)
        self.assertNotIn('zombie_fever', words)
        self.assertNotIn('infected', words)

    def test_owner_does_not_see_a_wound_made_only_by_the_infection(self):
        view = character_info.owner_view(sample_report())
        self.assertEqual([i['part'] for i in view['injuries']], ['Hand_L'])
        self.assertEqual(view['injuries'][0]['conditions'], ['bitten', 'bandaged'])

    def test_staff_see_the_infection(self):
        view = character_info.staff_view(sample_report())
        self.assertTrue(view['infection']['infected'])
        self.assertEqual(view['infection']['parts'], ['Hand_L', 'Neck'])
        self.assertEqual(view['infection']['level'], 12.5)
        self.assertEqual(set(view['infection']['stats']), {'zombie_infection', 'zombie_fever'})
        self.assertEqual(len(view['injuries']), 2)
        self.assertIn('zombie infection', view['injuries'][0]['conditions'])

    def test_owner_sees_their_character(self):
        view = character_info.owner_view(sample_report())
        self.assertEqual(view['name'], 'Da Sheep')
        self.assertEqual(view['status'], 'alive')
        self.assertEqual(view['zombie_kills'], 86)
        self.assertEqual(view['location']['text'], '8128,11744,1')
        self.assertEqual(view['skills']['Doctor']['level'], 6)
        self.assertEqual(view['stats']['hunger'], {'value': 0.15, 'percent': 15.0})
        self.assertEqual(view['weight'], 77.7)

    def test_an_undecodable_report_still_renders(self):
        for report in ({}, None, {'status': {'status': 'dead'}, 'skills': {}}):
            view = character_info.owner_view(report)
            self.assertEqual(view['skills'], {})
            self.assertEqual(view['injuries'], [])


class TestFetch(unittest.TestCase):
    def setUp(self):
        self.store = {}
        self.calls = []
        self.reply = ({'data': {'character': sample_report(), 'saved_at': '2026-10-06T10:00:00+00:00'}}, 200)

        def gs(method, path, **kwargs):
            self.calls.append(path)
            return self.reply

        for target, fn in (('cache_get', lambda key: self.store.get(key)),
                           ('cache_set', lambda key, value, ttl: self.store.__setitem__(key, value)),
                           ('gs_request', gs)):
            patcher = mock.patch.object(character_info, target, side_effect=fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_fetches_and_caches(self):
        entry, status = character_info.fetch(1, 'Thanos', now=1000)
        self.assertEqual(status, 200)
        self.assertFalse(entry['stale'])
        self.assertEqual(self.calls, ['/api/servers/1/characters/Thanos'])
        self.assertIn('charinfo:1:thanos', self.store)

    def test_a_fresh_copy_is_served_without_asking(self):
        character_info.fetch(1, 'thanos', now=1000)
        character_info.fetch(1, 'thanos', now=1000 + character_info.FRESH_SECONDS - 1)
        self.assertEqual(len(self.calls), 1)

    def test_a_due_copy_is_refreshed(self):
        character_info.fetch(1, 'thanos', now=1000)
        character_info.fetch(1, 'thanos', now=1000 + character_info.FRESH_SECONDS)
        self.assertEqual(len(self.calls), 2)

    def test_an_unreachable_game_server_gets_the_last_copy_marked_stale(self):
        character_info.fetch(1, 'thanos', now=1000)
        self.reply = ({'error': 'Game server unavailable'}, 503)
        entry, status = character_info.fetch(1, 'thanos', now=5000)
        self.assertEqual(status, 200)
        self.assertTrue(entry['stale'])
        self.assertEqual(entry['fetched_at'], 1000)

    def test_unreachable_with_nothing_kept_is_unavailable(self):
        self.reply = ({'error': 'Game server unavailable'}, 503)
        _, status = character_info.fetch(1, 'thanos', now=1000)
        self.assertEqual(status, 503)

    def test_not_found_replaces_the_copy_and_is_remembered_briefly(self):
        character_info.fetch(1, 'thanos', now=1000)
        self.reply = ({'error': 'not saved'}, 404)
        _, status = character_info.fetch(1, 'thanos', now=2000)
        self.assertEqual(status, 404)
        _, status = character_info.fetch(1, 'thanos', now=2001)
        self.assertEqual(status, 404)
        self.assertEqual(len(self.calls), 2)  # the second 404 came from the cache
        # ...and a later outage does not resurrect the character it replaced.
        self.reply = ({'error': 'down'}, 503)
        _, status = character_info.fetch(1, 'thanos', now=2000 + character_info.FRESH_SECONDS)
        self.assertEqual(status, 503)

    def test_the_username_cannot_change_the_path(self):
        character_info.fetch(1, '../../tasks?x=1', now=1000)
        self.assertEqual(self.calls, ['/api/servers/1/characters/..%2F..%2Ftasks%3Fx%3D1'])


class TestRoutes(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine, expire_on_commit=False)()
        self.addCleanup(self.session.close)

        for uid, name, role in ((1, 'alice', 'player'), (2, 'bob', 'player'), (3, 'mod', 'moderator')):
            self.session.add(User(id=uid, username=name, email=f'{name}@example.test',
                                  password_hash='x', role=role))
        self.session.add(Character(id=10, user_id=1, name='thanos', server_id=1,
                                   in_game_username='thanos', verified=True))
        self.session.add(Character(id=11, user_id=1, name='pending', verified=False))
        self.session.commit()

        @contextmanager
        def get_db():
            yield self.session
            self.session.commit()

        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='test-secret', TOKEN_ISSUER='test-issuer',
                               TOKEN_AUDIENCE='test-audience', TOKEN_EXPIRY_HOURS=24,
                               APP_SESSION_DAYS=30)
        self.app.register_blueprint(characters_bp)
        self.app.register_blueprint(admin_bp)
        self.client = self.app.test_client()

        entry = {'report': sample_report(), 'saved_at': 's', 'fetched_at': 1, 'stale': False}
        for target, kwargs in (
                ('src.database.db.get_db', {'side_effect': get_db}),
                ('src.middleware.auth._apply_live_authorisation', {'return_value': None}),
                ('src.utils.settings.get', {'side_effect': RuntimeError('no db')}),
                ('src.utils.character_info.fetch', {'return_value': (entry, 200)})):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def get(self, url, user_id, username, role):
        with self.app.test_request_context():
            token = auth.generate_token(user_id, username, role, 0)
        return self.client.get(url, headers={'Authorization': f'Bearer {token}'})

    def test_the_owner_gets_the_owner_view(self):
        response = self.get('/api/characters/10/game', 1, 'alice', 'player')
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['character']['name'], 'Da Sheep')
        self.assertNotIn('infection', body['character'])

    def test_another_player_is_refused(self):
        response = self.get('/api/characters/10/game', 2, 'bob', 'player')
        self.assertEqual(response.status_code, 403)

    def test_an_unlinked_character_has_nothing_to_show(self):
        response = self.get('/api/characters/11/game', 1, 'alice', 'player')
        self.assertEqual(response.status_code, 404)

    def test_staff_get_the_staff_view_and_it_is_audited(self):
        from src.models.audit_log import AuditLog
        response = self.get('/api/admin/characters/10/game', 3, 'mod', 'moderator')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['character']['infection']['infected'])
        self.assertEqual(self.session.query(AuditLog).filter_by(action='character.view').count(), 1)

    def test_the_staff_route_refuses_players(self):
        response = self.get('/api/admin/characters/10/game', 1, 'alice', 'player')
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
