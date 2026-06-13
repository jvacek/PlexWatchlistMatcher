"""Thin async client for the Plex APIs we use: PIN auth, user, watchlist, images."""

from urllib.parse import urlencode

import httpx

from . import config

PLEX_TV = "https://plex.tv/api/v2"
AUTH_APP = "https://app.plex.tv/auth"
DISCOVER = "https://discover.provider.plex.tv"
METADATA = "https://metadata.provider.plex.tv"


def _headers(client_id: str, token: str | None = None) -> dict:
    h = {
        "X-Plex-Client-Identifier": client_id,
        "X-Plex-Product": config.APP_PRODUCT,
        "X-Plex-Version": config.APP_VERSION,
        "Accept": "application/json",
    }
    if token:
        h["X-Plex-Token"] = token
    return h


async def create_pin(client_id: str) -> dict:
    """Create a login PIN. Returns {id, code}."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            f"{PLEX_TV}/pins", params={"strong": "true"}, headers=_headers(client_id)
        )
        r.raise_for_status()
        d = r.json()
        return {"id": d["id"], "code": d["code"]}


def auth_url(client_id: str, code: str, forward_url: str) -> str:
    """Browser destination where the user authorizes the PIN."""
    q = urlencode(
        {
            "clientID": client_id,
            "code": code,
            "forwardUrl": forward_url,
            "context[device][product]": config.APP_PRODUCT,
        }
    )
    return f"{AUTH_APP}#?{q}"


async def poll_pin(client_id: str, pin_id) -> str | None:
    """Return the authToken once the PIN is claimed, else None."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{PLEX_TV}/pins/{pin_id}", headers=_headers(client_id))
        r.raise_for_status()
        return r.json().get("authToken")


async def get_user(client_id: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{PLEX_TV}/user", headers=_headers(client_id, token))
        r.raise_for_status()
        d = r.json()
        return {
            "uuid": d.get("uuid") or str(d.get("id")),
            "username": d.get("username") or d.get("title") or "Plex user",
            "thumb": d.get("thumb"),
        }


def _normalize(meta: dict) -> dict:
    return {
        "guid": meta.get("guid"),
        "title": meta.get("title"),
        "type": meta.get("type"),
        "year": meta.get("year"),
        "summary": meta.get("summary"),
        "thumb": meta.get("thumb") or meta.get("art"),
        "rating": meta.get("rating"),
    }


async def fetch_watchlist(client_id: str, token: str) -> list[dict]:
    """Fetch the full watchlist for the token's account.

    Pages in chunks; in practice Plex usually returns everything in one request
    (we observe totalSize vs returned size and only loop if it actually caps).
    """
    items: list[dict] = []
    start, page = 0, 100  # 100 is Plex Discover's max container size; larger 400s
    async with httpx.AsyncClient(timeout=30) as c:
        while True:
            params = {
                "X-Plex-Container-Start": start,
                "X-Plex-Container-Size": page,
            }
            r = await c.get(
                f"{DISCOVER}/library/sections/watchlist/all",
                params=params,
                headers=_headers(client_id, token),
            )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"watchlist {r.status_code} from {r.request.url}: {r.text[:800]}"
                )
            mc = r.json().get("MediaContainer", {})
            batch = mc.get("Metadata", []) or []
            items.extend(batch)
            total = mc.get("totalSize", mc.get("size", len(items)))
            start += len(batch)
            if not batch or start >= total:
                break
    return [_normalize(m) for m in items]


async def fetch_image(client_id: str, token: str | None, src: str) -> tuple[bytes, str]:
    """Fetch a poster. `src` is either an absolute URL or a Plex metadata path."""
    if src.startswith("http://") or src.startswith("https://"):
        url, headers = src, {}
    else:
        url, headers = f"{METADATA}{src}", _headers(client_id, token)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        r = await c.get(url, headers=headers)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "image/jpeg")
