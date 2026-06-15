"""Plex sign-in entry point.

The whole PIN flow runs in the browser (see app/static/plex-client.js): it
creates a PIN against plex.tv, sends the user to app.plex.tv to approve it, then
polls for the token — which is born in the browser and NEVER sent to this server.
This route only serves the page that drives that flow and remembers the desired
role/room across the redirect bounce through Plex.
"""

from fastapi import APIRouter, Request

from .render import templates

router = APIRouter()


@router.get("/auth")
async def auth(request: Request, role: str = "host", room: str | None = None):
    return templates.TemplateResponse(
        request, "auth.html", {"role": role, "room": room or ""}
    )
