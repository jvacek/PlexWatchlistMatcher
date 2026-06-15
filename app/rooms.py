"""Room pages, status polling, TTL cleanup, and the client-driven data endpoints.

The Plex token never reaches this server. The user's browser does all Plex I/O
and POSTs the resulting (non-secret) data here: it registers a participant, then
uploads its watchlist and watch-state. Every write endpoint is bound to the
session's membership for that room, so a browser can only write its own row.
"""

import logging
import secrets
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from . import config
from .compare import compare
from .db import get_session
from .models import Participant, Room, WatchlistItem, WatchState, utcnow
from .render import templates

router = APIRouter()
log = logging.getLogger("watchlist")

_SLUG_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # no ambiguous chars
_STATUSES = {"pending", "fetching", "ready", "error"}


def new_slug() -> str:
    return "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(6))


def is_expired(room: Room) -> bool:
    return room.expires_at < utcnow()


def purge_expired(session: Session) -> None:
    """Delete expired rooms and their participants/items/watch-state."""
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
            for ws in session.exec(
                select(WatchState).where(WatchState.participant_id == p.id)
            ).all():
                session.delete(ws)
            session.delete(p)
        session.delete(room)
    session.commit()


def make_room() -> Room:
    return Room(
        id=new_slug(),
        expires_at=utcnow() + timedelta(hours=config.ROOM_TTL_HOURS),
    )


def _member_pid(request: Request, slug: str) -> int | None:
    return request.session.get("members", {}).get(slug)


def _require_member(request: Request, slug: str, pid: int) -> None:
    """A browser may only write the participant it registered for this room."""
    if _member_pid(request, slug) != pid:
        raise HTTPException(status_code=403, detail="not your participant")


# --- Client-driven data endpoints -------------------------------------------
# The browser holds the Plex token and calls Plex directly; these endpoints just
# receive the resulting data. See app/static/plex-client.js for the caller.


class RegisterIn(BaseModel):
    plex_uuid: str
    plex_username: str
    plex_thumb: str | None = None
    client_id: str
    role: str = "guest"
    room: str | None = None


class ItemIn(BaseModel):
    guid: str
    rating_key: str | None = None
    title: str | None = None
    type: str | None = None
    year: int | None = None
    summary: str | None = None
    thumb: str | None = None
    rating: float | None = None
    audience_rating: float | None = None
    content_rating: str | None = None
    duration: int | None = None
    genres: list[str] = []
    director: list[str] = []
    imdb_id: str | None = None
    tmdb_id: str | None = None
    tvdb_id: str | None = None
    view_count: int | None = None
    view_offset: int | None = None


class WatchlistIn(BaseModel):
    items: list[ItemIn]


class StateIn(BaseModel):
    rating_key: str
    view_count: int = 0
    view_offset: int = 0


class WatchStateIn(BaseModel):
    states: list[StateIn]


class StatusIn(BaseModel):
    status: str


@router.post("/participant")
async def register(
    body: RegisterIn, request: Request, session: Session = Depends(get_session)
):
    """Register (or re-join) a participant from browser-supplied identity. No
    token: the browser fetched /user from Plex and posts the public fields."""
    sess = request.session
    role, slug = body.role, body.room
    if role == "host" or not slug:
        room = make_room()
        session.add(room)
        session.commit()
        slug = room.id
    else:
        room = session.get(Room, slug)
        if not room or is_expired(room):
            raise HTTPException(status_code=404, detail="room not found")

    participant = session.exec(
        select(Participant).where(
            Participant.room_id == slug, Participant.plex_uuid == body.plex_uuid
        )
    ).first()
    if participant is None:
        participant = Participant(
            room_id=slug,
            plex_uuid=body.plex_uuid,
            plex_username=body.plex_username,
            plex_thumb=body.plex_thumb,
            client_id=body.client_id,
        )
    else:
        participant.plex_username = body.plex_username
        participant.plex_thumb = body.plex_thumb
        participant.client_id = body.client_id
    participant.status = "pending"
    session.add(participant)
    session.commit()
    session.refresh(participant)

    members = sess.get("members", {})
    members[slug] = participant.id
    sess["members"] = members

    log.info(
        "register instance=%s slug=%s pid=%s role=%s user=%s",
        config.INSTANCE_ID,
        slug,
        participant.id,
        role,
        body.plex_username,
    )
    return {
        "participant_id": participant.id,
        "slug": slug,
        "status": participant.status,
    }


