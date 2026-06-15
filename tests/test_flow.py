"""End-to-end wiring test for the client-driven flow.

The Plex token never reaches the server, so there is nothing Plex-side to mock:
the browser does all Plex I/O and POSTs the resulting data here. These tests
drive those endpoints directly with two TestClients (two browsers) and assert
the comparison renders.
"""

from fastapi.testclient import TestClient

from app.main import app


def _items(*titles_guids):
    return {
        "items": [
            {
                "guid": guid,
                "rating_key": guid.split("/")[-1],
                "title": title,
                "type": "movie",
                "year": 2020,
            }
            for title, guid in titles_guids
        ]
    }


def test_landing_page_renders():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Plex Watchlist Matcher" in r.text


def test_auth_page_renders():
    client = TestClient(app)
    r = client.get("/auth?role=host")
    assert r.status_code == 200
    assert 'id="auth-flow"' in r.text
    assert 'data-role="host"' in r.text


def test_two_user_room_flow():
    host = TestClient(app)
    guest = TestClient(app)

    # Host registers (creates the room) and uploads its watchlist.
    r = host.post(
        "/participant",
        json={
            "plex_uuid": "uuid-host",
            "plex_username": "host-user",
            "client_id": "cid-host",
            "role": "host",
        },
    )
    assert r.status_code == 200
    slug = r.json()["slug"]
    host_pid = r.json()["participant_id"]
    r = host.post(
        f"/room/{slug}/participant/{host_pid}/watchlist",
        json=_items(
            ("Shared Movie", "plex://movie/shared"),
            ("Only Host", "plex://movie/host"),
        ),
    )
    assert r.json() == {"ok": True, "count": 2}

    # Guest registers into the same room and uploads its watchlist.
    r = guest.post(
        "/participant",
        json={
            "plex_uuid": "uuid-guest",
            "plex_username": "guest-user",
            "client_id": "cid-guest",
            "role": "guest",
            "room": slug,
        },
    )
    assert r.status_code == 200
    guest_pid = r.json()["participant_id"]
    guest.post(
        f"/room/{slug}/participant/{guest_pid}/watchlist",
        json=_items(
            ("Shared Movie", "plex://movie/shared"),
            ("Only Guest", "plex://movie/guest"),
        ),
    )

    # The shared title shows up under "Everyone wants"; solo titles under singles.
    r = host.get(f"/room/{slug}/status")
    assert r.status_code == 200
    assert "Everyone wants" in r.text
    assert "Shared Movie" in r.text
    assert "Just one person wants" in r.text
    assert "Only Host" in r.text
    assert "Only Guest" in r.text


def test_gap_and_watch_state():
    host = TestClient(app)
    guest = TestClient(app)

    h = host.post(
        "/participant",
        json={
            "plex_uuid": "u-h",
            "plex_username": "h",
            "client_id": "c-h",
            "role": "host",
        },
    ).json()
    slug, host_pid = h["slug"], h["participant_id"]
    host.post(
        f"/room/{slug}/participant/{host_pid}/watchlist",
        json=_items(("Shared", "plex://movie/shared"), ("HostOnly", "plex://movie/h")),
    )
    g = guest.post(
        "/participant",
        json={
            "plex_uuid": "u-g",
            "plex_username": "g",
            "client_id": "c-g",
            "role": "guest",
            "room": slug,
        },
    ).json()
    guest_pid = g["participant_id"]
    guest.post(
        f"/room/{slug}/participant/{guest_pid}/watchlist",
        json=_items(("Shared", "plex://movie/shared"), ("GuestOnly", "plex://movie/g")),
    )

    # The host's gap is the titles only the guest has (rating_key "g").
    gap = host.get(f"/room/{slug}/participant/{host_pid}/gap").json()["rating_keys"]
    assert gap == ["g"]

    # Host reports having watched the guest-only title; it renders as seen.
    host.post(
        f"/room/{slug}/participant/{host_pid}/watch-state",
        json={"states": [{"rating_key": "g", "view_count": 1, "view_offset": 0}]},
    )
    r = host.get(f"/room/{slug}/status")
    assert r.status_code == 200
    assert "seen" in r.text  # the seen/partial avatar classes appear


def test_write_endpoints_require_membership():
    owner = TestClient(app)
    attacker = TestClient(app)

    reg = owner.post(
        "/participant",
        json={"plex_uuid": "u", "plex_username": "u", "client_id": "c", "role": "host"},
    ).json()
    slug, pid = reg["slug"], reg["participant_id"]

    # A browser that never registered for this participant can't write to it.
    r = attacker.post(
        f"/room/{slug}/participant/{pid}/watchlist",
        json=_items(("X", "plex://movie/x")),
    )
    assert r.status_code == 403


def test_register_into_missing_room_404s():
    client = TestClient(app)
    r = client.post(
        "/participant",
        json={
            "plex_uuid": "u",
            "plex_username": "u",
            "client_id": "c",
            "role": "guest",
            "room": "nope99",
        },
    )
    assert r.status_code == 404
