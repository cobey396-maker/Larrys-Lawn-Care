"""A very small router: Request/Response objects, path patterns, JSON helpers."""

import json
from urllib.parse import parse_qs

from . import config


class HTTPError(Exception):
    """Raised anywhere in a handler to return a clean JSON error."""

    def __init__(self, status, message, code=None, fields=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code or _DEFAULT_CODES.get(status, "error")
        self.fields = fields or {}

    def to_response(self):
        payload = {"error": {"code": self.code, "message": self.message}}
        if self.fields:
            payload["error"]["fields"] = self.fields
        return Response.json(payload, status=self.status)


_DEFAULT_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_failed",
    429: "rate_limited",
    500: "server_error",
}

STATUS_TEXT = {
    200: "OK", 201: "Created", 204: "No Content", 206: "Partial Content",
    304: "Not Modified", 400: "Bad Request", 401: "Unauthorized",
    403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
    409: "Conflict", 413: "Payload Too Large", 415: "Unsupported Media Type",
    422: "Unprocessable Content", 429: "Too Many Requests",
    500: "Internal Server Error",
}


class Request:
    def __init__(self, method, path, query_string, headers, body, client_ip):
        self.method = method
        self.path = path
        self.headers = headers
        self.body = body
        self.client_ip = client_ip
        self.params = {}          # filled in by the router from the path pattern
        self.user = None          # filled in by require_admin
        self.query = {k: v[0] for k, v in parse_qs(query_string, keep_blank_values=True).items()}

    def header(self, name, default=""):
        return self.headers.get(name, default)

    @property
    def content_type(self):
        return self.header("Content-Type", "").split(";")[0].strip().lower()

    def json_body(self):
        if not self.body:
            return {}
        if self.content_type not in ("application/json", ""):
            raise HTTPError(415, "Send this request as application/json.")
        if len(self.body) > config.MAX_JSON_BYTES:
            raise HTTPError(413, "Request body is too large.")
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HTTPError(400, "Request body is not valid JSON.")
        if not isinstance(data, dict):
            raise HTTPError(400, "Request body must be a JSON object.")
        return data


class Response:
    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self.body = body if isinstance(body, (bytes, bytearray)) else str(body).encode("utf-8")
        self.headers = headers or {}

    @classmethod
    def json(cls, payload, status=200, headers=None):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        head = {"Content-Type": "application/json; charset=utf-8"}
        head.update(headers or {})
        return cls(status, body, head)

    @classmethod
    def no_content(cls):
        return cls(204, b"", {})


class Router:
    """Matches "/api/leads/{id}" style patterns. Static segments win over params."""

    def __init__(self):
        self._routes = []          # (method, [segments], handler)

    def add(self, method, pattern, handler):
        self._routes.append((method.upper(), _split(pattern), handler))

    def route(self, method, pattern):
        def decorator(fn):
            self.add(method, pattern, fn)
            return fn
        return decorator

    def get(self, pattern):
        return self.route("GET", pattern)

    def post(self, pattern):
        return self.route("POST", pattern)

    def patch(self, pattern):
        return self.route("PATCH", pattern)

    def put(self, pattern):
        return self.route("PUT", pattern)

    def delete(self, pattern):
        return self.route("DELETE", pattern)

    def include(self, other):
        self._routes.extend(other._routes)

    def match(self, method, path):
        """Returns (handler, params). Raises 405 when only the method is wrong."""
        segments = _split(path)
        path_matched = False
        for route_method, pattern, handler in self._routes:
            params = _match_segments(pattern, segments)
            if params is None:
                continue
            path_matched = True
            if route_method == method or (route_method == "GET" and method == "HEAD"):
                return handler, params
        if path_matched:
            raise HTTPError(405, f"{method} is not allowed on this endpoint.")
        return None, None


def _split(path):
    return [s for s in path.split("/") if s]


def _match_segments(pattern, segments):
    if len(pattern) != len(segments):
        return None
    params = {}
    for expected, actual in zip(pattern, segments):
        if expected.startswith("{") and expected.endswith("}"):
            params[expected[1:-1]] = actual
        elif expected != actual:
            return None
    return params
