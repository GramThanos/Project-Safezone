"""Admin shop routes: categories, and the listings that appear in them.

Readable by moderators, like the reward catalog; changed by admins only. A
listing can sit in any number of categories, and is saved whole - reward, count,
price, daily limit, categories - so a half-edited listing never reaches players.
Its price is checked against its floor (`coins.min_price`) every time it is saved,
so nothing can be listed for less than it sells back for.
"""
import logging
from flask import Blueprint, request, jsonify
from src.database import db
from src.models.reward import Reward
from src.models.shop_category import ShopCategory
from src.models.shop_item import ShopItem
from src.models.shop_item_category import ShopItemCategory
from src.middleware.auth import moderator_required, admin_required
from src.utils import audit, coins
from src.utils.rewards import validate_item_count

logger = logging.getLogger(__name__)
shop_admin_bp = Blueprint('shop_admin', __name__, url_prefix='/api/admin/shop')

MAX_NAME = 80
MAX_SORT_ORDER = 100_000
MAX_CATEGORIES_PER_LISTING = 50


# ---------------------------------------------------------------------------
# Validation. Everything is checked before a session opens: `get_db` commits on
# normal exit, so an error returned after a change would keep the change.
# ---------------------------------------------------------------------------

def _common_fields(data, fields):
    if 'sort_order' in data:
        order = coins.whole_number(data['sort_order'])
        if order is None or abs(order) > MAX_SORT_ORDER:
            return f'sort_order must be a whole number up to {MAX_SORT_ORDER}'
        fields['sort_order'] = order
    if 'active' in data:
        if not isinstance(data['active'], bool):
            return 'active must be true or false'
        fields['active'] = data['active']
    return None


def _category_fields(data, partial):
    """``(fields, error)`` for a category create or update."""
    fields = {}
    if 'name' in data or not partial:
        name = data.get('name')
        if not isinstance(name, str) or not name.strip():
            return None, 'name is required'
        if len(name.strip()) > MAX_NAME:
            return None, f'name must be at most {MAX_NAME} characters'
        fields['name'] = name.strip()
    if 'description' in data:
        description = data['description']
        if description is not None and not isinstance(description, str):
            return None, 'description must be text'
        fields['description'] = (description or '').strip() or None
    error = _common_fields(data, fields)
    return (None, error) if error else (fields, None)


def _listing_fields(data, partial):
    """``(fields, category_ids, error)`` for a listing; the price floor is checked later.

    ``category_ids`` is None when the request leaves the categories alone.
    """
    fields = {}
    if 'reward_id' in data or not partial:
        reward_id = coins.whole_number(data.get('reward_id'))
        if reward_id is None:
            return None, None, 'reward_id is required'
        fields['reward_id'] = reward_id
    if 'count' in data or not partial:
        count = data.get('count', 1)
        error = validate_item_count(count)
        if error:
            return None, None, error
        fields['count'] = count
    if 'price' in data or not partial:
        price = coins.whole_number(data.get('price'))
        if price is None or not 1 <= price <= coins.MAX_PRICE:
            return None, None, f'price must be a whole number from 1 to {coins.MAX_PRICE}'
        fields['price'] = price
    if 'daily_limit' in data:
        limit = data['daily_limit']
        if limit is not None and (coins.whole_number(limit) is None
                                  or not 1 <= limit <= coins.MAX_DAILY_LIMIT):
            return None, None, (f'daily_limit must be empty for no limit, or a whole number '
                                f'from 1 to {coins.MAX_DAILY_LIMIT}')
        fields['daily_limit'] = limit
    error = _common_fields(data, fields)
    if error:
        return None, None, error

    category_ids = None
    if 'category_ids' in data or not partial:
        raw = data.get('category_ids', [])
        if not isinstance(raw, list) or len(raw) > MAX_CATEGORIES_PER_LISTING:
            return None, None, 'category_ids must be a list of category ids'
        category_ids = set()
        for value in raw:
            if coins.whole_number(value) is None:
                return None, None, 'category_ids must be whole numbers'
            category_ids.add(value)
    return fields, category_ids, None


