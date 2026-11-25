"""GET /partRequest/{id}/buyer-route: driving route from the selected seller group to the
request's buyer, both points read on the server (the client sends no coordinates)."""
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

import main
from app.services import PartRequestService as service
from app.services import RouteService as route
from app.services import authz
from tests.asgi_client import AsgiClient

KEY = "AIza-secret-test-key"
SELLER = str(ObjectId())
BUYER = str(ObjectId())
REQ = str(ObjectId())
ORIGIN = {"lat": 20.70, "lng": -103.40}
DEST = {"lat": 20.67, "lng": -103.39}


def _payload():
    return {"routes": [{"legs": [{"distanceMeters": 4100, "duration": "720s"}],
                        "polyline": {"encodedPolyline": "abc"}}]}


def _ok():
    return MagicMock(status_code=200, json=MagicMock(return_value=_payload()))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    route.clear_cache()
    monkeypatch.setenv("GOOGLE_DIRECTIONS_API_KEY", KEY)
    yield
    route.clear_cache()


# ── RouteService.get_pair_route ──────────────────────────────────────────────

def test_pair_route_returns_km_min_polyline():
    http = MagicMock(return_value=_ok())
    assert route.get_pair_route(ORIGIN, DEST, http_post=http) == {"km": 4.1, "min": 12, "polyline": "abc"}
    kw = http.call_args.kwargs
    assert kw["headers"]["X-Goog-FieldMask"] == (
        "routes.legs.distanceMeters,routes.legs.duration,routes.polyline.encodedPolyline")
    assert kw["json"]["travelMode"] == "DRIVE" and kw["json"]["routingPreference"] == "TRAFFIC_UNAWARE"


def test_pair_route_cached():
    http = MagicMock(return_value=_ok())
    route.get_pair_route(ORIGIN, DEST, http_post=http)
    near = {"lat": ORIGIN["lat"] + 0.00001, "lng": ORIGIN["lng"]}
    route.get_pair_route(near, DEST, http_post=http)
    assert http.call_count == 1


def test_pair_route_no_key_raises_unavailable(monkeypatch):
    monkeypatch.delenv("GOOGLE_DIRECTIONS_API_KEY")
    http = MagicMock()
    with pytest.raises(route.RouteEstimatesUnavailable):
        route.get_pair_route(ORIGIN, DEST, http_post=http)
    http.assert_not_called()


def test_pair_route_without_polyline_is_none():
    res = MagicMock(status_code=200, json=MagicMock(return_value={"routes": [{"legs": [{"distanceMeters": 900, "duration": "60s"}]}]}))
    assert route.get_pair_route(ORIGIN, DEST, http_post=MagicMock(return_value=res))["polyline"] is None


# ── service ──────────────────────────────────────────────────────────────────

def _groups(seller_coords=(-103.40, 20.70), buyer_coords=(-103.39, 20.67)):
    def find(gid, projection=None):
        coords = {SELLER: seller_coords, BUYER: buyer_coords}[gid]
        return {"location": {"type": "Point", "coordinates": list(coords) if coords is not None else []}}
    return find


def _patched(visible=True, **kw):
    ids = [ObjectId(REQ)] if visible else []
    return (
        patch.object(service.partRequestRepository, "find_open_ids", return_value=ids),
        patch.object(service.partRequestRepository, "find_one_by_id", return_value={"_id": ObjectId(REQ), "creatorGroup": BUYER}),
        patch.object(service.groupRepository, "find_by_id", side_effect=_groups(**kw)),
    )


def _run(visible=True, **kw):
    a, b, c = _patched(visible, **kw)
    with a as ids, b, c, patch.object(route, "get_pair_route", return_value={"km": 4.1, "min": 12, "polyline": "abc"}) as pair:
        return service.get_buyer_route(REQ, SELLER), pair, ids


def test_buyer_route_uses_server_points():
    out, pair, ids = _run()
    assert out == {"km": 4.1, "min": 12, "polyline": "abc"}
    assert pair.call_args.args == (ORIGIN, DEST)
    # visibility check is scoped to this request and doesn't filter by status
    flt = ids.call_args.args[0]
    assert {"_id": ObjectId(REQ)} in flt["$and"]
    assert "status" not in flt


def test_buyer_route_404_when_not_visible():
    with pytest.raises(service.HTTPException) as exc:
        _run(visible=False)
    assert exc.value.status_code == 404
    assert "coordinates" not in str(exc.value.detail) and "-103" not in str(exc.value.detail)


@pytest.mark.parametrize("coords", [(0, 0), None, (float("nan"), 1)])
def test_buyer_route_422_buyer_location_missing(coords):
    with pytest.raises(service.LocationMissing) as exc:
        _run(buyer_coords=coords)
    assert exc.value.status_code == 422 and exc.value.code == "buyer_location_missing"


def test_buyer_route_422_seller_location_missing():
    with pytest.raises(service.LocationMissing) as exc:
        _run(seller_coords=(0, 0))
    assert exc.value.code == "seller_location_missing"


# ── router ───────────────────────────────────────────────────────────────────

async def _account(request):
    request.state.user = {"uid": "seller-user"}
    request.state.groupSelected = SELLER
    return request.state.user


@pytest.fixture
def client():
    with patch.object(main, "verify_token", side_effect=_account):
        yield AsgiClient(main.app)


def _grants(*keys):
    return patch.object(authz, "effective_grants", return_value=frozenset(keys))


def test_buyer_route_200(client):
    with _grants("offers.view_incoming"), patch.object(service, "get_buyer_route", return_value={"km": 4.1, "min": 12, "polyline": "abc"}) as svc:
        res = client.get(f"/partRequest/{REQ}/buyer-route")
    assert res.status_code == 200
    assert res.json()["body"] == {"km": 4.1, "min": 12, "polyline": "abc"}
    assert svc.call_args.args == (REQ, SELLER)


def test_buyer_route_view_all_grant_also_works(client):
    with _grants("offers.view_all"), patch.object(service, "get_buyer_route", return_value={"km": 1.0, "min": 2, "polyline": None}):
        assert client.get(f"/partRequest/{REQ}/buyer-route").status_code == 200


def test_buyer_route_403_without_grant(client):
    with _grants("orders.view"), patch.object(service, "get_buyer_route") as svc:
        res = client.get(f"/partRequest/{REQ}/buyer-route")
    assert res.status_code == 403
    svc.assert_not_called()


def test_buyer_route_error_codes(client):
    with _grants("offers.view_incoming"), patch.object(service, "get_buyer_route", side_effect=service.LocationMissing("buyer_location_missing")):
        res = client.get(f"/partRequest/{REQ}/buyer-route")
    assert res.status_code == 422 and res.json()["code"] == "buyer_location_missing"
    with _grants("offers.view_incoming"), patch.object(service, "get_buyer_route", side_effect=route.RouteEstimatesUnavailable()):
        res = client.get(f"/partRequest/{REQ}/buyer-route")
    assert res.status_code == 503 and res.json()["code"] == "route_estimates_unavailable"
    assert KEY not in res.text
