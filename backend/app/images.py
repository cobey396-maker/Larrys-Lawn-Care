"""Saving gallery photos: sniff the real type, cap the size, random file name.

Photos are stored as rows rather than files. A Vercel function gets a
read-only filesystem and a fresh container on every cold start, so anything
written to disk is gone before the next visitor asks for it. Keeping the bytes
in the database means the photo Larry uploads is the photo everyone sees, and
it is covered by the same backup as the rest of the content.
"""

import re
import secrets

from . import config, db
from .routing import HTTPError

# Signature -> (extension, mime). The declared Content-Type is ignored; only
# the bytes decide, so a renamed .exe cannot land in the gallery.
SIGNATURES = [
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    (b"GIF87a", ".gif", "image/gif"),
    (b"GIF89a", ".gif", "image/gif"),
]

ALLOWED_DESCRIPTION = "JPEG, PNG, GIF or WebP"

# Names are generated here and never taken from the request, so anything that
# does not look like one we minted is rejected before it reaches the database.
NAME_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|gif|webp)$")


def detect(data):
    for signature, extension, mime in SIGNATURES:
        if data.startswith(signature):
            return extension, mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None, None


def save(data):
    """Stores the image and returns the name that addresses it."""
    if not data:
        raise HTTPError(422, "No image data was uploaded.", fields={"image": "Choose a file."})
    if len(data) > config.MAX_UPLOAD_BYTES:
        limit_mb = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPError(413, f"Images must be smaller than {limit_mb} MB.")

    extension, mime = detect(data)
    if extension is None:
        raise HTTPError(
            422,
            f"That file is not an image. Upload {ALLOWED_DESCRIPTION}.",
            fields={"image": f"Must be {ALLOWED_DESCRIPTION}."},
        )

    name = secrets.token_hex(16) + extension
    db.execute(
        "INSERT INTO images (name, mime, bytes, byte_size, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, mime, data, len(data), db.now()),
    )
    return name


def load(name):
    """Returns the stored row, or None. Safe to call with untrusted input."""
    if not name or not NAME_RE.match(name):
        return None
    return db.query_one("SELECT name, mime, bytes, byte_size FROM images WHERE name = ?", (name,))


def delete(name):
    if not name:
        return
    db.execute("DELETE FROM images WHERE name = ?", (name,))


def url(name):
    return f"/api/images/{name}" if name else None
