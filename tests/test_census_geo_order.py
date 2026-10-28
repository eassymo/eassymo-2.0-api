from unittest.mock import MagicMock, patch

from app.repositories import CensusRepository


def _pipeline(**kwargs):
    collection = MagicMock()
    collection.aggregate.return_value = iter([])
    fake_db = MagicMock()
    fake_db.db.__getitem__.return_value = collection
    with patch.object(CensusRepository, "database", fake_db):
        CensusRepository.find_with_geospatial({"limit": 20}, 20.6, -87.0, 5000, **kwargs)
    return collection.aggregate.call_args[0][0]


def test_groups_sort_before_plain_census_then_by_distance():
    stages = _pipeline()
    sort = next(stage["$sort"] for stage in stages if "$sort" in stage)
    assert list(sort)[:2] == ["_is_group", "distance_meters"]
    assert sort["_is_group"] == -1


def test_group_flag_is_computed_before_sorting_and_not_returned():
    stages = _pipeline()
    names = [next(iter(stage)) for stage in stages]
    flag = next(i for i, s in enumerate(stages) if "$addFields" in s and "_is_group" in s["$addFields"])
    assert flag < names.index("$sort")
    assert stages[-1] == {"$project": {"_is_group": 0}}
    assert names.index("$limit") < len(names) - 1
