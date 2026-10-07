"""Tests for coins: earning by playing, selling back, the shop and its rules.

The properties worth pinning:

  * **Nothing from before the link is paid.** The first reading is the
    baseline; a newly claimed character starts from what it already has.
  * **Whole steps only, and the rest carries.**
  * **One life at a time.** A new name is a new character, counted from zero.
    A counter that drops without a new name, or a name seen before, is a
    restored backup or a rollback: it starts again from where it stands and
    pays nothing - so a restored world is never paid twice.
  * **A reward sells once.** Its coin value, whatever its count; a split send
    keeps the value with the part left behind.
  * **Buying and selling back can never make coins**, and a daily limit holds.
  * **Every gain is logged**, and the daily report sums yesterday from the log.
"""
import os
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import src.models  # noqa: E402,F401  (every table, for create_all)
from src.database import Base  # noqa: E402
from src.middleware import auth  # noqa: E402
from src.models.audit_log import AuditLog  # noqa: E402
from src.models.character import Character  # noqa: E402
from src.models.coin_log import CoinLog  # noqa: E402
from src.models.inventory_item import InventoryItem  # noqa: E402
from src.models.notification import Notification  # noqa: E402
from src.models.reward import Reward  # noqa: E402
from src.models.shop_category import ShopCategory  # noqa: E402
from src.models.shop_item import ShopItem  # noqa: E402
from src.models.shop_item_category import ShopItemCategory  # noqa: E402
from src.models.shop_purchase import ShopPurchase  # noqa: E402
from src.models.user import User  # noqa: E402
from src.routes.admin import admin_bp  # noqa: E402
from src.routes.characters import characters_bp  # noqa: E402
from src.routes.claims import claims_bp  # noqa: E402
from src.routes.inventory import inventory_bp  # noqa: E402
from src.routes.rewards import rewards_bp  # noqa: E402
from src.routes.shop import coins_bp, shop_bp  # noqa: E402
from src.routes.shop_admin import shop_admin_bp  # noqa: E402
from src.utils import coins, jobs  # noqa: E402

RATE = (1, 10)   # one coin per ten kills
NOON = '2026-10-07T12:00:00+00:00'
ONE = '2026-10-07T13:00:00+00:00'
TWO = '2026-10-07T14:00:00+00:00'


def entry(kills, name='Da Sheep', saved_at=NOON, stale=False):
    """What `character_info.fetch` returns, cut to what coins read."""
    return {'report': {'character': {'name': name},
                       'status': {'zombie_kills': kills, 'hours_survived': 10.0}},
            'saved_at': saved_at, 'fetched_at': 1, 'stale': stale}


def reading(kills, name='Da Sheep', saved_at=NOON):
    return coins.reading_from_entry(entry(kills, name, saved_at))


class TestRule(unittest.TestCase):
    def test_the_first_reading_is_the_baseline_and_pays_nothing(self):
        self.assertEqual(coins.settle(None, 500, RATE), (0, 500))

    def test_whole_steps_are_paid_and_the_rest_carries(self):
        self.assertEqual(coins.settle(100, 137, RATE), (3, 130))
        self.assertEqual(coins.settle(130, 141, RATE), (1, 140))

    def test_a_new_life_counts_from_zero(self):
        self.assertEqual(coins.settle(130, 25, RATE, 'new'), (2, 20))
        # Even when the new character has already outkilled the old one.
        self.assertEqual(coins.settle(130, 150, RATE, 'new'), (15, 150))

    def test_a_drop_in_the_same_life_is_a_rollback_and_pays_nothing(self):
        self.assertEqual(coins.settle(900, 600, RATE), (0, 600))

    def test_a_restored_life_pays_nothing(self):
        self.assertEqual(coins.settle(20, 900, RATE, 'restored'), (0, 900))

    def test_with_nothing_to_pay_the_counter_still_keeps_up(self):
        self.assertEqual(coins.settle(100, 180, None), (0, 180))

    def test_which_life_a_reading_belongs_to(self):
        self.assertEqual(coins.life('Bob', [], 'Bob'), 'same')
        self.assertEqual(coins.life('Bob', [], 'Rob'), 'new')
        self.assertEqual(coins.life('Rob', ['Bob'], 'Bob'), 'restored')
        # Without a name either side, nothing can be told apart: a drop is
        # then treated as a rollback, which can only underpay.
        self.assertEqual(coins.life('Bob', [], None), 'same')
        self.assertEqual(coins.life(None, [], 'Bob'), 'same')