def _check_listing(session, values, category_ids):
    """``(error, status)`` for a listing about to be saved, or ``(None, None)``."""
    reward = session.get(Reward, values['reward_id'])
    if not reward:
        return 'Reward not found', 404
    if category_ids:
        found = {cid for (cid,) in session.query(ShopCategory.id)
                 .filter(ShopCategory.id.in_(category_ids))}
        if found != category_ids:
            return 'Category not found', 404
    # A usable runs once per holding, so a count above one would only ever
    # deliver one.
    if reward.kind == Reward.KIND_USABLE and values['count'] != 1:
        return 'An action is delivered once, so its count must be 1', 400
    floor = coins.min_price(reward)
    if values['price'] < floor:
        return (f"The price must be at least {floor} coin(s): {reward.name} "
                f"sells back for {reward.coin_value or 0}"), 400
    return None, None


def _set_categories(session, listing_id, category_ids):
    session.query(ShopItemCategory).filter_by(shop_item_id=listing_id).delete(
        synchronize_session=False)
    for category_id in sorted(category_ids):
        session.add(ShopItemCategory(shop_item_id=listing_id, category_id=category_id))


def _categories_of(session, listing_ids):
    out = {lid: [] for lid in listing_ids}
    if listing_ids:
        rows = (session.query(ShopItemCategory)
                .filter(ShopItemCategory.shop_item_id.in_(listing_ids)))
        for row in rows:
            out[row.shop_item_id].append(row.category_id)
    return out


def _describe(session, listing, category_ids):
    reward = session.get(Reward, listing.reward_id)
    names = [name for (name,) in session.query(ShopCategory.name)
             .filter(ShopCategory.id.in_(category_ids or [-1]))
             .order_by(ShopCategory.name)]
    return (f"'{reward.name if reward else listing.reward_id}' ×{listing.count} for "
            f"{listing.price}"
            + (f", {listing.daily_limit}/day" if listing.daily_limit else '')
            + f" in {', '.join(names) or 'no category'}")


def _listing_out(session, listing, category_ids):
    reward = session.get(Reward, listing.reward_id)
    data = listing.to_dict(reward=reward, category_ids=category_ids)
    if reward:
        data['min_price'] = coins.min_price(reward)
    return data


# ---------------------------------------------------------------------------
# The whole shop, for the panel
# ---------------------------------------------------------------------------

