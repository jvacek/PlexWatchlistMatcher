# Plex Watchlist Matcher

Compare Plex watchlists with friends. One person signs in with Plex and gets a
shareable link; friends open it, sign in with their own Plex accounts, and the
app shows what everyone has in common — **"Everyone wants"** (on every list) plus
**"Some of you want"** partial overlaps (with 3+ people), each with poster, year,
and who wants it. Rooms are ephemeral and expire after 24h.

FastAPI + SQLModel (SQLite) + HTMX. No Plex app registration or client secret —
it uses Plex's public PIN/OAuth flow. See `doc/PLAN.md` for the design and
`doc/design-brief.md` for the frontend handoff.

## Local development

```bash
uv sync
cp .env.example .env
uv run python scripts/gen_secrets.py >> .env   # fill in the required keys
uv run uvicorn app.main:app --reload
```

`SECRET_KEY` is **required** — the app refuses to start without it. It signs the
session cookie, so every instance must share the **same** value or sessions break
across instances. On a **multi-instance / autoscaling host** (e.g. fastapi cloud)
set the same value in that platform's env. Generate one with
`uv run python scripts/gen_secrets.py` (prints `SECRET_KEY=…`). There is no
token-encryption key any more — Plex tokens never reach the server.

Open http://localhost:8000 and click **Start comparing**.

**Accessing from a phone on your LAN:** set `BASE_URL=http://<your-mac-ip>:8000`
in `.env` (find it with `ipconfig getifaddr en0`) and run with
`--host 0.0.0.0`. The `BASE_URL` must match the address the phone uses, or the
Plex redirect will fail.

Run the tests:

```bash
uv run pytest
```

## SEO & share assets

The landing page (`/`) is the only public, indexable page; rooms, auth, and
polling fragments are `noindex` and disallowed in `robots.txt`.
Canonical URLs, Open Graph / Twitter tags, and `sitemap.xml` are all built from
**`BASE_URL`**, so it must be the public `https://` origin in production (it
already must be, for the Plex OAuth redirect).

The social-share image and icons in `app/static/` (`og-image.png`,
`apple-touch-icon.png`, `icon-192/512.png`, `favicon.ico`) are committed assets.
Regenerate them after a branding change with:

```bash
uv run python scripts/gen_og_image.py
```

(Pillow is a dev-only dependency; the committed PNGs are what ship, so the
production runtime needs nothing extra.)

## Deployment (Docker + Caddy)

`docker-compose.yml` runs the app behind Caddy, which auto-provisions HTTPS.

1. Point your domain's DNS at the host and make ports 80/443 reachable.
2. Create `.env` with:
   ```
   DOMAIN=watchlist.example.com
   BASE_URL=https://watchlist.example.com
   SECRET_KEY=...
   ```
3. `docker compose up -d --build`

SQLite lives in the `app-data` volume. Expired rooms (and their stored watchlist
data) are purged hourly and on access.

For plain-HTTP testing without a domain, set `DOMAIN=:80`,
`BASE_URL=http://<host>`, and `COOKIE_SECURE=false`.

## Security notes

Plex auth tokens are full-account credentials, so the server never touches one.
Sign-in runs entirely in the browser (Plex's PIN flow); the token is kept in the
tab's `sessionStorage` and used to call Plex directly for the watchlist, posters,
and watchlist-adds. The server only ever receives the **watchlist data** needed
to compute the overlap — never the token. Session cookies are signed, `HttpOnly`,
and `Secure` in production. (Trade-off: because the token is reachable from
client JS, the app avoids injecting third-party scripts and never writes the
token into the DOM or a URL — posters load as `blob:` URLs — to limit XSS exposure.)
