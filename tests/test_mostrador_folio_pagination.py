"""GET /mostrador pagination: list_for_group page/limit and the repository cursor."""

from unittest.mock import MagicMock, patch

from app.repositories import MostradorFolioRepository as repo
from app.services import MostradorFolioService as svc


def _list(**kwargs):
    with patch.object(svc.folioRepository, "find", return_value=[]) as find, \
            patch.object(svc, "_hydrate", side_effect=lambda d: d):
        svc.list_for_group("group-1", **kwargs)
    return find.call_args.kwargs


def test_without_limit_returns_everything():
    assert _list() == {"skip": 0, "limit": 0}


def test_page_and_limit_become_skip_and_limit():
    assert _list(page=1, limit=20) == {"skip": 0, "limit": 20}
    assert _list(page=3, limit=20) == {"skip": 40, "limit": 20}


def test_limit_without_page_starts_at_first_page():
    assert _list(limit=10) == {"skip": 0, "limit": 10}


def test_cursor_sorts_stably_and_applies_skip_limit():
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    collection = MagicMock()
    collection.find.return_value = cursor
    with patch.object(repo, "_col", return_value=collection):
        repo.find({"origin_group_id": "g"}, skip=40, limit=20)
    cursor.sort.assert_called_once_with([("updated_at", -1), ("_id", -1)])
    cursor.skip.assert_called_once_with(40)
    cursor.limit.assert_called_once_with(20)


def test_cursor_without_limit_is_unbounded():
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    collection = MagicMock()
    collection.find.return_value = cursor
    with patch.object(repo, "_col", return_value=collection):
        repo.find({"origin_group_id": "g"})
    cursor.skip.assert_not_called()
    cursor.limit.assert_not_called()


def _filters_for(search):
    with patch.object(svc.folioRepository, "find", return_value=[]) as find, \
            patch.object(svc, "_hydrate", side_effect=lambda d: d):
        svc.list_for_group("group-1", search=search)
    return find.call_args.args[0]


def test_blank_search_keeps_the_group_filter_only():
    assert _filters_for("  ") == {
        "$or": [{"origin_group_id": "group-1"}, {"participant_shops.group_id": "group-1"}]
    }


def test_search_requires_every_word_in_some_field_and_escapes_regex():
    filters = _filters_for("jetta 76D7(")
    group_filter, search_filter = filters["$and"]
    assert group_filter["$or"][0] == {"origin_group_id": "group-1"}
    first, second = search_filter["$and"]
    assert {"folio_code": {"$regex": "jetta", "$options": "i"}} in first["$or"]
    assert {"vehicle.model": {"$regex": "jetta", "$options": "i"}} in first["$or"]
    assert {"pieces.name": {"$regex": "76D7\\(", "$options": "i"}} in second["$or"]
