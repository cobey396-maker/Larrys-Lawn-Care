#!/usr/bin/env python3
"""Run the whole site locally: static files at "/" and the API under /api.

This is the development counterpart to the Vercel deployment. There, the CDN
serves public/ and api/index.py answers /api; here one process does both, which
gives the browser the same single origin and the same URLs.

    python scripts/serve.py            # http://127.0.0.1:8080
    python scripts/serve.py --port 3000
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import config, db, server        # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    args = parser.parse_args()

    if not config.USE_TURSO and not config.DB_PATH.exists():
        print("No database yet. Run: python scripts/setup_db.py\n", file=sys.stderr)
        sys.exit(1)

    print(f"\nServing {config.SITE_DIR}")
    server.run(args.host, args.port)
    db.close()


if __name__ == "__main__":
    main()
