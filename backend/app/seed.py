"""First-run content, lifted straight out of the design file.

Running the seed twice is safe: it only fills in rows and settings that are
not there yet, so edits made through the admin console survive a re-seed.
"""

import json

from . import db

SETTINGS = {
    "business_name": "Larry's Lawn Care",
    "eyebrow": "North Carolina & West Tennessee · Since 2009",
    "headline_lines": ["Mowed on time.", "Planted to last."],
    "intro": (
        "Larry and a small crew keep yards, gardens, fences and decks in good order "
        "across the Piedmont and out to Jackson. Same trucks, same faces, every visit. "
        "Call and you'll talk to someone who has stood in a yard like yours."
    ),
    "phone": "+13365550184",
    "phone_display": "(336) 555-0184",
    "email": "larry@larryslawncare.com",
    "hours": (
        "Monday to Saturday, 7am to 6pm. If the crew is on a mower, leave a message "
        "and Larry calls back the same evening."
    ),
    "service_area": (
        "Greensboro, Winston-Salem, High Point and the surrounding Piedmont; "
        "Jackson, Dyersburg and West Tennessee."
    ),
    "since_year": "2009",
    "estimate_note": "Free, in person, written down. Price holds thirty days.",
    "badges": ["Licensed", "Insured", "Weekly or one-time"],
    "stats": [
        {"value": "17", "label": "Years in business"},
        {"value": "1 yr", "label": "Warranty on every planting"},
        {"value": "2", "label": "States served"},
        {"value": "Free", "label": "Estimates, in person"},
    ],
    "process_heading": "You call, Larry walks the yard, you get a number",
    "process_body": (
        "No online forms to fill out twice. We come look at the property, tell you what "
        "it needs now and what can wait, and leave a written price that holds for thirty "
        "days. Work starts within a week most of the season."
    ),
    "cta_heading": "Ready for the yard to stop nagging you?",
    "cta_body": (
        "Call for a free estimate. Mowing routes fill up first in spring, so earlier "
        "is better."
    ),
    "callback_heading": "Rather we call you?",
    "callback_body": "Leave a number and the property address. We'll ring within a day.",
    "callback_confirmation": "Got it — talk soon",
    "warranty_heading": "The warranty, plainly",
    "warranty_body": (
        "Anything we plant is covered for one full year. If it dies and you watered it, "
        "we replace it and put it back in the ground at no charge. Fences and decks carry "
        "a two-year workmanship guarantee."
    ),
    "services_heading": "Four things, done properly",
    "services_intro": (
        "We stay small on purpose. These are the jobs we take, priced per property "
        "after a walk-through."
    ),
    "gallery_heading": "Yards we've kept",
    "gallery_intro": "Photos from jobs around the Piedmont and West Tennessee.",
    "contact_heading": "Call Larry",
    "footer_note": "Licensed & insured",
}

SERVICES = [
    {
        "slug": "lawn-care-mowing",
        "kicker": "Weekly or biweekly",
        "title": "Lawn care & mowing",
        "blurb": "Cut, edge, blow off the walks. Same day each week so you can plan around it.",
        "price": "From $45 a visit",
        "detail": (
            "Mowing at the right height for your grass type, string-trimmed edges, walks "
            "and drive blown clean, clippings hauled off if you want them gone. Fescue in "
            "the Piedmont gets a different cut height than the bermuda out west, and we set "
            "it by season rather than by habit."
        ),
        "tags": ["Fescue & bermuda", "Edging", "Leaf season"],
    },
    {
        "slug": "garden-design",
        "kicker": "Plans & planting",
        "title": "Garden design",
        "blurb": "A drawn plan for the whole yard, planted in stages if that suits the budget.",
        "price": "Plans from $350",
        "detail": (
            "We measure the property, note the sun and the drainage, and draw a plan you can "
            "build in one season or five. Plants are chosen for what actually thrives here "
            "— natives first, then the ones worth the extra water. You keep the drawing "
            "whether or not we do the planting."
        ),
        "tags": ["Measured plan", "Native-first", "Phased builds"],
    },
    {
        "slug": "planting-borders",
        "kicker": "Beds & borders",
        "title": "Planting & borders",
        "blurb": "Shrubs, perennials and clean bed lines that hold their shape.",
        "price": "Quoted per bed",
        "detail": (
            "Cut bed edges, amended soil, plants set at the right spacing for what they will "
            "be in five years rather than what looks full on day one. Mulch to two inches, no "
            "volcano mounds against the trunks. One-year warranty on everything we put in "
            "the ground."
        ),
        "tags": ["Bed edging", "Mulch", "1-year warranty"],
    },
    {
        "slug": "fences-decks",
        "kicker": "Built on site",
        "title": "Fences & decks",
        "blurb": "Pressure-treated and cedar builds, set in concrete, squared up.",
        "price": "Quoted per project",
        "detail": (
            "Privacy fence, picket, split rail and gates that still swing true in year ten. "
            "Decks framed to code with hidden fasteners if you want a clean surface. Two-year "
            "workmanship guarantee, and we pull the permits where the county wants them."
        ),
        "tags": ["Cedar & PT pine", "Gates", "2-year workmanship"],
    },
]

