"""Gallery photos. Each row lines up with one image-slot in the design."""

import re

from .. import db, images, multipart
from ..routing import HTTPError, Response, Router
from ..security import require_admin
from ..validation import Validator, path_int

router = Router()


def serialize(row):
    return {
        "id": row["id"],
        "slug": row["slug"],
        "caption": row["caption"],
        "hint": row["hint"],
        "alt": row["alt"] or row["caption"],
        "image_url": images.url(row["image_file"]),
        "has_image": bool(row["image_file"]),
        "position": row["position"],
        "published": bool(row["published"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _get_or_404(item_id):
    row = db.query_one("SELECT * FROM gallery_items WHERE id = ?", (item_id,))
    if row is None:
        raise HTTPError(404, "That gallery item does not exist.")
    return row


def _unique_slug(slug, exclude_id=None):
    candidate, suffix = slug, 2
    while True:
        row = db.query_one("SELECT id FROM gallery_items WHERE slug = ?", (candidate,))
        if row is None or row["id"] == exclude_id:
            return candidate
        candidate = f"{slug}-{suffix}"
        suffix += 1


def _slugify(text, fallback="photo"):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]
    return slug or fallback


# -- public --------------------------------------------------------------
@router.get("/api/gallery")
def list_gallery(request):
    """?with_images=1 hides frames that have no photo in them yet."""
    sql = "SELECT * FROM gallery_items WHERE published = 1"
    if request.query.get("with_images") in ("1", "true"):
        sql += " AND image_file IS NOT NULL"
    rows = db.query(sql + " ORDER BY position, id")
    return Response.json({"gallery": [serialize(r) for r in rows]})


# -- admin ---------------------------------------------------------------
@router.get("/api/admin/gallery")
@require_admin
def admin_list_gallery(request):
    rows = db.query("SELECT * FROM gallery_items ORDER BY position, id")
    return Response.json({"gallery": [serialize(r) for r in rows]})


@router.post("/api/admin/gallery")
@require_admin
def create_gallery_item(request):
    validator = Validator(request.json_body())
    validator.slug("slug")
    validator.text("caption", max_length=200)
    validator.text("hint", max_length=200)
    validator.text("alt", max_length=200)
    validator.integer("position", minimum=0, maximum=9999)
    validator.boolean("published", default=True)
    data = validator.done()

    slug = _unique_slug(data.get("slug") or _slugify(data.get("caption", "")))
    position = data.get("position")
    if position is None:
        position = db.query_one(
            "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM gallery_items"
        )["n"]

    timestamp = db.now()
    cursor = db.execute(
        "INSERT INTO gallery_items (slug, caption, hint, alt, position, published, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (slug, data.get("caption", ""), data.get("hint", ""), data.get("alt", ""),
         position, int(data.get("published", True)), timestamp, timestamp),
    )
    return Response.json({"item": serialize(_get_or_404(cursor.lastrowid))}, status=201)


@router.patch("/api/admin/gallery/{id}")
@require_admin
def update_gallery_item(request):
    item_id = path_int(request, "id")
    _get_or_404(item_id)

    validator = Validator(request.json_body())
    validator.slug("slug")
    validator.text("caption", max_length=200)
    validator.text("hint", max_length=200)
    validator.text("alt", max_length=200)
    validator.integer("position", minimum=0, maximum=9999)
    validator.boolean("published")
    data = validator.done()

    updates, values = [], []
    for field in ("caption", "hint", "alt", "position"):
        if field in data:
            updates.append(f"{field} = ?")
            values.append(data[field])
    if "slug" in data and data["slug"]:
        updates.append("slug = ?")
        values.append(_unique_slug(data["slug"], exclude_id=item_id))
    if "published" in data:
        updates.append("published = ?")
        values.append(int(data["published"]))
    if not updates:
        raise HTTPError(422, "Nothing to update.")

    updates.append("updated_at = ?")
    values.extend([db.now(), item_id])
    db.execute(f"UPDATE gallery_items SET {', '.join(updates)} WHERE id = ?", values)
    return Response.json({"item": serialize(_get_or_404(item_id))})


@router.post("/api/admin/gallery/{id}/image")
@require_admin
def upload_gallery_image(request):
    """multipart/form-data with an "image" file field. Replaces any old photo."""
    item_id = path_int(request, "id")
    row = _get_or_404(item_id)

    if request.content_type != "multipart/form-data":
        raise HTTPError(415, "Send the photo as multipart/form-data.")
    parts = multipart.parse(request.header("Content-Type"), request.body)
    part = parts.get("image")
    if part is None or not part.is_file:
        raise HTTPError(422, "Attach the photo in a field named 'image'.",
                        fields={"image": "No file was attached."})

    new_file = images.save(part.data)
    old_file = row["image_file"]
    db.execute(
        "UPDATE gallery_items SET image_file = ?, updated_at = ? WHERE id = ?",
        (new_file, db.now(), item_id),
    )
    if old_file and old_file != new_file:
        images.delete(old_file)

    if "caption" in parts and not parts["caption"].is_file:
        caption = parts["caption"].text()[:200]
        db.execute("UPDATE gallery_items SET caption = ? WHERE id = ?", (caption, item_id))

    return Response.json({"item": serialize(_get_or_404(item_id))})


@router.delete("/api/admin/gallery/{id}/image")
@require_admin
def delete_gallery_image(request):
    item_id = path_int(request, "id")
    row = _get_or_404(item_id)
    images.delete(row["image_file"])
    db.execute(
        "UPDATE gallery_items SET image_file = NULL, updated_at = ? WHERE id = ?",
        (db.now(), item_id),
    )
    return Response.json({"item": serialize(_get_or_404(item_id))})


@router.delete("/api/admin/gallery/{id}")
@require_admin
def delete_gallery_item(request):
    item_id = path_int(request, "id")
    row = _get_or_404(item_id)
    images.delete(row["image_file"])
    db.execute("DELETE FROM gallery_items WHERE id = ?", (item_id,))
    return Response.no_content()


@router.post("/api/admin/gallery/reorder")
@require_admin
def reorder_gallery(request):
    order = request.json_body().get("order")
    if not isinstance(order, list) or not order:
        raise HTTPError(422, "Send an 'order' list of gallery ids.",
                        fields={"order": "Expected a list of ids."})
    known = {row["id"] for row in db.query("SELECT id FROM gallery_items")}
    if set(order) - known:
        raise HTTPError(422, "That list contains ids that do not exist.",
                        fields={"order": "Unknown gallery id."})

    connection = db.connect()
    with connection:
        for position, item_id in enumerate(order):
            connection.execute(
                "UPDATE gallery_items SET position = ?, updated_at = ? WHERE id = ?",
                (position, db.now(), item_id),
            )
    rows = db.query("SELECT * FROM gallery_items ORDER BY position, id")
    return Response.json({"gallery": [serialize(r) for r in rows]})