class TestReading(unittest.TestCase):
    def test_save_time_becomes_naive_utc(self):
        self.assertEqual(coins.parse_saved_at('2026-10-07T14:00:00+02:00'),
                         datetime(2026, 10, 7, 12, 0, 0))
        self.assertIsNone(coins.parse_saved_at('yesterday'))

    def test_a_reading_from_either_shape(self):
        full = reading(12)
        summary = coins.reading_from_summary(
            {'username': 'thanos', 'name': 'Da Sheep', 'zombie_kills': 12}, NOON)
        self.assertEqual(full, summary)
        self.assertEqual(full.values, {'kills': 12})
        self.assertIsNone(coins.reading_from_summary(None, NOON))
        self.assertIsNone(coins.reading_from_entry(entry(12, saved_at=None)))

    def test_a_stale_copy_never_sets_a_baseline(self):
        self.assertIsNone(coins.reading_from_entry(entry(40, stale=True), allow_stale=False))
        character = Character()
        coins.baseline(character, coins.reading_from_entry(entry(40, stale=True), allow_stale=False))
        self.assertIsNone(character.coin_progress)

    def test_gains_described_in_a_sentence(self):
        self.assertEqual(coins.describe_gains([('sale', 4, 2), ('kills', 30, 300), ('other', 1, 0)]),
                         '30 for 300 zombie kills, 4 for selling 2 rewards, 1 from other')


class TestPrices(unittest.TestCase):
    def test_floor_and_suggestion_are_per_reward(self):
        reward = Reward(name='Nails', kind='item', coin_value=3)
        self.assertEqual(coins.min_price(reward), 3)
        self.assertEqual(coins.suggested_price(reward), 60)
        self.assertEqual(coins.min_price(Reward(name='Free', kind='item', coin_value=0)), 1)

    def test_a_holding_sells_once_whatever_its_count(self):
        reward = Reward(name='Nails', kind='item', coin_value=2)
        now = datetime(2026, 10, 7)
        self.assertEqual(InventoryItem(status='held', count=50).sell_value(reward, now), 2)
        self.assertEqual(InventoryItem(status='failed', count=1).sell_value(reward, now), 2)
        for status in ('sending', 'delivered', 'expired'):
            self.assertEqual(InventoryItem(status=status).sell_value(reward, now), 0)
        lapsed = InventoryItem(status='held', expires_at=now - timedelta(seconds=1))
        self.assertEqual(lapsed.sell_value(reward, now), 0)
        self.assertEqual(InventoryItem(status='held', sellable=False).sell_value(reward, now), 0)


class RouteCase(unittest.TestCase):
    """Real blueprints against SQLite, with settings and the game-server stubbed."""

    def setUp(self):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine, expire_on_commit=False)()
        self.addCleanup(self.session.close)

        self.session.add_all([
            User(id=1, username='alice', email='alice@example.test', password_hash='x',
                 role='player', coin_balance=100),
            User(id=2, username='admin', email='admin@example.test', password_hash='x',
                 role='admin'),
            Reward(id=1, kind='item', name='Axe', in_game_id='Base.Axe', coin_value=2),
            Reward(id=2, kind='usable', name='Heal', commands='heal', coin_value=5),
            ShopCategory(id=1, name='Weapons'),
            ShopCategory(id=2, name='Starter kit'),
            ShopItem(id=1, reward_id=1, count=3, price=60),
            ShopItemCategory(shop_item_id=1, category_id=1),
            ShopItemCategory(shop_item_id=1, category_id=2),
        ])
        self.session.commit()

        @contextmanager
        def get_db():
            yield self.session
            self.session.commit()

        self.settings = {'coins_enabled': True, 'coins_per_kill_step': 1,
                         'kills_per_coin_step': 10, 'shop_item_expiry_days': 0,
                         'inventory_expiry_days': 0}

        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='test-secret', TOKEN_ISSUER='test-issuer',
                               TOKEN_AUDIENCE='test-audience', TOKEN_EXPIRY_HOURS=24,
                               APP_SESSION_DAYS=30)
        for bp in (inventory_bp, coins_bp, shop_bp, shop_admin_bp, rewards_bp,
                   characters_bp, claims_bp, admin_bp):
            self.app.register_blueprint(bp)
        self.client = self.app.test_client()

        for target, kwargs in (
                ('src.database.db.get_db', {'side_effect': get_db}),
                ('src.middleware.auth._apply_live_authorisation', {'return_value': None}),
                ('src.utils.settings.get', {'side_effect': lambda key: self.settings[key]}),
                ('src.utils.daily.primary_timezone', {'return_value': ZoneInfo('UTC')})):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def call(self, method, url, user=(1, 'alice', 'player'), json=None):
        with self.app.test_request_context():
            token = auth.generate_token(*user, 0)
        return self.client.open(url, method=method, json=json,
                                headers={'Authorization': f'Bearer {token}'})

    def admin(self, method, url, json=None):
        return self.call(method, url, user=(2, 'admin', 'admin'), json=json)

    def balance(self, user_id=1):
        return coins.balance(self.session, user_id)

    def held(self, reward_id=1, count=1, status=InventoryItem.STATUS_HELD, **extra):
        item = InventoryItem(user_id=1, reward_id=reward_id, count=count, status=status, **extra)
        self.session.add(item)
        self.session.commit()
        return item.id


