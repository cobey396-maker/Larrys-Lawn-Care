"""Assembles every route into one router."""

from .. import db, images
from ..routing import HTTPError, Response, Router
from . import auth, gallery, leads, services, site

router = Router()
router.include(auth.router)
router.include(site.router)
router.include(services.router)
router.include(gallery.router)
router.include(leads.router)


@router.get("/api/health")
def health(request):
    return Response.json({"status": "ok", "time": db.now()})


@router.get("/api/images/{name}")
def serve_image(request):
    """Gallery photos live in the database, so they are served by the API.

    File names are random and a stored image is never rewritten, which makes
    the bytes safe to cache in the browser and on Vercel's CDN forever.
    """
    row = images.load(request.params.get("name", ""))
    if row is None:
        raise HTTPError(404, "No such image.")

    etag = f'"{row["name"]}"'
    headers = {
        "Content-Type": row["mime"],
        "Cache-Control": "public, max-age=31536000, immutable",
        "ETag": etag,
    }
    if request.header("If-None-Match") == etag:
        return Response(304, b"", headers)
    return Response(200, bytes(row["bytes"]), headers)


@router.get("/api/content")
def content(request):
    """Everything the public site needs, in one request.

    The design renders four pages from one component, so one call keeps it
    simple: no loading states scattered across the nav.
    """
    service_rows = db.query("SELECT * FROM services WHERE published = 1 ORDER BY position, id")
    gallery_rows = db.query(
        "SELECT * FROM gallery_items WHERE published = 1 ORDER BY position, id"
    )
    return Response.json({
        "site": db.all_settings(),
        "services": [services.serialize(r) for r in service_rows],
        "gallery": [gallery.serialize(r) for r in gallery_rows],
    })
