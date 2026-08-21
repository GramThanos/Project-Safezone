"""Flask extension instances.

These live outside `app.py` so blueprints can import them at module import time -
notably the rate limiter, whose per-endpoint limits are applied as decorators on
the view functions themselves.
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from src.config import Config

# Global per-IP limiter. Endpoint-specific limits are declared on the views (see
# src/routes/auth.py); everything else falls back to RATELIMIT_DEFAULT_LIMITS.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=Config.RATELIMIT_STORAGE_URI,
    default_limits=Config.RATELIMIT_DEFAULT_LIMITS,
    storage_options={"socket_connect_timeout": 30},
    strategy="fixed-window"
)
