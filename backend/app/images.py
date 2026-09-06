"""Saving gallery photos: sniff the real type, cap the size, random file name."""

import secrets

from . import config
from .routing import HTTPError

# Signature -> (extension, mime). The declared Content-Type is ignored; only
# the bytes decide, so a renamed .exe cannot land in the uploads folder.
SIGNATURES = [
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    (b"GIF87a", ".gif", "image/gif"),
    (b"GIF89a", ".gif", "image/gif"),
]

ALLOWED_DESCRIPTION = "JPEG, PNG, GIF or WebP"


def detect(data):
    for signature, extension, mime in SIGNATURES:
        if data.startswith(signature):
            return extension, mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None, None


def save(data):
    """Writes the image into the uploads dir and returns its file name."""
    if not data:
        raise HTTPError(422, "No image data was uploaded.", fields={"image": "Choose a file."})
    if len(data) > config.MAX_UPLOAD_BYTES:
        limit_mb = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPError(413, f"Images must be smaller than {limit_mb} MB.")

    extension, _ = detect(data)
    if extension is None:
        raise HTTPError(
            422,
            f"That file is not an image. Upload {ALLOWED_DESCRIPTION}.",
            fields={"image": f"Must be {ALLOWED_DESCRIPTION}."},
        )

    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(16) + extension
    (config.UPLOAD_DIR / name).write_bytes(data)
    return name


def delete(name):
    if not name:
        return
    target = config.UPLOAD_DIR / name
    # Guard against a stored name that tries to climb out of the uploads dir.
    try:
        target.resolve().relative_to(config.UPLOAD_DIR)
    except ValueError:
        return
    target.unlink(missing_ok=True)


def url(name):
    return f"/uploads/{name}" if name else None
