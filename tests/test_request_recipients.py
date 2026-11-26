"""Who received an order: the union of every part's sellers and followers, one entry per store."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import FastAPI

from app.routers import SellerReachRouter as store_mod
from app.services import RequestRecipientsService as recipients_mod
from tests.test_seller_reach_routes import GID, TODAY, _Client

G1, G2, G3, G4 = (str(ObjectId()) for _ in range(4))
VEHICLE = {"year": "2018", "maker": "Nissan", "model": "Versa", "group": GID, "user": "u1", "subModel": None}


def _part(sellers=(), followers=(), non_compatible=(), vehicle=None):
    return {
        "_id": ObjectId(), "creatorGroup": GID, "creatorUser": "u1", "vehicleId": "v1",
        "subscribedSellers": list(sellers), "subscribedFollowers": list(followers),
        "nonCompatibleSellers": [{"group_id": g, "reason": "Armadora"} for g in non_compatible],
        "vehicleInformation": vehicle,
        "part": {"tipoParteDescripcion": "Balata", "amount": 1, "unitOfMeasure": "Pieza"},
        "specific_order_uid": "so1",
    }


def _group(gid, name, coords=None):
    doc = {"_id": ObjectId(gid), "name": name}
    if coords is not None:
        doc["location"] = {"type": "Point", "coordinates": coords}
    return doc


@pytest.fixture
def env():
    ns = SimpleNamespace(parts=[], groups={})
    members = {("u1", GID)}

    def find_groups(ids, projection=None):
        return [ns.groups[i] for i in ids if i in ns.groups]

    with patch.object(store_mod.group_auth, "user_belongs_to_group", side_effect=lambda u, g: (u, g) in members), \
         patch.object(store_mod, "partRequestRepository") as prr, patch.object(store_mod, "reach") as svc, \
         patch.object(store_mod, "offerRepository") as offr, \
         patch.object(recipients_mod, "groupRepository") as grp:
        prr.find_by_specific_order_uid.side_effect = lambda uid: list(ns.parts) if uid == "so1" else []
        grp.find_many_by_string_ids.side_effect = find_groups
        svc.today.return_value = TODAY
        svc.audience.side_effect = lambda s, f: len(set(s or []) | set(f or []))
        svc.room.return_value = 0
        offr.find.return_value = []
        app = FastAPI()
        app.include_router(store_mod.sellerReachRouter)
        ns.grp = grp
        ns.user = _Client(app, {"uid": "u1"})
        ns.as_user = lambda u: _Client(app, u)
        yield ns


def _recipients(env):
    r = env.user.get("/seller-reach/requests/so1/recipients")
    assert r.status_code == 200, r.text
    return r.json()["body"]


def test_union_with_parts_count(env):
    env.parts += [_part(sellers=[G1, G2]), _part(sellers=[G2, G3])]
    env.groups.update({g: _group(g, f"Tienda {g[-4:]}") for g in (G1, G2, G3)})
    body = _recipients(env)
    by_id = {r["group_id"]: r for r in body["recipients"]}
    assert set(by_id) == {G1, G2, G3}
    assert len(body["recipients"]) == 3
    assert by_id[G2]["parts"] == 2
    assert by_id[G1]["parts"] == 1 and by_id[G3]["parts"] == 1
    assert by_id[G1]["name"] == f"Tienda {G1[-4:]}"
    env.grp.find_many_by_string_ids.assert_called_once()  # one batch read, no per-id loop


def test_followers_are_recipients(env):
    env.parts += [_part(sellers=[G1], followers=[G2]), _part(sellers=[G2], followers=[G2])]
    env.groups.update({g: _group(g, "Tienda") for g in (G1, G2)})
    by_id = {r["group_id"]: r for r in _recipients(env)["recipients"]}
    assert set(by_id) == {G1, G2}
    assert by_id[G2]["parts"] == 2  # a store listed twice in one part counts that part once


def test_missing_or_zero_location_is_null(env):
    env.parts += [_part(sellers=[G1, G2, G3])]
    env.groups.update({
        G1: _group(G1, "Con ubicación", [-99.1332, 19.4326]),
        G2: _group(G2, "En cero", [0, 0]),
        G3: _group(G3, "Sin ubicación"),
    })
    by_id = {r["group_id"]: r for r in _recipients(env)["recipients"]}
    assert by_id[G1]["location"] == {"lat": 19.4326, "lng": -99.1332}
    assert by_id[G2]["location"] is None
    assert by_id[G3]["location"] is None


def test_non_compatible_and_maker(env):
    env.parts += [
        _part(sellers=[G1], non_compatible=[G3, G4], vehicle=VEHICLE),
        _part(sellers=[G1], non_compatible=[G3], vehicle={**VEHICLE, "maker": "Ford"}),
    ]
    env.groups[G1] = _group(G1, "Tienda")
    body = _recipients(env)
    assert body["non_compatible"] == 2
    assert body["maker"] == "Nissan"


def test_maker_is_null_without_vehicle(env):
    env.parts += [_part(sellers=[G1])]
    env.groups[G1] = _group(G1, "Tienda")
    body = _recipients(env)
    assert body["maker"] is None
    assert body["non_compatible"] == 0


def test_other_store_member_is_403(env):
    env.parts += [_part(sellers=[G1])]
    r = env.as_user({"uid": "outsider"}).get("/seller-reach/requests/so1/recipients")
    assert r.status_code == 403
    env.grp.find_many_by_string_ids.assert_not_called()


def test_unknown_order_is_404(env):
    r = env.user.get("/seller-reach/requests/nope/recipients")
    assert r.status_code == 404
    assert "Solicitud no encontrada" in r.text  # the route's own 404, not a missing route


def test_union_size_equals_reach_audience_total(env):
    # One part reached 55 stores, another 12 (5 shared, 3 of them only as followers): the screen's
    # "La recibieron N" (reach audience_total) must equal the recipients list it shows.
    wide = [str(ObjectId()) for _ in range(55)]
    extra = [str(ObjectId()) for _ in range(7)]
    env.parts += [
        _part(sellers=wide[:50], followers=wide[50:]),
        _part(sellers=[*extra, *wide[:2]], followers=[*wide[2:5], ""]),
    ]
    env.groups.update({g: _group(g, "Tienda") for g in wide + extra})
    reach_body = env.user.get("/seller-reach/requests/so1").json()["body"]
    body = _recipients(env)
    assert reach_body["audience_total"] == len(body["recipients"]) == 62
    assert sum(r["parts"] for r in body["recipients"]) == 55 + 12


def test_store_missing_from_groups_still_counts(env):
    env.parts += [_part(sellers=[G1, G2])]
    env.groups[G1] = _group(G1, "Tienda")
    reach_body = env.user.get("/seller-reach/requests/so1").json()["body"]
    by_id = {r["group_id"]: r for r in _recipients(env)["recipients"]}
    assert len(by_id) == reach_body["audience_total"] == 2
    assert by_id[G2]["name"] is None and by_id[G2]["location"] is None


@pytest.mark.parametrize("group, expected", [
    ({"location": "19.4,-99.1"}, None),  # not a dict
    ({"location": {"coordinates": "19.4,-99.1"}}, None),  # coordinates not a list
    ({"location": {"coordinates": [None, 19.4]}}, None),
    ({"location": {"coordinates": ["abc", "19.4"]}}, None),
    ({"location": {"coordinates": [{"x": 1}, 19.4]}}, None),
    ({"location": {"coordinates": ["0", "0.0"]}}, None),  # the [0, 0] placeholder, as strings
    ({"location": {"coordinates": [-99.1332]}}, None),
    ({"location": {"coordinates": ["nan", "19.4"]}}, None),
    ({"location": {"coordinates": ["-99.1332", "19.4326"]}}, {"lat": 19.4326, "lng": -99.1332}),
    ({"location": {"coordinates": [-99.1332, 19.4326]}}, {"lat": 19.4326, "lng": -99.1332}),
    ("not a group", None),
])
def test_location_never_raises_on_malformed_data(group, expected):
    assert recipients_mod._location(group) == expected


def test_a_malformed_location_does_not_fail_the_list(env):
    env.parts += [_part(sellers=[G1, G2])]
    env.groups.update({
        G1: {"_id": ObjectId(G1), "name": "Rota", "location": {"type": "Point", "coordinates": ["x", None]}},
        G2: _group(G2, "Bien", [-99.1332, 19.4326]),
    })
    by_id = {r["group_id"]: r for r in _recipients(env)["recipients"]}
    assert by_id[G1]["location"] is None
    assert by_id[G2]["location"] == {"lat": 19.4326, "lng": -99.1332}
