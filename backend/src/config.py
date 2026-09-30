"""Centralized configuration for the Flask application"""
import os


class Config:
    """Application configuration with default values"""

    # The release this build is. Declared once here rather than repeated in the
    # endpoints that report it, and overridable so a deployment can stamp a tag
    # or commit without editing code.
    APP_VERSION = os.getenv('APP_VERSION', '2.0.0')

    # Database Configuration
    DATABASE_HOST = os.getenv('DATABASE_HOST', 'db')
    DATABASE_NAME = os.getenv('DATABASE_NAME', 'safezone')
    DATABASE_USER = os.getenv('DATABASE_USER', 'safezone')
    DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD', 'safezone')
    
    # Build database URL for SQLAlchemy
    SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}/{DATABASE_NAME}"
    
    # JWT Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    TOKEN_EXPIRY_HOURS = int(os.getenv('TOKEN_EXPIRY_HOURS', '24'))
    TOKEN_ISSUER = os.getenv('TOKEN_ISSUER', 'safezone-api')
    TOKEN_AUDIENCE = os.getenv('TOKEN_AUDIENCE', 'safezone-frontend')
    
    # Redis Configuration
    REDIS_HOST = os.getenv('REDIS_HOST', 'cache')
    REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}"
    
    # CORS Configuration
    ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'http://localhost:3000').split(',')
    
    # Security Configuration
    HTTPS_ENABLED = os.getenv('HTTPS_ENABLED', 'false').lower() == 'true'
    
    # Game Server Configuration
    # Internal address of the game-server manager API (listens on 5000 in-container).
    GAME_SERVER_API_URL = os.getenv('GAME_SERVER_API_URL', 'http://game-server:5000')
    API_TOKEN = os.getenv('API_TOKEN', '')
    
    # Observability. LOG_FORMAT=json when something is collecting logs; plain
    # text otherwise, because a person reading `docker compose logs` is the
    # common case.
    LOG_FORMAT = os.getenv('LOG_FORMAT', 'text')
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    # Flask Configuration
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    # Outbound email is composed here and sent by the game-server (see
    # src/utils/mailer.py), so the SMTP_* variables belong to *that* container -
    # this one has no egress and no DNS, and never could have reached a mail
    # server. Only the link base stays here, because it is about the site.
    SITE_URL = os.getenv('SITE_URL', 'http://localhost:8080')

    # Defaults for runtime-editable settings. These seed the values; an admin can
    # override any of them from the panel without a redeploy, which is stored in
    # the `app_settings` table. See src/utils/settings.py for the registry.
    REGISTRATION_ENABLED = os.getenv('REGISTRATION_ENABLED', 'true').lower() == 'true'
    REGISTRATION_PASSWORD = os.getenv('REGISTRATION_PASSWORD', '')
    INVITES_ENABLED = os.getenv('INVITES_ENABLED', 'true').lower() == 'true'
    PLAYER_INVITES_ENABLED = os.getenv('PLAYER_INVITES_ENABLED', 'false').lower() == 'true'
    PLAYER_INVITE_QUOTA = int(os.getenv('PLAYER_INVITE_QUOTA', '3'))
    STREAK_THRESHOLD = int(os.getenv('STREAK_THRESHOLD', '5'))
    CAPTCHA_ENABLED = os.getenv('CAPTCHA_ENABLED', 'true').lower() == 'true'
    ALERTS_ENABLED = os.getenv('ALERTS_ENABLED', 'true').lower() == 'true'
    ALERT_COOLDOWN_MINUTES = int(os.getenv('ALERT_COOLDOWN_MINUTES', '60'))
    DORMANT_LINK_DAYS = int(os.getenv('DORMANT_LINK_DAYS', '0'))
    BOX_EXPIRY_DAYS = int(os.getenv('BOX_EXPIRY_DAYS', '0'))
    INVENTORY_EXPIRY_DAYS = int(os.getenv('INVENTORY_EXPIRY_DAYS', '0'))
    AUDIT_RETENTION_DAYS = int(os.getenv('AUDIT_RETENTION_DAYS', '0'))
    STAFF_ALERT_RETENTION_DAYS = int(os.getenv('STAFF_ALERT_RETENTION_DAYS', '30'))

    # --- Site content -------------------------------------------------------
    # What the public pages say. Same mechanism as the settings above: these are
    # the defaults, and the panel writes overrides. An operator running their
    # own community should not have to fork the code to put their own name on
    # it, which is what editing these in source would amount to.
    SITE_BRAND_NAME = os.getenv('SITE_BRAND_NAME', 'Project Safezone')
    SITE_HERO_TITLE = os.getenv('SITE_HERO_TITLE', 'Time to fight zombies')
    SITE_HERO_SUBTITLE = os.getenv('SITE_HERO_SUBTITLE', (
        'Join our Project Zomboid dedicated servers and survive the apocalypse '
        'with your friends. Create your character, explore the world, and fight '
        'for survival in this multiplayer experience.'
    ))
    # Blank means "no such link", and the footer leaves the icon out entirely
    # rather than showing one that goes nowhere.
    SITE_SOCIAL_DISCORD = os.getenv('SITE_SOCIAL_DISCORD', '')
    SITE_SOCIAL_TWITTER = os.getenv('SITE_SOCIAL_TWITTER', '')
    SITE_SOCIAL_YOUTUBE = os.getenv('SITE_SOCIAL_YOUTUBE', '')
    SITE_SOCIAL_STEAM = os.getenv('SITE_SOCIAL_STEAM', '')
    # Markdown for the three legal pages. Empty means the page says it has not
    # been written yet, which is honest - better than shipping boilerplate terms
    # nobody wrote and nobody checked.
    SITE_LEGAL_TERMS = os.getenv('SITE_LEGAL_TERMS', '')
    SITE_LEGAL_PRIVACY = os.getenv('SITE_LEGAL_PRIVACY', '')
    SITE_LEGAL_COOKIES = os.getenv('SITE_LEGAL_COOKIES', '')
    # Server rules. Not a legal document, but it lives on the same mechanism:
    # rules that exist only in a chat server get enforced against players who
    # never saw them, which is where ban appeals come from.
    SITE_RULES = os.getenv('SITE_RULES', '')

    # SQLAlchemy Connection Pool Configuration
    SQLALCHEMY_POOL_PRE_PING = True  # Verify connections before using
    SQLALCHEMY_POOL_RECYCLE = 3600   # Recycle connections after 1 hour
    SQLALCHEMY_ECHO = False          # Set to True for SQL logging during development


def configure_app(app):
    """Apply configuration to Flask app instance"""
    app.config.from_object(Config)
    return app
