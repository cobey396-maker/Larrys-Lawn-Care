"""The HTTP layer: dispatch to the API router, otherwise serve files.

The design folder is served at "/" and the API lives under "/api", so the
browser sees one origin and CORS never enters the picture.
"""

import mimetypes
import sys
import traceback
from datetime import datetime, timezone
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from . import config, db
from .api import router
from .routing import HTTPError, Request, Response, STATUS_TEXT

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/woff2", ".woff2")

MAX_BODY_BYTES = max(config.MAX_UPLOAD_BYTES, config.MAX_JSON_BYTES) + 64 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "LarrysLawnCare"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- entry points ----------------------------------------------------
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
        response = Response(204, b"", {"Allow": "GET, POST, PUT, PATCH, DELETE, OPTIONS"})
        self._send(response, head_only=True)

    # -- dispatch --------------------------------------------------------
    def _handle(self, method):
        try:
            split = urlsplit(self.path)
            path = unquote(split.path)
            if path.startswith("/api/"):
                response = self._handle_api(method, path, split.query)
            elif method in ("GET", "HEAD"):
                response = self._serve_file(path)
            else:
                raise HTTPError(405, f"{method} is not allowed here.")
        except HTTPError as error:
            response = error.to_response()
        except Exception:                      # noqa: BLE001 - last resort
            traceback.print_exc(file=sys.stderr)
            response = HTTPError(500, "Something went wrong on our end.").to_response()
        finally:
            db.close()

        self._send(response, head_only=(method == "HEAD"))

    def _handle_api(self, method, path, query):
        handler, params = router.match(method, path)
        if handler is None:
            raise HTTPError(404, "No such endpoint.")

        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise HTTPError(413, "That request is too large.")
        body = self.rfile.read(length) if length > 0 else b""

        request = Request(method, path, query, self.headers, body, self._client_ip())
        request.params = params
        response = handler(request)
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    # -- static files ----------------------------------------------------
    def _serve_file(self, path):
        if path.startswith("/uploads/"):
            target = _resolve(config.UPLOAD_DIR, path[len("/uploads/"):])
            cache = "public, max-age=31536000, immutable"   # names are content-random
        elif path in ("/admin", "/admin/"):
            target, cache = config.ADMIN_DIR / "index.html", "no-cache"
        elif path.startswith("/admin/"):
            target, cache = _resolve(config.ADMIN_DIR, path[len("/admin/"):]), "no-cache"
        elif path in ("/", ""):
            target, cache = _site_index(), "no-cache"
        else:
            target, cache = _resolve(config.SITE_DIR, path.lstrip("/")), "no-cache"

        if target is None or not target.is_file():
            raise HTTPError(404, "Not found.")

        stat = target.stat()
        etag = f'W/"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
        if self.headers.get("If-None-Match") == etag:
            return Response(304, b"", {"ETag": etag, "Cache-Control": cache})

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
            "application/javascript", "application/json"
        ):
            content_type += "; charset=utf-8"

        return Response(200, target.read_bytes(), {
            "Content-Type": content_type,
            "Cache-Control": cache,
            "ETag": etag,
            "Last-Modified": formatdate(stat.st_mtime, usegmt=True),
        })

    # -- writing ---------------------------------------------------------
    def _send(self, response, head_only=False):
        body = b"" if head_only else response.body
        try:
            self.send_response(response.status, STATUS_TEXT.get(response.status, ""))
            for name, value in response.headers.items():
                self.send_header(name, value)
            for name, value in _cors_headers(self.headers.get("Origin")).items():
                self.send_header(name, value)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                                  # the browser walked away

    def _client_ip(self):
        if config.TRUST_PROXY:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()[:45]
        return self.client_address[0]

    def log_message(self, fmt, *args):
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        sys.stderr.write(f"[{stamp}] {self.address_string()} {fmt % args}\n")


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


def _resolve(root, relative):
    """Join a request path onto a root without letting it escape the root."""
    if not relative or "\x00" in relative:
        return None
    try:
        candidate = (root / relative).resolve()
        candidate.relative_to(root)
    except (ValueError, OSError):
        return None
    return candidate


def _site_index():
    """The design exports one .dc.html file; fall back to index.html."""
    if not config.SITE_DIR.is_dir():
        return config.ADMIN_DIR / "index.html"
    for candidate in sorted(config.SITE_DIR.glob("*.dc.html")):
        return candidate
    index = config.SITE_DIR / "index.html"
    return index if index.is_file() else None


def serve(host=None, port=None):
    host = host or config.HOST
    port = port or config.PORT
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def run(host=None, port=None):
    httpd = serve(host, port)
    host, port = httpd.server_address[0], httpd.server_address[1]
    print(f"  Site   http://{host}:{port}/")
    print(f"  API    http://{host}:{port}/api/content")
    print(f"  Admin  http://{host}:{port}/admin/")
    print("  Ctrl+C to stop\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