class TestSelling(RouteCase):
    def test_discarding_sells_each_reward_once_and_logs_it(self):
        ids = [self.held(count=40), self.held(reward_id=2)]
        listed = self.call('GET', '/api/inventory').get_json()['inventory']
        self.assertEqual(sum(i['sell_value'] for i in listed), 2 + 5)

        res = self.call('POST', '/api/inventory/remove', json={'ids': ids})
        self.assertEqual(res.get_json()['coins'], 7)
        self.assertEqual(self.balance(), 107)
        log = self.session.query(CoinLog).one()
        self.assertEqual((log.source, log.amount, log.quantity), ('sale', 7, 2))

    def test_a_second_discard_of_the_same_holding_pays_nothing(self):
        item = self.held(count=4)
        self.call('POST', '/api/inventory/remove', json={'ids': [item]})
        self.assertEqual(self.call('POST', '/api/inventory/remove', json={'ids': [item]})
                         .get_json()['coins'], 0)
        self.assertEqual(self.balance(), 102)

    def test_used_expired_and_in_flight_holdings_pay_nothing(self):
        delivered = self.held(status=InventoryItem.STATUS_DELIVERED)
        lapsed = self.held(expires_at=datetime.utcnow() - timedelta(minutes=1))
        sending = self.held(status=InventoryItem.STATUS_SENDING)
        res = self.call('POST', '/api/inventory/remove',
                        json={'ids': [delivered, lapsed, sending]})
        self.assertEqual(res.get_json(), {'removed': 2, 'coins': 0, 'balance': 100})

    def test_a_split_send_keeps_the_value_with_what_stays(self):
        self.session.add(Character(id=10, user_id=1, name='thanos', server_id=1,
                                   in_game_username='thanos', verified=True))
        self.session.commit()
        item = self.held(count=10)
        with mock.patch('src.routes.inventory.is_player_online', return_value=True), \
                mock.patch('src.routes.inventory.gs_request', return_value=({'data': {'id': 7}}, 201)):
            res = self.call('POST', f'/api/inventory/{item}/send',
                            json={'character_id': 10, 'count': 3})
        self.assertEqual(res.status_code, 200, res.get_json())
        sent = self.session.get(InventoryItem, item)
        rest = self.session.query(InventoryItem).filter(InventoryItem.id != item).one()
        self.assertFalse(sent.sellable)
        self.assertTrue(rest.sellable)
        # The delivery comes back: the reward is still only worth its value once.
        sent.status = InventoryItem.STATUS_FAILED
        self.session.commit()
        res = self.call('POST', '/api/inventory/remove', json={'ids': [item, rest.id]})
        self.assertEqual(res.get_json()['coins'], 2)

    def test_with_coins_off_discarding_is_just_discarding(self):
        self.settings['coins_enabled'] = False
        res = self.call('POST', '/api/inventory/remove', json={'ids': [self.held(count=4)]})
        self.assertEqual(res.get_json(), {'removed': 1, 'coins': 0})


