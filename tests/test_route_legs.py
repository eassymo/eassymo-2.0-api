"""POST /delivery/route-legs: Google Directions through our server, one leg per stop in
the order sent, 5-minute cache, 503 route_estimates_unavailable when there is no key or
Directions fails. The key never reaches logs or responses."""
import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import main
from app.schemas.GuestDeliveryProfile import GuestDeliveryProfileStatus
from app.services import DeliveryService
from app.services import RouteService as route
from tests.asgi_client import AsgiClient

KEY = "AIza-secret-test-key"
ORIGIN = {"lat": 19.432608, "lng": -99.133209}
STOPS = [{"lat": 19.4, "lng": -99.1}, {"lat": 19.35, "lng": -99.16}, {"lat": 19.3, "lng": -99.2}]


def _ok(legs):
    res = MagicMock()
    res.status_code = 200
    res.json.return_value = {
        "status": "OK",
        "routes": [{"legs": [{"distance": {"value": m}, "duration": {"value": s}} for m, s in legs]}],
    }
    return res


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    route.clear_cache()
    monkeypatch.setenv("GOOGLE_DIRECTIONS_API_KEY", KEY)
    yield
    route.clear_cache()


def test_one_leg_per_stop_in_order():
    http = MagicMock(return_value=_ok([(2450, 380), (5000, 610), (12345, 1501)]))
    assert route.get_route_legs(ORIGIN, STOPS, http_get=http) == [
        {"km": 2.5, "min": 6}, {"km": 5.0, "min": 10}, {"km": 12.3, "min": 25},
    ]


def test_waypoints_are_sent_in_the_given_order_not_optimized():
    http = MagicMock(return_value=_ok([(1, 1)] * 3))
    route.get_route_legs(ORIGIN, STOPS, http_get=http)
    params = http.call_args.kwargs["params"]
    assert params["origin"] == "19.432608,-99.133209"
    assert params["destination"] == "19.3,-99.2"
    assert params["waypoints"] == "19.4,-99.1|19.35,-99.16"
    assert "optimize" not in params["waypoints"]
    assert http.call_args.kwargs["timeout"] <= 10


def test_single_stop_sends_no_waypoints():
    http = MagicMock(return_value=_ok([(1000, 60)]))
    assert route.get_route_legs(ORIGIN, STOPS[:1], http_get=http) == [{"km": 1.0, "min": 1}]
    assert "waypoints" not in http.call_args.kwargs["params"]


def test_missing_key_is_503_route_estimates_unavailable(monkeypatch):
    monkeypatch.delenv("GOOGLE_DIRECTIONS_API_KEY")
    http = MagicMock()
    with pytest.raises(route.RouteEstimatesUnavailable) as exc:
        route.get_route_legs(ORIGIN, STOPS, http_get=http)
    assert exc.value.status_code == 503 and exc.value.code == "route_estimates_unavailable"
    http.assert_not_called()


@pytest.mark.parametrize("response", [
    MagicMock(status_code=200, json=MagicMock(return_value={"status": "ZERO_RESULTS", "routes": []})),
    MagicMock(status_code=200, json=MagicMock(return_value={"status": "REQUEST_DENIED", "error_message": "bad"})),
    MagicMock(status_code=500, json=MagicMock(return_value={})),
    MagicMock(status_code=200, json=MagicMock(return_value={"status": "OK", "routes": [{"legs": [{}]}]})),
])
def test_directions_error_status_is_503(response):
    with pytest.raises(route.RouteEstimatesUnavailable):
        route.get_route_legs(ORIGIN, STOPS, http_get=MagicMock(return_value=response))


def test_network_error_is_503():
    with pytest.raises(route.RouteEstimatesUnavailable):
        route.get_route_legs(ORIGIN, STOPS, http_get=MagicMock(side_effect=OSError("down")))


def test_more_than_12_stops_is_422():
    with pytest.raises(HTTPException) as exc:
        route.get_route_legs(ORIGIN, [STOPS[0]] * 13, http_get=MagicMock())
    assert exc.value.status_code == 422


def test_no_stops_is_empty_without_calling_directions():
    http = MagicMock()
    assert route.get_route_legs(ORIGIN, [], http_get=http) == []
    http.assert_not_called()


