#!/usr/bin/env python3
"""Create the schema, load the starting content, and make the admin account.

Run this once against whichever database the site will use. A Vercel function
is the wrong place to do it -- it would add a round trip to every cold start
for work that only ever needs to happen once -- so it lives here instead.

    # against the local SQLite file
    python scripts/setup_db.py

    # against Turso, the same database production will use
    TURSO_DATABASE_URL=libsql://... TURSO_AUTH_TOKEN=... python scripts/setup_db.py

Running it again is safe: the schema uses CREATE TABLE IF NOT EXISTS, the seed
only fills in rows that are missing, and an existing admin account is left
alone. Pass --force to overwrite seeded content with the originals again.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import config, db, seed, security      # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="rewrite seeded services, gallery items and settings back to the originals",
    )
    args = parser.parse_args()

    target = config.TURSO_DATABASE_URL if config.USE_TURSO else f"sqlite file {config.DB_PATH}"
    print(f"Database: {target}")

    db.init_db()
    print("Schema is in place.")

    added = seed.run(force=args.force)
    print(
        "Seeded {settings} settings, {services} services, {gallery} gallery items.".format(**added)
    )

    # ensure_bootstrap_admin returns a password only when it generated one, so
    # ask first whether an account existed to report the outcome accurately.
    had_admin = db.query_one("SELECT COUNT(*) AS n FROM admin_users")["n"] > 0
    password = security.ensure_bootstrap_admin()
    if had_admin:
        print("Admin account already exists; leaving it untouched.")
    elif password:
        print("\n  Admin account created")
        print(f"    username  {config.ADMIN_USERNAME}")
        print(f"    password  {password}")
        print("\n  Write this down now; it is not stored anywhere and not shown again.")
    else:
        print(f"Admin account '{config.ADMIN_USERNAME}' created with the password you supplied.")

    db.close()
    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as error:                   # noqa: BLE001 - a CLI wants a clean message
        print(f"\nSetup failed: {error}", file=sys.stderr)
        sys.exit(1)