@router.post("/room/{slug}/participant/{pid}/watchlist")
async def upload_watchlist(
    slug: str,
    pid: int,
    body: WatchlistIn,
    request: Request,
    session: Session = Depends(get_session),
):
    """Receive a participant's watchlist (fetched client-side) and store it."""
    _require_member(request, slug, pid)
    p = session.get(Participant, pid)
    if not p or p.room_id != slug:
        raise HTTPException(status_code=404, detail="participant not found")

    # Clear prior items so re-uploads (retry / re-enrich) don't duplicate.
    for old in session.exec(
        select(WatchlistItem).where(WatchlistItem.participant_id == p.id)
    ).all():
        session.delete(old)

    count = 0
    for it in body.items:
        if not it.guid:
            continue
        session.add(
            WatchlistItem(
                participant_id=p.id,
                plex_guid=it.guid,
                rating_key=it.rating_key,
                title=it.title or "Untitled",
                type=it.type,
                year=it.year,
                summary=it.summary,
                thumb=it.thumb,
                rating=it.rating,
                audience_rating=it.audience_rating,
                content_rating=it.content_rating,
                duration=it.duration,
                genres="|".join(it.genres) or None,
                director="|".join(it.director) or None,
                imdb_id=it.imdb_id,
                tmdb_id=it.tmdb_id,
                tvdb_id=it.tvdb_id,
                view_count=it.view_count,
                view_offset=it.view_offset,
            )
        )
        count += 1

    p.status = "ready"
    p.watchlist_fetched_at = utcnow()
    session.add(p)
    session.commit()
    log.info("watchlist uploaded for participant %s: %d items", p.id, count)
    return {"ok": True, "count": count}