def test_repeated_request_within_ttl_does_not_call_directions_again():
    http = MagicMock(return_value=_ok([(1000, 60)] * 3))
    with patch.object(route, "_now", return_value=1000.0):
        first = route.get_route_legs(ORIGIN, STOPS, http_get=http)
    # same points within rounding (4 decimals), 299 s later
    nearby = [{"lat": s["lat"] + 0.00001, "lng": s["lng"]} for s in STOPS]
    with patch.object(route, "_now", return_value=1299.0):
        assert route.get_route_legs(ORIGIN, nearby, http_get=http) == first
    assert http.call_count == 1
    with patch.object(route, "_now", return_value=1301.0):
        route.get_route_legs(ORIGIN, STOPS, http_get=http)
    assert http.call_count == 2


def test_a_different_order_is_a_different_route():
    http = MagicMock(return_value=_ok([(1000, 60)] * 3))
    route.get_route_legs(ORIGIN, STOPS, http_get=http)
    route.get_route_legs(ORIGIN, list(reversed(STOPS)), http_get=http)
    assert http.call_count == 2


def test_key_never_appears_in_logs_or_the_error(caplog):
    caplog.set_level(logging.DEBUG)
    leaky = OSError(f"Max retries exceeded with url: /json?key={KEY}")
    with pytest.raises(route.RouteEstimatesUnavailable) as exc:
        route.get_route_legs(ORIGIN, STOPS, http_get=MagicMock(side_effect=leaky))
    assert KEY not in caplog.text
    assert KEY not in str(exc.value.detail)
    denied = MagicMock(status_code=200, json=MagicMock(
        return_value={"status": "REQUEST_DENIED", "error_message": f"The provided API key {KEY} is invalid"}))
    with pytest.raises(route.RouteEstimatesUnavailable) as exc:
        route.get_route_legs(ORIGIN, STOPS, http_get=MagicMock(return_value=denied))
    assert KEY not in caplog.text
    assert KEY not in str(exc.value.detail)


# ── route ────────────────────────────────────────────────────────────────────

async def _account(request):
    request.state.user = {"uid": "rider-1"}
    request.state.groupSelected = "seller"
    return request.state.user


@pytest.fixture
def client():
    with patch.object(main, "verify_token", side_effect=_account), \
         patch.object(DeliveryService, "_assert_has_delivery_role"):
        yield AsgiClient(main.app)


def test_route_returns_legs(client):
    with patch.object(route, "get_route_legs", return_value=[{"km": 1.0, "min": 2}]) as legs:
        res = client.post("/delivery/route-legs", json={"origin": ORIGIN, "stops": STOPS[:1]})
    assert res.status_code == 200
    assert res.json()["body"] == {"legs": [{"km": 1.0, "min": 2}]}
    assert legs.call_args.args == (ORIGIN, STOPS[:1])


def test_route_without_key_is_503_with_code(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_DIRECTIONS_API_KEY")
    res = client.post("/delivery/route-legs", json={"origin": ORIGIN, "stops": STOPS})
    assert res.status_code == 503
    assert res.json()["code"] == "route_estimates_unavailable"
    assert KEY not in res.text


def test_route_more_than_12_stops_is_422(client):
    res = client.post("/delivery/route-legs", json={"origin": ORIGIN, "stops": [STOPS[0]] * 13})
    assert res.status_code == 422


def test_route_rejects_out_of_range_coordinates(client):
    res = client.post("/delivery/route-legs", json={"origin": {"lat": 91, "lng": 0}, "stops": STOPS[:1]})
    assert res.status_code == 422


def test_route_guest_skips_firebase(client):
    profile = {"token": "tok", "name": "Beto", "status": GuestDeliveryProfileStatus.ACTIVE}
    with patch.object(main, "verify_token", side_effect=AssertionError("guest must not need Firebase")), \
         patch.object(DeliveryService.guestProfileRepository, "find_by_token", return_value=profile), \
         patch.object(route, "get_route_legs", return_value=[]):
        res = client.post("/delivery/route-legs", headers={"X-Guest-Token": "tok"},
                          json={"origin": ORIGIN, "stops": []})
    assert res.status_code == 200