@shop_admin_bp.route('', methods=['GET'])
@moderator_required
def get_shop(current_user):
    """Every category and every listing, shown or not (moderator/admin)."""
    try:
        with db.get_db() as session:
            categories = (session.query(ShopCategory)
                          .order_by(ShopCategory.sort_order.asc(), ShopCategory.name.asc())
                          .all())
            rows = (session.query(ShopItem, Reward)
                    .join(Reward, Reward.id == ShopItem.reward_id)
                    .order_by(ShopItem.sort_order.asc(), Reward.name.asc())
                    .all())
            in_categories = _categories_of(session, [listing.id for listing, _ in rows])
            listings = []
            for listing, reward in rows:
                entry = listing.to_dict(reward=reward, category_ids=in_categories[listing.id])
                entry['min_price'] = coins.min_price(reward)
                listings.append(entry)
            counts = {}
            for ids in in_categories.values():
                for cid in ids:
                    counts[cid] = counts.get(cid, 0) + 1
            return jsonify({
                'enabled': coins.enabled(),
                'price_multiplier': coins.SUGGESTED_PRICE_MULTIPLIER,
                'categories': [dict(c.to_dict(), listings=counts.get(c.id, 0)) for c in categories],
                'items': listings,
            }), 200
    except Exception as e:
        logger.error(f"Admin get shop error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@shop_admin_bp.route('/categories', methods=['POST'])
@admin_required
def create_category(current_user):
    fields, error = _category_fields(request.get_json(silent=True) or {}, partial=False)
    if error:
        return jsonify({'error': error}), 400
    try:
        with db.get_db() as session:
            category = ShopCategory(**fields)
            session.add(category)
            session.flush()
            audit.record(session, current_user['user_id'], 'shop.category_create',
                         target=f'shop_category:{category.id}', detail=f"'{category.name}'")
            return jsonify({'message': 'Category created', 'category': category.to_dict()}), 201
    except Exception as e:
        logger.error(f"Create shop category error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@shop_admin_bp.route('/categories/<int:category_id>', methods=['PUT'])
@admin_required
def update_category(current_user, category_id):
    fields, error = _category_fields(request.get_json(silent=True) or {}, partial=True)
    if error:
        return jsonify({'error': error}), 400
    try:
        with db.get_db() as session:
            category = session.get(ShopCategory, category_id)
            if not category:
                return jsonify({'error': 'Category not found'}), 404
            for key, value in fields.items():
                setattr(category, key, value)
            audit.record(session, current_user['user_id'], 'shop.category_update',
                         target=f'shop_category:{category_id}',
                         detail=f"'{category.name}' changed: {', '.join(fields) or 'nothing'}")
            return jsonify({'message': 'Category updated', 'category': category.to_dict()}), 200
    except Exception as e:
        logger.error(f"Update shop category error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@shop_admin_bp.route('/categories/<int:category_id>', methods=['DELETE'])
@admin_required
def delete_category(current_user, category_id):
    """Delete a category. Its listings stay, in whatever other categories they are in."""
    try:
        with db.get_db() as session:
            category = session.get(ShopCategory, category_id)
            if not category:
                return jsonify({'error': 'Category not found'}), 404
            name = category.name
            # Explicitly, not only by the foreign key: SQLite enforces cascades
            # only when told to.
            (session.query(ShopItemCategory).filter_by(category_id=category_id)
             .delete(synchronize_session=False))
            session.delete(category)
            audit.record(session, current_user['user_id'], 'shop.category_delete',
                         target=f'shop_category:{category_id}', detail=f"'{name}'")
            return jsonify({'message': 'Category deleted'}), 200
    except Exception as e:
        logger.error(f"Delete shop category error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

@shop_admin_bp.route('/items', methods=['POST'])
@admin_required
def create_item(current_user):
    fields, category_ids, error = _listing_fields(request.get_json(silent=True) or {},
                                                  partial=False)
    if error:
        return jsonify({'error': error}), 400
    try:
        with db.get_db() as session:
            error, status = _check_listing(session, fields, category_ids)
            if error:
                return jsonify({'error': error}), status
            listing = ShopItem(**fields)
            session.add(listing)
            session.flush()
            _set_categories(session, listing.id, category_ids)
            audit.record(session, current_user['user_id'], 'shop.item_create',
                         target=f'shop_item:{listing.id}',
                         detail=_describe(session, listing, category_ids))
            return jsonify({'message': 'Listed',
                            'item': _listing_out(session, listing, sorted(category_ids))}), 201
    except Exception as e:
        logger.error(f"Create shop item error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@shop_admin_bp.route('/items/<int:item_id>', methods=['PUT'])
@admin_required
def update_item(current_user, item_id):
    fields, category_ids, error = _listing_fields(request.get_json(silent=True) or {},
                                                  partial=True)
    if error:
        return jsonify({'error': error}), 400
    try:
        with db.get_db() as session:
            listing = session.get(ShopItem, item_id)
            if not listing:
                return jsonify({'error': 'Listing not found'}), 404
            # Checked as it would be saved, without touching the row first:
            # returning an error after changing it would commit the change.
            values = {key: fields.get(key, getattr(listing, key))
                      for key in ('reward_id', 'count', 'price')}
            error, status = _check_listing(session, values, category_ids)
            if error:
                return jsonify({'error': error}), status
            for key, value in fields.items():
                setattr(listing, key, value)
            if category_ids is not None:
                _set_categories(session, listing.id, category_ids)
            session.flush()
            now_in = _categories_of(session, [listing.id])[listing.id]
            changed = list(fields) + (['categories'] if category_ids is not None else [])
            audit.record(session, current_user['user_id'], 'shop.item_update',
                         target=f'shop_item:{item_id}',
                         detail=f"{_describe(session, listing, now_in)}; "
                                f"changed: {', '.join(changed) or 'nothing'}")
            return jsonify({'message': 'Listing saved',
                            'item': _listing_out(session, listing, now_in)}), 200
    except Exception as e:
        logger.error(f"Update shop item error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@shop_admin_bp.route('/items/<int:item_id>', methods=['DELETE'])
@admin_required
def delete_item(current_user, item_id):
    """Take a listing out of the shop. Anything already bought stays bought."""
    try:
        with db.get_db() as session:
            listing = session.get(ShopItem, item_id)
            if not listing:
                return jsonify({'error': 'Listing not found'}), 404
            detail = _describe(session, listing, _categories_of(session, [item_id])[item_id])
            (session.query(ShopItemCategory).filter_by(shop_item_id=item_id)
             .delete(synchronize_session=False))
            session.delete(listing)
            audit.record(session, current_user['user_id'], 'shop.item_delete',
                         target=f'shop_item:{item_id}', detail=detail)
            return jsonify({'message': 'Listing removed'}), 200
    except Exception as e:
        logger.error(f"Delete shop item error: {e}")
        return jsonify({'error': 'Internal server error'}), 500
