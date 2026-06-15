"""FastAPI app wiring: middleware, static, routers, startup."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from starlette.middleware.sessions import SessionMiddleware

from . import config, db
from .auth import router as auth_router
from .render import templates
from .rooms import purge_expired
from .rooms import router as rooms_router

# uvicorn doesn't attach a handler that captures our "watchlist" logger, so
# INFO lines never reach `fastapi cloud logs`. Give it its own stdout handler.
log = logging.getLogger("watchlist")
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False

# Reclaim expired rooms even on an instance that never serves a room page. The
# DB is now durable (shared Postgres), so unlike the old per-instance SQLite it
# isn't wiped on restart — this hourly sweep is what keeps stale rows from piling
# up. Idempotent, so concurrent loops across autoscaled instances are harmless.
_PURGE_INTERVAL_SECONDS = 3600


async def _purge_loop():
    while True:
        await asyncio.sleep(_PURGE_INTERVAL_SECONDS)
        with Session(db.engine) as session:
            purge_expired(session)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "boot instance=%s secret_fp=%s db=%s cookie_secure=%s",
        config.INSTANCE_ID,
        config.SECRET_KEY_FP,
        db.engine.dialect.name,
        config.COOKIE_SECURE,
    )
    db.init_db()
    with Session(db.engine) as session:
        purge_expired(session)
    task = asyncio.create_task(_purge_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Plex Watchlist Matcher", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    https_only=config.COOKIE_SECURE,
    same_site="lax",
)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(auth_router)
app.include_router(rooms_router)


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/about")
async def about(request: Request):
    return templates.TemplateResponse(request, "about.html", {})


# --- SEO: crawl directives + favicon at the conventional root paths ---------
# Only the landing page ("/") is permanent and public; everything else is an
# ephemeral 24h room, an auth redirect, or a polling fragment, so keep crawlers
# out of those and point them at the sitemap.

_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    body = (
        "User-agent: *\n"
        "Disallow: /room/\n"
        "Disallow: /auth\n"
        "Allow: /\n"
        f"Sitemap: {config.BASE_URL}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{config.BASE_URL}/</loc>"
        "<changefreq>monthly</changefreq><priority>1.0</priority></url>\n"
        f"  <url><loc>{config.BASE_URL}/about</loc>"
        "<changefreq>monthly</changefreq><priority>0.8</priority></url>\n"
        "</urlset>\n"
    )
    return Response(body, media_type="application/xml")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(_STATIC_DIR / "favicon.ico", media_type="image/x-icon")
