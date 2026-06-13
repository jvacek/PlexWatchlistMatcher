from app.compare import compare


def _p(pid, username, *items):
    return {"id": pid, "username": username, "items": {i["guid"]: i for i in items}}


def m(guid, title, **kw):
    return {"guid": guid, "title": title, **kw}


def test_strict_intersection_needs_everyone():
    res = compare(
        [
            _p(1, "ann", m("g:shared", "Dune"), m("g:a", "Only Ann")),
            _p(2, "bob", m("g:shared", "Dune"), m("g:b", "Only Bob")),
        ]
    )
    titles = [r["item"]["title"] for r in res["intersection"]]
    assert titles == ["Dune"]
    assert res["intersection"][0]["count"] == 2
    assert set(res["intersection"][0]["who_users"]) == {"ann", "bob"}
    assert res["partials"] == []


def test_partials_are_shared_by_some_not_all():
    res = compare(
        [
            _p(1, "ann", m("g:x", "X"), m("g:y", "Y")),
            _p(2, "bob", m("g:x", "X"), m("g:z", "Z")),
            _p(3, "cat", m("g:y", "Y"), m("g:z", "Z")),
        ]
    )
    # No title is on all three lists.
    assert res["intersection"] == []
    # X, Y, Z each appear on exactly 2 lists.
    partial_titles = sorted(r["item"]["title"] for r in res["partials"])
    assert partial_titles == ["X", "Y", "Z"]
    assert all(r["count"] == 2 and r["total"] == 3 for r in res["partials"])


def test_partials_sorted_by_count_desc():
    res = compare(
        [
            _p(1, "a", m("g:hot", "Hot"), m("g:warm", "Warm")),
            _p(2, "b", m("g:hot", "Hot"), m("g:warm", "Warm")),
            _p(3, "c", m("g:hot", "Hot")),
        ]
    )
    # Hot is on all 3 -> intersection. Warm on 2 -> partial.
    assert [r["item"]["title"] for r in res["intersection"]] == ["Hot"]
    assert [r["item"]["title"] for r in res["partials"]] == ["Warm"]


def test_empty_guids_ignored():
    res = compare([_p(1, "a", m("", "Ghost")), _p(2, "b", m("", "Ghost"))])
    assert res["intersection"] == []
    assert res["partials"] == []
