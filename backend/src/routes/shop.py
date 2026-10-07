"""The coin shop, the account's coin balance, and its characters' progress.

`GET /api/coins` is the small, always-available answer to "is the coin system on
and what do I have", polled with the rest of the player's counts.
`GET /api/coins/characters` is the fuller answer the Characters page shows: how
far each linked character is from its next coin, and when it was last checked -
checking each one on the way, since its data is being read anyway.

A purchase takes the coins, records the purchase and adds the reward to the
inventory in one transaction, as an ordinary held item (source ``shop``) with the
shop's own expiry; from there it is sent like every other reward.
"""
import logging
from flask import Blueprint, request, jsonify
from sqlalchemy import func
from src.database import db
from src.models.character import Character
from src.models.inventory_item import InventoryItem
from src.models.reward import Reward
from src.models.shop_category import ShopCategory
from src.models.shop_item import ShopItem
from src.models.shop_item_category import ShopItemCategory
from src.models.shop_purchase import ShopPurchase
from src.models.user import User
from src.middleware.auth import token_required
from src.utils import audit, character_info, coins, expiry, settings

logger = logging.getLogger(__name__)
coins_bp = Blueprint('coins', __name__, url_prefix='/api/coins')
shop_bp = Blueprint('shop', __name__, url_prefix='/api/shop')

CLOSED = {'error': 'The shop is closed'}


def _iso(moment):
    return moment.isoformat() if moment else None


def _expiry_days():
    try:
        return settings.get('shop_item_expiry_days') or 0
    except Exception:
        return 0


