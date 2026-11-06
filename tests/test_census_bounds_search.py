from unittest.mock import MagicMock, patch

from app.repositories import CensusRepository
from app.services import CensusService

BOUNDS = (20.6, -87.1, 20.7, -87.0)


def _pipeline(filters=None, lat=None, lng=None, limit=200):
    collection = MagicMock()
    collection.aggregate.return_value = iter([])
    fake_db = MagicMock()
    fake_db.db.__getitem__.return_value = collection
    with patch.object(CensusRepository, "database", fake_db):
        CensusRepository.find_within_bounds(filters or {"limit": 50, "page": 1}, BOUNDS, lat, lng, limit)
    return collection.aggregate.call_args[0][0]


def _parameters(**overrides):
    parameters = {
        "id": None,
        "userUid": "user-1",
        "group_id": None,
        "Entity_Type": None,
        "exclude_group": None,
        "search_argument": None,
        "show_only_census": None,
        "has_group_reference_id": None,
        "Entity_Location_State": None,
        "Entity_Address_City": None,
        "lat": None,
        "lng": None,
        "range_km": None,
        "min_lat": None,
        "min_lng": None,
        "max_lat": None,
        "max_lng": None,
        "limit": 50,
        "page": 1,
    }
    parameters.update(overrides)
    return parameters


def test_filters_by_viewport_polygon():
    stages = _pipeline()
    query = stages[0]["$match"]
    polygon = query["location"]["$geoWithin"]["$geometry"]
    assert polygon["type"] == "Polygon"
    assert polygon["coordinates"] == [[
        [-87.1, 20.6], [-87.0, 20.6], [-87.0, 20.7], [-87.1, 20.7], [-87.1, 20.6],
    ]]
    assert "limit" not in query and "page" not in query


def test_uses_geo_near_only_with_a_reference_point():
    without_point = _pipeline()
    assert "$geoNear" not in without_point[0]
    assert all("distance_km" not in s.get("$addFields", {}) for s in without_point)

    with_point = _pipeline(lat=20.63, lng=-87.07)
    geo_near = with_point[0]["$geoNear"]
    assert geo_near["near"]["coordinates"] == [-87.07, 20.63]
    assert "maxDistance" not in geo_near
    assert "$geoWithin" in geo_near["query"]["location"]
    assert any("distance_km" in s.get("$addFields", {}) for s in with_point)


def test_groups_first_and_limited():
    stages = _pipeline(lat=20.63, lng=-87.07, limit=123)
    sort = next(stage["$sort"] for stage in stages if "$sort" in stage)
    assert list(sort)[:2] == ["_is_group", "distance_meters"]
    assert {"$limit": 123} in stages
    assert stages[-1] == {"$project": {"_is_group": 0}}


def test_bounds_override_radius_filter():
    filters = CensusService.build_filters(_parameters(
        lat=20.63, lng=-87.07, range_km=10,
        min_lat=20.6, min_lng=-87.1, max_lat=20.7, max_lng=-87.0,
    ))
    assert "location" not in filters


def test_radius_filter_kept_without_bounds():
    filters = CensusService.build_filters(_parameters(lat=20.63, lng=-87.07, range_km=10))
    assert "$near" in filters["location"]


def test_find_routes_bounds_search_and_caps_limit():
    with patch.object(CensusService.censusRepository, "find_within_bounds", return_value=iter([])) as within, \
            patch.object(CensusService.censusRepository, "find_with_geospatial") as radius, \
            patch.object(CensusService, "check_census_status", side_effect=lambda _u, r, _g: r):
        response = CensusService.find(_parameters(
            lat=20.63, lng=-87.07, range_km=10, limit=500,
            min_lat=20.6, min_lng=-87.1, max_lat=20.7, max_lng=-87.0,
        ))
    radius.assert_not_called()
    args = within.call_args[0]
    assert args[1] == BOUNDS
    assert args[2:] == (20.63, -87.07, CensusService.BOUNDS_SEARCH_MAX_LIMIT)
    assert response["is_bounds_search"] is True
    assert response["is_geospatial_search"] is False
