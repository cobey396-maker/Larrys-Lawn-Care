"""Vercel entry point: every /api/* request lands here.

Vercel's Python runtime looks for a class named `handler`, so this module
adapts the project's router to that contract. It deliberately does not serve
static files -- public/ is handled by Vercel's CDN, and reaching for the disk
is exactly what does not work in a serverless function.

vercel.json rewrites the whole /api/* space onto this one function and passes
the original path along in `__path`, because the rewritten request otherwise
arrives here pointing at /api/index.
"""

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlsplit

# The application package lives in backend/, next to this function rather than
# under it, so that Vercel does not mistake each module for its own endpoint.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import config, db                                   # noqa: E402
from app.api import router                                   # noqa: E402
from app.routing import HTTPError, Request, STATUS_TEXT      # noqa: E402

MAX_BODY_BYTES = max(config.MAX_UPLOAD_BYTES, config.MAX_JSON_BYTES) + 64 * 1024


class handler(BaseHTTPRequestHandler):        # noqa: N801 - the name Vercel looks for
    server_version = "LarrysLawnCare"
    sys_version = ""

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        self._respond(204, b"", {"Allow": "GET, POST, PUT, PATCH, DELETE, OPTIONS"}, True)

    # -- dispatch --------------------------------------------------------
    def _handle(self, method):
        try:
            path, query = _target(self.path)
            response = self._dispatch(method, path, query)
        except HTTPError as error:
            response = error.to_response()
        except Exception:                      # noqa: BLE001 - last resort
            traceback.print_exc(file=sys.stderr)
            response = HTTPError(500, "Something went wrong on our end.").to_response()
        finally:
            # The container may be reused for the next request, but the database
            # session must not be: drop it so a cold-started function never
            # inherits a connection the server has already forgotten.
            db.close()

        self._respond(
            response.status, response.body, response.headers, head_only=(method == "HEAD")
        )

    def _dispatch(self, method, path, query):
        route, params = router.match(method, path)
        if route is None:
            raise HTTPError(404, "No such endpoint.")

        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise HTTPError(413, "That request is too large.")
        body = self.rfile.read(length) if length > 0 else b""

        request = Request(method, path, query, self.headers, body, self._client_ip())
        request.params = params
        response = route(request)
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    # -- writing ---------------------------------------------------------
    def _respond(self, status, body, headers, head_only=False):
        try:
            self.send_response(status, STATUS_TEXT.get(status, ""))
            for name, value in headers.items():
                self.send_header(name, value)
            for name, value in _cors_headers(self.headers.get("Origin")).items():
                self.send_header(name, value)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body and not head_only:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                                  # the browser walked away

    def _client_ip(self):
        # Vercel always fronts the function, so the forwarded header is the only
        # place a real visitor address appears. The platform sets it itself.
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:45]
        return (self.client_address or ("",))[0]

    def log_message(self, fmt, *args):
        sys.stderr.write((fmt % args) + "\n")


def _target(raw_path):
    """The path the visitor actually asked for, plus its query string.

    A Vercel rewrite re-points the request at this function, so `__path`
    carries the original route. Everything else in the query string is passed
    through to the handler untouched.
    """
    split = urlsplit(raw_path)
    pairs = parse_qsl(split.query, keep_blank_values=True)
    original = next((value for key, value in pairs if key == "__path"), None)
    query = "&".join(
        f"{key}={value}" for key, value in _quote_back(pairs) if key != "__path"
    )
    return unquote(original or split.path), query


def _quote_back(pairs):
    """parse_qsl already decoded the pairs; Request re-parses, so re-encode."""
    return [(quote(key, safe=""), quote(value, safe="")) for key, value in pairs]


def _cors_headers(origin):
    if not origin:
        return {}
    allowed = config.ALLOWED_ORIGINS
    if "*" in allowed:
        value = "*"
    elif origin in allowed:
        value = origin
    else:
        return {}
    return {
        "Access-Control-Allow-Origin": value,
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }


# Surfaces a misconfigured database as a clear message in the build/function
# log rather than as an opaque 500 on the first request that touches it.
if not config.USE_TURSO:
    print(
        json.dumps({
            "warning": "TURSO_DATABASE_URL is not set; this function is using a local "
                       "SQLite file that Vercel will discard between requests."
        }),
        file=sys.stderr,
    )
