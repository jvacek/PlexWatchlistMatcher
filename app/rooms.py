"""Room pages, status polling, the background watchlist fetch, and TTL cleanup."""

import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func
from sqlmodel import Session, select

from . import config, plex
from .compare import compare
from .db import engine, get_session
from .models import Participant, Room, WatchlistItem, WatchState, utcnow
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
            for ws in session.exec(
                select(WatchState).where(WatchState.participant_id == p.id)
            ).all():
                session.delete(ws)
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
            details = await plex.fetch_details(
                p.client_id,
                token,
                [it["rating_key"] for it in items if it.get("rating_key")],
            )
            # Clear prior items so re-fetches (retry / re-enrich) don't duplicate.
            for old in session.exec(
                select(WatchlistItem).where(WatchlistItem.participant_id == p.id)
            ).all():
                session.delete(old)
            for it in items:
                if not it.get("guid"):
                    continue
                d = details.get(it.get("rating_key"), {})
                session.add(
                    WatchlistItem(
                        participant_id=p.id,
                        plex_guid=it["guid"],
                        rating_key=it.get("rating_key"),
                        title=it.get("title") or "Untitled",
                        type=it.get("type"),
                        year=_to_int(it.get("year")),
                        summary=d.get("summary"),
                        thumb=it.get("thumb"),
                        rating=_to_float(it.get("rating")),
                        audience_rating=_to_float(it.get("audience_rating")),
                        content_rating=it.get("content_rating"),
                        duration=_to_int(it.get("duration")),
                        studio=it.get("studio"),
                        tagline=it.get("tagline"),
                        genres="|".join(d.get("genres") or []) or None,
                        director="|".join(d.get("director") or []) or None,
                        view_count=_to_int(d.get("view_count")),
                        view_offset=_to_int(d.get("view_offset")),
                    )
                )
            p.status = "ready"
            p.watchlist_fetched_at = utcnow()
            room_id = p.room_id
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
            return
    # Cross-reference everyone's watch state against the whole room's items.
    await sync_watch_states(room_id)


async def sync_watch_states(room_id: str) -> None:
    """For every ready participant, look up their watch state for items they
    DON'T have on their own watchlist (others' picks) — so we can show that
    someone has already seen a title that's left their watchlist."""
    with Session(engine) as session:
        ready = session.exec(
            select(Participant).where(
                Participant.room_id == room_id, Participant.status == "ready"
            )
        ).all()
        own_keys: dict[int, set] = {}
        union: set = set()
        for p in ready:
            keys = {
                it.rating_key
                for it in session.exec(
                    select(WatchlistItem).where(WatchlistItem.participant_id == p.id)
                ).all()
                if it.rating_key
            }
            own_keys[p.id] = keys
            union |= keys

        pids = [p.id for p in ready]
        for old in session.exec(
            select(WatchState).where(WatchState.participant_id.in_(pids))
        ).all():
            session.delete(old)
        session.commit()

        for p in ready:
            gap = list(union - own_keys[p.id])
            if not gap or not p.token_enc:
                continue
            try:
                details = await plex.fetch_details(
                    p.client_id, config.decrypt(p.token_enc), gap
                )
            except Exception:
                log.exception("watch-state sync failed for participant %s", p.id)
                continue
            for rk, d in details.items():
                vc = _to_int(d.get("view_count")) or 0
                vo = _to_int(d.get("view_offset")) or 0
                if vc > 0 or vo > 0:  # only store items they've actually engaged with
                    session.add(
                        WatchState(
                            participant_id=p.id,
                            rating_key=rk,
                            view_count=vc,
                            view_offset=vo,
                        )
                    )
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
        "rating_key": it.rating_key,
        "title": it.title,
        "type": it.type,
        "year": it.year,
        "summary": it.summary,
        "thumb": it.thumb,
        "rating": it.rating,
        "audience_rating": it.audience_rating,
        "content_rating": it.content_rating,
        "duration": it.duration,
        "studio": it.studio,
        "tagline": it.tagline,
        "genres": it.genres.split("|") if it.genres else [],
        "director": it.director.split("|") if it.director else [],
        "watched": (it.view_count or 0) > 0,
        "in_progress": (it.view_offset or 0) > 0 and (it.view_count or 0) == 0,
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

    my_pid = request.session.get("members", {}).get(slug)
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


@router.post("/room/{slug}/watchlist/add")
async def watchlist_add(
    slug: str,
    rating_key: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Add an item to the current browser's own Plex watchlist."""
    pid = request.session.get("members", {}).get(slug)
    ok = False
    if pid and rating_key:
        p = session.get(Participant, pid)
        if p and p.token_enc:
            ok = await plex.add_to_watchlist(
                p.client_id, config.decrypt(p.token_enc), rating_key
            )
    if ok:
        return HTMLResponse('<span class="added">✓ On your watchlist</span>')
    return HTMLResponse('<span class="add-failed">Couldn\'t add</span>')
