"""Plex PIN/OAuth flow: login -> redirect to Plex -> callback -> poll -> join room."""

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from . import config, plex
from .db import get_session
from .models import Participant, Room
from .render import templates
from .rooms import is_expired, make_room, run_watchlist_fetch

router = APIRouter()


def _hx_redirect(url: str) -> HTMLResponse:
    resp = HTMLResponse("")
    resp.headers["HX-Redirect"] = url
    return resp


@router.get("/auth/login")
async def login(request: Request, role: str = "host", room: str | None = None):
    sess = request.session
    client_id = sess.get("client_id") or str(uuid4())
    sess["client_id"] = client_id

    pin = await plex.create_pin(client_id)
    sess["pending"] = {"pin_id": pin["id"], "role": role, "room": room}

    forward_url = f"{config.BASE_URL}/auth/callback"
    return RedirectResponse(
        plex.auth_url(client_id, pin["code"], forward_url), status_code=303
    )


@router.get("/auth/callback")
async def callback(request: Request):
    # Plex sends the browser here after login. The token isn't in this request —
    # this page just starts polling /auth/poll.
    return templates.TemplateResponse(request, "linking.html", {})


@router.get("/auth/poll")
async def poll(
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    sess = request.session
    pending = sess.get("pending")
    client_id = sess.get("client_id")
    if not pending or not client_id:
        return _hx_redirect("/")

    token = await plex.poll_pin(client_id, pending["pin_id"])
    if not token:
        return HTMLResponse("<p>Waiting for you to approve access in Plex…</p>")

    user = await plex.get_user(client_id, token)

    role, slug = pending["role"], pending.get("room")
    if role == "host" or not slug:
        room = make_room()
        session.add(room)
        session.commit()
        slug = room.id
    else:
        room = session.get(Room, slug)
        if not room or is_expired(room):
            sess.pop("pending", None)
            return _hx_redirect(f"/room/{slug}")

    # Reuse an existing participant if this account already joined this room.
    participant = session.exec(
        select(Participant).where(
            Participant.room_id == slug, Participant.plex_uuid == user["uuid"]
        )
    ).first()
    if participant is None:
        participant = Participant(
            room_id=slug,
            plex_uuid=user["uuid"],
            plex_username=user["username"],
            plex_thumb=user.get("thumb"),
            client_id=client_id,
        )
    participant.token_enc = config.encrypt(token)
    participant.status = "pending"
    session.add(participant)
    session.commit()
    session.refresh(participant)

    if room.host_participant_id is None and (role == "host"):
        room.host_participant_id = participant.id
        session.add(room)
        session.commit()

    members = sess.get("members", {})
    members[slug] = participant.id
    sess["members"] = members
    sess.pop("pending", None)

    background.add_task(run_watchlist_fetch, participant.id)
    return _hx_redirect(f"/room/{slug}")
