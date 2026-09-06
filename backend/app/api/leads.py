"""Callback requests from the contact page, and the inbox Larry works from."""

from datetime import datetime, timedelta, timezone

from .. import config, db
from ..routing import HTTPError, Response, Router
from ..security import require_admin
from ..validation import Validator, path_int

router = Router()

STATUSES = ("new", "contacted", "scheduled", "quoted", "won", "lost")


def serialize(row, include_private=False):
    data = {
        "id": row["id"],
        "name": row["name"],
        "phone": row["phone"],
        "email": row["email"],
        "address": row["address"],
        "message": row["message"],
        "service_slug": row["service_slug"],
        "source": row["source"],
        "status": row["status"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_private:
        data["ip"] = row["ip"]
        data["user_agent"] = row["user_agent"]
    return data


def _get_or_404(lead_id):
    row = db.query_one("SELECT * FROM leads WHERE id = ?", (lead_id,))
    if row is None:
        raise HTTPError(404, "That request does not exist.")
    return row


def _iso_seconds_ago(seconds):
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_rate_limit(ip):
    since = _iso_seconds_ago(config.LEAD_RATE_WINDOW_SECONDS)
    db.execute("DELETE FROM submissions WHERE created_at < ?", (since,))
    recent = db.query_one(
        "SELECT COUNT(*) AS n FROM submissions WHERE ip = ? AND created_at >= ?", (ip, since)
    )["n"]
    if recent >= config.LEAD_RATE_LIMIT:
        raise HTTPError(
            429,
            "That is a lot of requests from one place. Give it an hour, or just call us.",
            code="rate_limited",
        )


def _is_duplicate(phone_digits):
    since = _iso_seconds_ago(config.LEAD_DUPLICATE_SECONDS)
    row = db.query_one(
        "SELECT id FROM leads WHERE phone_digits = ? AND created_at >= ?",
        (phone_digits, since),
    )
    return row is not None


# -- public --------------------------------------------------------------
@router.post("/api/leads")
def create_lead(request):
    """The "Request a callback" box. Phone is the only thing actually required."""
    body = request.json_body()

    # Honeypot: real people never fill in a field they cannot see. Answer with
    # the same success shape so a bot learns nothing from the response.
    if str(body.get("website", "")).strip():
        return Response.json({"ok": True, "message": _confirmation()}, status=201)

    validator = Validator(body)
    validator.phone("phone", required=True)
    validator.text("name", max_length=120)
    validator.email("email")
    validator.text("address", max_length=300)
    validator.text("message", max_length=2000)
    validator.text("source", max_length=40, default="website")
    service_slug = validator.text("service_slug", max_length=80)
    data = validator.done()

    if service_slug:
        known = db.query_one("SELECT slug FROM services WHERE slug = ?", (service_slug,))
        if known is None:
            raise HTTPError(422, "That service does not exist.",
                            fields={"service_slug": "Unknown service."})

    _check_rate_limit(request.client_ip)

    if _is_duplicate(data["phone_digits"]):
        # Someone double-clicked the button. Do not create a second row.
        return Response.json({"ok": True, "message": _confirmation()}, status=200)

    timestamp = db.now()
    cursor = db.execute(
        "INSERT INTO leads (name, phone, phone_digits, email, address, message, service_slug, "
        "source, status, ip, user_agent, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)",
        (data.get("name", ""), data["phone"], data["phone_digits"], data.get("email", ""),
         data.get("address", ""), data.get("message", ""), service_slug or None,
         data.get("source") or "website", request.client_ip,
         request.header("User-Agent", "")[:300], timestamp, timestamp),
    )
    db.execute("INSERT INTO submissions (ip, created_at) VALUES (?, ?)",
               (request.client_ip, timestamp))

    return Response.json(
        {"ok": True, "message": _confirmation(), "lead": {"id": cursor.lastrowid}}, status=201
    )


def _confirmation():
    return db.get_setting("callback_confirmation", "Got it — talk soon.")


# -- admin ---------------------------------------------------------------
@router.get("/api/admin/leads")
@require_admin
def list_leads(request):
    """Filter with ?status=new and page with ?limit= &offset= ."""
    where, values = [], []
    status = request.query.get("status")
    if status:
        if status not in STATUSES:
            raise HTTPError(422, "Unknown status filter.",
                            fields={"status": "Must be one of: " + ", ".join(STATUSES) + "."})
        where.append("status = ?")
        values.append(status)

    search = request.query.get("q", "").strip()
    if search:
        where.append("(name LIKE ? OR phone LIKE ? OR address LIKE ? OR message LIKE ?)")
        values.extend([f"%{search}%"] * 4)

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.query_one(f"SELECT COUNT(*) AS n FROM leads{clause}", values)["n"]

    limit = min(max(int(request.query.get("limit", 50) or 50), 1), 200)
    offset = max(int(request.query.get("offset", 0) or 0), 0)
    rows = db.query(
        f"SELECT * FROM leads{clause} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        values + [limit, offset],
    )
    counts = {row["status"]: row["n"] for row in
              db.query("SELECT status, COUNT(*) AS n FROM leads GROUP BY status")}

    return Response.json({
        "leads": [serialize(r, include_private=True) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "counts": {status: counts.get(status, 0) for status in STATUSES},
    })


@router.get("/api/admin/leads/{id}")
@require_admin
def get_lead(request):
    row = _get_or_404(path_int(request, "id"))
    return Response.json({"lead": serialize(row, include_private=True)})


@router.patch("/api/admin/leads/{id}")
@require_admin
def update_lead(request):
    lead_id = path_int(request, "id")
    _get_or_404(lead_id)

    validator = Validator(request.json_body())
    validator.choice("status", STATUSES)
    validator.text("notes", max_length=4000)
    data = validator.done()

    updates, values = [], []
    for field in ("status", "notes"):
        if field in data:
            updates.append(f"{field} = ?")
            values.append(data[field])
    if not updates:
        raise HTTPError(422, "Nothing to update.")

    updates.append("updated_at = ?")
    values.extend([db.now(), lead_id])
    db.execute(f"UPDATE leads SET {', '.join(updates)} WHERE id = ?", values)
    return Response.json({"lead": serialize(_get_or_404(lead_id), include_private=True)})


@router.delete("/api/admin/leads/{id}")
@require_admin
def delete_lead(request):
    lead_id = path_int(request, "id")
    _get_or_404(lead_id)
    db.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    return Response.no_content()


@router.get("/api/admin/summary")
@require_admin
def summary(request):
    """Small dashboard numbers for the admin console."""
    week_ago = _iso_seconds_ago(7 * 24 * 3600)
    counts = {row["status"]: row["n"] for row in
              db.query("SELECT status, COUNT(*) AS n FROM leads GROUP BY status")}
    return Response.json({
        "leads": {
            "total": db.query_one("SELECT COUNT(*) AS n FROM leads")["n"],
            "new": counts.get("new", 0),
            "last_7_days": db.query_one(
                "SELECT COUNT(*) AS n FROM leads WHERE created_at >= ?", (week_ago,)
            )["n"],
            "by_status": {status: counts.get(status, 0) for status in STATUSES},
        },
        "services": db.query_one("SELECT COUNT(*) AS n FROM services WHERE published = 1")["n"],
        "gallery": db.query_one(
            "SELECT COUNT(*) AS n FROM gallery_items WHERE published = 1"
        )["n"],
        "gallery_missing_photos": db.query_one(
            "SELECT COUNT(*) AS n FROM gallery_items WHERE image_file IS NULL"
        )["n"],
    })
