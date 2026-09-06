# Larry's Lawn Care

The website for Larry's Lawn Care, set up to deploy on Vercel: a static page
served from the CDN, and a small Python API running as one serverless function.

## Layout

```
public/          the site itself, served at "/" straight off Vercel's CDN
  index.html       the design, rendered in the browser by the runtime below
  support.js       Claude Design runtime (renders <x-dc>, needs React)
  image-slot.js    the <image-slot> element used by the gallery
  image-slots.state.json  the gallery photos, base64, keyed by slot id
  vendor/          React 18.3.1 UMD builds, served from our own origin
  _ds/             the design system: fonts, colours, component styles

api/index.py     the one serverless function; everything under /api lands here
backend/app/     the API itself, plain Python with no third-party packages
scripts/         one-off setup and a local dev server
vercel.json      routing, function config and cache headers
```

## Deploying

The API stores content, callback requests and photos in a database. Vercel gives
a function a read-only filesystem and a fresh container on every cold start, so
the SQLite file this project began with cannot live there — anything written to
disk is gone before the next visitor arrives. Production therefore runs on
[Turso](https://turso.tech), which speaks the same SQL dialect, so every query in
`backend/` is unchanged; only the connection differs.

### 1. Create the database

```sh
turso db create larryslawncare
turso db show larryslawncare --url        # libsql://...
turso db tokens create larryslawncare     # the auth token
```

### 2. Load the schema and starting content

Run this once, from your machine, against that database. It creates the tables,
loads the copy and services from the design, and makes the admin account:

```sh
TURSO_DATABASE_URL="libsql://..." TURSO_AUTH_TOKEN="..." python3 scripts/setup_db.py
```

It prints a generated admin password once — write it down. Set
`LLC_ADMIN_PASSWORD` beforehand to choose your own instead. Running it again is
safe: it never overwrites content or touches an existing admin account.

### 3. Deploy

Import the repository at [vercel.com/new](https://vercel.com/new), or run
`vercel`. No build step and no framework preset are needed — `vercel.json`
already points the static site at `public/` and routes `/api/*` to the function.

Set these environment variables in the Vercel project, for every environment you
deploy:

| Variable              | Required | Notes                                          |
| --------------------- | -------- | ---------------------------------------------- |
| `TURSO_DATABASE_URL`  | yes      | `libsql://...` from step 1                      |
| `TURSO_AUTH_TOKEN`    | yes      | from step 1                                     |
| `LLC_ADMIN_PASSWORD`  | no       | only read by `scripts/setup_db.py`              |
| `LLC_ALLOWED_ORIGINS` | no       | extra origins allowed to call the API cross-site |

Without `TURSO_DATABASE_URL` the function still starts, but falls back to a
throwaway SQLite file and logs a warning; every callback request would be lost.

## Running it locally

One process serves the site and the API together, on the same origin Vercel
gives you, so the URLs match production:

```sh
python3 scripts/setup_db.py     # creates backend/data/larryslawncare.db
python3 scripts/serve.py        # http://127.0.0.1:8080
```

No virtualenv and no `pip install`: the API uses only the standard library,
including its Turso client (`backend/app/libsql.py`), which talks to the
database over HTTPS with `urllib`. That is also why `requirements.txt` is empty
— nothing has to compile during a Vercel build, and cold starts stay short.

To develop against the real database instead of the local file, export
`TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` before running either script.

## How the page gets its content

`public/index.html` renders in the browser: `support.js` reads the `<x-dc>`
block and draws it with React. On mount it fetches `/api/content` and swaps in
the services and gallery captions from the database. The design's own copy stays
in the file as a fallback, so the page still renders correctly on the first
paint and when the API cannot be reached.

The callback box posts to `/api/leads`. It carries a hidden honeypot field, and
the API rate-limits by IP and ignores the same phone number submitted twice
within ten minutes.

Gallery photos come from `image-slots.state.json`, which the design ships with.
Photos uploaded through the admin API are stored as rows and served from
`/api/images/<name>` with a one-year cache, since their names are random and
their contents never change.

## Known gaps

These are worth knowing about before pointing a real customer at the site.

- **There is no admin UI.** `backend/app/api/` exposes a full admin API — sign
  in, edit services, upload photos, work through callback requests — but nothing
  renders it. Everything admin-side has to go through HTTP calls by hand today.
  `/admin` is not routed on Vercel at all.
- **Most of the page copy is not editable.** Only the services list and the
  gallery captions come from the database. The headline, phone number, hours and
  footer are written into `public/index.html`, so changing `site_settings`
  through the API will not move them. Wiring those up means replacing that text
  with `{{ }}` bindings in the design.
- **Uploaded photos do not replace the design's photos.** `image-slot` prefers
  its own stored photo over a `src` attribute, so a photo uploaded through the
  API will not show in a slot that `image-slots.state.json` already fills.
- **The contact details are placeholders.** The phone number and email in the
  design are made up, and the footer says so.
- **The page renders client-side**, so it needs JavaScript and is thin for
  search engines. Fine for a site people reach from a business card or an ad;
  worth revisiting if search traffic matters.
