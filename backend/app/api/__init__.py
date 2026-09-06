"""Assembles every route into one router."""

from .. import db
from ..routing import Response, Router
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
