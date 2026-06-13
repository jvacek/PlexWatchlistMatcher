# Plex Watchlist Compare — Plan

## Status (2026-06-14)

Core app is **built and working end-to-end** (verified with two real Plex
accounts — 30 shared titles between a 360-item and an 88-item watchlist).

- **M0–M3 done.** Setup, real Plex PIN login, ephemeral rooms + multi-participant
  HTMX lobby, comparison engine (intersection + partials).
- **M4 done +.** Poster proxy with disk + browser cache; "your watchlist while you
  wait" preview; movie/show filter; lobby + per-card avatars; error pill with
  retry. Polling re-renders only when state changes (client echoes a signature →
  `204`), so loaded posters aren't torn down each tick.
- **M5 (deploy) written, not yet run on a host.** `Dockerfile`, `docker-compose`
  (app + Caddy auto-HTTPS + sqlite volume), prod env wiring, hourly TTL purge.
  The `uv` install step is validated; the image build needs a Docker host.
- Quality: 6/6 tests pass, `ruff` clean, `pyrefly` 0 errors.
- **Remaining:** run the Docker stack on a real host/domain; optional further
  polish (partials need 3+ people to appear; richer error/login-failure UX).

---

## Context

We want a small web app where a person logs in with their Plex account, gets a
shareable link, and friends who open the link and log in with their own Plex
accounts get their watchlists compared. The headline result is the set of
titles **everyone** has on their watchlist; below that we show **partial
overlaps** ("3 of 4 want this"), each with poster, year, and summary pulled from
Plex metadata.

Decisions already made with the user:
- **Session model:** ephemeral comparison **rooms** (no long-lived accounts).
- **Deployment:** self-hosted **Docker** behind a reverse proxy for HTTPS.
- **Match logic:** strict intersection as the headline **plus** partial overlaps.

Constraints from the user: keep it simple, FastAPI + an ORM + SQLite, HTMX for
the frontend. Visual design is handed off later (see `doc/design-brief.md`), so
this plan keeps templates structurally clean and unstyled.

---

## Plex API research (what we need to access it)

**Good news: there is no app registration, no client secret, and no approval
process.** Plex third-party access works through a public PIN/OAuth flow. You
only invent a stable `X-Plex-Client-Identifier` (a UUID you generate) and send a
product name. Everything is token-based.

### Authentication — PIN / OAuth flow
Plex does not use classic OAuth2 with a client secret. The flow is:

1. **Create a PIN** — `POST https://plex.tv/api/v2/pins?strong=true`
   Headers: `X-Plex-Client-Identifier` (our UUID), `X-Plex-Product`,
   `X-Plex-Version`, `Accept: application/json`.
   Response: JSON `{ id, code, ... }`.
2. **Send the user to Plex to authorize** — redirect the browser to
   `https://app.plex.tv/auth#?clientID=<client-id>&code=<code>&forwardUrl=<our-callback>&context[device][product]=<product>`
   (note the literal `#?` — params live in the URL fragment).
3. **User logs in on Plex**, then Plex redirects the browser back to
   `forwardUrl`. The redirect itself carries **no token** — it's only a signal
   to start polling.
4. **Poll for the token** — `GET https://plex.tv/api/v2/pins/<id>` with the same
   `X-Plex-Client-Identifier` header. Once the PIN is claimed the response
   contains `authToken`.
5. **Identify the user** — `GET https://plex.tv/api/v2/user` with
   `X-Plex-Token: <authToken>` → `uuid`, `username`, `email`, `thumb`.

The `authToken` is a full-access account token, so it is **sensitive** (treat it
like a password — see Security below).

### Watchlist
- **Endpoint:** `GET https://discover.provider.plex.tv/library/sections/watchlist/all`
  (the older `metadata.provider.plex.tv` host for this is deprecated; current
  `python-plexapi` uses the `discover.provider.plex.tv` host).
- **Auth:** `X-Plex-Token` header (+ `X-Plex-Client-Identifier`, `Accept: application/json`).
- **Useful params:** `libtype=movie|show`, `sort=watchlistedAt:desc`, and
  pagination via `X-Plex-Container-Start` / `X-Plex-Container-Size` (the list can
  be large — page in chunks of ~100 until `totalSize` is reached).
- **Returns:** a `MediaContainer` with a `Metadata[]` list. Each item gives us
  what we need: `guid` (e.g. `plex://movie/5d77...`), `ratingKey`, `title`,
  `type` (`movie`/`show`), `year`, `summary`, `thumb`, `art`, `rating`. There is
  also a nested `Guid[]` array with external IDs (`imdb://`, `tmdb://`, `tvdb://`).
