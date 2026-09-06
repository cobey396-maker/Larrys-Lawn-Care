"""Admin passwords and bearer-token sessions."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from . import config, db
from .routing import HTTPError


# -- passwords -----------------------------------------------------------
def hash_password(password, *, salt=None, iterations=None):
    salt = salt or secrets.token_bytes(16)
    iterations = iterations or config.PASSWORD_ITERATIONS
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(expected.hex(), digest_hex)


# -- accounts ------------------------------------------------------------
def create_admin(username, password):
    if len(password) < 8:
        raise HTTPError(422, "Password must be at least 8 characters.",
                        fields={"password": "At least 8 characters."})
    db.execute(
        "INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, hash_password(password), db.now()),
    )
    return db.query_one("SELECT * FROM admin_users WHERE username = ?", (username,))


def set_password(username, password):
    db.execute(
        "UPDATE admin_users SET password_hash = ? WHERE username = ?",
        (hash_password(password), username),
    )


def authenticate(username, password, ip=""):
    user = db.query_one("SELECT * FROM admin_users WHERE username = ?", (username,))
    # Hash regardless of whether the user exists, so a missing account and a
    # wrong password take the same amount of time.
    stored = user["password_hash"] if user else hash_password("no-such-user")
    if not verify_password(password, stored) or user is None:
        raise HTTPError(401, "Wrong username or password.", code="invalid_credentials")
    db.execute("UPDATE admin_users SET last_login_at = ? WHERE id = ?", (db.now(), user["id"]))
    return user, create_session(user["id"], ip)


# -- sessions ------------------------------------------------------------
def create_session(user_id, ip=""):
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=config.SESSION_HOURS)
    db.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at, ip) VALUES (?, ?, ?, ?, ?)",
        (token, user_id, db.now(), expires.strftime("%Y-%m-%dT%H:%M:%SZ"), ip),
    )
    db.purge_expired_sessions()
    return {"token": token, "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ")}


def destroy_session(token):
    db.execute("DELETE FROM sessions WHERE token = ?", (token,))


def session_user(token):
    row = db.query_one(
        "SELECT u.id, u.username, s.expires_at FROM sessions s "
        "JOIN admin_users u ON u.id = s.user_id WHERE s.token = ?",
        (token,),
    )
    if row is None:
        return None
    if row["expires_at"] < db.now():
        destroy_session(token)
        return None
    return {"id": row["id"], "username": row["username"]}


def require_admin(handler):
    """Decorator for admin-only routes. Puts the user on request.user."""

    def wrapper(request, *args, **kwargs):
        header = request.header("Authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPError(401, "Sign in to use this endpoint.", code="not_authenticated")
        user = session_user(header[7:].strip())
        if user is None:
            raise HTTPError(401, "Your session has expired. Sign in again.",
                            code="session_expired")
        request.user = user
        return handler(request, *args, **kwargs)

    wrapper.__name__ = getattr(handler, "__name__", "wrapper")
    return wrapper


def ensure_bootstrap_admin():
    """Create the first account on first run. Returns a password to show once."""
    existing = db.query_one("SELECT COUNT(*) AS n FROM admin_users")["n"]
    if existing:
        return None
    password = config.ADMIN_PASSWORD or secrets.token_urlsafe(12)
    create_admin(config.ADMIN_USERNAME, password)
    return None if config.ADMIN_PASSWORD else password
