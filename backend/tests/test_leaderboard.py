"""Tests for the leaderboard of living characters.

The properties worth pinning:

  * **The character, never the account.** A player's browser gets an allowlist
    of fields: no owning username, no linked account, no reason for hiding.
  * **Who is left out.** An excluded username matches the in-game owner or the
    linked account, without case; characters linked to a banned account are
    hidden unless that is switched off; hidden rows take no rank.
  * **The order.** Most zombie kills first, then longest alive; tied kills
    share a rank.
  * **Who may read it.** Public is open to anonymous visitors, signed-in needs
    a session, disabled is staff-only - and an unrecognised value fails closed.
    The staff view is moderator-only and always available.
  * **The cache.** A fresh board is served without asking the game-server; a
    game-server that cannot answer gets the last copy marked stale.
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
from src.routes.leaderboard import leaderboard_admin_bp, leaderboard_bp  # noqa: E402
from src.utils import leaderboard  # noqa: E402


def saved():
    return [
        {'username': 'alice_ig', 'name': 'Alice A', 'zombie_kills': 50, 'hours_survived': 10,
         'survivor_kills': 0, 'profession': 'base:doctor', 'time_alive': '10 hours'},
        {'username': 'Bob_IG', 'name': 'Bob B', 'zombie_kills': 80, 'hours_survived': 5},
        {'username': 'carol', 'name': 'Carol C', 'zombie_kills': 50, 'hours_survived': 30},
        {'username': 'banned_ig', 'name': 'Dan D', 'zombie_kills': 999, 'hours_survived': 1},
        {'username': 'eve', 'name': 'Eve E', 'zombie_kills': None, 'hours_survived': None},
    ]


class TestRank(unittest.TestCase):
    def test_sorted_by_kills_then_time_alive_with_shared_ranks(self):
        rows = leaderboard.rank(saved())
        self.assertEqual([r['name'] for r in rows],
                         ['Dan D', 'Bob B', 'Carol C', 'Alice A', 'Eve E'])
        self.assertEqual([r['rank'] for r in rows], [1, 2, 3, 3, 5])

    def test_excluded_by_owner_or_by_linked_account_without_case(self):
        accounts = {'bob_ig': {'id': 2, 'username': 'Bobby'}}
        rows = leaderboard.rank(saved(), excluded={'alice_ig', 'bobby'}, accounts=accounts)
        hidden = {r['name']: r['hidden'] for r in rows}
        self.assertEqual(hidden['Alice A'], leaderboard.HIDDEN_EXCLUDED)
        self.assertEqual(hidden['Bob B'], leaderboard.HIDDEN_EXCLUDED)
        self.assertIsNone(hidden['Carol C'])

    def test_hidden_rows_take_no_rank(self):
        rows = leaderboard.rank(saved(), banned={'banned_ig'})
        ranks = {r['name']: r['rank'] for r in rows}
        self.assertIsNone(ranks['Dan D'])
        self.assertEqual(ranks['Bob B'], 1)

    def test_public_rows_are_an_allowlist(self):
        accounts = {'alice_ig': {'id': 1, 'username': 'alice'}}
        rows = leaderboard.public_rows(leaderboard.rank(saved(), banned={'banned_ig'},
                                                        accounts=accounts))
        self.assertNotIn('Dan D', [r['name'] for r in rows])
        for row in rows:
            self.assertEqual(set(row), set(leaderboard.PUBLIC_FIELDS) | {'rank'})

    def test_excluded_names_accept_lines_and_commas(self):
        self.assertEqual(leaderboard.excluded_names(' Alice\n\nbob, Carol \r\n'),
                         {'alice', 'bob', 'carol'})
        self.assertEqual(leaderboard.excluded_names(None), set())


class TestVisibility(unittest.TestCase):
    def test_unrecognised_or_unreadable_fails_closed(self):
        with mock.patch('src.utils.settings.get', return_value=' Public '):
            self.assertEqual(leaderboard.visibility(), leaderboard.PUBLIC)
        with mock.patch('src.utils.settings.get', return_value='everyone'):
            self.assertEqual(leaderboard.visibility(), leaderboard.DISABLED)
        with mock.patch('src.utils.settings.get', side_effect=RuntimeError('no db')):
            self.assertEqual(leaderboard.visibility(), leaderboard.DISABLED)


class TestFetch(unittest.TestCase):
    def setUp(self):
        self.store = {}
        self.calls = []
        self.answer = ({'data': {'characters': saved(), 'saved_at': 's'}}, 200)
        for target, fn in (('cache_get', self.store.get),
                           ('cache_set', lambda k, v, ttl: self.store.__setitem__(k, v)),
                           ('gs_request', self.game_server)):
            patcher = mock.patch.object(leaderboard, target, side_effect=fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def game_server(self, method, path, **kwargs):
        self.calls.append(path)
        return self.answer

    def test_fresh_copy_is_served_without_asking(self):
        leaderboard.fetch(1, now=1000)
        entry, status = leaderboard.fetch(1, now=1030)
        self.assertEqual((status, len(self.calls), entry['stale']), (200, 1, False))

    def test_unreachable_game_server_serves_the_last_copy_stale(self):
        leaderboard.fetch(1, now=1000)
        self.answer = ({'error': 'down'}, 503)
        entry, status = leaderboard.fetch(1, now=2000)
        self.assertEqual((status, entry['stale'], len(entry['characters'])), (200, True, 5))

    def test_nothing_saved_yet_is_an_empty_board(self):
        self.answer = ({'error': 'The server has no saved characters yet'}, 404)
        entry, status = leaderboard.fetch(1, now=1000)
        self.assertEqual((status, entry['characters']), (200, []))

    def test_no_copy_and_no_answer_is_unavailable(self):
        self.answer = ({'error': 'down'}, 503)
        _, status = leaderboard.fetch(1, now=1000)
        self.assertEqual(status, 503)


class TestRoutes(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine, expire_on_commit=False)()
        self.addCleanup(self.session.close)

        for uid, name, role in ((1, 'alice', 'player'), (3, 'mod', 'moderator'),
                                (5, 'gone', 'banned')):
            self.session.add(User(id=uid, username=name, email=f'{name}@example.test',
                                  password_hash='x', role=role))
        self.session.add(Character(id=10, user_id=1, name='a', server_id=1,
                                   in_game_username='alice_ig', verified=True))
        self.session.add(Character(id=11, user_id=5, name='d', server_id=1,
                                   in_game_username='BANNED_IG', verified=True))
        self.session.commit()

        @contextmanager
        def get_db():
            yield self.session
            self.session.commit()

        self.settings = {'leaderboard_visibility': 'public', 'leaderboard_hide_banned': True,
                         'leaderboard_excluded': ''}

        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='test-secret', TOKEN_ISSUER='test-issuer',
                               TOKEN_AUDIENCE='test-audience', TOKEN_EXPIRY_HOURS=24,
                               APP_SESSION_DAYS=30)
        self.app.register_blueprint(leaderboard_bp)
        self.app.register_blueprint(leaderboard_admin_bp)
        self.client = self.app.test_client()

        servers = [{'id': 2, 'name': 'two'}, {'id': 1, 'name': 'one', 'is_primary': True}]
        entry = {'characters': saved(), 'saved_at': 's', 'fetched_at': 1, 'stale': False}
        for target, kwargs in (
                ('src.database.db.get_db', {'side_effect': get_db}),
                ('src.middleware.auth._apply_live_authorisation', {'return_value': None}),
                ('src.utils.settings.get', {'side_effect': self.settings.get}),
                ('src.routes.leaderboard._server_list', {'return_value': (servers, None, 200)}),
                ('src.utils.leaderboard.fetch', {'return_value': (entry, 200)})):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def get(self, url, user=None):
        headers = {}
        if user:
            with self.app.test_request_context():
                token = auth.generate_token(*user, 0)
            headers['Authorization'] = f'Bearer {token}'
        return self.client.get(url, headers=headers)

    PLAYER = (1, 'alice', 'player')
    MOD = (3, 'mod', 'moderator')

    def test_public_is_open_to_anonymous_visitors_and_names_no_account(self):
        response = self.get('/api/leaderboard')
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['server_id'], 1)
        self.assertEqual([s['id'] for s in body['servers']], [1, 2])
        self.assertNotIn('Dan D', [c['name'] for c in body['characters']])
        for row in body['characters']:
            self.assertNotIn('username', row)
            self.assertNotIn('account', row)

    def test_signed_in_needs_a_session(self):
        self.settings['leaderboard_visibility'] = 'authenticated'
        self.assertEqual(self.get('/api/leaderboard').status_code, 401)
        self.assertEqual(self.get('/api/leaderboard', self.PLAYER).status_code, 200)

    def test_disabled_is_refused_to_players_but_not_to_staff(self):
        self.settings['leaderboard_visibility'] = 'disabled'
        self.assertEqual(self.get('/api/leaderboard', self.PLAYER).status_code, 404)
        self.assertEqual(self.get('/api/admin/leaderboard', self.MOD).status_code, 200)

    def test_banned_players_show_when_the_switch_is_off(self):
        self.settings['leaderboard_hide_banned'] = False
        names = [c['name'] for c in self.get('/api/leaderboard').get_json()['characters']]
        self.assertEqual(names[0], 'Dan D')

    def test_excluded_by_account_username(self):
        self.settings['leaderboard_excluded'] = 'ALICE'
        names = [c['name'] for c in self.get('/api/leaderboard').get_json()['characters']]
        self.assertNotIn('Alice A', names)

    def test_staff_see_owners_accounts_and_why_hidden(self):
        rows = self.get('/api/admin/leaderboard', self.MOD).get_json()['characters']
        dan = next(r for r in rows if r['name'] == 'Dan D')
        self.assertEqual(dan['hidden'], leaderboard.HIDDEN_BANNED)
        self.assertEqual(dan['account']['username'], 'gone')
        self.assertEqual(dan['username'], 'banned_ig')

    def test_the_staff_view_refuses_players(self):
        self.assertEqual(self.get('/api/admin/leaderboard', self.PLAYER).status_code, 403)

    def test_an_unknown_server_is_not_found(self):
        self.assertEqual(self.get('/api/leaderboard?server_id=9').status_code, 404)


if __name__ == '__main__':
    unittest.main()