class TestBuying(RouteCase):
    def test_a_purchase_takes_the_price_and_records_it(self):
        self.settings['shop_item_expiry_days'] = 3
        res = self.call('POST', '/api/shop/items/1/buy', json={'price': 60})
        self.assertEqual(res.status_code, 201, res.get_json())
        self.assertEqual(res.get_json()['balance'], 40)
        item = self.session.query(InventoryItem).one()
        self.assertEqual((item.reward_id, item.count, item.source), (1, 3, 'shop'))
        self.assertGreater(item.expires_at, datetime.utcnow() + timedelta(days=2))
        self.assertEqual(self.session.query(ShopPurchase).count(), 1)
        self.assertEqual(self.session.query(AuditLog).filter_by(action='shop.buy').count(), 1)

    def test_a_listing_in_two_categories_shows_in_both(self):
        body = self.call('GET', '/api/shop').get_json()
        self.assertEqual([c['name'] for c in body['categories']], ['Starter kit', 'Weapons'])
        self.assertEqual(body['expiry_days'], 0)

    def test_the_daily_limit_holds_and_resets_with_the_day(self):
        self.session.get(ShopItem, 1).daily_limit = 1
        self.session.get(User, 1).coin_balance = 1000
        self.session.commit()
        self.assertEqual(self.call('POST', '/api/shop/items/1/buy').status_code, 201)
        res = self.call('POST', '/api/shop/items/1/buy')
        self.assertEqual(res.status_code, 409)
        self.assertIn('once a day', res.get_json()['error'])
        listed = self.call('GET', '/api/shop').get_json()['categories'][0]['items'][0]
        self.assertEqual(listed['left_today'], 0)
        # Yesterday's purchase no longer counts.
        self.session.query(ShopPurchase).update({'created_at': datetime.utcnow() - timedelta(days=1)})
        self.session.commit()
        self.assertEqual(self.call('POST', '/api/shop/items/1/buy').status_code, 201)

    def test_a_purchase_the_balance_cannot_cover_writes_nothing(self):
        self.session.get(User, 1).coin_balance = 59
        self.session.commit()
        self.assertEqual(self.call('POST', '/api/shop/items/1/buy').status_code, 409)
        self.assertEqual(self.balance(), 59)
        self.assertEqual(self.session.query(InventoryItem).count(), 0)
        self.assertEqual(self.session.query(ShopPurchase).count(), 0)

    def test_a_changed_price_is_not_charged(self):
        res = self.call('POST', '/api/shop/items/1/buy', json={'price': 50})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(self.balance(), 100)

    def test_a_listing_in_no_shown_category_is_not_for_sale(self):
        for category in self.session.query(ShopCategory):
            category.active = False
        self.session.commit()
        self.assertEqual(self.call('POST', '/api/shop/items/1/buy').status_code, 404)
        self.settings['coins_enabled'] = False
        self.assertEqual(self.call('GET', '/api/shop').status_code, 404)

    def test_the_shop_never_shows_command_text(self):
        self.session.add_all([ShopItem(id=2, reward_id=2, count=1, price=100),
                              ShopItemCategory(shop_item_id=2, category_id=1)])
        self.session.commit()
        listed = [i['reward'] for c in self.call('GET', '/api/shop').get_json()['categories']
                  for i in c['items']]
        self.assertTrue(listed)
        self.assertTrue(all('commands' not in r for r in listed))

    def test_buying_and_selling_back_never_makes_coins(self):
        self.call('POST', '/api/shop/items/1/buy')
        item = self.session.query(InventoryItem).one()
        self.call('POST', '/api/inventory/remove', json={'ids': [item.id]})
        self.assertLessEqual(self.balance(), 100)


