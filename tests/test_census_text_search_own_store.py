"""Directory search for invites never offers the viewer's own store."""

from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId

from app.services import CensusService as svc


def _request():
    return SimpleNamespace(state=SimpleNamespace(_state={"user": {"uid": "u1"}, "groupSelected": "me"}))


def test_text_search_excludes_the_viewers_census_entry():
    own_census = ObjectId("64b0000000000000000000aa")
    with patch("app.services.CensusService.groupRepository.find_by_id", return_value={"censusReference": str(own_census)}), \
         patch("app.services.CensusService.censusRepository.find", return_value=[]) as c_find, \
         patch("app.services.CensusService.partRequestInviteRepository.find", return_value=[]):
        svc.text_search(_request(), "refacc", "parent-1")

    query = c_find.call_args.args[0]
    assert query["_id"] == {"$ne": own_census}
    assert query["group_reference_id"] == {"$eq": None}


def test_text_search_without_census_reference_adds_no_exclusion():
    with patch("app.services.CensusService.groupRepository.find_by_id", return_value={}), \
         patch("app.services.CensusService.censusRepository.find", return_value=[]) as c_find, \
         patch("app.services.CensusService.partRequestInviteRepository.find", return_value=[]):
        svc.text_search(_request(), "refacc", "parent-1")

    assert "_id" not in c_find.call_args.args[0]
