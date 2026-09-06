"""Site settings: the copy and contact details the design renders."""

from .. import db
from ..routing import HTTPError, Response, Router
from ..security import require_admin
from ..validation import Validator

router = Router()

# Every editable key, with the shape it must hold. Anything not listed here is
# rejected, so the settings table cannot fill up with junk.
FIELDS = {
    "business_name":   ("text", 120),
    "eyebrow":         ("text", 120),
    "headline_lines":  ("list", 80),
    "intro":           ("text", 800),
    "phone":           ("text", 40),
    "phone_display":   ("text", 40),
    "email":           ("text", 254),
    "hours":           ("text", 200),
    "service_area":    ("text", 500),
    "since_year":      ("text", 8),
    "estimate_note":   ("text", 300),
    "badges":          ("list", 60),
    "stats":           ("stats", 0),
    "process_heading": ("text", 200),
    "process_body":    ("text", 800),
    "cta_heading":     ("text", 200),
    "cta_body":        ("text", 800),
    "callback_heading": ("text", 200),
    "callback_body":   ("text", 800),
    "warranty_heading": ("text", 200),
    "warranty_body":   ("text", 1200),
    "services_heading": ("text", 200),
    "services_intro":  ("text", 800),
    "gallery_heading": ("text", 200),
    "gallery_intro":   ("text", 800),
    "contact_heading": ("text", 200),
    "footer_note":     ("text", 300),
}


@router.get("/api/site")
def get_site(request):
    return Response.json({"site": db.all_settings()})


@router.route("PUT", "/api/admin/site")
@require_admin
def update_site(request):
    """Partial update: send only the keys you want to change."""
    data = request.json_body()
    unknown = sorted(set(data) - set(FIELDS))
    if unknown:
        raise HTTPError(422, "Unknown settings: " + ", ".join(unknown),
                        fields={key: "Not a known setting." for key in unknown})

    validator = Validator(data)
    for key, value in data.items():
        kind, limit = FIELDS[key]
        if kind == "text":
            validator.text(key, max_length=limit)
        elif kind == "list":
            validator.string_list(key, max_items=12, max_length=limit)
        elif kind == "stats":
            _validate_stats(validator, key, value)
    clean = validator.done()

    for key, value in clean.items():
        db.set_setting(key, value)
    return Response.json({"site": db.all_settings()})


def _validate_stats(validator, key, value):
    """Stats are the four coloured tiles on the home page."""
    if not isinstance(value, list):
        return validator._fail(key, "Expected a list of {value, label} entries.")
    if len(value) > 8:
        return validator._fail(key, "No more than 8 stats.")
    cleaned = []
    for entry in value:
        if not isinstance(entry, dict):
            return validator._fail(key, "Each stat must be an object.")
        stat_value = str(entry.get("value", "")).strip()
        stat_label = str(entry.get("label", "")).strip()
        if not stat_value or not stat_label:
            return validator._fail(key, "Each stat needs a value and a label.")
        if len(stat_value) > 20 or len(stat_label) > 60:
            return validator._fail(key, "Stat text is too long.")
        cleaned.append({"value": stat_value, "label": stat_label})
    validator.clean[key] = cleaned
    return cleaned