class TestAdminShop(RouteCase):
    def test_a_listing_cannot_be_priced_below_its_sell_value(self):
        self.session.get(Reward, 1).coin_value = 20
        self.session.commit()
        body = {'reward_id': 1, 'count': 10, 'price': 19, 'category_ids': [1]}
        self.assertEqual(self.admin('POST', '/api/admin/shop/items', json=body).status_code, 400)
        body['price'] = 20
        self.assertEqual(self.admin('POST', '/api/admin/shop/items', json=body).status_code, 201)

    def test_a_listing_is_saved_whole_with_its_categories_and_limit(self):
        res = self.admin('PUT', '/api/admin/shop/items/1',
                         json={'price': 80, 'daily_limit': 2, 'category_ids': [2]})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json()['item']['category_ids'], [2])
        listing = self.session.get(ShopItem, 1)
        self.assertEqual((listing.price, listing.daily_limit), (80, 2))
        # Taking the limit off again.
        self.admin('PUT', '/api/admin/shop/items/1', json={'daily_limit': None})
        self.assertIsNone(self.session.get(ShopItem, 1).daily_limit)

    def test_a_refused_edit_changes_nothing(self):
        res = self.admin('PUT', '/api/admin/shop/items/1', json={'price': 1, 'category_ids': [2]})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.session.get(ShopItem, 1).price, 60)
        self.assertEqual(self.session.query(ShopItemCategory).filter_by(shop_item_id=1).count(), 2)

    def test_deleting_a_category_keeps_the_listing_in_its_others(self):
        self.admin('DELETE', '/api/admin/shop/categories/1')
        self.assertEqual([r.category_id for r in self.session.query(ShopItemCategory)], [2])
        self.assertIsNotNone(self.session.get(ShopItem, 1))

    def test_an_action_is_listed_one_at_a_time(self):
        res = self.admin('POST', '/api/admin/shop/items',
                         json={'reward_id': 2, 'count': 2, 'price': 100, 'category_ids': []})
        self.assertEqual(res.status_code, 400)

    def test_raising_a_value_above_a_listing_is_refused(self):
        res = self.admin('PUT', '/api/admin/rewards/1', json={'coin_value': 61})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(self.session.get(Reward, 1).coin_value, 2)
        self.assertEqual(self.admin('PUT', '/api/admin/rewards/1', json={'coin_value': 60}).status_code, 200)

    def test_rewards_can_be_searched(self):
        res = self.admin('GET', '/api/admin/rewards?q=base.ax')
        self.assertEqual([r['name'] for r in res.get_json()['rewards']], ['Axe'])
        res = self.admin('GET', '/api/admin/rewards?q=100%25')
        self.assertEqual(res.get_json()['rewards'], [])

    def test_players_cannot_change_the_shop(self):
        res = self.call('POST', '/api/admin/shop/categories', json={'name': 'Free stuff'})
        self.assertEqual(res.status_code, 403)


class TestSettlement(RouteCase):
    def setUp(self):
        super().setUp()
        self.session.add(Character(id=10, user_id=1, name='thanos', server_id=1,
                                   in_game_username='thanos', verified=True))
        self.session.commit()

    def settle(self, kills, saved_at, name='Da Sheep'):
        return coins.settle_character(self.session, 10, reading(kills, name, saved_at))

    def test_baseline_then_pay_and_log(self):
        self.assertEqual(self.settle(500, NOON), 0)
        self.assertEqual(self.settle(537, ONE), 3)
        self.assertEqual(self.balance(), 103)
        log = self.session.query(CoinLog).one()
        self.assertEqual((log.source, log.amount, log.quantity, log.character_id),
                         ('kills', 3, 30, 10))
        # Paying no longer notifies one by one: the daily report does.
        self.assertEqual(self.session.query(Notification).count(), 0)

    def test_an_older_save_is_only_noted_as_checked(self):
        self.settle(500, NOON)
        self.settle(537, ONE)
        self.assertEqual(self.settle(510, NOON), 0)
        character = self.session.get(Character, 10)
        self.assertEqual(character.coin_progress['kills'], {'counted': 530, 'seen': 537})
        self.assertIsNotNone(character.coin_checked_at)

    def test_a_restored_backup_is_not_paid_again(self):
        # 900 kills paid for, then the world is restored to when it had 600.
        self.settle(0, NOON)
        self.settle(900, ONE)
        self.assertEqual(self.balance(), 190)
        self.assertEqual(self.settle(600, TWO), 0)
        self.assertEqual(self.session.get(Character, 10).coin_progress['kills']['counted'], 600)
        # Only kills made after the restore pay.
        self.assertEqual(self.settle(615, '2026-10-07T15:00:00+00:00'), 1)

    def test_a_death_starts_a_new_life_and_an_old_life_coming_back_is_a_restore(self):
        self.settle(0, NOON)
        self.settle(900, ONE)                         # Da Sheep: 90 coins
        self.assertEqual(self.settle(45, TWO, name='New Guy'), 4)
        # A backup from before the death brings Da Sheep back with 900 again.
        self.assertEqual(self.settle(900, '2026-10-07T15:00:00+00:00'), 0)
        self.assertEqual(self.balance(), 194)

    def test_a_banned_owner_earns_nothing_but_the_counter_moves(self):
        self.settle(500, NOON)
        self.session.get(User, 1).role = User.ROLE_BANNED
        self.session.commit()
        self.assertEqual(self.settle(600, ONE), 0)
        self.assertEqual(self.session.get(Character, 10).coin_progress['kills']['counted'], 600)

    def test_viewing_and_unlinking_settle(self):
        self.settle(500, NOON)
        with mock.patch('src.utils.character_info.fetch', return_value=(entry(520, saved_at=ONE), 200)):
            self.assertEqual(self.call('GET', '/api/characters/10/game').status_code, 200)
        self.assertEqual(self.balance(), 102)
        with mock.patch('src.utils.character_info.fetch', return_value=(entry(540, saved_at=TWO), 200)):
            self.assertEqual(self.call('DELETE', '/api/characters/10').status_code, 200)
        self.assertEqual(self.balance(), 104)

    def test_the_progress_page_shows_what_is_left_to_the_next_coin(self):
        self.settle(500, NOON)
        with mock.patch('src.utils.character_info.fetch', return_value=(entry(537, saved_at=ONE), 200)):
            body = self.call('GET', '/api/coins/characters').get_json()
        character = body['characters'][0]
        kills = character['sources'][0]
        self.assertEqual((kills['counted'], kills['seen'], kills['to_next']), (530, 537, 3))
        self.assertEqual(character['earned'], 3)
        self.assertEqual(body['sources'][0]['per'], 10)


