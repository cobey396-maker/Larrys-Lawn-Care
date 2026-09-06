"""Minimal multipart/form-data parser.

Python dropped the `cgi` module in 3.13, and the only multipart request this
backend accepts is a single gallery photo, so a focused parser is enough.
"""

import re

from .routing import HTTPError

_BOUNDARY_RE = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)
_DISPOSITION_NAME_RE = re.compile(r'\bname="([^"]*)"', re.IGNORECASE)
_DISPOSITION_FILENAME_RE = re.compile(r'\bfilename="([^"]*)"', re.IGNORECASE)


class Part:
    def __init__(self, name, filename, content_type, data):
        self.name = name
        self.filename = filename
        self.content_type = content_type
        self.data = data

    @property
    def is_file(self):
        return self.filename is not None

    def text(self):
        return self.data.decode("utf-8", "replace").strip()


def parse(content_type_header, body, max_parts=12):
    """Returns {field_name: Part}. Later parts with the same name win."""
    match = _BOUNDARY_RE.search(content_type_header or "")
    if not match:
        raise HTTPError(400, "Upload is missing its multipart boundary.")

    delimiter = b"--" + match.group(1).encode("latin-1")
    chunks = body.split(delimiter)
    if len(chunks) < 2:
        raise HTTPError(400, "Upload body is not valid multipart data.")

    parts = {}
    for chunk in chunks[1:]:
        if chunk[:2] == b"--":            # closing boundary
            break
        chunk = chunk.lstrip(b"\r\n")
        head, separator, data = chunk.partition(b"\r\n\r\n")
        if not separator:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]

        name = filename = None
        part_type = "application/octet-stream"
        for line in head.decode("utf-8", "replace").split("\r\n"):
            field, _, value = line.partition(":")
            field = field.strip().lower()
            if field == "content-disposition":
                name_match = _DISPOSITION_NAME_RE.search(value)
                file_match = _DISPOSITION_FILENAME_RE.search(value)
                name = name_match.group(1) if name_match else None
                filename = file_match.group(1) if file_match else None
            elif field == "content-type":
                part_type = value.split(";")[0].strip().lower()

        if name is None:
            continue
        parts[name] = Part(name, filename, part_type, data)
        if len(parts) > max_parts:
            raise HTTPError(400, "Too many fields in this upload.")

    if not parts:
        raise HTTPError(400, "Upload contained no fields.")
    return parts
