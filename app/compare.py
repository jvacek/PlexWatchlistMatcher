"""Pure comparison logic over participants' watchlists. No I/O — easy to test.

Each participant is a dict:
    {"id", "username", "thumb",
     "items": {guid: item},                       # what they want (watchlist)
     "watch": {guid: {"watched", "in_progress"}}}  # optional; what they've seen

`watch` may include guids that aren't in `items` (Plex drops watched titles from
the watchlist), so we can show "already seen by X" on someone else's pick.
"""


def compare(participants: list[dict]) -> dict:
    total = len(participants)

    # Representative metadata per guid (titles/years are global), from whoever
    # has it on their watchlist.
    item_by_guid: dict[str, dict] = {}
    for p in participants:
        for guid, item in p["items"].items():
            if guid:
                item_by_guid.setdefault(guid, item)

    intersection: list[dict] = []
    partials: list[dict] = []
    singles: list[dict] = []
    for guid, item in item_by_guid.items():
        wants = [p["id"] for p in participants if guid in p["items"]]
        people = []
        seen_any = False
        for p in participants:
            w = (p.get("watch") or {}).get(guid, {})
            watched = bool(w.get("watched"))
            in_progress = bool(w.get("in_progress"))
            seen_any = seen_any or watched or in_progress
            if guid in p["items"] or watched or in_progress:
                people.append(
                    {
                        "username": p.get("username"),
                        "thumb": p.get("thumb"),
                        "wants": guid in p["items"],
                        "watched": watched,
                        "in_progress": in_progress,
                    }
                )
        count = len(wants)
        rec = {
            "guid": guid,
            "item": item,
            "who": wants,
            "who_users": [p.get("username") for p in participants if guid in p["items"]],
            "people": people,
            "count": count,
            "total": total,
            "seen_any": seen_any,
        }
        if total >= 2 and count == total:
            intersection.append(rec)
        elif count >= 2:
            partials.append(rec)
        else:  # count == 1
            singles.append(rec)

    def by_title(r):
        return (r["item"].get("title") or "").lower()

    intersection.sort(key=by_title)
    partials.sort(key=lambda r: (-r["count"], by_title(r)))
    singles.sort(key=by_title)

    return {
        "intersection": intersection,
        "partials": partials,
        "singles": singles,
        "total": total,
    }