class TestJobs(RouteCase):
    def setUp(self):
        super().setUp()
        self.session.add_all([
            Character(id=10, user_id=1, name='thanos', server_id=1, in_game_username='thanos',
                      verified=True),
            Character(id=11, user_id=1, name='alt', server_id=2, in_game_username='Alt',
                      verified=True)])
        self.session.commit()

    def test_one_snapshot_per_server_after_a_save(self):
        calls = []

        def snapshot(method, path, json=None, timeout=None, **kw):
            calls.append((path, json))
            server = path.split('/')[3]
            return {'data': {'saved': True, 'saved_at': ONE, 'characters': [
                {'username': 'thanos' if server == '1' else 'ALT', 'name': 'X', 'zombie_kills': 25}]}}, 200

        coins.settle_character(self.session, 10, reading(0, 'X', NOON))
        coins.settle_character(self.session, 11, reading(0, 'X', NOON))
        with mock.patch('src.utils.game_server.gs_request', side_effect=snapshot):
            _, follow_up = jobs.settle_coins(self.session)
            outcome = follow_up()
        self.assertEqual(calls, [('/api/servers/1/characters/snapshot', {'save': True}),
                                 ('/api/servers/2/characters/snapshot', {'save': True})])
        self.assertEqual(outcome, 'read 2, paid 4 coin(s)')
        self.assertEqual(self.balance(), 104)

    def test_a_server_that_cannot_answer_is_reported_and_skipped(self):
        with mock.patch('src.utils.game_server.gs_request',
                        return_value=({'error': 'Game server unavailable'}, 503)):
            _, follow_up = jobs.settle_coins(self.session)
            self.assertIn('server 1: Game server unavailable', follow_up())

    def test_yesterdays_earnings_are_reported_once(self):
        yesterday = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        self.session.add_all([
            CoinLog(user_id=1, amount=30, source='kills', quantity=300, created_at=yesterday),
            CoinLog(user_id=1, amount=4, source='sale', quantity=2, created_at=yesterday),
            CoinLog(user_id=1, amount=50, source='admin', created_at=yesterday),
            CoinLog(user_id=1, amount=9, source='kills', quantity=90, created_at=datetime.utcnow())])
        self.session.commit()
        marks = set()

        class Redis:
            def set(self, key, value, nx=False, ex=None):
                if key in marks:
                    return None
                marks.add(key)
                return True

        with mock.patch('src.utils.redis_utils.get_redis_connection', return_value=Redis()):
            self.assertIn('reported', jobs.coin_report(self.session))
            self.assertIn('already reported', jobs.coin_report(self.session))
        note = self.session.query(Notification).filter_by(kind='coins').one()
        self.assertEqual(note.title, 'Yesterday you earned 34 coins')
        self.assertEqual(note.body, '30 for 300 zombie kills, 4 for selling 2 rewards.')


