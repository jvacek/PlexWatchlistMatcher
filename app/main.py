"""FastAPI app wiring: middleware, static, routers, startup."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from starlette.middleware.sessions import SessionMiddleware

from . import config, db
from .auth import router as auth_router
from .images import router as images_router
from .render import templates
from .rooms import purge_expired
from .rooms import router as rooms_router

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
app.include_router(images_router)


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})
