"""A small sqlite3-shaped client for Turso (libSQL), over its HTTP API.

Vercel gives a function a read-only filesystem and throws the container away
between requests, so the on-disk SQLite file this project started with cannot
live there: every lead and every login would vanish on the next cold start.
Turso speaks the same SQL dialect, so the fix is to change the connection and
nothing else -- every query, every "?" placeholder and every AUTOINCREMENT in
the app stays exactly as it was.

Only the slice of sqlite3 that db.py actually uses is implemented here:
execute, executescript, rows addressed by column name, lastrowid, and
`with connection:` transactions. It talks to the /v2/pipeline endpoint using
nothing but the standard library, which keeps the deployed function free of
compiled dependencies that would have to build on Vercel.
"""

import base64
import json
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

PIPELINE_PATH = "/v2/pipeline"
DEFAULT_TIMEOUT = 15.0
RETRYABLE_ATTEMPTS = 3


class Error(Exception):
    """Base class, mirroring sqlite3.Error."""


class DatabaseError(Error):
    """The server rejected a statement, or the transport failed."""


def http_url(database_url):
    """Turns libsql://db-org.turso.io into https://db-org.turso.io."""
    parts = urlsplit(database_url.strip())
    scheme = {"libsql": "https", "wss": "https", "ws": "http"}.get(parts.scheme, parts.scheme)
    if scheme not in ("http", "https"):
        raise DatabaseError(f"Unsupported database URL scheme: {parts.scheme!r}")
    return urlunsplit((scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


# -- value conversion ----------------------------------------------------
def _encode(value):
    """Python value -> the libSQL wire form. Integers travel as strings."""
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "blob", "value": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    raise DatabaseError(f"Cannot bind a {type(value).__name__} to a statement.")


def _decode(cell):
    kind = cell.get("type")
    value = cell.get("value")
    if kind == "null":
        return None
    if kind == "integer":
        return int(value)
    if kind == "float":
        return float(value)
    if kind == "blob":
        # The wire format is standard base64; pad defensively, some servers strip it.
        return base64.b64decode(value + "=" * (-len(value) % 4))
    return value


class Row:
    """Mapping-ish result row, addressable by column name like sqlite3.Row."""

    __slots__ = ("_columns", "_values")

    def __init__(self, columns, values):
        self._columns = columns
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        try:
            return self._values[self._columns.index(key)]
        except ValueError:
            raise IndexError(f"No column named {key!r}") from None

    def keys(self):
        return list(self._columns)

    def __contains__(self, key):
        return key in self._columns

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return f"Row({dict(zip(self._columns, self._values))!r})"


class Cursor:
    """Just enough of a DB-API cursor for the call sites in this project."""

    def __init__(self, rows=(), lastrowid=None, rowcount=-1):
        self._rows = list(rows)
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    """One logical session against a Turso database.

    libSQL's HTTP protocol threads a "baton" through the responses to keep a
    server-side session alive; holding onto it is what lets BEGIN and COMMIT
    in a `with` block land on the same connection.
    """

    def __init__(self, database_url, auth_token=None, timeout=DEFAULT_TIMEOUT):
        self._endpoint = http_url(database_url) + PIPELINE_PATH
        self._redirect = None
        self._auth_token = auth_token
        self._timeout = timeout
        self._baton = None
        self._closed = False
        self._depth = 0
        self.row_factory = None      # accepted for parity; rows are already named

    # -- transport -------------------------------------------------------
    def _post(self, requests):
        payload = {"requests": requests}
        if self._baton:
            payload["baton"] = self._baton
        body = json.dumps(payload).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        url = self._redirect or self._endpoint
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")

        # A dropped connection is ordinary against a pooled edge database, so a
        # call that failed before the server saw it is worth retrying. That is
        # only safe with no live session: once a baton exists the server holds
        # state a replay would not share, so a failed statement stays failed.
        attempts = RETRYABLE_ATTEMPTS if self._baton is None else 1
        last_error = None
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(
                    request, timeout=self._timeout, context=_ssl_context()
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:500]
                raise DatabaseError(f"Turso returned HTTP {error.code}: {detail}") from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = error
        raise DatabaseError(f"Could not reach the database: {last_error}") from last_error

    def _pipeline(self, requests):
        if self._closed:
            raise DatabaseError("This connection is already closed.")

        # Outside a transaction there is no reason to keep a server-side
        # session alive, and every reason not to: a function that goes cold
        # between requests would otherwise come back holding a baton the
        # server has long since forgotten. Closing in the same round trip
        # costs nothing and leaves the connection stateless between calls.
        standalone = self._depth == 0
        if standalone:
            requests = list(requests) + [{"type": "close"}]

        document = self._post(requests)
        self._baton = None if standalone else (document.get("baton") or None)
        base = document.get("base_url")
        if base:
            self._redirect = base.rstrip("/") + PIPELINE_PATH

        results = []
        for entry in document.get("results", []):
            if entry.get("type") == "error":
                message = (entry.get("error") or {}).get("message", "unknown error")
                raise DatabaseError(message)
            results.append((entry.get("response") or {}).get("result"))
        return results

    # -- statements ------------------------------------------------------
    def execute(self, sql, params=()):
        statement = {"sql": sql}
        if params:
            statement["args"] = [_encode(value) for value in params]
        result = self._pipeline([{"type": "execute", "stmt": statement}])[0]
        return _to_cursor(result)

    def executescript(self, script):
        """Runs a multi-statement script, as sqlite3's executescript does."""
        statements = [s.strip() for s in script.split(";")]
        requests = [
            {"type": "execute", "stmt": {"sql": statement}}
            for statement in statements
            if statement
        ]
        if requests:
            self._pipeline(requests)
        return Cursor()

    # -- transactions ----------------------------------------------------
    def commit(self):
        if self._depth:
            self._depth = 0
            self.execute("COMMIT")

    def rollback(self):
        if self._depth:
            self._depth = 0
            self.execute("ROLLBACK")

    def __enter__(self):
        # sqlite3 allows nesting a `with` block inside an open transaction and
        # treats only the outermost one as the real boundary; match that. Depth
        # rises before BEGIN so the statement keeps the session open.
        self._depth += 1
        if self._depth == 1:
            self.execute("BEGIN")
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._depth > 1:
            self._depth -= 1
            return False
        # Dropping to zero first lets the closing statement carry the session
        # teardown, so a transaction costs no extra round trip.
        self._depth = 0
        self.execute("ROLLBACK" if exc_type else "COMMIT")
        return False

    def close(self):
        if self._closed:
            return
        if self._baton:                   # a transaction was left open
            self._depth = 0
            try:
                self._pipeline([{"type": "execute", "stmt": {"sql": "ROLLBACK"}}])
            except DatabaseError:
                pass                      # the session times out on its own anyway
        self._closed = True


def _to_cursor(result):
    if not result:
        return Cursor()
    columns = [column.get("name") for column in result.get("cols", [])]
    rows = [
        Row(columns, [_decode(cell) for cell in raw])
        for raw in result.get("rows", [])
    ]
    last_id = result.get("last_insert_rowid")
    return Cursor(
        rows,
        lastrowid=int(last_id) if last_id not in (None, "") else None,
        rowcount=result.get("affected_row_count", -1),
    )


_CONTEXT = None


def _ssl_context():
    global _CONTEXT
    if _CONTEXT is None:
        _CONTEXT = ssl.create_default_context()
    return _CONTEXT


def connect(database_url, auth_token=None, timeout=DEFAULT_TIMEOUT):
    return Connection(database_url, auth_token, timeout)
