"""Pure comparison logic over participants' watchlists. No I/O — easy to test.

Each participant is a dict: {"id", "username", "thumb", "items": {guid: item}}
where `item` is a plain dict with at least title/year/type/thumb/summary.
"""


def compare(participants: list[dict]) -> dict:
    total = len(participants)
    by_guid: dict[str, dict] = {}

    for p in participants:
        for guid, item in p["items"].items():
            if not guid:
                continue
            entry = by_guid.setdefault(guid, {"item": item, "who": []})
            entry["who"].append(p["id"])

    username = {p["id"]: p.get("username") for p in participants}
    thumb = {p["id"]: p.get("thumb") for p in participants}

    intersection: list[dict] = []
    partials: list[dict] = []
    for guid, entry in by_guid.items():
        count = len(entry["who"])
        rec = {
            "guid": guid,
            "item": entry["item"],
            "who": entry["who"],
            "who_users": [username.get(i) for i in entry["who"]],
            "who_people": [
                {"username": username.get(i), "thumb": thumb.get(i)} for i in entry["who"]
            ],
            "count": count,
            "total": total,
        }
        if total >= 2 and count == total:
            intersection.append(rec)
        elif count >= 2:
            partials.append(rec)

    intersection.sort(key=lambda r: (r["item"].get("title") or "").lower())
    partials.sort(key=lambda r: (-r["count"], (r["item"].get("title") or "").lower()))

    return {"intersection": intersection, "partials": partials, "total": total}