class TestRetention(RouteCase):
    def test_pruning_keeps_every_total(self):
        self.session.add(Character(id=10, user_id=1, name='thanos', server_id=1,
                                   in_game_username='thanos', verified=True))
        self.session.commit()
        coins.settle_character(self.session, 10, reading(0, saved_at=NOON))
        coins.settle_character(self.session, 10, reading(50, saved_at=ONE))
        self.call('POST', '/api/shop/items/1/buy')
        old = datetime.utcnow() - timedelta(days=200)
        self.session.query(CoinLog).update({'created_at': old})
        self.session.query(ShopPurchase).update({'created_at': old})
        self.session.add(CoinLog(user_id=1, amount=1, source='sale', quantity=1))
        self.session.commit()
        self.settings['coin_log_retention_days'] = 90

        self.assertIn('removed 1 coin log entry and 1 purchase', jobs.prune_coin_log(self.session))
        self.assertEqual(self.session.query(CoinLog).count(), 1)
        self.assertEqual(self.session.query(ShopPurchase).count(), 0)
        # The history went; the totals did not.
        self.assertEqual(self.balance(), 100 + 5 - 60)
        self.assertEqual(self.session.get(Character, 10).coin_earned, 5)
        self.assertEqual(self.session.get(ShopItem, 1).sold, 1)

    def test_zero_keeps_everything(self):
        self.session.add(CoinLog(user_id=1, amount=1, source='sale',
                                 created_at=datetime.utcnow() - timedelta(days=999)))
        self.session.commit()
        self.settings['coin_log_retention_days'] = 0
        self.assertIn('kept indefinitely', jobs.prune_coin_log(self.session))
        self.assertEqual(self.session.query(CoinLog).count(), 1)

    def test_the_window_cannot_be_shorter_than_the_daily_summary_needs(self):
        validate = settings_registry()['coin_log_retention_days']['validate']
        self.assertIsNone(validate('0'))
        self.assertIsNone(validate('2'))
        self.assertIsNotNone(validate('1'))
        self.assertIsNotNone(validate('soon'))


def settings_registry():
    from src.utils import settings
    return settings.REGISTRY


class TestClaimBaseline(RouteCase):
    def claim(self, fetched):
        with mock.patch('src.routes.claims.gs_request', return_value=({}, 200)), \
                mock.patch('src.routes.claims.is_player_online', return_value=True), \
                mock.patch('src.routes.claims.alerting.emit'), \
                mock.patch('src.utils.character_info.fetch', return_value=fetched):
            return self.call('POST', '/api/claims',
                             json={'server_id': 1, 'in_game_username': 'veteran'})

    def test_a_new_link_starts_from_what_it_already_has(self):
        self.assertEqual(self.claim((entry(4000), 200)).status_code, 201)
        character = self.session.query(Character).filter_by(in_game_username='veteran').one()
        self.assertEqual(character.coin_progress, {'kills': {'counted': 4000, 'seen': 4000}})
        coins.settle_character(self.session, character.id, reading(4010, saved_at=ONE))
        self.assertEqual(self.balance(), 101)

    def test_without_a_fresh_reading_the_first_check_is_the_baseline(self):
        self.claim((entry(4000, stale=True), 200))
        character = self.session.query(Character).filter_by(in_game_username='veteran').one()
        self.assertIsNone(character.coin_progress)
        self.assertEqual(coins.settle_character(self.session, character.id, reading(4000)), 0)
        self.assertEqual(character.coin_progress['kills']['counted'], 4000)


class TestAdjust(RouteCase):
    def test_grants_are_logged_and_deductions_refused_beyond_the_balance(self):
        res = self.admin('POST', '/api/admin/users/1/coins', json={'amount': 25, 'reason': 'prize'})
        self.assertEqual(res.get_json()['balance'], 125)
        self.assertEqual(self.session.query(CoinLog).one().source, 'admin')
        res = self.admin('POST', '/api/admin/users/1/coins', json={'amount': -126, 'reason': 'x'})
        self.assertEqual(res.status_code, 409)
        log = self.admin('GET', '/api/admin/users/1/coin-log').get_json()['log']
        self.assertEqual([(e['amount'], e['label']) for e in log], [(25, 'staff')])

    def test_the_user_page_carries_each_characters_coin_progress(self):
        self.session.add(Character(id=10, user_id=1, name='thanos', server_id=1,
                                   in_game_username='thanos', verified=True))
        self.session.commit()
        coins.settle_character(self.session, 10, reading(500))
        body = self.admin('GET', '/api/admin/users/1').get_json()
        self.assertEqual(body['characters'][0]['coins']['sources'][0]['counted'], 500)
        self.assertEqual(body['characters'][0]['coins']['life'], 'Da Sheep')


if __name__ == '__main__':
    unittest.main()
