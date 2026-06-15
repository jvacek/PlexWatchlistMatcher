"""Poster proxy: fetches Plex artwork server-side (keeps tokens off the client)
and caches bytes to disk keyed by the source path."""

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlmodel import Session, select

from . import config, plex
from .db import get_session
from .models import Participant

router = APIRouter()

# Posters are immutable per source URL, so let the browser cache them — this
# stops re-renders of the room (every poll) from re-requesting every image.
CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}


@router.get("/img")
async def img(room: str, src: str, session: Session = Depends(get_session)):
    cache_dir = Path(config.CACHE_DIR)
    cache_path = cache_dir / hashlib.sha1(src.encode()).hexdigest()
    if cache_path.exists():
        return FileResponse(cache_path, media_type="image/jpeg", headers=CACHE_HEADERS)

    # Any participant in the room with a live token can fetch global metadata art.
    p = session.exec(
        select(Participant).where(
            Participant.room_id == room, Participant.token_enc.is_not(None)
        )
    ).first()
    token = config.decrypt(p.token_enc) if p else None
    client_id = p.client_id if p else "plex-watchlist-matcher"

    try:
        content, content_type = await plex.fetch_image(client_id, token, src)
    except Exception:
        raise HTTPException(status_code=404, detail="image unavailable")

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(content)
    return Response(content, media_type=content_type, headers=CACHE_HEADERS)
