"""The four services shown on the home page and listed on the services page."""

import json
import re

from .. import db
from ..routing import HTTPError, Response, Router
from ..security import require_admin
from ..validation import Validator, path_int

router = Router()


def serialize(row):
    return {
        "id": row["id"],
        "slug": row["slug"],
        "kicker": row["kicker"],
        "title": row["title"],
        "blurb": row["blurb"],
        "price": row["price"],
        "detail": row["detail"],
        "tags": json.loads(row["tags"]),
        "position": row["position"],
        "published": bool(row["published"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _get_or_404(service_id):
    row = db.query_one("SELECT * FROM services WHERE id = ?", (service_id,))
    if row is None:
        raise HTTPError(404, "That service does not exist.")
    return row


def _slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "service"


def _unique_slug(slug, exclude_id=None):
    candidate, suffix = slug, 2
    while True:
        row = db.query_one("SELECT id FROM services WHERE slug = ?", (candidate,))
        if row is None or row["id"] == exclude_id:
            return candidate
        candidate = f"{slug}-{suffix}"
        suffix += 1


# -- public --------------------------------------------------------------
@router.get("/api/services")
def list_services(request):
    rows = db.query(
        "SELECT * FROM services WHERE published = 1 ORDER BY position, id"
    )
    return Response.json({"services": [serialize(r) for r in rows]})


@router.get("/api/services/{slug}")
def get_service(request):
    row = db.query_one(
        "SELECT * FROM services WHERE slug = ? AND published = 1", (request.params["slug"],)
    )
    if row is None:
        raise HTTPError(404, "That service does not exist.")
    return Response.json({"service": serialize(row)})


# -- admin ---------------------------------------------------------------
@router.get("/api/admin/services")
@require_admin
def admin_list_services(request):
    rows = db.query("SELECT * FROM services ORDER BY position, id")
    return Response.json({"services": [serialize(r) for r in rows]})


@router.post("/api/admin/services")
@require_admin
def create_service(request):
    validator = Validator(request.json_body())
    validator.slug("slug")
    validator.text("title", required=True, max_length=120)
    validator.text("kicker", max_length=80)
    validator.text("blurb", max_length=400)
    validator.text("price", max_length=80)
    validator.text("detail", max_length=4000)
    validator.string_list("tags", default=[])
    validator.integer("position", minimum=0, maximum=9999)
    validator.boolean("published", default=True)
    data = validator.done()

    slug = _unique_slug(data.get("slug") or _slugify(data["title"]))
    position = data.get("position")
    if position is None:
        position = (db.query_one("SELECT COALESCE(MAX(position), -1) + 1 AS n FROM services")["n"])

    timestamp = db.now()
    cursor = db.execute(
        "INSERT INTO services (slug, kicker, title, blurb, price, detail, tags, position, "
        "published, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (slug, data.get("kicker", ""), data["title"], data.get("blurb", ""),
         data.get("price", ""), data.get("detail", ""), json.dumps(data.get("tags", [])),
         position, int(data.get("published", True)), timestamp, timestamp),
    )
    return Response.json({"service": serialize(_get_or_404(cursor.lastrowid))}, status=201)


@router.patch("/api/admin/services/{id}")
@require_admin
def update_service(request):
    service_id = path_int(request, "id")
    _get_or_404(service_id)

    body = request.json_body()
    validator = Validator(body)
    validator.slug("slug")
    validator.text("title", max_length=120)
    validator.text("kicker", max_length=80)
    validator.text("blurb", max_length=400)
    validator.text("price", max_length=80)
    validator.text("detail", max_length=4000)
    validator.string_list("tags")
    validator.integer("position", minimum=0, maximum=9999)
    validator.boolean("published")
    data = validator.done()

    updates, values = [], []
    for field in ("title", "kicker", "blurb", "price", "detail", "position"):
        if field in data:
            updates.append(f"{field} = ?")
            values.append(data[field])
    if "slug" in data and data["slug"]:
        updates.append("slug = ?")
        values.append(_unique_slug(data["slug"], exclude_id=service_id))
    if "tags" in data:
        updates.append("tags = ?")
        values.append(json.dumps(data["tags"]))
    if "published" in data:
        updates.append("published = ?")
        values.append(int(data["published"]))
    if not updates:
        raise HTTPError(422, "Nothing to update.")

    updates.append("updated_at = ?")
    values.extend([db.now(), service_id])
    db.execute(f"UPDATE services SET {', '.join(updates)} WHERE id = ?", values)
    return Response.json({"service": serialize(_get_or_404(service_id))})


@router.delete("/api/admin/services/{id}")
@require_admin
def delete_service(request):
    service_id = path_int(request, "id")
    _get_or_404(service_id)
    db.execute("DELETE FROM services WHERE id = ?", (service_id,))
    return Response.no_content()


@router.post("/api/admin/services/reorder")
@require_admin
def reorder_services(request):
    """Body: {"order": [3, 1, 4, 2]} — service ids in the order to display."""
    body = request.json_body()
    order = body.get("order")
    if not isinstance(order, list) or not order:
        raise HTTPError(422, "Send an \"order\" list of service ids.",
                        fields={"order": "Expected a list of ids."})
    known = {row["id"] for row in db.query("SELECT id FROM services")}
    if set(order) - known:
        raise HTTPError(422, "That list contains ids that do not exist.",
                        fields={"order": "Unknown service id."})

    connection = db.connect()
    with connection:
        for position, service_id in enumerate(order):
            connection.execute(
                "UPDATE services SET position = ?, updated_at = ? WHERE id = ?",
                (position, db.now(), service_id),
            )
    rows = db.query("SELECT * FROM services ORDER BY position, id")
    return Response.json({"services": [serialize(r) for r in rows]})
