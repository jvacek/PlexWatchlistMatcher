"""FastAPI app wiring: middleware, static, routers, startup."""

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    with Session(db.engine) as session:
        purge_expired(session)
    yield


app = FastAPI(title="Watchlist Compare", lifespan=lifespan)
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
