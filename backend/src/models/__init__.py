"""Database models

The backend owns the account/reward tables (`users`, `players`, `claim_requests`,
`rewards`, `box_loot_pools`, `user_boxes`, `inventory_items`). The `servers` and
`tasks` tables are owned by the game-server service; the backend accesses them
only through the game-server API (see src/utils/game_server.py).
"""
from .user import User
from .player import Player
from .claim_request import ClaimRequest
from .reward import Reward
from .box_loot_pool import BoxLootPool
from .user_box import UserBox
from .inventory_item import InventoryItem
from .audit_log import AuditLog

__all__ = [
    'User', 'Player', 'ClaimRequest', 'Reward',
    'BoxLootPool', 'UserBox', 'InventoryItem', 'AuditLog'
]
