"""SQLite access: one connection per thread, schema creation, small helpers."""

import json
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,          -- JSON-encoded
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,
    kicker      TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL,
    blurb       TEXT NOT NULL DEFAULT '',
    price       TEXT NOT NULL DEFAULT '',
    detail      TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '[]',   -- JSON array of strings
    position    INTEGER NOT NULL DEFAULT 0,
    published   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gallery_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,         -- matches the image-slot id in the design
    caption     TEXT NOT NULL DEFAULT '',
    hint        TEXT NOT NULL DEFAULT '',     -- placeholder text when no photo yet
    alt         TEXT NOT NULL DEFAULT '',
    image_file  TEXT,                         -- file name inside the uploads dir
    position    INTEGER NOT NULL DEFAULT 0,
    published   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL DEFAULT '',
    phone            TEXT NOT NULL,
    phone_digits     TEXT NOT NULL,
    email            TEXT NOT NULL DEFAULT '',
    address          TEXT NOT NULL DEFAULT '',
    message          TEXT NOT NULL DEFAULT '',
    service_slug     TEXT,
    source           TEXT NOT NULL DEFAULT 'website',
    status           TEXT NOT NULL DEFAULT 'new',
    notes            TEXT NOT NULL DEFAULT '',
    ip               TEXT NOT NULL DEFAULT '',
    user_agent       TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    FOREIGN KEY (service_slug) REFERENCES services(slug) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_status  ON leads(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_phone   ON leads(phone_digits, created_at DESC);

CREATE TABLE IF NOT EXISTS admin_users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    last_login_at  TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    ip          TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES admin_users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS submissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ip          TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_submissions_ip ON submissions(ip, created_at);
"""


def now():
    """UTC timestamp, ISO 8601 with a Z suffix. Stored as TEXT everywhere."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect():
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(config.DB_PATH), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        _local.conn = conn
    return conn


def close():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def query(sql, params=()):
    return connect().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return connect().execute(sql, params).fetchone()


def execute(sql, params=()):
    conn = connect()
    with conn:
        cur = conn.execute(sql, params)
    return cur


def init_db():
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)


def get_setting(key, default=None):
    row = query_one("SELECT value FROM site_settings WHERE key = ?", (key,))
    return default if row is None else json.loads(row["value"])


def all_settings():
    return {r["key"]: json.loads(r["value"]) for r in query("SELECT key, value FROM site_settings")}


def set_setting(key, value):
    execute(
        "INSERT INTO site_settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, json.dumps(value), now()),
    )


def purge_expired_sessions():
    execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