GALLERY = [
    {
        "slug": "ll-g1",
        "caption": "Fescue lawn kept through a dry August — Greensboro",
        "hint": "Wide shot of a healthy mowed lawn",
    },
    {
        "slug": "ll-g2",
        "caption": "Front border rebuilt with natives — Winston-Salem",
        "hint": "Planted bed along a front walk",
    },
    {
        "slug": "ll-g3",
        "caption": "Cedar privacy fence, 6ft with a walk gate — High Point",
        "hint": "New fence run along a property line",
    },
    {
        "slug": "ll-g4",
        "caption": "Backyard deck, hidden fasteners — Jackson, TN",
        "hint": "Finished deck off the back of a house",
    },
    {
        "slug": "ll-g5",
        "caption": "Bed edges cut fresh for spring — Dyersburg",
        "hint": "Close-up of a crisp bed edge and mulch",
    },
    {
        "slug": "ll-g6",
        "caption": "Whole-yard plan, second season in — Piedmont",
        "hint": "Yard showing a planted design filling in",
    },
]


def run(force=False):
    """Returns a short summary of what was inserted."""
    added = {"settings": 0, "services": 0, "gallery": 0}
    timestamp = db.now()

    existing_settings = set(db.all_settings())
    for key, value in SETTINGS.items():
        if force or key not in existing_settings:
            db.set_setting(key, value)
            added["settings"] += 1

    for position, service in enumerate(SERVICES):
        row = db.query_one("SELECT id FROM services WHERE slug = ?", (service["slug"],))
        if row and not force:
            continue
        if row:
            db.execute(
                "UPDATE services SET kicker = ?, title = ?, blurb = ?, price = ?, detail = ?, "
                "tags = ?, position = ?, updated_at = ? WHERE id = ?",
                (service["kicker"], service["title"], service["blurb"], service["price"],
                 service["detail"], json.dumps(service["tags"]), position, timestamp, row["id"]),
            )
        else:
            db.execute(
                "INSERT INTO services (slug, kicker, title, blurb, price, detail, tags, "
                "position, published, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (service["slug"], service["kicker"], service["title"], service["blurb"],
                 service["price"], service["detail"], json.dumps(service["tags"]),
                 position, timestamp, timestamp),
            )
        added["services"] += 1

    for position, item in enumerate(GALLERY):
        row = db.query_one("SELECT id FROM gallery_items WHERE slug = ?", (item["slug"],))
        if row and not force:
            continue
        if row:
            db.execute(
                "UPDATE gallery_items SET caption = ?, hint = ?, position = ?, updated_at = ? "
                "WHERE id = ?",
                (item["caption"], item["hint"], position, timestamp, row["id"]),
            )
        else:
            db.execute(
                "INSERT INTO gallery_items (slug, caption, hint, alt, position, published, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (item["slug"], item["caption"], item["hint"], item["caption"],
                 position, timestamp, timestamp),
            )
        added["gallery"] += 1

    return added