@router.get("/room/{slug}/participant/{pid}/gap")
async def watch_state_gap(
    slug: str,
    pid: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Rating keys on OTHER ready participants' watchlists but not this one's, so
    the browser can ask Plex whether this user has already seen them."""
    _require_member(request, slug, pid)
    ready = session.exec(
        select(Participant).where(
            Participant.room_id == slug, Participant.status == "ready"
        )
    ).all()
    union: set[str] = set()
    own: set[str] = set()
    for person in ready:
        keys = {
            it.rating_key
            for it in session.exec(
                select(WatchlistItem).where(WatchlistItem.participant_id == person.id)
            ).all()
            if it.rating_key
        }
        union |= keys
        if person.id == pid:
            own = keys
    return {"rating_keys": sorted(union - own)}


@router.post("/room/{slug}/participant/{pid}/watch-state")
async def upload_watch_state(
    slug: str,
    pid: int,
    body: WatchStateIn,
    request: Request,
    session: Session = Depends(get_session),
):
    """Receive this participant's watch state for other people's titles."""
    _require_member(request, slug, pid)
    p = session.get(Participant, pid)
    if not p or p.room_id != slug:
        raise HTTPException(status_code=404, detail="participant not found")

    for old in session.exec(
        select(WatchState).where(WatchState.participant_id == pid)
    ).all():
        session.delete(old)
    for s in body.states:
        if s.view_count > 0 or s.view_offset > 0:
            session.add(
                WatchState(
                    participant_id=pid,
                    rating_key=s.rating_key,
                    view_count=s.view_count,
                    view_offset=s.view_offset,
                )
            )
    session.commit()
    return {"ok": True}


@router.post("/room/{slug}/participant/{pid}/status")
async def set_status(
    slug: str,
    pid: int,
    body: StatusIn,
    request: Request,
    session: Session = Depends(get_session),
):
    """Let the browser flag fetching/error so other viewers see the right pill."""
    _require_member(request, slug, pid)
    if body.status not in _STATUSES:
        raise HTTPException(status_code=422, detail="bad status")
    p = session.get(Participant, pid)
    if not p or p.room_id != slug:
        raise HTTPException(status_code=404, detail="participant not found")
    p.status = body.status
    session.add(p)
    session.commit()
    return {"ok": True}


# --- Room pages + status polling (server-rendered, unchanged behaviour) ------


def _external_links(it: WatchlistItem) -> dict:
    """Build IMDB/TMDB/TVDB URLs from the external IDs Plex gave us. TMDB and
    TVDB segment by media kind, so a show's id points at a series page."""
    kind = "tv" if it.type == "show" else "movie"
    series = "series" if it.type == "show" else "movie"
    return {
        "imdb_url": f"https://www.imdb.com/title/{it.imdb_id}/" if it.imdb_id else None,
        "tmdb_url": (
            f"https://www.themoviedb.org/{kind}/{it.tmdb_id}" if it.tmdb_id else None
        ),
        "tvdb_url": (
            f"https://thetvdb.com/dereferrer/{series}/{it.tvdb_id}"
            if it.tvdb_id
            else None
        ),
    }


def _plex_url(it: WatchlistItem) -> str | None:
    """Deep link that opens the title on Plex Discover. Keyed by ratingKey."""
    if not it.rating_key:
        return None
    key = quote(f"/library/metadata/{it.rating_key}", safe="")
    return (
        "https://app.plex.tv/desktop/#!/provider/"
        f"tv.plex.provider.discover/details?key={key}"
    )


def _item_dict(it: WatchlistItem) -> dict:
    return {
        "guid": it.plex_guid,
        "rating_key": it.rating_key,
        "plex_url": _plex_url(it),
        "title": it.title,
        "type": it.type,
        "year": it.year,
        "summary": it.summary,
        "thumb": it.thumb,
        "rating": it.rating,
        "audience_rating": it.audience_rating,
        "content_rating": it.content_rating,
        "duration": it.duration,
        "genres": it.genres.split("|") if it.genres else [],
        "director": it.director.split("|") if it.director else [],
        "watched": (it.view_count or 0) > 0,
        "in_progress": (it.view_offset or 0) > 0 and (it.view_count or 0) == 0,
        **_external_links(it),
    }


@router.get("/room/{slug}")
async def room_page(
    slug: str, request: Request, session: Session = Depends(get_session)
):
    purge_expired(session)
    room = session.get(Room, slug)
    return templates.TemplateResponse(
        request, "room.html", {"slug": slug, "exists": room is not None}
    )


@router.get("/room/{slug}/status")
async def room_status(
    slug: str, request: Request, session: Session = Depends(get_session)
):
    room = session.get(Room, slug)
    if not room or is_expired(room):
        return templates.TemplateResponse(
            request, "partials/status.html", {"state": "expired"}
        )

    participants = session.exec(
        select(Participant).where(Participant.room_id == slug).order_by(Participant.id)
    ).all()

    # The client echoes back the signature it last rendered (csig). If it still
    # matches, return 204 so HTMX leaves the current DOM (and its loaded posters)
    # untouched — no flicker, no poster re-requests. Stateless and per-page, so
    # fresh loads and extra tabs always render. The watch-state row count is part
    # of the signature so a finished cross-reference sync triggers a re-render.
    pids = [p.id for p in participants]
    ws_count = (
        session.scalar(
            select(func.count())
            .select_from(WatchState)
            .where(WatchState.participant_id.in_(pids))
        )
        if pids
        else 0
    )
    sig = ";".join(f"{p.id}:{p.status}" for p in participants) + f"|ws{ws_count}"
    if request.query_params.get("csig") == sig:
        return Response(status_code=204)

    my_pid = _member_pid(request, slug)
    is_member = any(p.id == my_pid for p in participants)

    ready = [p for p in participants if p.status == "ready"]
    results = None
    previews = []
    if len(ready) >= 2:
        items_by_pid = {
            p.id: session.exec(
                select(WatchlistItem).where(WatchlistItem.participant_id == p.id)
            ).all()
            for p in ready
        }
        # WatchState is keyed by rating_key; map to guid via any item that has it.
        rk_to_guid = {
            it.rating_key: it.plex_guid
            for its in items_by_pid.values()
            for it in its
            if it.rating_key
        }
        watch_by_pid: dict[int, dict] = {}
        for w in session.exec(
            select(WatchState).where(
                WatchState.participant_id.in_([p.id for p in ready])
            )
        ).all():
            guid = rk_to_guid.get(w.rating_key)
            if guid:
                watch_by_pid.setdefault(w.participant_id, {})[guid] = {
                    "watched": w.view_count > 0,
                    "in_progress": w.view_offset > 0 and w.view_count == 0,
                }
        parts_data = []
        for p in ready:
            items = {it.plex_guid: _item_dict(it) for it in items_by_pid[p.id]}
            watch = dict(watch_by_pid.get(p.id, {}))
            for guid, item in items.items():  # own items can carry watch state too
                if item.get("watched") or item.get("in_progress"):
                    watch[guid] = {
                        "watched": item["watched"],
                        "in_progress": item["in_progress"],
                    }
            parts_data.append(
                {
                    "id": p.id,
                    "username": p.plex_username,
                    "thumb": p.plex_thumb,
                    "items": items,
                    "watch": watch,
                }
            )
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

    # Unique genres across everything shown, for the genre filter dropdown.
    rec_lists = (
        [results["intersection"], results["partials"], results["singles"]]
        if results
        else [pv["recs"] for pv in previews]
    )
    genres = sorted(
        {g for lst in rec_lists for r in lst for g in r["item"].get("genres", [])}
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
            "genres": genres,
            "share_url": f"{config.BASE_URL}/room/{slug}",
        },
    )