- With the user's own token, this returns **that user's** watchlist. Each friend
  authenticates separately, so we get each person's own list.

### Matching key
Use the **`plex://` `guid`** as the match key — it is globally consistent across
Plex accounts for the same title, so intersection is a straight set operation on
guids. (External IDs are a fallback we don't need for v1.)

### Posters / images
- `thumb` / `art` are paths on the Plex provider host and require a valid
  `X-Plex-Token` to fetch (any valid token works — this is global metadata, not
  per-account media). We must **not** ship tokens to the browser.
- **Approach:** a backend image-proxy endpoint that fetches the poster with a
  server-side token and **caches the bytes to a disk cache keyed by guid**. Only
  posters actually displayed get fetched; repeats serve from disk. This also
  means we don't need a token after a room expires.

### Caveats
- These endpoints are community-documented, not an official public API; be a
  polite client (cache, paginate, modest concurrency, retry with backoff).
- A user's watchlist is always readable with their own token regardless of their
  public watchlist privacy setting.

---

## Architecture

**Stack (all `uv`-managed, Python 3.13):**
- **FastAPI** + **uvicorn** — web framework / ASGI server.
- **SQLModel** — ORM (SQLAlchemy core + Pydantic in one model layer; the
  lightest "real ORM" pairing with FastAPI). Tables created with
  `SQLModel.metadata.create_all`; add Alembic later only if the schema churns.
- **SQLite** — single file on a mounted volume.
- **httpx** (async) — all Plex API calls.
- **Jinja2 + HTMX** — server-rendered templates with HTMX for the polling parts
  (lobby "waiting for friends", per-participant fetch status). HTMX is the right
  call here: the app is almost entirely server-rendered with a few async states,
  and HTMX polling models that cleanly without a JS build step. A sprinkle of
  Alpine.js only if the designer needs small client interactions.
- **Starlette `SessionMiddleware`** (signed cookie) — to carry the in-flight
  `client_identifier` + `pin_id` + room/role across the OAuth round-trip.
- **cryptography (Fernet)** — encrypt the per-room Plex token at rest (key from
  env).
- Dev: **pytest** + **respx** (mock Plex HTTP) + **ruff**.

**Suggested layout:**
```
app/
  main.py            # FastAPI app, middleware, route registration
  config.py          # settings (env): SECRET_KEY, FERNET_KEY, DB_URL, BASE_URL, ROOM_TTL
  db.py              # engine + session dependency + create_all on startup
  models.py          # SQLModel tables: Room, Participant, WatchlistItem
  plex.py            # PlexClient: create_pin, poll_pin, get_user, fetch_watchlist, fetch_image
  auth.py            # routes: /auth/login, /auth/callback, /auth/poll
  rooms.py           # routes: create room, /room/{slug}, /room/{slug}/status
  compare.py         # pure function: compute intersection + partials from participant guid-sets
  images.py          # /img proxy + disk cache
  templates/         # Jinja2 (HTMX partials kept separate for swaps)
  static/            # CSS/JS (designer territory)
doc/                 # this plan + design brief
tests/
Dockerfile
docker-compose.yml   # app + Caddy (HTTPS) + sqlite volume
```

### Data model (SQLModel)
- **Room** — `id` (slug, short random), `created_at`, `expires_at`,
  `match_mode`, `host_participant_id?`, `status`.
- **Participant** — `id`, `room_id` (FK), `plex_uuid`, `plex_username`,
  `plex_thumb`, `joined_at`, `status` (`pending|fetching|ready|error`),
  `watchlist_fetched_at`, `plex_token_enc?` (Fernet; purged on expiry).
- **WatchlistItem** — `id`, `participant_id` (FK), `plex_guid`, `title`, `type`,
  `year`, `summary`, `thumb_path`, `rating`. (Stored per participant;
  intersection is computed by grouping on `plex_guid`. Simple and fast at this
  scale.)

### Request flow
1. `GET /` → landing ("Start a comparison"). Button → `/auth/login?role=host`.
2. `GET /auth/login` → create PIN, stash `client_id`+`pin_id`+`room`+`role` in
   the signed session, redirect to `app.plex.tv/auth#?...&forwardUrl=/auth/callback`.
3. `GET /auth/callback` → render a "Linking to Plex…" page that **HTMX-polls**
   `/auth/poll`.
4. `GET /auth/poll` → check the PIN; once `authToken` arrives: fetch user, create
   the Room (if host) or attach a Participant (if guest), store the encrypted
   token, kick off the watchlist fetch (FastAPI background task), then return an
   HTMX redirect to `/room/{slug}`.
5. `GET /room/{slug}` → lobby: share link + copy button, participant avatars with
   status pills; **HTMX-polls** `/room/{slug}/status`.
6. `GET /room/{slug}/status` → HTMX partial. While participants are fetching it
   shows progress; once ≥2 are `ready` it renders results (intersection hero +
   partials grid). Guests join by opening the share link → `/auth/login?role=guest&room={slug}`.
7. `GET /img?guid=...` → poster proxy with disk cache.

### Comparison engine (`compare.py`)
Pure, easily testable function:
- Input: list of participants, each with a set of `(guid → item metadata)`.
- **Strict intersection:** guids present in **all** participants.
- **Partials:** guids in **≥2 but not all**, annotated with count and which
  participants want them, sorted by count desc.
- Output feeds the results template. No I/O in this function → unit-testable in
  isolation.

### Security & privacy (explicit tradeoff)
Plex tokens are full-account credentials. Mitigations:
- Tokens are **encrypted at rest** (Fernet) and only kept for the room's life.
- A background TTL job purges expired rooms and their tokens/items.
- Tokens are **never** sent to the browser; posters go through the proxy.
- Cookies are signed, `HttpOnly`, `Secure`, `SameSite=Lax`.
- *Tradeoff:* we keep one encrypted token per room so the image proxy can fetch
  posters for that room's lifetime. The alternative — pre-downloading every
  poster at fetch time so tokens can be dropped immediately — is more private but
  fetches many images that may never be viewed. We take the proxy-with-disk-cache
  middle ground and purge on expiry.

---

## Milestones

Built so the **riskiest integration is proven first** (per the cross-stack-slice
preference): auth + watchlist are the unknowns, so M1 is a thin vertical slice
through them before any room/multi-user machinery exists.

- **M0 — Setup.** `uv` deps, FastAPI skeleton, SQLModel + SQLite, Jinja2/HTMX
  wired, config from env, hello-world route + one passing test.
  *Verify:* `uv run uvicorn app.main:app` serves `/`.

- **M1 — Validation slice (single user).** Full Plex PIN login end-to-end, then
  fetch and list the logged-in user's own watchlist (titles only, no posters).
  *Verify:* log in with a real Plex account in the browser, see your watchlist
  titles rendered. This de-risks the whole project.

- **M2 — Rooms + multi-participant.** Host creates a room, share link, guests
  join via OAuth, participants persisted, per-participant watchlist fetch with
  status, HTMX-polling lobby.
  *Verify:* open the share link in a second browser/incognito with a second Plex
  account; both appear in the lobby and reach `ready`.

- **M3 — Comparison + results.** `compare.py` (intersection + partials) with unit
  tests; results rendered with title/year/summary and "who wants it" avatars.
  *Verify:* unit tests for the compare function; manual check with two real lists.

- **M4 — Posters + polish.** `/img` proxy + disk cache, poster cards,
  movie/show filter, empty/error states. Hook in the designer's CSS/templates.
  *Verify:* posters render; cached on second load.

- **M5 — Deploy.** Dockerfile, docker-compose with Caddy (auto-HTTPS) + sqlite
  volume, env config, TTL cleanup job for expired rooms/tokens.
  *Verify:* `docker compose up` reachable over HTTPS at the configured domain;
  full two-person flow works end-to-end; expired room is purged.

---

## Verification strategy
- **Unit:** `compare.py` (pure set logic over guids) — the core correctness risk.
- **Mocked integration:** `respx` to stub Plex PIN/user/watchlist responses so
  auth and fetch routes are testable without hitting Plex.
- **Manual e2e:** real Plex login (M1), two-account room (M2+), driven in a
  browser; use the `run` skill / browser tooling to confirm.
- Pull current FastAPI / SQLModel / HTMX / httpx usage from **Context7** during
  implementation rather than relying on memory.

## Open questions / things to confirm during build
- Exact watchlist page size cap and whether `discover.provider.plex.tv` enforces
  rate limits (tune concurrency/backoff once we see real responses in M1).
- Room TTL value (default proposal: 24h) and whether a host can extend it.
- Whether to also surface "available on a connected server" (out of scope for v1;
  watchlist-only as requested).