@coins_bp.route('', methods=['GET'])
@token_required
def get_coins(current_user):
    """Whether coins are on, this account's balance, and what playing earns."""
    try:
        paying = coins.rates()
        kills = next((r for r in paying if r['key'] == 'kills'), None)
        with db.get_db() as session:
            return jsonify({
                'enabled': coins.enabled(),
                'balance': coins.balance(session, current_user['user_id']),
                'sources': paying,
                # Kept for the shop's one-line hint.
                'kills': {'coins': kills['coins'], 'kills': kills['per']} if kills else None,
            }), 200
    except Exception as e:
        logger.error(f"Get coins error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@coins_bp.route('/characters', methods=['GET'])
@token_required
def get_character_coins(current_user):
    """Each linked character's progress towards its next coin.

    Each one is checked first - its save is read (from the cache when it is
    fresh) and anything due is paid - so what is shown is current as of the
    game's last save, not the last time somebody happened to look.
    """
    user_id = current_user['user_id']
    try:
        with db.get_db() as session:
            linked = [(c.id, c.server_id, c.in_game_username)
                      for c in session.query(Character).filter_by(user_id=user_id).all()
                      if c.is_deliverable()]

        if coins.enabled():
            for character_id, server_id, username in linked:
                entry, status = character_info.fetch(server_id, username)
                if status == 200:
                    coins.settle_quietly(character_id, coins.reading_from_entry(entry))

        with db.get_db() as session:
            paying = coins.rates()
            by_key = {r['key']: r for r in paying}
            ids = [cid for cid, _, _ in linked]
            characters = (session.query(Character)
                          .filter(Character.id.in_(ids))
                          .order_by(Character.id.asc())
                          .all()) if ids else []
            return jsonify({
                'enabled': coins.enabled(),
                'sources': paying,
                'next_check_at': _iso(coins.next_sweep(session)),
                'daily_report': coins.report_enabled(session),
                'characters': [coins.character_status(c, by_key) for c in characters],
            }), 200
    except Exception as e:
        logger.error(f"Get character coins error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def _bought_today(session, user_id, listing_ids):
    """``{listing_id: purchases}`` by this account since the start of today."""
    if not listing_ids:
        return {}
    start, _ = coins.day_bounds()
    rows = (session.query(ShopPurchase.shop_item_id, func.count(ShopPurchase.id))
            .filter(ShopPurchase.user_id == user_id,
                    ShopPurchase.shop_item_id.in_(listing_ids),
                    ShopPurchase.created_at >= start)
            .group_by(ShopPurchase.shop_item_id))
    return dict(rows)


def _listing_view(listing, reward, bought_today):
    """A listing as a player sees it: no command text, nothing admin-only."""
    limit = listing.daily_limit
    return {
        'id': listing.id,
        'count': coins.units(reward.kind, listing.count),
        'price': listing.price,
        'daily_limit': limit,
        'left_today': None if limit is None else max(limit - bought_today, 0),
        'reward': {
            'id': reward.id,
            'kind': reward.kind,
            'name': reward.name,
            'description': reward.description,
            'icon': reward.icon,
        },
    }


def _on_sale(session):
    """Listings a player can buy, with their reward and the open categories each is in."""
    rows = (session.query(ShopItem, Reward, ShopItemCategory.category_id)
            .join(Reward, Reward.id == ShopItem.reward_id)
            .join(ShopItemCategory, ShopItemCategory.shop_item_id == ShopItem.id)
            .join(ShopCategory, ShopCategory.id == ShopItemCategory.category_id)
            .filter(ShopItem.active.is_(True),
                    Reward.active.is_(True),
                    ShopCategory.active.is_(True))
            .order_by(ShopItem.sort_order.asc(), Reward.name.asc())
            .all())
    return rows


@shop_bp.route('', methods=['GET'])
@token_required
def get_shop(current_user):
    """Every open category with what is for sale in it, the balance, and how long purchases last."""
    if not coins.enabled():
        return jsonify(CLOSED), 404
    user_id = current_user['user_id']
    try:
        with db.get_db() as session:
            categories = (session.query(ShopCategory)
                          .filter(ShopCategory.active.is_(True))
                          .order_by(ShopCategory.sort_order.asc(), ShopCategory.name.asc())
                          .all())
            rows = _on_sale(session)
            bought = _bought_today(session, user_id, list({listing.id for listing, _, _ in rows}))

            by_category = {c.id: [] for c in categories}
            for listing, reward, category_id in rows:
                if category_id in by_category:
                    by_category[category_id].append(
                        _listing_view(listing, reward, bought.get(listing.id, 0)))

            return jsonify({
                'balance': coins.balance(session, user_id),
                'expiry_days': _expiry_days(),
                # A category with nothing to buy is left out rather than shown empty.
                'categories': [
                    {'id': c.id, 'name': c.name, 'description': c.description,
                     'items': by_category[c.id]}
                    for c in categories if by_category[c.id]
                ],
            }), 200
    except Exception as e:
        logger.error(f"Get shop error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@shop_bp.route('/items/<int:item_id>/buy', methods=['POST'])
@token_required
def buy(current_user, item_id):
    """Buy one listing: take its price and put the reward in the inventory.

    ``price`` is the price the buyer was shown. If the listing has changed since,
    nothing is bought and the current price is returned instead, so nobody pays
    an amount they never saw.

    The account's row is locked first, so its purchases happen one at a time:
    two at once could otherwise both count the same purchases towards a daily
    limit and both get through.
    """
    if not coins.enabled():
        return jsonify(CLOSED), 404
    data = request.get_json(silent=True) or {}
    expected = data.get('price')
    if expected is not None and coins.whole_number(expected) is None:
        return jsonify({'error': 'price must be a whole number'}), 400
    user_id = current_user['user_id']
    deadline = expiry.shop_deadline()

    try:
        with db.get_db() as session:
            session.query(User.id).filter(User.id == user_id).with_for_update().first()

            listing = session.get(ShopItem, item_id)
            reward = session.get(Reward, listing.reward_id) if listing else None
            shown = listing is not None and (session.query(ShopItemCategory)
                                             .join(ShopCategory,
                                                   ShopCategory.id == ShopItemCategory.category_id)
                                             .filter(ShopItemCategory.shop_item_id == listing.id,
                                                     ShopCategory.active.is_(True))
                                             .first()) is not None
            if not listing or not listing.active or not shown:
                return jsonify({'error': 'That is not for sale'}), 404
            if not reward or not reward.active:
                return jsonify({'error': 'That is no longer available'}), 409
            if expected is not None and expected != listing.price:
                return jsonify({'error': f'The price has changed to {listing.price} coins',
                                'price': listing.price}), 409
            if listing.daily_limit is not None:
                bought = _bought_today(session, user_id, [listing.id]).get(listing.id, 0)
                if bought >= listing.daily_limit:
                    times = 'once' if listing.daily_limit == 1 else f'{listing.daily_limit} times'
                    return jsonify({'error': f'You can buy this {times} a day. '
                                             'Try again tomorrow.'}), 409

            # The gate: refused in the same statement that would overdraw, and
            # nothing has been written yet if it is.
            if not coins.debit(session, user_id, listing.price):
                return jsonify({'error': 'You do not have enough coins',
                                'balance': coins.balance(session, user_id)}), 409

            count = coins.units(reward.kind, listing.count)
            item = InventoryItem(
                user_id=user_id,
                reward_id=reward.id,
                count=count,
                source=InventoryItem.SOURCE_SHOP,
                status=InventoryItem.STATUS_HELD,
                expires_at=deadline,
            )
            session.add(item)
            session.add(ShopPurchase(user_id=user_id, shop_item_id=listing.id,
                                     reward_id=reward.id, count=count, price=listing.price))
            listing.sold = (listing.sold or 0) + 1
            session.flush()
            audit.record(session, user_id, 'shop.buy',
                         target=f'shop_item:{listing.id}',
                         detail=f"'{reward.name}' x{count} for {listing.price} coin(s)")

            return jsonify({
                'message': f'{reward.name} is in your inventory',
                'item': item.to_dict(reward=reward),
                'balance': coins.balance(session, user_id),
            }), 201
    except Exception as e:
        logger.error(f"Buy shop item error: {e}")
        return jsonify({'error': 'Internal server error'}), 500
