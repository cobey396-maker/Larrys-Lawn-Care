"""Configuration, read once at import time from the environment.

Every value has a working default so the server runs with no setup at all.
Override anything by exporting the matching LLC_* environment variable.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
PROJECT_DIR = BASE_DIR.parent                              # landscaping/


def _env(name, default):
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_int(name, default):
    try:
        return int(_env(name, default))
    except (TypeError, ValueError):
        return default


def _env_path(name, default):
    return Path(_env(name, str(default))).expanduser().resolve()


HOST = _env("LLC_HOST", "127.0.0.1")
PORT = _env_int("LLC_PORT", 8080)

DB_PATH = _env_path("LLC_DB", BASE_DIR / "data" / "larryslawncare.db")
UPLOAD_DIR = _env_path("LLC_UPLOADS", BASE_DIR / "uploads")
ADMIN_DIR = BASE_DIR / "admin"

# The design folder that gets served at "/". Serving the site and the API from
# one origin is what keeps the browser from ever asking about CORS.
SITE_DIR = _env_path("LLC_SITE_DIR", PROJECT_DIR / "Landscaping business design questions")

# Bootstrap credentials for the first admin account. If no password is given a
# random one is generated on first run and printed to the console once.
ADMIN_USERNAME = _env("LLC_ADMIN_USER", "larry")
ADMIN_PASSWORD = os.environ.get("LLC_ADMIN_PASSWORD") or None

SESSION_HOURS = _env_int("LLC_SESSION_HOURS", 12)
PASSWORD_ITERATIONS = 240_000

MAX_JSON_BYTES = 256 * 1024
MAX_UPLOAD_BYTES = _env_int("LLC_MAX_UPLOAD", 8 * 1024 * 1024)

# Callback requests: how many one IP may send per window, and how long an
# identical phone number is treated as a duplicate submission.
LEAD_RATE_LIMIT = _env_int("LLC_LEAD_RATE_LIMIT", 5)
LEAD_RATE_WINDOW_SECONDS = _env_int("LLC_LEAD_RATE_WINDOW", 3600)
LEAD_DUPLICATE_SECONDS = _env_int("LLC_LEAD_DUPLICATE_WINDOW", 600)

# Extra origins allowed to call the API cross-site (a separate front end, a
# preview host). Same-origin requests never need this. "*" allows all.
_origins = _env("LLC_ALLOWED_ORIGINS", "null")
ALLOWED_ORIGINS = [o.strip() for o in _origins.split(",") if o.strip()]

# Trust X-Forwarded-For only when the server sits behind a proxy you control.
TRUST_PROXY = _env("LLC_TRUST_PROXY", "0") not in ("0", "false", "no")
