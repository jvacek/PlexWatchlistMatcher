"""End-to-end wiring test with Plex HTTP calls mocked via respx.

Drives two browsers (two TestClients) through the full PIN flow into one room
and asserts the comparison renders.
"""

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app


def test_landing_page_renders():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Plex Watchlist Matcher" in r.text


@respx.mock(assert_all_mocked=False, assert_all_called=False)
def test_two_user_room_flow(respx_mock):
    counter = {"n": 0}

    def create_pin(_request):
        counter["n"] += 1
        return httpx.Response(
            200, json={"id": counter["n"], "code": f"C{counter['n']}"}
        )

    def poll(request):
        pin_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"authToken": f"tok{pin_id}"})

    def user(request):
        tok = request.headers["X-Plex-Token"]
        return httpx.Response(
            200, json={"uuid": f"uuid-{tok}", "username": f"user-{tok}"}
        )

    def watchlist(request):
        tok = request.headers["X-Plex-Token"]
        shared = {
            "guid": "plex://movie/shared",
            "title": "Shared Movie",
            "type": "movie",
            "year": 2020,
        }
        only = {"guid": f"plex://movie/{tok}", "title": f"Only {tok}", "type": "movie"}
        return httpx.Response(
            200,
            json={
                "MediaContainer": {
                    "size": 2,
                    "totalSize": 2,
                    "Metadata": [shared, only],
                }
            },
        )

    respx_mock.post("https://plex.tv/api/v2/pins").mock(side_effect=create_pin)
    respx_mock.get(url__regex=r"https://plex\.tv/api/v2/pins/\d+").mock(
        side_effect=poll
    )
    respx_mock.get("https://plex.tv/api/v2/user").mock(side_effect=user)
    respx_mock.get(
        "https://discover.provider.plex.tv/library/sections/watchlist/all"
    ).mock(side_effect=watchlist)

    host = TestClient(app, follow_redirects=False)
    guest = TestClient(app, follow_redirects=False)

    # Host creates a room.
    r = host.get("/auth/login?role=host")
    assert r.status_code == 303
    assert "app.plex.tv/auth" in r.headers["location"]
    r = host.get("/auth/poll")  # background watchlist fetch runs here
    assert "HX-Redirect" in r.headers
    slug = r.headers["HX-Redirect"].split("/room/")[1]

    # Guest joins the same room.
    r = guest.get(f"/auth/login?role=guest&room={slug}")
    assert r.status_code == 303
    r = guest.get("/auth/poll")
    assert r.headers["HX-Redirect"] == f"/room/{slug}"

    # The shared title shows up under "Everyone wants"; solo titles under singles.
    r = host.get(f"/room/{slug}/status")
    assert r.status_code == 200
    assert "Everyone wants" in r.text
    assert "Shared Movie" in r.text
    assert "Just one person wants" in r.text
    assert "Only tok1" in r.text
    assert "Only tok2" in r.text
