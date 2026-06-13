"""Room pages, status polling, the background watchlist fetch, and TTL cleanup."""

import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import Response
from sqlmodel import Session, select

from . import config, plex
from .compare import compare
from .db import engine, get_session
from .models import Participant, Room, WatchlistItem, utcnow
from .render import templates

router = APIRouter()
log = logging.getLogger("watchlist")

_SLUG_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # no ambiguous chars


def new_slug() -> str:
    return "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(6))


def is_expired(room: Room) -> bool:
    return room.expires_at < utcnow()


def purge_expired(session: Session) -> None:
    """Delete expired rooms and their participants/items (and their tokens)."""
    expired = session.exec(select(Room).where(Room.expires_at < utcnow())).all()
    for room in expired:
        participants = session.exec(
            select(Participant).where(Participant.room_id == room.id)
        ).all()
        for p in participants:
            items = session.exec(
                select(WatchlistItem).where(WatchlistItem.participant_id == p.id)
            ).all()
            for it in items:
                session.delete(it)
            session.delete(p)
        session.delete(room)
    session.commit()


async def run_watchlist_fetch(participant_id: int) -> None:
    """Background task: pull a participant's watchlist into the DB."""
    with Session(engine) as session:
        p = session.get(Participant, participant_id)
        if not p or not p.token_enc:
            return
        p.status = "fetching"
        session.add(p)
        session.commit()
        try:
            token = config.decrypt(p.token_enc)
            items = await plex.fetch_watchlist(p.client_id, token)
            for it in items:
                if not it.get("guid"):
                    continue
                session.add(
                    WatchlistItem(
                        participant_id=p.id,
                        plex_guid=it["guid"],
                        title=it.get("title") or "Untitled",
                        type=it.get("type"),
                        year=_to_int(it.get("year")),
                        summary=it.get("summary"),
                        thumb=it.get("thumb"),
                        rating=_to_float(it.get("rating")),
                    )
                )
            p.status = "ready"
            p.watchlist_fetched_at = utcnow()
            session.add(p)
            session.commit()
            log.info("watchlist ready for participant %s: %d items", p.id, len(items))
        except Exception:
            log.exception("watchlist fetch failed for participant %s", participant_id)
            session.rollback()
            p = session.get(Participant, participant_id)
            if p:
                p.status = "error"
                session.add(p)
                session.commit()


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def make_room() -> Room:
    return Room(
        id=new_slug(),
        expires_at=utcnow() + timedelta(hours=config.ROOM_TTL_HOURS),
    )


def _item_dict(it: WatchlistItem) -> dict:
    return {
        "guid": it.plex_guid,
        "title": it.title,
        "type": it.type,
        "year": it.year,
        "summary": it.summary,
        "thumb": it.thumb,
    }


@router.get("/room/{slug}")
async def room_page(slug: str, request: Request, session: Session = Depends(get_session)):
    purge_expired(session)
    room = session.get(Room, slug)
    return templates.TemplateResponse(
        request, "room.html", {"slug": slug, "exists": room is not None}
    )


@router.get("/room/{slug}/status")
async def room_status(slug: str, request: Request, session: Session = Depends(get_session)):
    room = session.get(Room, slug)
    if not room or is_expired(room):
        return templates.TemplateResponse(request, "partials/status.html", {"state": "expired"})

    participants = session.exec(
        select(Participant).where(Participant.room_id == slug).order_by(Participant.id)
    ).all()

    # The client echoes back the signature it last rendered (csig). If it still
    # matches, return 204 so HTMX leaves the current DOM (and its loaded posters)
    # untouched — no flicker, no poster re-requests. Stateless and per-page, so
    # fresh loads and extra tabs always render.
    sig = ";".join(f"{p.id}:{p.status}" for p in participants)
    if request.query_params.get("csig") == sig:
        return Response(status_code=204)

    my_pid = request.session.get("members", {}).get(slug)
    is_member = any(p.id == my_pid for p in participants)

    ready = [p for p in participants if p.status == "ready"]
    results = None
    previews = []
    if len(ready) >= 2:
        parts_data = [
            {
                "id": p.id,
                "username": p.plex_username,
                "thumb": p.plex_thumb,
                "items": {
                    it.plex_guid: _item_dict(it)
                    for it in session.exec(
                        select(WatchlistItem).where(WatchlistItem.participant_id == p.id)
                    ).all()
                },
            }
            for p in ready
        ]
        results = compare(parts_data)
    elif ready:
        # Waiting for a second person — show each ready person's own watchlist.
        for p in ready:
            items = session.exec(
                select(WatchlistItem)
                .where(WatchlistItem.participant_id == p.id)
                .order_by(WatchlistItem.id)
            ).all()
            previews.append(
                {
                    "username": p.plex_username,
                    "count": len(items),
                    "recs": [{"item": _item_dict(it)} for it in items],
                }
            )

    return templates.TemplateResponse(
        request,
        "partials/status.html",
        {
            "state": "ok",
            "slug": slug,
            "sig": sig,
            "participants": participants,
            "is_member": is_member,
            "my_pid": my_pid,
            "ready_count": len(ready),
            "results": results,
            "previews": previews,
            "share_url": f"{config.BASE_URL}/room/{slug}",
        },
    )


@router.post("/room/{slug}/retry")
async def retry(
    slug: str,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Re-run the watchlist fetch for the current browser's errored participant."""
    pid = request.session.get("members", {}).get(slug)
    if pid:
        p = session.get(Participant, pid)
        if p and p.status == "error" and p.token_enc:
            p.status = "pending"
            session.add(p)
            session.commit()
            background.add_task(run_watchlist_fetch, p.id)
    # The status change itself makes the signature differ from what the client
    # last rendered, so its next poll re-renders — nothing else to do here.
    return Response(status_code=204)
