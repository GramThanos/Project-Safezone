"""Authentication against the server's account database (read-only).

The account database is ``Zomboid/db/<servername>.db``; its ``whitelist`` table
holds each account's username, password hash, role and ban state.  Usage::

    from zomboid_db_api import ServerDB

    server = ServerDB("Zomboid/db/servertest.db")
    result = server.authenticate("thanos", "secret")
    if result:                       # result.authenticated
        print("welcome", result.account.getUsername(), result.account.getRole())
    else:
        print(result.reason)         # "wrong_password", "unknown_user", "banned", ...

Passwords are checked exactly like the game does (from its source): the stored
value is ``bcrypt(md5_hex(password))``.  bcrypt is not in Python's standard
library, so checking such a password needs the ``bcrypt`` package
(``pip install bcrypt``); everything else works without it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .players import PathLike, _bool, _connect, _int, _text

__all__ = ["Account", "AuthResult", "ServerDB"]

# PZcrypt's fixed bcrypt salt; used to keep the timing of unknown users similar.
_GAME_SALT = b"$2a$12$O/BFHoDFPrfFaNPAACmWpu"
# whitelist.authType (Build 42); Build 41 accounts always use a password.
_AUTH_METHODS = {1: "password", 2: "authenticator", 3: "password+authenticator"}


class Account:
    """One account (a row of ``whitelist``).  The password hash is never exposed."""

    def __init__(self, row: Dict[str, Any], role: str, can_login: bool, ban_reason: Optional[str]):
        self._row = row
        self._role = role
        self._can_login = can_login
        self._ban_reason = ban_reason

    def __repr__(self) -> str:
        return f"<Account {self.getUsername()!r} role={self._role!r}{' BANNED' if self.isBanned() else ''}>"

    def getUsername(self) -> str:
        return _text(self._row.get("username")) or ""

    def getRole(self) -> str:
        """``"admin"``, ``"moderator"``, ``"user"``, ``"banned"``, ... (Build 42: the role's name)."""
        return self._role

    def isBanned(self) -> bool:
        """Banned, or (Build 42) in a role that may not log in."""
        return not self._can_login

    def getBanReason(self) -> Optional[str]:
        return self._ban_reason

    def getAuthMethod(self) -> str:
        """``"password"``, ``"authenticator"`` or ``"password+authenticator"`` (what to ask the user for)."""
        return _AUTH_METHODS.get(_int(self._row.get("authtype")) or 1, "password")


@dataclass
class AuthResult:
    """Outcome of :meth:`ServerDB.authenticate`; true when authenticated.

    ``reason`` is ``"ok"`` or one of ``"unknown_user"``, ``"wrong_password"``,
    ``"no_password_set"``, ``"code_required"``, ``"wrong_code"``, ``"banned"``.
    Show users a generic message: the distinct reasons are for your own logic
    and logs.
    """

    authenticated: bool
    reason: str
    account: Optional[Account] = None

    def __bool__(self) -> bool:
        return self.authenticated


class ServerDB:
    """A server's account database, read once and kept in memory (read-only)."""

    def __init__(self, path: PathLike):
        self.path = Path(path)
        self._accounts: Dict[str, Account] = {}  # lower-case username -> account
        self.refresh()

    def __repr__(self) -> str:
        return f"<ServerDB {self.path.name!r} {len(self._accounts)} accounts>"

    def refresh(self) -> None:
        """Re-read the file (picks up accounts, passwords and bans changed since)."""
        conn = _connect(self.path)
        try:
            tables = {r[0].lower() for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

            def rows(table: str) -> List[Dict[str, Any]]:
                if table not in tables:
                    return []
                return [{k.lower(): r[k] for k in r.keys()} for r in conn.execute(f'SELECT * FROM "{table}"')]

            accounts = rows("whitelist")
            steam_bans = {_text(r.get("steamid")): _text(r.get("reason")) or "" for r in rows("bannedid")}
            role_names = {_int(r.get("id")): _text(r.get("name")) for r in rows("role")}
            login_roles = {_int(r.get("role")) for r in rows("capabilities")
                           if (_text(r.get("name")) or "").lower() == "loginonserver"}
        finally:
            conn.close()

        self._accounts = {}
        for row in sorted(accounts, key=lambda r: _int(r.get("id")) or 0):
            role, can_login, reason = self._role(row, role_names, login_roles if role_names else None)
            steam_id = _text(row.get("steamid"))
            if steam_id and steam_id in steam_bans:
                can_login, reason = False, steam_bans[steam_id] or reason
            account = Account(row, role, can_login, reason if not can_login else None)
            self._accounts.setdefault(account.getUsername().lower(), account)

    @staticmethod
    def _role(row: Dict[str, Any], role_names: Dict[Optional[int], Optional[str]], login_roles):
        """(role name, may log in, ban reason) for Build 41 and Build 42 accounts."""
        raw = row.get("role")
        if raw is not None and _int(raw) is not None and login_roles is not None:  # Build 42: role id
            role_id = _int(raw)
            name = role_names.get(role_id) or f"role #{role_id}"
            can_login = role_id in login_roles
            return name.lower(), can_login, None if can_login else "role may not log in"
        level = (_text(raw) or _text(row.get("accesslevel")) or "").strip().lower()
        if _bool(row.get("banned")) or level == "banned":
            return "banned", False, "banned"
        if level and level != "none":
            return level, True, None
        if _bool(row.get("admin")):
            return "admin", True, None
        if _bool(row.get("moderator")):
            return "moderator", True, None
        return "user", True, None

    def getAccount(self, username: str) -> Optional[Account]:
        """Look an account up by username, case-insensitively like the game does.

        Useful before asking for credentials: ``getAuthMethod()`` tells whether the
        user needs a password, an authenticator code, or both.
        """
        return self._accounts.get(username.lower())

    # -- authentication ------------------------------------------------------------------
    def authenticate(self, username: str, password: Optional[str] = None,
                     code: Optional[str] = None) -> AuthResult:
        """Check a username and password (and authenticator code, if the account uses one).

        Accounts without a stored password are refused, although the game itself lets
        them in.  Bans are reported only after the credentials check out.
        """
        account = self.getAccount(username)
        if account is None:
            _spend_like_bcrypt(password or "")  # do not reveal unknown users by timing
            return AuthResult(False, "unknown_user")
        method = account.getAuthMethod()
        if method in ("password", "password+authenticator"):
            if not _text(account._row.get("password")):
                return AuthResult(False, "no_password_set", account)
            if password is None or not _password_matches(account._row, password):
                return AuthResult(False, "wrong_password", account)
        if method in ("authenticator", "password+authenticator"):
            secret = _text(account._row.get("googlekey"))
            if not secret:
                return AuthResult(False, "no_password_set", account)
            if not code:
                return AuthResult(False, "code_required", account)
            if not _totp_matches(secret, code):
                return AuthResult(False, "wrong_code", account)
        if account.isBanned():
            return AuthResult(False, "banned", account)
        return AuthResult(True, "ok", account)


# =============================================================================
# password and code checks
# =============================================================================

def _md5_hex(password: str) -> str:
    """``ServerWorldDatabase.encrypt``: MD5 of the password, lowercase hex."""
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def _bcrypt():
    try:
        import bcrypt
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError("checking Project Zomboid passwords needs the 'bcrypt' package: "
                          "pip install bcrypt") from exc
    return bcrypt


def _password_matches(row: Dict[str, Any], password: str) -> bool:
    stored = _text(row.get("password")) or ""
    encrypted = row.get("encryptedpwd")
    if encrypted is not None and not _bool(encrypted):  # Build 41 legacy: plain text
        return hmac.compare_digest(stored.encode("utf-8"), password.encode("utf-8"))
    if _int(row.get("pwdencrypttype")) == 1:             # Build 41 legacy: MD5 only
        return hmac.compare_digest(stored.lower(), _md5_hex(password))
    if not stored.startswith("$2"):
        return False
    return _bcrypt().checkpw(_md5_hex(password).encode("ascii"), stored.encode("ascii"))


def _spend_like_bcrypt(password: str) -> None:
    try:
        _bcrypt().hashpw(_md5_hex(password).encode("ascii"), _GAME_SALT)
    except ImportError:
        pass


def _totp_matches(secret: str, code: str, *, step: int = 30, window: int = 1) -> bool:
    """Standard 6-digit TOTP (RFC 6238, SHA-1), accepting one step of clock skew."""
    cleaned = secret.replace(" ", "").strip().upper()
    try:
        key = base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))
    except (ValueError, TypeError):
        return False
    code = code.strip()
    counter = int(time.time()) // step
    for offset in range(-window, window + 1):
        digest = hmac.new(key, struct.pack(">Q", counter + offset), hashlib.sha1).digest()
        pos = digest[-1] & 0x0F
        value = (struct.unpack(">I", digest[pos:pos + 4])[0] & 0x7FFFFFFF) % 1_000_000
        if hmac.compare_digest(f"{value:06d}", code):
            return True
    return False
