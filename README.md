# Watchlist Compare

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
cp .env.example .env        # SECRET_KEY/FERNET_KEY optional locally (see below)
uv run uvicorn app.main:app --reload
```

`SECRET_KEY` and `FERNET_KEY` are generated on startup if unset, which is fine
for a single local instance. On any **multi-instance / autoscaling host** (e.g.
fastapi cloud) every process must share the **same** keys, or sessions and
encrypted Plex tokens break across instances. Generate a fixed pair and set them
in that platform's env:

```bash
uv run python scripts/gen_secrets.py        # prints SECRET_KEY=… / FERNET_KEY=…
```

Open http://localhost:8000 and click **Start comparing**.

**Accessing from a phone on your LAN:** set `BASE_URL=http://<your-mac-ip>:8000`
in `.env` (find it with `ipconfig getifaddr en0`) and run with
`--host 0.0.0.0`. The `BASE_URL` must match the address the phone uses, or the
Plex redirect will fail.

Run the tests:

```bash
uv run pytest
```

## Deployment (Docker + Caddy)

`docker-compose.yml` runs the app behind Caddy, which auto-provisions HTTPS.

1. Point your domain's DNS at the host and make ports 80/443 reachable.
2. Create `.env` with:
   ```
   DOMAIN=watchlist.example.com
   BASE_URL=https://watchlist.example.com
   SECRET_KEY=...
   FERNET_KEY=...
   ```
3. `docker compose up -d --build`

SQLite and the poster cache live in the `app-data` volume. Expired rooms (and
their stored Plex tokens) are purged hourly and on access.

For plain-HTTP testing without a domain, set `DOMAIN=:80`,
`BASE_URL=http://<host>`, and `COOKIE_SECURE=false`.

## Security notes

Plex auth tokens are full-account credentials. They're encrypted at rest
(Fernet), never sent to the browser (posters go through a server-side proxy),
and purged when a room expires. Session cookies are signed, `HttpOnly`, and
`Secure` in production.
