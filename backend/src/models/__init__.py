"""Database models

The backend owns the account/reward tables (`users`, `characters`, `claim_requests`,
`rewards`, `boxes`, `events`, `event_boxes`, `box_loot_pools`, `user_boxes`,
`inventory_items`, `staff_alerts`, `push_subscriptions`, `shop_categories`,
`shop_items`, `shop_item_categories`, `shop_purchases`, `coin_log`). The `servers` and `tasks` tables are owned by the game-server
service; the backend accesses them only through the game-server API (see
src/utils/game_server.py).
"""
from .user import User
from .character import Character
from .claim_request import ClaimRequest
from .reward import Reward
from .box import Box
from .event import Event
from .event_box import EventBox
from .box_loot_pool import BoxLootPool
from .user_box import UserBox
from .inventory_item import InventoryItem
from .audit_log import AuditLog
from .app_setting import AppSetting
from .auth_token import AuthToken
from .invitation import Invitation
from .notification import Notification
from .scheduled_job import ScheduledJob
from .ban import Ban
from .report import Report
from .alert_channel import AlertChannel
from .staff_alert import StaffAlert
from .push_subscription import PushSubscription
from .shop_category import ShopCategory
from .shop_item import ShopItem
from .shop_item_category import ShopItemCategory
from .coin_log import CoinLog
from .shop_purchase import ShopPurchase

__all__ = [
    'User', 'Character', 'ClaimRequest', 'Reward', 'Box', 'Event', 'EventBox',
    'BoxLootPool', 'UserBox', 'InventoryItem', 'AuditLog', 'AppSetting',
    'AuthToken', 'Invitation', 'Notification', 'ScheduledJob', 'Ban', 'Report',
    'AlertChannel', 'StaffAlert', 'PushSubscription', 'ShopCategory', 'ShopItem',
    'ShopItemCategory', 'CoinLog', 'ShopPurchase'
]
